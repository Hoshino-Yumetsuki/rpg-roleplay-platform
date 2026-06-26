# 拆分方案:rpg/platform_app/workspace.py(1199 行)

- **判定**:needs-refactor
- **优先级**:medium(可工作、测试覆盖完整、非当前火点;但 4 类职责混杂 + 342 行巨型函数,继续往里加酒馆/向导功能只会更糟)
- **工作量**:M(1 个串行主批次 + 2 个可选后续批次)
- **方案日期**:2026-06-10
- **本方案只是计划,未做任何源码改动**(并行审计约束)

---

## 1. 现状结构图(精读结论)

```
workspace.py (1199 行) —— "用户工作区"伞形模块,实际混着 4 类职责
│
├── [A] 工作区保活 / 概览(~95 行)
│   ├── ensure_default(user_id)            @20   存量存档补 seed_tree/runtime 指针(不再造默认档)
│   └── overview(user)                     @56   /api/platform 概览聚合(显式列防 65MB jsonb de-TOAST)
│
├── [B] 游戏存档创建 + 初始快照流水线(~700 行,核心重量级)
│   ├── create_save(...)                   @116  权限闸→复核闸→快照→insert→身份卡落库→seed_tree→后台锚点 seed
│   ├── _build_initial_snapshot(...)       @451  ★342 行流水线:角色卡解析/秘密抽取/出生点/身份 overlay/
│   │                                            story_intent/player_origin/权限偏好 → state.data
│   ├── _OPENING_{LOCATION,OBJECTIVE,TIME}_RE  @799  开场 inline 元数据正则(仅本文件用)
│   ├── _is_doc_title_only / _has_opening_meta @804/@819  章节形态判定
│   ├── _apply_script_opening(...)         @830  真实首章/锚点章 → 地点/目标/时间/known_events/last_retrieval
│   ├── _DEFAULT_BERLIN_* 常量 + _scrub_berlin_default @977  DEFAULT_STATE 柏林硬编码清洗
│   └── _read_state_snapshot()             @1137 ☠ 死代码:全仓 0 调用(grep 实查,含自身文件内)
│
├── [C] 酒馆存档创建(~180 行)
│   ├── _ingest_character_book(...)        @269  SillyTavern character_book → save 级 worldbook overlay
│   └── create_tavern_save(...)            @317  无剧本 1:1 对话存档(persona 解析/first_mes/content_pack)
│
└── [D] 列表 / 分页 / 就绪度查询(~190 行)
    ├── scripts / scripts_page             @1011/@1017  剧本列表(显式列 + 订阅 union + readiness 摊平)
    ├── _READINESS_KEYS/_empty_readiness/_readiness_for_scripts @1060  5 维就绪度单 SQL 防 N+1
    ├── _SAVE_LIST_COLUMNS                 @1151  存档列表摘要列(achievements/engine.py 注释引用同源)
    └── saves / saves_page / save_detail   @1163/@1172/@1189
```

A/B/C/D 四簇之间唯一的内部耦合是:[D] 与 [A] 的 `ensure_default`(scripts/scripts_page/saves/saves_page 开头各调一次)、[B] 内 `create_save → _build_initial_snapshot → _apply_script_opening` 链。簇间无共享可变状态,无模块级单例(`log = get_logger(__name__)` 各自建即可),无注册表/装饰器副作用,**无 `Path(__file__)`(grep 实查 0 处)**。

## 2. 内聚簇分析与判定理由

判 **needs-refactor** 而非 acceptable 的理由:

1. **职责混杂**:HTTP 层(api/saves.py、api/scripts.py、api/auth.py、api/_deps.py、routes/tavern.py、tools_dsl/command_tools_saves.py)分别只消费其中一簇,却都被迫 import 整个 1199 行模块;改酒馆逻辑的 diff 和改列表分页的 diff 落在同一文件,审阅噪音大。
2. **`_build_initial_snapshot` 342 行**是典型顺序流水线(12 个互相独立的 state 写入阶段,见 §5),不是纯数据表,该拆。
3. **本包已有完全相同的拆分先例**:`platform_app/branches/`、`platform_app/db/`、`platform_app/knowledge/`、`platform_app/achievements/` 都是「大模块 → 子包 + `__init__.py` 全量 re-export」,且 `branches/__init__.py` 头部就写着 PATCH SAFETY 注释——直接照抄该惯例,迁移风险已被本仓库验证过一轮。
4. **外部消费面极干净**(grep 实查):全部调用方都是 `from platform_app import workspace` / `from .. import workspace` 后做 `workspace.X(...)` 属性访问,**全仓 0 处 `from workspace import X` 符号绑定**,0 处外部直调私有符号(只有 docstring/注释提及)。换成「同名子包 + `__init__` re-export」对所有调用方 100% 透明。

## 3. 目标布局(遵循 branches/、db/ 子包惯例)

```
rpg/platform_app/workspace/          ← 原 workspace.py 转为同名子包,import 路径不变
├── __init__.py      (~70 行)  纯 re-export shim + PATCH SAFETY 文档注释(抄 branches/__init__.py 风格)
├── core.py          (~115 行) [A] ensure_default + overview
├── save_create.py   (~520 行) [B] create_save + _build_initial_snapshot(死代码 _read_state_snapshot 不搬,见 §7)
├── opening.py       (~225 行) [B] 开场派生:3 个正则 + _is_doc_title_only + _has_opening_meta
│                              + _apply_script_opening + _DEFAULT_BERLIN_* + _scrub_berlin_default
├── tavern_save.py   (~195 行) [C] create_tavern_save + _ingest_character_book
└── listing.py       (~185 行) [D] scripts/scripts_page/saves/saves_page/save_detail
                               + _READINESS_KEYS/_empty_readiness/_readiness_for_scripts/_SAVE_LIST_COLUMNS
```

- 命名:子包内用 branches/ 同款的简短功能名(`seed.py`/`activation.py` 风格)。不叫 `tavern.py` 以免与 `routes/tavern.py`、`context_providers/tavern.py` 在 grep 时混淆,取 `tavern_save.py`。
- `save_create.py` 在批次 1 后仍 ~520 行,但已是**单一职责**(一条创建流水线);批次 2 的阶段函数拆分(§5)进一步把 `_build_initial_snapshot` 摊平,摊平后该文件不再有 >160 行的函数。

### `__init__.py` shim 内容(全量,可机械照写)

```python
"""platform_app.workspace — 用户工作区子包(由单文件 workspace.py 拆分)。

⚠️ PATCH SAFETY: 测试通过 mock.patch("platform_app.workspace.create_save") 与
   monkeypatch.setattr(_deps.workspace, "ensure_default", ...) 打补丁,
   补丁目标必须解析到本包属性。所有公开符号(含测试/文档引用的私有符号)
   都在此 re-export;外部调用方一律 `workspace.X(...)` 属性访问,补丁可穿透。
"""
from __future__ import annotations

from platform_app.workspace.core import ensure_default, overview
from platform_app.workspace.save_create import _build_initial_snapshot, create_save
from platform_app.workspace.opening import (
    _apply_script_opening,
    _has_opening_meta,
    _is_doc_title_only,
    _scrub_berlin_default,
)
from platform_app.workspace.tavern_save import _ingest_character_book, create_tavern_save
from platform_app.workspace.listing import (
    _SAVE_LIST_COLUMNS,
    _empty_readiness,
    _readiness_for_scripts,
    save_detail,
    saves,
    saves_page,
    scripts,
    scripts_page,
)

__all__ = [
    "ensure_default", "overview", "create_save", "create_tavern_save",
    "scripts", "scripts_page", "saves", "saves_page", "save_detail",
]
```

(子包内部模块互相引用用**绝对导入直指子模块**,如 `from platform_app.workspace.core import ensure_default`,不经过包 `__init__`,避免包初始化中途的部分初始化态;branches/ 子包即此风格。)

## 4. 可机械执行的搬运清单(符号 → 目标文件)

**铁律:逐字搬运,禁止改写任何函数体逻辑、注释、SQL、正则;唯一允许的改动是文件头 import 区(按下表换成绝对导入)和新增模块自己的 `log = get_logger(__name__)`。**

### 批次 1:模块级搬运(单文件→子包,必须一人串行完成)

| 原符号(@原起始行) | 目标文件 | 备注 |
|---|---|---|
| `ensure_default` @20 | core.py | |
| `overview` @56 | core.py | |
| `create_save` @116 | save_create.py | 体内 `_apply_script_opening` 经 `_build_initial_snapshot` 间接用 |
| `_ingest_character_book` @269 | tavern_save.py | |
| `create_tavern_save` @317 | tavern_save.py | |
| `_build_initial_snapshot` @451 | save_create.py | 体内 L656 调 `_apply_script_opening` → 改为顶部 `from platform_app.workspace.opening import _apply_script_opening`(无测试 patch 此符号,grep 实查) |
| `_OPENING_LOCATION_RE` `_OPENING_OBJECTIVE_RE` `_OPENING_TIME_RE` @799 | opening.py | 仅 opening.py 内用(grep 实查全仓无外部引用) |
| `_is_doc_title_only` @804 | opening.py | |
| `_has_opening_meta` @819 | opening.py | |
| `_apply_script_opening` @830 | opening.py | |
| `_DEFAULT_BERLIN_LOC/TIME/PHASE/OBJECTIVE_FRAG` @971 | opening.py | |
| `_scrub_berlin_default` @977 | opening.py | |
| `scripts` @1011, `scripts_page` @1017 | listing.py | |
| `_READINESS_KEYS` @1060, `_empty_readiness` @1063, `_readiness_for_scripts` @1073 | listing.py | |
| `_read_state_snapshot` @1137 | **不搬,删除** | ☠ 死代码:grep 全仓(含本文件)0 调用;§7⑤ 有判据 |
| `_SAVE_LIST_COLUMNS` @1151 | listing.py | achievements/engine.py:53 仅注释引用,仍 re-export 保险 |
| `saves` @1163, `saves_page` @1172, `save_detail` @1189 | listing.py | |

### 各新文件头部 import(原文件 L1-L17 按需分发;原相对导入升包后须改写,逐处列出)

原 workspace.py 顶部(模块级):
```python
from . import branches, runtime                      # → 子包内变 from platform_app import branches, runtime
from .db import connect, cursor_id, expose, init_db, limit_value, page_payload
from .db import status as db_status                  # → from platform_app.db import ...
from .security import public_user                    # → from platform_app.security import public_user
```
分发:
- **core.py**:`get_logger, SAVE_FILE` + `platform_app import branches, runtime` + `platform_app.db import connect, expose, init_db; status as db_status` + `platform_app.security import public_user`
- **save_create.py**:`Jsonb, get_logger, SAVE_FILE` + `state.core import _extract_secret_sections, _strip_secret_sections` + `platform_app import branches` + `platform_app.db import connect, expose, init_db` + `platform_app.workspace.opening import _apply_script_opening`
- **opening.py**:`re, get_logger?(体内无 log,可不要)` + `platform_app.db import connect`
- **tavern_save.py**:`Jsonb, get_logger, SAVE_FILE` + `platform_app import branches` + `platform_app.db import connect, expose, init_db`
- **listing.py**:`get_logger?(无 log 调用,可不要)` + `platform_app.db import connect, cursor_id, expose, limit_value, page_payload` + `platform_app.workspace.core import ensure_default`

### 函数体内的**惰性 import 必须原位保留**(逐处列出,严禁提升到模块顶部——它们是防环/防启动开销的刻意设计)

| 位置(原行号) | 惰性 import | 新归属文件 |
|---|---|---|
| create_save L253-255 | `import threading` + `from agents.anchor_seed_agent import seed_anchors_for_save` | save_create.py |
| create_tavern_save L337-341 | `import copy as _copy` + `from context_providers.registry import DEFAULT_TAVERN_MANIFEST` + `from . import user_cards as _ucards` → **改 `from platform_app import user_cards as _ucards`** | tavern_save.py |
| create_tavern_save L397 | `from state import GameState` | tavern_save.py |
| _build_initial_snapshot L465 | `from state import GameState` | save_create.py |
| _build_initial_snapshot L475/L544/L554/L574 | `from . import user_cards as _ucards` → **改 `from platform_app import user_cards as _ucards`**(4 处) | save_create.py |
| _build_initial_snapshot L563 | `from . import knowledge as _know` → **改 `from platform_app import knowledge as _know`** | save_create.py |
| _build_initial_snapshot L742 | `from datetime import datetime as _dt` | save_create.py |

> 注意 `from . import user_cards` 这类**包内相对导入在子包里语义会变**(`.` 从 platform_app 变成 platform_app.workspace),这是本次搬运里唯一一类"不改就炸"的行级改动,共 **6 处**(上表加粗),全部机械替换为绝对导入即可。

## 5. ≥80 行巨型函数逐个评估

| 函数 | 行数 | 类型判定 | 结论 |
|---|---|---|---|
| `_build_initial_snapshot` | 342 | **流水线型**(12 个顺序独立的 state 写入阶段,各阶段 try/except 自兜底) | **该拆**(批次 2) |
| `create_save` | 151 | 流水线型(闸→快照→insert→身份卡落库→seed→后台锚点) | 值得轻拆(批次 3,可选) |
| `_apply_script_opening` | 137 | 流水线型但内聚度高(选章→解析→写回,共享 chosen/content 局部量,注释密) | **不强拆**:阶段间数据流粗,拆了只是搬注释;保持原样 |
| `create_tavern_save` | 132 | 流水线型 | 可选拆 persona 解析,收益小,**默认不拆** |

### 批次 2(可选,推荐):`_build_initial_snapshot` 阶段化(全部留在 save_create.py 内,不跨文件)

按原函数体的天然段落切阶段函数,**每段逐字剪切**,签名显式传递共享量(`_extra_card_fields`/`_extra_private_secrets` 两个收集器跨 S2 各分支共享,作为参数传入):

| 阶段函数(新私有名) | 原行段 | 签名 |
|---|---|---|
| `_resolve_default_character` | L471-485(task 91 默认 persona 回退) | `(user_id, new_card, character) -> character`(注意原逻辑会**重绑 character**,返回值必须接住) |
| `_resolve_card_fields` | L491-583(含 `_absorb_card_secrets` 闭包整体随段搬入) | `(user_id, script_id, new_card, character) -> tuple[name, role, background, extra_fields: dict, private_secrets: list]` |
| `_apply_player_setup` | L585-638(setup_player + script_card POV 绑定 + extra_fields/secrets 写入) | `(state, name, role, background, character, extra_fields, private_secrets) -> None` |
| `_apply_birthpoint` | L647-678(prefer_chapter 推导 + timeline 覆盖;`_apply_script_opening` 调用留在主函数里夹在两段之间,顺序不可变) | 拆两半:`_birthpoint_prefer_chapter(birthpoint) -> int|None` + `_apply_birthpoint_overlay(state, birthpoint) -> None` |
| `_apply_identity_overlay` | L688-726(v27 身份卡 + npc_card 魂穿改名) | `(state, identity, player_origin) -> None` |
| `_apply_player_fallbacks` | L729-738(无名者占位) | `(state) -> None` |
| `_apply_story_intent` | L740-758(player_private + dual-write) | `(state, story_intent) -> None` |
| `_apply_player_origin` | L760-772(4 档出身 + identity_known) | `(state, player_origin, identity, identity_known) -> None` |
| `_apply_perm_mode_pref` | L774-790(Bug 5 用户偏好注入) | `(state, user_id) -> None` |

主函数瘦身为 ~40 行编排器,**阶段调用顺序必须与原行序完全一致**(scrub→opening 在 birthpoint 覆盖之前、identity 在 birthpoint 之后、fallback 在 identity 之后……顺序就是语义)。无任何测试 patch `_build_initial_snapshot` 的内部(grep 实查只有 docstring 提及),阶段函数全私有,无 shim 负担。

### 批次 3(可选):create_save 轻拆(留在 save_create.py 内)

- L179-242 身份卡落库 + 绑定 → `_persist_identity_binding(db, save, snapshot, identity, new_card, character) -> None`
- L243-265 后台锚点 seed → `_schedule_anchor_seed(save_id) -> None`

## 6. 测试 patch 点清单(陷阱①,Grep 实查列全)

外部 patch/monkeypatch 直指 workspace 符号的,全仓共 **3 处**:

| # | 文件:行 | 形式 | 拆分后是否存活 |
|---|---|---|---|
| 1 | `rpg/tests/integration/test_console_assistant.py:155` | `mock.patch("platform_app.workspace.create_save", ...)` | ✅ 调用方 `tools_dsl/command_tools_saves.py` 是 `from platform_app import workspace as _ws; _ws.create_save(...)` 运行时属性访问 → patch 落在包 `__init__` 属性上,穿透成立 |
| 2 | `rpg/tests/unit/test_ensure_default_once_guard.py:22` | `monkeypatch.setattr(_deps.workspace, "ensure_default", ...)` | ✅ `_deps.workspace` 与 `platform_app.workspace` 是同一包对象;`_deps.py:200` 调 `workspace.ensure_default(uid)` 运行时属性访问 |
| 3 | `rpg/tests/unit/test_ensure_default_once_guard.py:38` | 同上 | ✅ 同上 |

补充核查(都不构成 patch 点,但与穿透性相关):
- **listing.py 内部调 `ensure_default`**(scripts/scripts_page/saves/saves_page 4 处)改为直绑 `from platform_app.workspace.core import ensure_default` 后,包属性级补丁**不会**穿透这 4 个内部调用——已 grep 确认**没有任何测试**依赖"patch ensure_default 后影响 scripts_page 行为"(仅 #2/#3 经 `_deps` 间接层测,不经 listing)。可接受;若想绝对保险,listing.py 改用 `import platform_app.workspace.core as _core; _core.ensure_default(uid)`(模块属性访问,monkeypatch `_core.ensure_default` 仍可拦,且不依赖包 `__init__` 初始化完成)。**推荐后者写法**。
- `_build_initial_snapshot` 内调 `_apply_script_opening`:无测试 patch,直绑导入安全。
- 其余测试(test_tavern_mode、test_branches_continue_contract、test_branch_seed_isolation、test_opening_no_default_leak、test_qa_fixes_birthpoint_protagonist、test_tavern_tool_user_fencing、test_player_private、test_new_save_uses_script_opening)只**真调** `workspace.create_save/create_tavern_save/ensure_default`,不 patch → re-export 即兼容,零改动。

## 7. 五大陷阱逐条核对

1. **patch 命名空间穿透**:见 §6,3 个 patch 点全部经包 `__init__` re-export 存活;0 个测试文件需要改。
2. **`Path(__file__)` 错位**:grep 实查 workspace.py **0 处** `Path(__file__)`、0 处相对文件路径拼接(`SAVE_FILE` 来自 `state` 包常量,与本文件位置无关)。唯一位置敏感点是 §4 列出的 **6 处 `from . import ...` 相对导入**(模块级 3 行 + 函数级惰性 6 处中含相对的 5 处),升入子包后 `.` 的指向改变,必须按清单机械替换为绝对导入。
3. **执行代理顺手简化**:本方案给出符号级搬运表(§4)与阶段切割行段表(§5),执行时**逐字剪切粘贴**;特别警告:`_build_initial_snapshot` 里大量 `try/except Exception: pass` 兜底块、`_absorb_card_secrets` 闭包、L594 用函数参数 `character` 重判的注释("局部 kind/cid 此处不在作用域")都是带血教训,一个字都不准"优化"。执行子代理用 sonnet 时把本节原文贴进指令。
4. **并行中间状态**:三个批次**严格串行**,且批次 1 是"单文件 → 5 个新文件 + 删 1 个旧文件"的原子操作,不可再切分给两个并行代理;批次 2/3 只动 save_create.py 一个文件。每批次结束跑 §8 验证门后才允许进下一批。
5. **孤儿文件/死代码**:旧 `workspace.py` **删除**(被同名子包取代,不是留 shim 文件——shim 职责由子包 `__init__.py` 承担);`_read_state_snapshot` 是确认的死代码(grep 全仓含自身 0 调用,职责已被 `_build_initial_snapshot` 取代,其 docstring 描述的"安全:不读全局 SAVE_FILE"语义已由后者 L464-468 同款代码覆盖)→ **批次 1 直接不搬即删**,在 commit message 里注明。`rpg/claude_design_upload/current_code/` 下的 api.py 是历史快照副本,不在本次范围、不改。

**循环导入核查**:workspace 依赖 branches/runtime/db/security/user_cards/knowledge/state/agents/context_providers;grep 实查这些模块**无一回头 import workspace**;`platform_app/__init__.py` 仅 docstring 无 import。子包内部 core←listing 单向、opening←save_create 单向,无环。惰性 import 保持惰性(§4)后,新边界不引入任何 import 环。

**模块级单例/副作用核查**:仅 `log = get_logger(__name__)`(各新模块自建,logger 名变化只影响日志前缀,无功能语义)与纯正则/字符串常量;无注册表、无装饰器注册、无 import 时 DB 访问(`init_db()` 全在函数体内)。

## 8. 批次划分与验证门

| 批次 | 内容 | 验证门 |
|---|---|---|
| 1(必做) | 建 `workspace/` 子包,按 §4 搬运 + 删旧 workspace.py + 删 `_read_state_snapshot` | ① `python -m py_compile` 全部新文件;② `python -c "from platform_app import workspace; workspace.create_save"` 冒烟(rpg/ 为 cwd);③ 定向 pytest:`test_console_assistant test_ensure_default_once_guard test_tavern_mode test_tavern_tool_user_fencing test_player_private test_opening_no_default_leak test_new_save_uses_script_opening test_branches_continue_contract test_branch_seed_isolation test_qa_fixes_birthpoint_protagonist test_new_save_applies_card`;④ 全量 pytest |
| 2(可选推荐) | `_build_initial_snapshot` 阶段化(§5,仅动 save_create.py) | 同上 ③④,重点 test_player_private / test_qa_fixes_birthpoint_protagonist / test_opening_no_default_leak |
| 3(可选) | create_save 轻拆(仅动 save_create.py) | 同上 ③④,重点 test_console_assistant / 身份卡相关集成测 |

## 9. 风险汇总

- **低**:外部接口零变化(包路径同名、全属性访问消费、3 个 patch 点全存活)。
- **需手工注意**:6 处相对导入改绝对(§4 加粗项)——漏一处即 ImportError,但 py_compile + 冒烟门必抓。
- **批次 2 的真实风险**:阶段函数签名传递 `character` 重绑值与两个收集器列表;若执行代理擅自把"重绑后的 character"丢掉,task 91 默认 persona 回退会静默失效(测试 test_new_save_applies_card / test_qa_fixes 会抓,但要确保跑)。
- **不做的代价**:该文件是存档创建主路径,酒馆 v2 与新手向导仍在迭代,继续单文件膨胀会让下一次 LLM 辅助修改的上下文窗口与冲突面持续变大。
