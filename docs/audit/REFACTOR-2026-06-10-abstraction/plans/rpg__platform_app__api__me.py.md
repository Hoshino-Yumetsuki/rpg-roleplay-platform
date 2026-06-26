# 拆分方案:rpg/platform_app/api/me.py(997 行)

- **结论(verdict)**:needs-refactor
- **优先级**:medium · **工作量**:S(纯机械搬运,薄 HTTP 适配层,补丁面极小)
- **一句话**:me.py 是 5 个互不耦合领域(个人资料/成就/卡片库+酒馆互通/账号迁移/凭证)的杂物抽屉,按本包既有「主题 sub-router」惯例拆成 5 个同级模块即可,me.py 保留 profile 主线 + re-export shim;全仓只有 2 个测试调用点经由 me 模块取符号,shim 全覆盖,零测试改动。
- **前置条件**:另一审计工作流正在并行读本仓源码 —— **本方案现在只落文档,执行须等该工作流结束后再动源码**。

---

## 1. 现状结构图(精读 + AST 实查)

997 行、40 个顶层定义,全部是薄 FastAPI handler(业务逻辑都委托给 `platform_app.{usage, achievements, user_cards, tavern_cards, tavern_chats, save_io, account_io, user_credentials, knowledge.embedding}`)。按文件内注释分隔线与职责,天然聚成 5 个簇:

```
me.py (997 行)
├─ 簇 A 个人主页/偏好/用量/统计/活动/GM风格  (~315 行) ← "me" 本义
│   api_my_profile(41) api_patch_profile(31) api_welcome_dismiss(10)
│   api_my_usage(19) api_my_usage_timeline(11) api_my_stats(34)
│   api_my_activity(80) api_set_preference(34)
│   api_gm_style_schema(4) api_get_my_gm_style(10) api_set_my_gm_style(25)
├─ 簇 B 成就(含两条非 /api/me 路由)            (~65 行)
│   api_public_achievements(6) api_my_achievements(6)
│   api_my_achievements_seen(8) api_public_wall(28)        ← /api/achievements、/api/u/{username}/achievements
├─ 簇 C 卡片库:persona/NPC卡 CRUD + 在线卡库   (~95 行)
│   api_my_personas(4) api_upsert_persona(8) api_get_persona(6) api_delete_persona(3)
│   api_my_character_cards(5) api_upsert_character_card(7) api_get_character_card(6) api_delete_character_card(3)
│   api_set_card_visibility(8) api_list_public_cards(4) api_clone_public_card(7)   ← /api/cards/public*
├─ 簇 D 酒馆(SillyTavern)互通:卡导入导出+聊天导入 (~195 行)
│   _truthy(2) api_import_tavern_card(79) api_export_tavern_card(8)
│   api_export_tavern_png(15) api_import_json_card(30) api_import_tavern_chat(42)
├─ 簇 E 账号级导出/导入(迁移)                  (~70 行)
│   _MAX_ACCOUNT_IMPORT_BYTES  api_account_export_estimate(4)
│   api_account_export(22) api_account_import(30)
└─ 簇 F 用户凭证 + embedder 状态 + 连通性自检   (~230 行)
    api_my_credentials(4) api_set_credential(37) api_delete_credential(4)
    _PING_CACHE/_PING_TTL(模块级单例缓存) api_embedder_status(66) api_test_credential(98)
```

簇间耦合:**零**。唯一共享物是 `router = APIRouter()` 和 `_deps` 公共依赖;无簇间函数调用、无共享可变状态(`_PING_CACHE` 只被簇 F 用,`_truthy` 只被簇 D 用,`_MAX_ACCOUNT_IMPORT_BYTES` 只被簇 E 用 —— 均 Grep 实查无外部引用)。

### 为什么判 needs-refactor 而非 acceptable
- 模块名 "me" 已名不副实:`/api/achievements`、`/api/u/{username}/achievements`、`/api/cards/public*` 都不是 "me" 路由。
- 簇 D(酒馆互通)是活跃增长面(酒馆模式 v2 刚上线,`rpg/routes/tavern.py` 还复制了一份解析逻辑),继续往 me.py 堆只会更糟。
- 本包既有惯例就是「主题 sub-router 平铺」(`auth.py / saves.py / scripts.py / feedback.py / splash.py …`,见 `api/__init__.py`),拆分完全顺势,无新抽象。
- 反方向论据(为何不是 high):全是薄 handler、当下无正确性问题;admin.py(1463)/scripts.py(1354)更大。属「应拆但不急」。

## 2. 引用面与测试 patch 点(Grep 实查,陷阱①)

| 引用方 | 内容 | 拆分后影响 |
|---|---|---|
| `rpg/platform_app/api/__init__.py:11` | `from .me import router as _me_router` | 改为多 router 引入(见 §4) |
| `rpg/tests/test_credentials_api.py:16,39` | `from platform_app.api import me as me_api` | shim 覆盖,**不改** |
| `rpg/tests/test_credentials_api.py:28,50` | `me_api.api_set_credential(...)` 直调(**2 个受影响调用点**) | me.py re-export `api_set_credential` 即可 |
| `rpg/routes/tavern.py:123` | 仅注释提及「复用 me.py:api_import_tavern_card 的解析逻辑」,实际是**复制粘贴**,无 import | 无影响(见 §7 可选去重) |
| `rpg/platform_app/frontend_routes.py:325,430` | 同名 `api_account_export` 是它自己的本地函数,与 me.py 无关 | 无影响 |

- 全仓 `mock.patch`/`monkeypatch` **没有任何**指向 `platform_app.api.me.<符号>` 的 patch;`test_credentials_api.py` 的 monkeypatch 目标是 `platform_app.user_credentials.set_credential`,而 handler 内部是函数内惰性 `from .. import user_credentials`,调用时才解析 —— 搬到任何兄弟模块后 monkeypatch 依旧生效。
- **受影响 patch/取符号点合计:2**(test_credentials_api.py:28、:50),re-export shim 全覆盖,零测试文件改动。
- HTTP 路径类测试(`test_splash.py`、`integration/*` 走 `/api/me/...` URL)不依赖模块路径,router 行为不变即不受影响。

⚠️ **既有基线失败(与本拆分无关,已实跑确认)**:`test_credentials_api.py::test_non_admin_cannot_save_unknown_api_credential` **今天就 FAIL** —— 断言旧文案「自定义供应商需管理员先配置」,而代码已改为「自定义供应商必须填写 Base URL(中转站地址)」(中转站策略放宽时未同步测试)。执行拆分前先记录此基线,验收标准是「无新增失败」;该测试断言文案需另行修复(不属本机械搬运范围)。

## 3. 五大陷阱逐项核对

| 陷阱 | 核查结果 |
|---|---|
| ① patch 命名空间穿透 | 见 §2,仅 2 个调用点,me.py 留 re-export shim 全覆盖 |
| ② Path(\_\_file\_\_) 错位 | `grep -n "__file__\|Path(" me.py` → **0 处**。所有相对 import(`from ..db`、`from .. import X`、`from ..knowledge.embedding`)在同包兄弟模块中语义完全相同;绝对 import(`model_registry`/`agents.gm`/`core.llm_backend`)与位置无关 |
| ③ 执行代理顺手简化 | 本方案 §5 为逐符号搬运清单;**铁律:函数体逐字搬运,一个字符都不许改写**(含注释/docstring/惰性 import);唯一允许的新增代码是各新模块的文件头(§4 已逐模块给出精确 import 头)与 me.py 的 shim 块 |
| ④ 并行中间状态 | 所有批次都要改 me.py(往外搬)→ **全程禁止并行,单执行者串行**,批次间跑验证闸(§6) |
| ⑤ 孤儿/死代码 | me.py **保留**(簇 A + shim),不删除;搬走的代码在 me.py 中必须删净(不许留注释尸体);新增 5 文件全部在 `__init__.py` 挂载,无孤儿 |
| 循环导入 | 新模块只依赖 `fastapi`/`._deps`/`..db`/惰性业务模块,均不 import me;me.py shim import 新模块 → 单向,无环。`api/achievements.py` 与 `platform_app/achievements/` 包、`api/cards*.py` 与 `platform_app/user_cards.py` 是不同模块路径,代码内统一用 `from ..achievements import …` 相对形式(原文即如此),无遮蔽歧义 |
| 模块级单例/副作用 | 路由注册靠各模块自己的 `router` 装饰器 + `__init__.py` include,顺序见 §4;`_PING_CACHE`(可变 dict 单例)与唯一消费者 `api_test_credential` 同迁 credentials.py,无跨模块别名问题(Grep 无外部引用) |
| 路由遮蔽 | 逐对核过:跨新模块不存在「参数段 vs 字面段」同方法冲突(如 GET `/api/me/character-cards/{card_id}` 与 POST `…/import-tavern` 方法不同;`…/{card_id}/export-tavern` 段数不同;Starlette 全表扫描,partial match 不短路)。include 顺序按 §4 镜像原文件顺序,行为零漂移 |

## 4. 目标布局(遵循 api/ 平铺 sub-router 惯例)

```
rpg/platform_app/api/
├─ me.py               (保留, ~360 行)  簇 A + re-export shim
├─ achievements.py     (新, ~80 行)    簇 B
├─ cards.py            (新, ~150 行)   簇 C
├─ cards_tavern.py     (新, ~230 行)   簇 D(与 cards.py 前缀同簇相邻,类比 scripts.py/script_edit.py)
├─ account_transfer.py (新, ~95 行)    簇 E(不叫 account_io.py,避免与 platform_app/account_io.py 重名混淆)
└─ credentials.py      (新, ~240 行)   簇 F
```

### 各新模块精确文件头(执行者照抄,不得自行增删)

```python
# achievements.py
"""platform_app.api.achievements — 成就目录/解锁/公开墙 (见 docs/design/I_achievements.md)。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..db import connect
from ._deps import json_response, require_user

router = APIRouter()
```

```python
# cards.py
"""platform_app.api.cards — 用户 persona / NPC 角色卡 CRUD + 在线公开卡库。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ._deps import json_response, require_user

router = APIRouter()
```

```python
# cards_tavern.py
"""platform_app.api.cards_tavern — 酒馆 (SillyTavern) 角色卡/聊天记录 导入导出兼容层。"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request

from ._deps import json_response, require_user

router = APIRouter()
```

```python
# account_transfer.py
"""platform_app.api.account_transfer — 账号级数据导出/导入(免部署服务 → 本地自部署 迁移)。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ._deps import json_response, require_user

router = APIRouter()
```

```python
# credentials.py
"""platform_app.api.credentials — 用户级 API 凭证 + embedder 状态 + 凭证连通性自检。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ._deps import json_response, require_user

router = APIRouter()
```

注:函数体内的惰性 import(`from fastapi.responses import Response`、`from fastapi import HTTPException`、`import os as _os`、`import time as _time`、`import base64 as _b64`、`import json as _json`、`from urllib.parse import quote as _quote` 等)随函数体逐字搬走,**不要**上提为模块级。

### me.py 拆后保留
- 模块 docstring 更新为:`"""platform_app.api.me — /api/me/* 个人主页/偏好/用量/统计/活动/GM风格。"""`
- 顶层 import 删 `import asyncio`(仅簇 D 使用);保留 `APIRouter, Depends, Request / Jsonb / connect / public_user / SESSION_COOKIE, json_response, require_user`。
- 文件尾追加 shim(陷阱①⑤):

```python
# ── re-export shim:历史导入路径兼容(rpg/tests/test_credentials_api.py 经
#    `from platform_app.api import me` 取符号)。勿删;新代码请直接 import 新模块。
from .account_transfer import (  # noqa: E402,F401
    api_account_export, api_account_export_estimate, api_account_import,
)
from .achievements import (  # noqa: E402,F401
    api_my_achievements, api_my_achievements_seen, api_public_achievements, api_public_wall,
)
from .cards import (  # noqa: E402,F401
    api_clone_public_card, api_delete_character_card, api_delete_persona,
    api_get_character_card, api_get_persona, api_list_public_cards,
    api_my_character_cards, api_my_personas, api_set_card_visibility,
    api_upsert_character_card, api_upsert_persona,
)
from .cards_tavern import (  # noqa: E402,F401
    _truthy, api_export_tavern_card, api_export_tavern_png,
    api_import_json_card, api_import_tavern_card, api_import_tavern_chat,
)
from .credentials import (  # noqa: E402,F401
    api_delete_credential, api_embedder_status, api_my_credentials,
    api_set_credential, api_test_credential,
)
```

(`_PING_CACHE`/`_PING_TTL`/`_MAX_ACCOUNT_IMPORT_BYTES` 不进 shim:Grep 全仓无外部引用,且 re-export 可变单例反而制造双名别名隐患;若执行期发现遗漏引用再按名补。)

### api/__init__.py 改动
第 11 行 `from .me import router as _me_router` 之后追加:

```python
from .achievements import router as _me_achievements_router
from .cards import router as _me_cards_router
from .cards_tavern import router as _me_cards_tavern_router
from .account_transfer import router as _me_account_router
from .credentials import router as _me_credentials_router
```

原第 32 行 `router.include_router(_me_router)` 处,按**原文件内出现顺序**展开为:

```python
router.include_router(_me_router)
router.include_router(_me_achievements_router)
router.include_router(_me_cards_router)
router.include_router(_me_cards_tavern_router)
router.include_router(_me_account_router)
router.include_router(_me_credentials_router)
```

## 5. 机械搬运清单(符号 → 目标文件;逐字搬运,按表顺序)

| # | 符号(me.py 原行号) | 目标文件 |
|---|---|---|
| 1 | `api_public_achievements` @183 | achievements.py |
| 2 | `api_my_achievements` @192 | achievements.py |
| 3 | `api_my_achievements_seen` @201 | achievements.py |
| 4 | `api_public_wall` @212 | achievements.py |
| 5 | `api_my_personas` @413 | cards.py |
| 6 | `api_upsert_persona` @420 | cards.py |
| 7 | `api_get_persona` @431 | cards.py |
| 8 | `api_delete_persona` @440 | cards.py |
| 9 | `api_my_character_cards` @446 | cards.py |
| 10 | `api_upsert_character_card` @454 | cards.py |
| 11 | `api_get_character_card` @464 | cards.py |
| 12 | `api_delete_character_card` @473 | cards.py |
| 13 | `api_set_card_visibility` @480 | cards.py |
| 14 | `api_list_public_cards` @491 | cards.py |
| 15 | `api_clone_public_card` @498 | cards.py |
| 16 | `_truthy` @508 | cards_tavern.py |
| 17 | `api_import_tavern_card` @513 | cards_tavern.py |
| 18 | `api_export_tavern_card` @595 | cards_tavern.py |
| 19 | `api_export_tavern_png` @606 | cards_tavern.py |
| 20 | `api_import_json_card` @624 | cards_tavern.py |
| 21 | `api_import_tavern_chat` @658 | cards_tavern.py |
| 22 | `_MAX_ACCOUNT_IMPORT_BYTES` @703 | account_transfer.py |
| 23 | `api_account_export_estimate` @707 | account_transfer.py |
| 24 | `api_account_export` @714 | account_transfer.py |
| 25 | `api_account_import` @739 | account_transfer.py |
| 26 | `api_my_credentials` @772 | credentials.py |
| 27 | `api_set_credential` @779 | credentials.py |
| 28 | `api_delete_credential` @819 | credentials.py |
| 29 | `_PING_CACHE` + `_PING_TTL` @825-826 | credentials.py |
| 30 | `api_embedder_status` @830 | credentials.py |
| 31 | `api_test_credential` @899 | credentials.py |

搬运规则:含 `@router.…` 装饰器、docstring、函数体、相邻分隔注释(如 `# ── 酒馆 (SillyTavern) 角色卡兼容 ──`)整块剪切;簇 A 的 11 个函数 + 顶部分隔注释原样留在 me.py。

### ≥80 行巨型函数单独评估
- `api_my_activity`(80 行,留在 me.py):3 段同构「SQL→events.append」+ 排序的扁平流水线,共享一个 db 连接与 events 列表;拆阶段函数只增加传参噪音 → **不拆**。
- `api_import_tavern_card`(79 行,→ cards_tavern.py):multipart/JSON 两分支解析出 v2 + 共享收尾,属流水线型;且 `rpg/routes/tavern.py:api_tavern_import_character` 复制了同一段解析 → **值得拆**,但属逻辑改动,**不进本次机械批次**,列为 §7 可选后续。
- `api_test_credential`(98 行,→ credentials.py):缓存→凭证→catalog 选模→ping→错误分类 流水线;`error_kind` 分类段可抽纯函数 `_classify_ping_error(msg)` → 同上,列 §7,本次逐字搬运。

## 6. 串行批次与验证闸(陷阱④)

执行前基线:`cd rpg && ../rpg_env/bin/python -m pytest tests/test_credentials_api.py tests/test_splash.py -q`(预期:1 failed〔§2 既有失败〕 1 passed + splash 全过),并快照路由表:

```bash
cd rpg && ../rpg_env/bin/python -c "
from platform_app.api import router
print('\n'.join(sorted(f'{sorted(r.methods)} {r.path}' for r in router.routes)))" > /tmp/routes_before.txt
```

| 批次 | 内容 | 验证闸 |
|---|---|---|
| B1 | 建 credentials.py(#26-31)+ me.py 删该段 + shim(credentials 行)+ `__init__.py` 挂载 | `py_compile` 全 api/*.py;pytest 上述两文件结果 == 基线;路由表 diff 为空 |
| B2 | 建 cards.py + cards_tavern.py(#5-21)+ me.py 删段/删 `import asyncio` + shim 两行块 | 同上 |
| B3 | 建 achievements.py + account_transfer.py(#1-4, #22-25)+ me.py 删段 + shim | 同上 |
| B4 | me.py docstring 更新、分隔注释清理;终验 | 路由表 diff 为空 + `../rpg_env/bin/python -m pytest tests/ -q` 与全量基线对比无新增失败 + 前端不涉及(纯后端路由模块位置变化,URL 不变) |

同一执行者串行执行;B1-B3 之间不得交叉编辑同一文件的两个未完成批次。路由表 before/after `diff` 为空是本次重构的**机械不变量**(路径×方法集合完全不变)。

## 7. 风险与可选后续

**风险(均低)**
1. 既有失败测试被误归因:`test_non_admin_cannot_save_unknown_api_credential` 今天就 FAIL(断言陈旧文案),务必先录基线。其修复(改断言为「自定义供应商必须填写 Base URL」或补 base_url 用例)是独立小改,不混入本批次。
2. 执行代理擅自「整理」惰性 import 或错误分类逻辑 → 已用 §3③ 铁律 + §4 精确文件头 + §5 整块剪切规则约束。
3. OSS 同步(origin=开源 / deploy=生产 cherry-pick 流程):本拆分是纯文件移动,cherry-pick 冲突面 = 未来改动∩本次移动;建议拆分单独成一个 commit、message 写明「pure move, no logic change」,降低后续三方同步冲突排查成本。

**可选后续(独立批次,非本方案范围)**
- 抽 `_parse_tavern_upload(content_type, form_or_body) -> v2` 进 `platform_app/tavern_cards.py`,让 `api/cards_tavern.py` 与 `rpg/routes/tavern.py:api_tavern_import_character` 共用,消除现存复制粘贴。
- `api_test_credential` 内错误分类抽纯函数 `_classify_ping_error`,顺手补单测。
- 修复 §2 的陈旧测试断言。
