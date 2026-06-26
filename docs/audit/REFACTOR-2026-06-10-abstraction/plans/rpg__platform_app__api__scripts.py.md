# 拆分方案:rpg/platform_app/api/scripts.py(1355 行)

- 审计日期:2026-06-10
- 判定:**needs-refactor**(优先级 medium,工作量 M)
- 一句话:该文件是 9 个子域按时间累加的"/api/scripts* 杂物抽屉",但每个 handler 彼此独立、无共享可变状态,沿 api/ 包既有的 `script_edit.py` 平铺惯例拆 6 个 sibling 模块即可,核心 ingest/status 留守原文件可保住全部测试 pin 点,对外路由零变更。

---

## 1. 判定理由

**为什么不是 acceptable**:
- 文件不是"单一职责的大账本"。45 个端点横跨 9 个互不相干的子域:导入/分片上传、KB 模块状态、章节编辑、入场 wizard(时间线/出生点/身份推荐)、角色卡/世界书读、pack 导入导出、公开剧本库、overrides/GM 风格、复核图+canon god 编辑。
- 包内已有先例:`script_edit.py`(worldbook/canon/anchors 编辑)早已是从剧本域拆出去的 sibling;`imports.py`(rebuild/import-jobs)同理。本文件只是这个演化没拆完的剩余部分。
- 增长趋势确定:历史 task 注释(task 17/51/67/123/141、Phase E、phase_backend)显示该文件是新剧本端点的默认落点,不拆会继续膨胀(同包 admin.py 已 1463 行)。

**为什么风险可控(支持动手)**:
- 每个 handler 是独立的 FastAPI 端点,handler 之间零调用(仅 3 个私有 helper 有簇内复用,且复用边界与拆分边界完全重合)。
- 业务逻辑几乎全部委托给 `script_import` / `knowledge.*` / `workspace` / `script_pack`,handler 只是薄壳。
- 全文件无 `Path(__file__)`、无模块级可变单例(除 `router` 注册表本身)。

**优先级 medium 而非 high**:无正确性问题,纯可维护性;且本仓库有 OSS cherry-pick 同步流程,大规模文件移动会放大未来 cherry-pick 冲突面 —— 应择期单独成 commit、双侧同步,不与功能改动混做。

---

## 2. 现状结构图(按内聚簇着色)

```
rpg/platform_app/api/scripts.py  (1355 行, 45 路由 + 3 helper)
│ 模块级 import: knowledge, script_import, db.connect, _deps.{json_response,require_user}
│ 模块级常量: _ALLOWED_SCRIPT_EXTS
│
├─ [A 导入/上传/生命周期 — 留守]
│   _check_script_ext @20        (helper, A 簇内复用: import + upload_init)
│   _safe_zip_read @26           (helper, 仅 batch_import 用)
│   api_scripts @43              GET  /api/scripts
│   api_import_script @49        POST /api/scripts/import          ← 测试直调+monkeypatch pin
│   api_script_resplit @679      POST /{id}/resplit
│   api_script_unsubscribe @693  POST /{id}/unsubscribe
│   api_script_delete @707       POST /{id}/delete
│   api_script_preview @721      POST /api/scripts/preview
│   api_scripts_batch_import @738 POST /api/scripts/batch-import
│   api_upload_init/chunk/finish/cancel @799-844  /api/uploads/*   ← 用 _check_script_ext
│
├─ [B KB 模块状态 — 留守(测试三重 pin)]
│   api_script_modules_status @96 (118行) GET /{id}/modules-status ← patch.object(mod,"connect") + inspect.getsource + router.routes 三重 pin
│   api_script_embed_status @217  GET /{id}/embed/status
│
├─ [C 章节 → script_chapters.py]
│   api_script_chapters @235, api_chapter_detail @609, api_chapter_update @638,
│   api_chapter_merge @652, api_chapter_split @665
│
├─ [D 入场 wizard → script_wizard.py]
│   api_script_timeline @274 (55行), api_script_birthpoints @332 (105行),
│   api_script_recommend_identity @440 (69行)
│
├─ [E 知识读/角色卡 → script_kb.py]
│   api_script_chapter_facts @266, api_script_character_cards @512,
│   api_script_character_card @520, api_script_upsert_character_card @532,
│   api_script_delete_character_card @542, api_script_card_enabled @550,
│   api_script_card_protagonist @562, api_audit_character_cards @577,
│   api_script_worldbook @601
│
├─ [F 公开库+pack → script_public.py]
│   api_export_script_pack @850, api_import_script_pack @874,
│   api_script_visibility @914, api_public_scripts @963,
│   api_public_script_detail @997, api_clone_public_script @1041,
│   api_fork_public_script @1088
│
├─ [G overrides/GM风格 → script_overrides.py]
│   api_get_script_overrides @1106, api_update_script_overrides @1121,
│   api_get_script_gm_style @1145, api_set_script_gm_style @1177
│
└─ [H 复核/canon god 编辑 → script_review.py]
    _owned_script @1202          (helper, 仅 H 簇用)
    api_script_graph @1211, api_patch_canon @1262,
    api_script_mark_reviewed @1327, api_script_unmark_reviewed @1344
```

---

## 3. 引用面与测试 pin 点(Grep 实查,全量)

对 `platform_app.api.scripts` 的**模块/符号级**引用只有 3 个测试文件(生产代码仅 `api/__init__.py` 引 `router`;`federation.py`、`knowledge/_utils.py` 等命中均为注释/字符串,非代码引用):

| # | 文件:行 | 引用方式 | 约束 |
|---|---------|----------|------|
| 1 | `rpg/tests/test_script_import_api.py:24` | `monkeypatch.setattr(scripts_api.script_import, "import_script", ...)` | 改的是 `platform_app.script_import` 模块对象本体(穿透共享),但要求 `scripts.py` 顶层保留 `from .. import script_import` |
| 2 | `rpg/tests/test_script_import_api.py:26` | 直调 `scripts_api.api_import_script(...)` | `api_import_script` 必须可从 `platform_app.api.scripts` 取到 |
| 3 | `rpg/tests/integration/test_modules_status.py:14` | `api_scripts_mod.router.routes` 断言含 `/api/scripts/{script_id}/modules-status` | 该路由必须仍注册在 **scripts.py 自己的 router** 上 |
| 4 | `rpg/tests/integration/test_modules_status.py:20` | `patch.object(api_scripts_mod, "connect")` | **命名空间穿透型 patch(陷阱①最危险点)**:`api_script_modules_status` 的函数体按其**定义模块**的 globals 解析 `connect`,该函数若搬走,patch 失效。⇒ 该函数必须留在 scripts.py,且顶层保留 `from ..db import connect` |
| 5 | `rpg/tests/integration/test_modules_status.py:40` | 直调 `api_scripts_mod.api_script_modules_status(12, ...)` | 同上,留守即满足 |
| 6 | `rpg/tests/integration/test_embed_status_pgvector.py:23-26` | `inspect.getsource(api_scripts.api_script_modules_status)` 断言源码含 `embedding_vec is not null` | 该函数体内的 SQL **禁止抽成阶段函数**(getsource 只取本函数源码),留守且逐字不动 |

**受影响(需要方案显式处理)的 mock patch 点:2 个**(上表 #1、#4)。本方案的处理方式 = 把被 pin 的符号全部留守原文件,**0 个测试需要改**。

其余 grep 命中(`tools_dsl/command_tools_imports.py`、`script_pack.py`、`character_cards.py`、`workspace.py`、`federation.py`)均为 URL 字符串/注释,与模块路径无关,不受拆分影响。私有 helper `_check_script_ext`/`_safe_zip_read`/`_owned_script` 在仓库内无任何外部引用(Grep 实查,仅本文件内使用)。

---

## 4. 目标布局

遵循 api/ 包现有平铺惯例(`script_edit.py`、`imports.py` 先例;非 `_mixins/` 风格——本包从未用过 mixin,不引入新形态)。**新模块不做成 scripts.py 的子 router,而是 api/__init__.py 里的平级 sibling**(与 script_edit.py 完全同构),从根上避免 shim↔新模块循环导入。

| 新文件(绝对路径基于 `rpg/platform_app/api/`) | 内容 | 预计行数 |
|---|---|---|
| `script_chapters.py` | C 簇:章节列表/详情/编辑/合并/拆分(5 路由) | ~120 |
| `script_kb.py` | E 簇:chapter-facts + 角色卡 6 端点 + audit-cards + worldbook 读(9 路由) | ~125 |
| `script_wizard.py` | D 簇:timeline + birthpoints + recommend-identity(3 路由) | ~250 |
| `script_public.py` | F 簇:visibility + 公开库 4 端点 + export-pack/import-pack(7 路由) | ~265 |
| `script_overrides.py` | G 簇:overrides 读写 + gm-style 读写(4 路由) | ~110 |
| `script_review.py` | H 簇:`_owned_script` + graph + patch-canon + mark/unmark-reviewed(4 路由) | ~170 |
| `scripts.py`(瘦身留守) | A+B 簇:列表/导入/preview/batch/uploads/resplit/unsubscribe/delete + modules-status/embed-status(13 路由 + 2 helper) | ~400 |

拆后最大文件 ~400 行,全部测试 pin 点零迁移。

---

## 5. 可机械执行的搬运清单(符号名 → 目标文件)

**铁律:逐字搬运(verbatim),禁止改写任何函数体、docstring、注释、task 编号注释、函数内局部 import(包括 `__import__("binascii")` 这类怪写法)。只允许新增文件头部的模块 docstring 与模块级 import。**

### 5.1 `script_chapters.py`(新建)
文件头(新写):
```python
"""platform_app.api.script_chapters — /api/scripts/{id}/chapters* 章节读写路由(从 scripts.py 拆出)。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from .. import script_import
from ..db import connect
from ._deps import json_response, require_user

router = APIRouter()
```
搬入(连同 `@router.*` 装饰器,按原文件顺序):
1. `api_script_chapters`(原 @234-262,含装饰器行)
2. `api_chapter_detail`(原 @608-634)
3. `api_chapter_update`(原 @637-648)
4. `api_chapter_merge`(原 @651-661)
5. `api_chapter_split`(原 @664-675)

注意:`api_script_chapters`/`api_chapter_detail` 函数体内的 `from ..db import expose as _expose` 是**函数内 import,原样保留在函数体内**,不上提。

### 5.2 `script_kb.py`(新建)
文件头:
```python
"""platform_app.api.script_kb — 剧本知识读取/角色卡/世界书路由(从 scripts.py 拆出)。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from .. import knowledge
from ._deps import json_response, require_user

router = APIRouter()
```
搬入:
1. `api_script_chapter_facts`(原 @265-270)
2. `api_script_character_cards`(原 @511-516)
3. `api_script_character_card`(原 @519-528)
4. `api_script_upsert_character_card`(原 @531-538)
5. `api_script_delete_character_card`(原 @541-546)
6. `api_script_card_enabled`(原 @549-558)
7. `api_script_card_protagonist`(原 @561-573)
8. `api_audit_character_cards`(原 @576-597;体内 `from platform_app import import_pipeline`、`from platform_app.knowledge.card_audit import audit_character_cards` 均为函数内 import,原样保留)
9. `api_script_worldbook`(原 @600-605)

### 5.3 `script_wizard.py`(新建)
文件头:
```python
"""platform_app.api.script_wizard — 入场 wizard:时间线/出生点/身份推荐(从 scripts.py 拆出)。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from ..db import connect
from ._deps import json_response, require_user

router = APIRouter()
```
搬入:
1. `api_script_timeline`(原 @273-328)
2. `api_script_birthpoints`(原 @331-436)
3. `api_script_recommend_identity`(原 @439-508;体内 `import secrets as _sec`、`from console_assistant import dispatch_assistant_tool`、`import json as _j` 原样保留在函数体内)

### 5.4 `script_public.py`(新建)
文件头:
```python
"""platform_app.api.script_public — 在线剧本库(公开/浏览/订阅/fork)+ pack 导入导出(从 scripts.py 拆出)。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from ..db import connect
from ._deps import json_response, require_user

router = APIRouter()
```
搬入(连同原文件的两条分节注释 `# ── script pack export / import ──…` 与 `# ── 在线剧本库…──`):
1. `api_export_script_pack`(原 @849-870;体内 `from platform_app.knowledge.script_pack import export_script_pack`、`from urllib.parse import quote as _quote` 原样保留)
2. `api_import_script_pack`(原 @873-908)
3. `api_script_visibility`(原 @913-959)
4. `api_public_scripts`(原 @962-993)
5. `api_public_script_detail`(原 @996-1037)
6. `api_clone_public_script`(原 @1040-1084)
7. `api_fork_public_script`(原 @1087-1100)

### 5.5 `script_overrides.py`(新建)
文件头:
```python
"""platform_app.api.script_overrides — 剧本 overrides + 剧本级 GM 叙事风格(从 scripts.py 拆出)。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..db import connect
from ._deps import json_response, require_user

router = APIRouter()
```
搬入(连同分节注释 `# ── script overrides API ──…`):
1. `api_get_script_overrides`(原 @1105-1117)
2. `api_update_script_overrides`(原 @1120-1141)
3. `api_get_script_gm_style`(原 @1144-1173;体内 `from agents.gm.style_harness import resolve_profile` 等 3 个函数内 import 原样保留)
4. `api_set_script_gm_style`(原 @1176-1198)

### 5.6 `script_review.py`(新建)
文件头:
```python
"""platform_app.api.script_review — Phase E 可视化复核:图/canon god 编辑/复核状态机(从 scripts.py 拆出)。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from ..db import connect
from ._deps import json_response, require_user

router = APIRouter()
```
搬入(连同分节注释 `# ── Phase E: 可视化复核…──`):
1. `_owned_script`(原 @1202-1207)
2. `api_script_graph`(原 @1210-1258)
3. `api_patch_canon`(原 @1261-1323;体内两处 `from psycopg.types.json import Jsonb` 原样保留在分支内)
4. `api_script_mark_reviewed`(原 @1326-1340)
5. `api_script_unmark_reviewed`(原 @1343-1354)

### 5.7 `scripts.py`(留守,只删不搬)
- 删除上述 5.1-5.6 全部已搬符号(含各自装饰器与分节注释),其余**一字不动**。
- 顶层 import 调整:`from .. import knowledge, script_import` **保持原样不删**(`knowledge` 留守后无人使用,但删除会破坏潜在 `scripts_api.knowledge` 引用面,留作 shim,行尾加 `# noqa: F401  — re-export shim,勿删`)。`connect`、`json_response`、`require_user`、`HTTPException`/`JSONResponse`/`Response` 中留守代码不再用到的(`HTTPException`、`JSONResponse`、`Response` 三者在搬走 pack/public 后无人用)可删,但 fastapi 符号无人 patch,删除安全;若求零风险也可全部保留加 noqa。
- 文件末尾追加 re-export shim(防陷阱①的未知动态引用,成本为零、无环——新模块均不 import scripts.py):

```python
# ── re-export shim(2026-06-10 拆分):历史上这些 handler 定义在本模块。
# 新代码请直接 import 对应 script_* 模块;此处仅为兼容旧引用面保留。
# ruff: noqa: E402, F401
from .script_chapters import (
    api_chapter_detail, api_chapter_merge, api_chapter_split,
    api_chapter_update, api_script_chapters,
)
from .script_kb import (
    api_audit_character_cards, api_script_card_enabled, api_script_card_protagonist,
    api_script_chapter_facts, api_script_character_card, api_script_character_cards,
    api_script_delete_character_card, api_script_upsert_character_card, api_script_worldbook,
)
from .script_overrides import (
    api_get_script_gm_style, api_get_script_overrides,
    api_set_script_gm_style, api_update_script_overrides,
)
from .script_public import (
    api_clone_public_script, api_export_script_pack, api_fork_public_script,
    api_import_script_pack, api_public_script_detail, api_public_scripts,
    api_script_visibility,
)
from .script_review import (
    _owned_script, api_patch_canon, api_script_graph,
    api_script_mark_reviewed, api_script_unmark_reviewed,
)
from .script_wizard import (
    api_script_birthpoints, api_script_recommend_identity, api_script_timeline,
)
```
注意:**只 re-export 函数符号,绝不 re-export 新模块的 `router`**(避免双重 include 的歧义)。

### 5.8 `api/__init__.py`(注册新 router)
在 `from .scripts import router as _scripts_router` 之后追加(import 区,保持现有风格):
```python
from .script_chapters import router as _script_chapters_router
from .script_kb import router as _script_kb_router
from .script_wizard import router as _script_wizard_router
from .script_public import router as _script_public_router
from .script_overrides import router as _script_overrides_router
from .script_review import router as _script_review_router
```
include 区:在 `router.include_router(_scripts_router)` 之后、`_script_edit_router` 之前,按下列顺序插入(理由见 §7 路由次序分析):
```python
router.include_router(_script_chapters_router)
router.include_router(_script_kb_router)
router.include_router(_script_wizard_router)
router.include_router(_script_public_router)
router.include_router(_script_overrides_router)
router.include_router(_script_review_router)
```

---

## 6. ≥80 行巨型函数逐个评估

| 函数 | 行数 | 类型 | 结论 |
|---|---|---|---|
| `api_script_modules_status` | 118 | 流水线型(owner 校验→7 个 count→job 映射→`_build` 状态机) | **不拆,逐字留守**。理由:被 `inspect.getsource` 测试 pin(源码必须含 `embedding_vec is not null`,SQL 抽出去即红);被 `patch.object(module,"connect")` pin(依赖定义模块命名空间);内部已用局部闭包 `_scalar`/`_build` 自我组织,可读性达标。拆它 = 同时改 2 个测试,收益不抵风险。 |
| `api_script_birthpoints` | 105 | 线性流水线(owner 校验→phase 查询→空表 5 段 fallback→逐 phase 采样) | **本轮不拆,整体搬到 script_wizard.py**。fallback 段(@360-390)与采样段(@406-415)理论上可抽 `_fallback_phases(db, script_id)` / `_sample_anchors(rows)`,但属行为敏感的数值逻辑(步长 `round(n/12)`、尾锚点补全),为执行安全本轮整函数 verbatim 搬运;后续如需再拆,作为独立小 PR 配新单测。 |

其余 55-69 行函数(`api_script_timeline`、`api_script_recommend_identity`、`api_patch_canon` 62 行、`api_scripts_batch_import` 57 行)均低于阈值且为单一线性流程/分支调度,不拆。

---

## 7. 五大陷阱 + 循环导入/单例 逐条核对

**① patch 命名空间穿透** — Grep 实查全部 patch/直引点共 6 处(§3 表),其中真 mock patch 2 处:
- `monkeypatch.setattr(scripts_api.script_import, "import_script", ...)`:留守 `api_import_script` + 保留顶层 `from .. import script_import` ⇒ 不受影响。
- `patch.object(api_scripts_mod, "connect")`:留守 `api_script_modules_status` + 保留顶层 `from ..db import connect` ⇒ 不受影响。
- 结论:**0 个测试需要修改**。同时文件末尾加全量函数 re-export shim,兜住仓库外/动态引用。

**② Path(__file__) 错位** — 全文件 Grep `__file__`/`Path(`:**0 处**。无相对路径文件读写。无此风险。

**③ 执行代理顺手简化** — 本方案 §5 给出符号级搬运清单(符号名→目标文件→原行号区间),执行约束:逐字搬运;函数内局部 import(共 14 处,含 `__import__("binascii")`、`import base64 as _b64`、`from psycopg.types.json import Jsonb` ×2)一律留在函数体内原位;所有 task/Phase 历史注释随函数体一起搬;分节注释(`# ── … ──`)随簇搬运。执行后用 §9 的 AST diff 校验函数体哈希一致。

**④ 并行中间状态** — 批次划分(§8):新建 6 文件互不重叠可同批;`scripts.py` 与 `api/__init__.py` 各只在一个批次被改一次;严禁任何两个批次并行触碰同一文件。

**⑤ 孤儿/死代码** — `scripts.py` **保留**为"留守核心(A+B 簇)+ 函数 re-export shim",不删除;搬走的符号在原文件必须物理删除(由 §9 的"无重复 route 注册"校验兜底:同 path+method 在 `api.router.routes` 中只允许出现一次)。无其他孤儿文件产生。

**循环导入** — 新模块的依赖集 = `{fastapi, ..db, .._deps, ..knowledge, ..script_import}` ∪ 函数内延迟 import,全部是 scripts.py 今天已有的依赖,**无一 import `.scripts`**;`scripts.py` 末尾 shim import 新模块是单向边;`api/__init__.py` → 各子模块也是单向。依赖图无环。注意 shim 的 import 顺序副作用:`import platform_app.api.scripts` 会连带 import 6 个新模块并触发其 `@router` 注册——这正是现状语义(今天 import scripts 即注册全部 45 路由),行为等价。

**模块级单例/注册顺序** — 唯一的 import 副作用是 FastAPI 路由装饰器注册。次序分析:本文件 45 条路由中所有"字面量 vs `{script_id}` 参数"的潜在竞争(`/api/scripts/public` vs `/api/scripts/{id}/…`、`/api/scripts/import-pack` vs `/api/scripts/{id}/visibility` 等)均因**段数不同或字面段不同**而不存在真实重叠;唯一理论重叠是无意义 URL(如 `/api/scripts/public/chapters`)在新旧次序下都 422,行为等价。尽管如此,§5.8 的 include 顺序仍按原文件簇出现顺序排列(chapters→kb→wizard→public→overrides→review),并整体保持在 `_scripts_router` 之后、`_script_edit_router` 之前,与现状 `scripts → script_edit → imports` 的相对次序一致。`script_kb.py` 的 GET `/worldbook` 与 `script_edit.py` 的 PUT/POST/DELETE `/worldbook` 是同 path 异 method,Starlette 按 method 区分,维持现状不冲突。

---

## 8. 串行批次划分(可机械执行)

| 批次 | 动作 | 触碰文件 | 验证 |
|---|---|---|---|
| B1 | 新建 6 个模块,按 §5.1-5.6 逐字搬入(此批**只新增文件,不改任何旧文件**;6 个新文件互不重叠,如用子代理可并行,但推荐单代理串行) | 6 个新文件 | `python -m py_compile` 6 文件;`grep -c "@router"` 各文件路由数 = 5/9/3/7/4/4 |
| B2 | 改 `api/__init__.py`:加 6 行 import + 6 行 include(§5.8 顺序) | `api/__init__.py` | import 包不报错(此时路由会短暂双注册——属预期中间态,**B2/B3 之间不得运行服务或测试做验收**) |
| B3 | 改 `scripts.py`:物理删除已搬符号与其装饰器/分节注释;顶层 import 按 §5.7 调整;文件末尾加 re-export shim | `scripts.py` | `grep -c "@router" scripts.py` = 13 |
| B4 | 全量验证(§9) | 无 | 见下 |

执行代理要求:用 `Agent+model=sonnet` 做 B1/B3 的机械搬运(仓库既有规约),opus 只做 B4 验证;B1→B2→B3 严格串行。

---

## 9. 验证清单(B4)

1. **路由奇偶校验(最关键)**:拆分前先抓基线
   `python -c "from platform_app.api import router; rs=sorted((tuple(sorted(r.methods)), r.path) for r in router.routes); print(len(rs)); [print(m,p) for m,p in rs]"`
   拆后重跑,**集合必须逐字节相等,且无重复项**(重复 = ⑤ 删除不净或双注册)。
2. **AST 等价抽查**:对 6 个新文件每个搬入函数,`ast.dump` 与拆前原文件对应函数比对(忽略 lineno),哈希一致。
3. **定向测试**:
   - `pytest rpg/tests/test_script_import_api.py rpg/tests/integration/test_modules_status.py rpg/tests/integration/test_embed_status_pgvector.py rpg/tests/integration/test_upload_import_chain.py rpg/tests/integration/test_scripts_preview.py rpg/tests/integration/test_script_character_cards.py`(本机一次性 PG 配方见 project_rpg_local_testdb)
   - 然后全量 pytest 回归(基线 838+)。
4. **ruff/编译**:`python -m compileall rpg/platform_app/api`。
5. **前端零改动确认**:本方案不改任何 URL/method/响应结构,前端无需动。

---

## 10. 风险与缓解

| 风险 | 等级 | 缓解 |
|---|---|---|
| `test_modules_status` 的 `patch.object(模块, "connect")` 因函数搬迁失效 | 高(若搬) | **设计上规避**:B 簇整体留守,connect 顶层 import 不动 |
| `inspect.getsource` 源码断言因抽阶段函数失效 | 高(若拆函数) | `api_script_modules_status` 函数体一字不动 |
| 路由注册次序变化引发字面量/参数段匹配漂移 | 低 | §7 已逐对分析无真实重叠;include 顺序按原簇序;B4-1 奇偶校验兜底 |
| 执行代理顺手改写函数体/丢失函数内 import | 中 | §5 行号级清单 + B4-2 AST 哈希比对 |
| OSS cherry-pick 同步冲突面扩大(deploy-prod ↔ OSS main 双线) | 中 | 本重构独立成单 commit、不与功能改动混合;同步时按既有 oss-sync 流程整 commit cherry-pick,新文件无冲突历史,冲突面集中在 scripts.py 删除段,可接受 |
| 双注册中间态(B2 后、B3 前)被误用于验收 | 低 | 批次规则明示 B2/B3 间禁跑服务与测试 |
| `knowledge` 顶层 import 留守后成为"未用 import"被 lint 清理 | 低 | 加 `# noqa: F401` + 注释说明是 shim |

---

## 11. 拆后收益

- 最大文件从 1355 → ~400 行;7 个文件各自单一子域,新增剧本端点有明确落点(wizard 改动不再 diff 进 public 库代码)。
- 与 `script_edit.py`/`imports.py` 的既有拆分逻辑对齐,api/ 包形态统一为"一文件一子域 + __init__ 聚合"。
- 全部 6 个测试 pin 点零迁移、0 个测试修改、前端零改动、路由表逐字节不变 —— 整个方案可被路由奇偶校验一票验收。
