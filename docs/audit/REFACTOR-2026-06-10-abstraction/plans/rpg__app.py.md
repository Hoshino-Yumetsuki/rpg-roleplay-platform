# rpg/app.py 函数抽象层体检 + 拆分方案

- 目标文件:`rpg/app.py`(2233 行,61 个顶层定义)
- 判定:**needs-refactor**,优先级 medium,工作量 M(机械搬运为主,可委派 sonnet 子代理串行执行)
- 本方案为纯规划文档,**未改动任何源码**(并行审计工作流正在读源码)。

---

## 1. 体检结论(一段话)

app.py 名为 FastAPI 组装根,实为「组装根 + 七个互不相干的共享内核」混居:用户偏好门控、验收验证、鉴权/部署模式、按用户运行时缓存(state/GM/run-id/stop 信号)、模型目录视图/脱敏、chat 持久化与附件、5E 规则桥接胶水、控制台助手 backend 解析,全部堆在一个文件里。Phase 1.1/1.2 已把**路由**搬去 `routes/`,但刻意留下「routes 调用时 `from app import X` 惰性导入」的设计 —— **app 模块命名空间是测试 monkeypatch 的公开契约**(routes/game.py:655 有明文注释)。因此结论是:应拆,但 app.py 必须保留为 re-export 门面,routes 一行不动;拆出 8 个内聚模块后 app.py 回到 ~290 行纯组装根。

为什么不是 acceptable:这不是追加式账本/纯数据表 —— QA 修复(出生锚点、模型解析、缓存一致性、规则去重)反复落在此文件不同簇上,2200 行混居让每次修复都要在七种职责间导航;且 `_ensure_loaded`/`_payload`/`_execute_rules_action` 三个热点分属三个完全无关的领域。

---

## 2. 现状结构图(按内聚簇)

```
rpg/app.py (2233 行)
├─ [ROOT] 组装根(必须留在 app.py)
│   L29-35   _APP_DIR + load_dotenv ×2 + sys.path.insert   ← import 副作用,顺序敏感
│   L37-82   顶层 imports(其中大量 noqa: F401 = 既有 re-export 惯例)+ app = FastAPI()
│   L460-498 configure_app + include_router ×14
│   L502-537 _SPAStaticFiles(20 行)+ 静态挂载(_FRONTEND_ROOT = Path(__file__)...)
│   L541     _bootstrap_init_db re-export(core/startup.py lifespan 惰性取用)
│   L543     _startup_auth_banner() 调用
│   L2227-   __main__ uvicorn 入口
├─ [A] 验收验证(145 行):_verify_acceptance_rule(85) / _verify_acceptance(60)
├─ [B] 用户偏好门控(~135 行):_prefs_cache_var / _get_user_preferences_cached /
│       _clear_prefs_cache / _is_set_parser_enabled / _is_extractor_enabled /
│       _is_black_swan_enabled / _clarify_threshold / _acceptance_verifier_mode /
│       _chat_max_tokens + CHAT_MAX_TOKENS_{DEFAULT,MIN,MAX}
├─ [C] 鉴权与部署模式(~95 行):_deployment_mode / _LOCAL_MODES / _SERVER_MODES /
│       _api_auth_required / _startup_auth_banner / _require_api_user / _resolve_persist_target
├─ [D] 按用户运行时缓存(~400 行):_lru_set/_lru_get/_LRU_MAXSIZE、
│       7 个 OrderedDict 注册表 + _state_lock/_run_lock、run-id/stop 信号 5 函数、
│       _user_key / _selfheal_player_from_save_snapshot(64) / _ensure_loaded(130) /
│       _invalidate_user_cache / _get_gm / _get_sub_gm(59) / _backup_save
├─ [E] 模型目录视图 + /api/state payload(~290 行):_session_model_app_view /
│       _resolve_user_default_model_view / _payload(80) / _user_credentialed_api_ids /
│       _redact_catalog / _redact_tools / _MCP_SECRET_FIELDS / _check_probe_permission /
│       ROLES / PRESET
├─ [F] chat 持久化 + 附件 + 斜杠命令(~380 行):_persist_chat_turn(75) /
│       _build_usage_payload(65) / _mark_context_run / _persist_runtime_checkpoint /
│       _build_turn_context / _active_script_id / _sse / _split_inline_assignment /
│       _save_attachments(41) / _text_preview_for_attachment / _message_with_attachments /
│       _command_response(62) + UPLOAD_DIR/MAX_ATTACHMENT_BYTES/MAX_ATTACHMENTS_PER_REQUEST
├─ [G] 5E 规则桥接胶水(~530 行):L1608 `import modules`(注册表副作用)+
│       rules_bridge 13 个 _rb_* 别名 import + _coerce_rule_seed / _canonicalize_exit_target(49) /
│       _execute_rules_action(128) / _chat_rule_candidates(60) / _apply_chat_rule_candidates(44) /
│       _rule_results_prompt(67) / _rules_payload / _append_rules_receipt /
│       _clear_pending_questions_after_rule_action / _room_receipt / _roll_line /
│       _action_receipt / _encounter_receipt
└─ [H] 控制台助手 backend 解析(70 行):_resolve_console_assistant_backend
```

### 关键约束(全方案的地基):app 命名空间 = monkeypatch 契约

- routes/* 全部在**函数体内**做 `from app import X` / `import app as _self_mod`(routes/game.py:511),
  并显式注释「注入 run_context_agent 让测试 monkeypatch (app.run_context_agent = ...) 能透到 pipeline」(routes/game.py:655)。
- 测试大量 `ui_mod._get_gm = stub`、`_app._state_by_user[uid] = ...` 直接 setattr/改 app 模块属性。
- 推论:**新模块绝不 import app(防环);routes/* 本轮一行不改;app.py 对外符号 100% re-export**。
  re-export 后:dict/lock 是同一对象(突变可见 ✓);setattr `app._get_gm` 仍被 routes 调用时导入读到 ✓;
  唯一破坏类 = 「测试 patch app.A,被测函数 B 与 A 同迁一个新模块,B 体内对 A 的名字解析落到新模块全局」——
  此类共 9 处,已逐一列在 §6。

---

## 3. 目标布局

| 新文件 | 簇 | 估行数 | 命名依据 |
|---|---|---|---|
| `rpg/user_prefs.py` | B | ~135 | rpg/ 根已有扁平模块惯例(state_repository.py、game_policy.py 等) |
| `rpg/agents/acceptance_verifier.py`(追加) | A | +150 | LLM 半实现(`verify_acceptance_llm`)本就在此文件;rule 版与 dispatcher 归位 |
| `rpg/auth_gate.py` | C | ~95 | 扁平模块 |
| `rpg/runtime_cache.py` | D | ~400 | 扁平模块;名称呼应注释「按用户运行时缓存」 |
| `rpg/state_views.py` | E | ~290 | 扁平模块;/api/state payload + catalog 脱敏视图 |
| `rpg/chat_helpers.py` | F | ~380 | 扁平模块;呼应既有 chat_pipeline.py(「chat 路由辅助」) |
| `rpg/rules_actions.py` | G | ~530 | 扁平模块;rules_bridge/ 是底层包,此为 app 级胶水 |
| `rpg/console_assistant/backend_resolver.py` | H | ~75 | console_assistant/ 包已存在(_state.py、llm_loop.py 等) |

`rpg/app.py` 残留(~290 行):组装根([ROOT] 全部)+ 一个集中 re-export 块(见 §5.9)。
**保留为 re-export shim,永不删除**(tools_dsl/command_tools_saves.py、platform_app/api/saves.py、
platform_app/frontend_routes.py、core/startup.py、scripts/、所有 routes/、30+ 测试都依赖 `import app`)。

依赖方向(已逐模块核查,无环):

```
user_prefs ──────→ core.config, platform_app.db(惰性)
acceptance_verifier → (自身已有依赖;dispatcher 体内 self-import 惰性,见 §5.2)
auth_gate ───────→ core.config, platform_app.api.current_user, platform_app.{runtime,branches}(惰性)
runtime_cache ───→ state, agents.gm, model_registry, core.llm_backend(惰性), platform_app.*(惰性)
state_views ─────→ runtime_cache, user_prefs, model_registry, tools_dsl.tool_registry, state, platform_app.*(惰性)
chat_helpers ────→ state, agents.gm(仅类型), context_engine, platform_app.*, save_phase_manager(惰性)
rules_actions ───→ modules(副作用), rules_bridge, rules.seed_policy(惰性), state
backend_resolver → agents.gm, model_registry, core.llm_backend/platform_app.db(惰性)
app ─────────────→ 以上全部(re-export)+ routes(include_router)
```

核查结论:`modules/`、`rules_bridge/`、`rules/`、`agents/`、`console_assistant/`、`gm_serving/`、
`context_engine`、`context_providers/` **均不 import app**(grep 实查);platform_app 与 tools_dsl
只在函数体内惰性 `import app`,不构成模块级环。

---

## 4. ≥80 行巨型函数逐个评估

| 函数 | 行数 | 类型 | 是否拆阶段 | 理由 |
|---|---|---|---|---|
| `_verify_acceptance_rule` | 85 | 单一算法(bigram 匹配,含 `_key_bigrams` 闭包) | **不拆** | 非流水线;行数一半是踩坑注释(否定条款假阳性史),拆散即毁档案价值 |
| `_ensure_loaded` | 130 | 流水线(缓存校验→加载→selfheal→GM 优先级链→BYOK 守卫) | **本轮不拆,搬运后另立后续任务** | 值得拆 `_cache_is_stale`/`_load_state_for`/`_build_gm_for` 三阶段,**但** 2 个源码文本 grep 测试 pin 死了 `_ensure_loaded` 函数体必须含 `read_runtime`/`_state_save_id_by_user`/`_rt_commit`/`commit_drift` 字面(§6.B);拆阶段=同时重写 7 条 grep 断言,与「逐字搬运」批次混做违反陷阱③,单独成批后续做 |
| `_payload` | 80 | 顺序组装(模型视图→ctx_window→app 块→catalog→save 信息),段间已有独立 try/except | **不拆** | 各段已隔离,无共享中间态可抽;拆了反增参数传递 |
| `_execute_rules_action` | 128 | **kind 分发表**(if/elif 每 kind 一段,互不耦合) | **不拆** | 纯数据表型;若优化应改 dict-dispatch,但那是改写逻辑(违反逐字搬运),且 grep 测试 pin 函数体,留作后续可选 |

---

## 5. 可机械执行搬运清单(逐字搬运,禁止改写任何函数体逻辑)

> 执行规则(给执行代理的硬约束):
> 1. **逐字复制**源行区间到目标文件,只允许动「模块级 import 补齐」,函数体一个字符不许动(含注释、空行、踩坑说明)。
> 2. 函数体内的惰性 import(`from platform_app.db import connect` 等)**原样保留**,不许上提为模块级。
> 3. 每搬完一个模块,app.py 对应区间删除并在 re-export 块加一行;立即跑该批验证闸再进下一批。

### 5.1 `rpg/user_prefs.py`(新建)
| 符号 | 源行 |
|---|---|
| `import contextvars as _contextvars` + `_prefs_cache_var` 定义(含 P0-3 注释) | 243-248 |
| `_get_user_preferences_cached` | 251-275 |
| `_clear_prefs_cache` | 278-280 |
| `_is_set_parser_enabled` | 283-288 |
| `_is_extractor_enabled` | 291-296 |
| `_is_black_swan_enabled` | 299-311 |
| `_clarify_threshold` | 314-336 |
| `_acceptance_verifier_mode` | 339-354 |
| `CHAT_MAX_TOKENS_DEFAULT/MIN/MAX` | 357-359 |
| `_chat_max_tokens` | 362-378 |

模块头需补:`from core.logging import get_logger`(若搬入体内有 log 引用 — 实查:此簇无 log 调用,不需要)。无其他模块级依赖。

### 5.2 `rpg/agents/acceptance_verifier.py`(追加到文件尾)
| 符号 | 源行 | 注意 |
|---|---|---|
| `_verify_acceptance_rule` | 94-178 | 体内 `import re as _re` 原样保留 |
| `_verify_acceptance` | 181-240 | 体内 `from agents.acceptance_verifier import verify_acceptance_llm` **原样保留**(自 import 合法且保住 `patch("agents.acceptance_verifier.verify_acceptance_llm")` 既有 patch 点);体内 `log.warning` → 该文件已有自己的 logger,确认其模块级 `log` 存在,否则补 `log = get_logger(__name__)` |

### 5.3 `rpg/auth_gate.py`(新建)
| 符号 | 源行 |
|---|---|
| `_LOCAL_MODES` / `_SERVER_MODES` | 85-86 |
| `_deployment_mode` | 89-91 |
| `_api_auth_required` | 381-401 |
| `_startup_auth_banner` | 404-414 |
| `_require_api_user` | 417-428 |
| `_resolve_persist_target` | 431-457 |

模块头需补:`from fastapi import HTTPException, Request`、`from typing import Any`、
`from core.logging import get_logger; log = get_logger(__name__)`、
`from platform_app.api import current_user as platform_current_user`、
`from platform_app import branches as platform_branches`、`from platform_app import runtime as platform_runtime`。

### 5.4 `rpg/runtime_cache.py`(新建)
| 符号 | 源行 |
|---|---|
| `_LRU_MAXSIZE` + P1-2 注释 | 546-550 |
| `_lru_set` / `_lru_get` | 553-567 |
| 7 个 OrderedDict + 2 个 Lock + `_last_run_id`(含全部注释) | 570-588 |
| `_next_run_id_locked` | 591-602 |
| `_get_run_state` / `_current_run_id` / `_stop_user` / `_is_stop_requested_global` / `_user_key` | 605-656 |
| `_selfheal_player_from_save_snapshot` | 668-731 |
| `_ensure_loaded` | 734-863 |
| `_invalidate_user_cache` | 866-874 |
| `_get_gm` | 877-879 |
| `_get_sub_gm` | 882-940 |
| `_backup_save` | 943-951 |

模块头需补:`json/shutil/time`、`OrderedDict`、`Event, Lock`、`Any`、
`from agents.gm import GameMaster`、`from state import SAVE_FILE, GameState`、
`from model_registry import selected_model`、`log = get_logger(__name__)`。
**注意**:`_state_save_id_by_user: OrderedDict[int, int]` 等类型声明行必须原样保留
(测试用正则 pin 了声明形状,见 §6.B)。

### 5.5 `rpg/state_views.py`(新建)
| 符号 | 源行 | 注意 |
|---|---|---|
| `ROLES` / `PRESET` | 658-665 | |
| `APP_TITLE = _app_title_cfg()` | 新增一行 | 从 `core.config import app_title as _app_title_cfg` 计算;app.py 改为 `from state_views import APP_TITLE`(纯 env 读,值与现状一致) |
| `_session_model_app_view` | 954-986 | |
| `_resolve_user_default_model_view` | 989-1016 | |
| `_payload` | 1019-1098 | 体内引用 `_ensure_loaded`(改从 `runtime_cache` 模块级 import)、`load_catalog_for_user/selected_model`(model_registry)、`tool_payload`(tools_dsl.tool_registry)、`SAVE_FILE`(state)、`_get_user_preferences_cached`(user_prefs) |
| `_user_credentialed_api_ids` | 1101-1121 | |
| `_redact_catalog` | 1124-1165 | |
| `_MCP_SECRET_FIELDS` | 1168 | |
| `_redact_tools` | 1171-1190 | |
| `_check_probe_permission` | 1573-1601 | 体内惰性 import 原样保留 |

### 5.6 `rpg/chat_helpers.py`(新建,**必须直接放 rpg/ 根**,见 §7)
| 符号 | 源行 | 注意 |
|---|---|---|
| `APP_DIR = Path(__file__).parent` + `UPLOAD_DIR` + `MAX_ATTACHMENT_BYTES` | 78-80 | 见 §7 Path 语义说明 |
| `_persist_chat_turn` | 1194-1268 | 引用 `platform_branches/platform_knowledge/SAVE_FILE` → 模块级 import |
| `_build_usage_payload` | 1271-1335 | `GameMaster` 仅类型注解 → `from agents.gm import GameMaster` |
| `_mark_context_run` | 1338-1350 | |
| `_persist_runtime_checkpoint` | 1353-1363 | |
| `_build_turn_context` | 1366-1379 | `from context_engine import build_context_bundle` |
| `_active_script_id` | 1382-1415 | |
| `_sse` | 1418-1419 | |
| `_split_inline_assignment` | 1422-1427 | |
| `MAX_ATTACHMENTS_PER_REQUEST` | 1430 | |
| `_save_attachments` | 1433-1473 | 引用 UPLOAD_DIR/MAX_ATTACHMENT_BYTES(同文件)|
| `_text_preview_for_attachment` | 1476-1485 | |
| `_message_with_attachments` | 1488-1505 | |
| `_command_response` | 1508-1569 | |

### 5.7 `rpg/rules_actions.py`(新建)
| 符号 | 源行 | 注意 |
|---|---|---|
| `import modules as _rules_module_registry` + IP 免责注释 | 1605-1608 | **副作用 import 必须随迁**;modules/ 是纯数据目录包(已核,无注册顺序依赖、不 import app),提前到 app.py import 链头部无害 |
| rules_bridge 13 个 `_rb_*` 别名 import 块 | 1609-1646 | 原样保留别名(函数体内全用 `_rb_*` 名) |
| `_coerce_rule_seed` | 1650-1654 | |
| `_canonicalize_exit_target` | 1657-1705 | |
| `_execute_rules_action` | 1708-1835 | |
| `_chat_rule_candidates` | 1838-1897 | 函数体 grep-pin,逐字搬(§6.C) |
| `_apply_chat_rule_candidates` | 1900-1943 | 同上 |
| `_rule_results_prompt` | 1946-2012 | |
| `_rules_payload` | 2015-2023 | |
| `_append_rules_receipt` | 2026-2034 | |
| `_clear_pending_questions_after_rule_action` | 2037-2050 | |
| `_room_receipt` / `_roll_line` / `_action_receipt` / `_encounter_receipt` | 2053-2138 | |

模块头需补:`re`、`Any`、`from state import GameState`。

### 5.8 `rpg/console_assistant/backend_resolver.py`(新建)
| 符号 | 源行 |
|---|---|
| `_resolve_console_assistant_backend` | 2149-2218 |

模块头需补:`Any`、`from agents.gm import GameMaster`、`from model_registry import selected_model`。

### 5.9 `rpg/app.py` 残留 + re-export 块(替换被搬区间)

在 L543 `_startup_auth_banner()` 调用之前插入集中 re-export 块(全部 `# noqa: F401`),
覆盖 §5.1-5.8 全部公开符号 —— **下列每个符号都有外部消费者(AST 实查),一个都不能漏**:

```python
# ── 拆分后的 re-export 门面:app 命名空间是 routes 惰性导入 + 测试 monkeypatch 的公开契约,
# ── 以下符号的权威实现已迁至各模块,此处仅 re-export,新代码请直接 import 新模块。
from user_prefs import (  # noqa: F401
    CHAT_MAX_TOKENS_DEFAULT, CHAT_MAX_TOKENS_MAX, CHAT_MAX_TOKENS_MIN,
    _acceptance_verifier_mode, _chat_max_tokens, _clarify_threshold,
    _clear_prefs_cache, _get_user_preferences_cached, _is_black_swan_enabled,
    _is_extractor_enabled, _is_set_parser_enabled, _prefs_cache_var,
)
from agents.acceptance_verifier import _verify_acceptance, _verify_acceptance_rule  # noqa: F401
from auth_gate import (  # noqa: F401
    _api_auth_required, _deployment_mode, _LOCAL_MODES, _SERVER_MODES,
    _require_api_user, _resolve_persist_target, _startup_auth_banner,
)
from runtime_cache import (  # noqa: F401
    _LRU_MAXSIZE, _backup_save, _current_run_id, _ensure_loaded, _get_gm,
    _get_run_state, _get_sub_gm, _gm_by_user, _invalidate_user_cache,
    _is_stop_requested_global, _lru_get, _lru_set, _next_run_id_locked,
    _run_id_by_user, _run_lock, _selfheal_player_from_save_snapshot,
    _state_by_user, _state_commit_id_by_user, _state_lock,
    _state_mtime_by_user, _state_save_id_by_user, _stop_events_by_user,
    _stop_user, _sub_gm_by_user, _user_key,
)
from state_views import (  # noqa: F401
    APP_TITLE, PRESET, ROLES, _check_probe_permission, _MCP_SECRET_FIELDS,
    _payload, _redact_catalog, _redact_tools, _resolve_user_default_model_view,
    _session_model_app_view, _user_credentialed_api_ids,
)
from chat_helpers import (  # noqa: F401
    MAX_ATTACHMENT_BYTES, MAX_ATTACHMENTS_PER_REQUEST, UPLOAD_DIR,
    _active_script_id, _build_turn_context, _build_usage_payload,
    _command_response, _mark_context_run, _message_with_attachments,
    _persist_chat_turn, _persist_runtime_checkpoint, _save_attachments,
    _split_inline_assignment, _sse, _text_preview_for_attachment,
)
from rules_actions import (  # noqa: F401
    _action_receipt, _append_rules_receipt, _apply_chat_rule_candidates,
    _canonicalize_exit_target, _chat_rule_candidates,
    _clear_pending_questions_after_rule_action, _coerce_rule_seed,
    _encounter_receipt, _execute_rules_action, _roll_line, _room_receipt,
    _rule_results_prompt, _rules_payload,
)
from console_assistant.backend_resolver import _resolve_console_assistant_backend  # noqa: F401
```

app.py 顶部既有的第三方 re-export(`GameState/SAVE_FILE/selected_model/load_model_catalog/
delete_model/select_model/upsert_*/tool_payload/*_mcp_server/import_skill_bundle/
retrieve_context/run_context_agent/platform_branches/platform_knowledge/GameMaster/
load_catalog_for_user/_bootstrap_init_db`)**全部原样保留** —— routes 与测试在用。
`APP_TITLE = _app_title_cfg()`(L74)与 `app = FastAPI(title=...)`(L82)之间的依赖:
将 L82 改为读取 `from state_views import APP_TITLE`(import 在 FastAPI() 之前即可);
`MODEL_LABEL/HOST/PORT` 留在 app.py。

> 注意 import 顺序:re-export 块要放在 `sys.path.insert`(L35)之后(显然)且
> `configure_app(app)`/路由 include 之前或之后皆可(routes 是调用时导入),
> 但 `_startup_auth_banner()` 调用(L543)必须在 auth_gate re-export 之后。
> `import modules` 的副作用从 L1608 提前到 import 链头部:modules/ 是纯数据包,已核无顺序依赖。

---

## 6. patch 点清单(Grep 实查,共 12 个需同步修改点)

### 6.A mock.patch 命名空间穿透(9 个 patch 站点,3 个文件)— 陷阱①

这 3 个文件 patch app 命名空间里的符号 A,同时调用与 A **同迁一个模块**的函数 B:
搬迁后 B 体内对 A 的解析落到新模块全局,patch app.* 失效,**必须改 patch 目标**
(测试在 rpg/ 为 sys.path 根下运行,模块名无 `rpg.` 前缀):

| # | 文件:行 | 现 patch 目标 | 改为 |
|---|---|---|---|
| 1-5 | `rpg/tests/unit/test_chat_max_tokens.py` L22, L28, L33, L38, L41 | `mock.patch.object(app, "_get_user_preferences_cached", ...)`(被测 `app._chat_max_tokens`) | `mock.patch.object(user_prefs, "_get_user_preferences_cached", ...)`(顶部补 `import user_prefs`) |
| 6-8 | `rpg/tests/integration/test_black_swan_toggle.py` L55, L65, L76 | `patch.object(_app, "_get_user_preferences_cached", ...)`(被测 `_app._is_black_swan_enabled`) | `patch.object(user_prefs, ...)` |
| 9 | `rpg/tests/integration/test_sub_agent_separation.py` L79 | `patch("app.GameMaster")`(被测 `ui._get_sub_gm`) | `patch("runtime_cache.GameMaster")` |

### 6.B 源码文本 grep 测试(3 个文件,各 1 行路径替换)— 本仓特有坑

这 3 个测试把 `rpg/app.py` **读成文本**断言函数体/声明存在,搬迁后必须把读取路径换成新模块
(断言内容本身不变,因为是逐字搬运):

| # | 文件 | pin 内容 | 修改 |
|---|---|---|---|
| 10 | `rpg/tests/unit/test_branch_runtime_switch.py` L40 `APP_PY = (PROJECT/"rpg"/"app.py").read_text()` | `_state_save_id_by_user` 声明正则(L51/L55)+ `def _ensure_loaded(` 函数体含 `read_runtime`/`_state_save_id_by_user` | L40 路径 → `rpg/runtime_cache.py` |
| 11 | `rpg/tests/unit/test_state_repository_single_source.py` L27 同上 | `_state_commit_id_by_user` 声明 + `_ensure_loaded` 体含 `active_commit_id`/`_rt_commit`/`commit_drift` + `_invalidate_user_cache` 体含 `_state_commit_id_by_user.pop` | L27 路径 → `rpg/runtime_cache.py` |
| 12 | `rpg/tests/unit/test_multi_consume_same_turn.py` L8 同上 | `_chat_rule_candidates` 去重 key 含 `item_id`、`_apply_chat_rule_candidates` 按 item_id 去重 | L8 路径 → `rpg/rules_actions.py` |

(已核对:这两个文件里 APP_PY 的全部断言都只涉及随迁符号,单行路径替换即可,无需拆 APP_PY 为两份。)

### 6.C 实查后确认**不受影响**、禁止顺手改的点(回归红线)

- `ui_mod._get_gm = stub` / `ui_mod._get_sub_gm = stub` / `ui_mod.run_context_agent = fake`:
  test_e2e_narrative_guard_chat_flow / test_opening_no_default_leak / test_rules_chat_pipeline(×3 块)/
  test_chat_field_contract / test_set_persists_on_gm_failure —— routes/game.py 在请求时
  `from app import` + `getattr(_self_mod, "run_context_agent")`,setattr app 属性仍生效。**不改**。
- `_app._state_by_user[uid] = ...`(test_branch_runtime_switch L109-129)、
  `ui._gm_by_user[...] = fake`(test_sub_agent_separation L45-95)、
  `_ui._state_by_user.get(...)`(test_e2e_memory_invariant)、
  `with ui_mod._state_lock` + `.pop`(test_click_retest_existing_card L211-213):
  dict/lock 经 re-export 是**同一对象**,突变跨模块可见。**不改**。
- `patch("platform_app.db.connect")` + `app._clear_prefs_cache()`(test_acceptance_verifier L332-387):
  惰性 import 在函数体内,patch 的是 platform_app.db 模块属性,不受搬迁影响。**不改**。
- `patch("agents.acceptance_verifier.verify_acceptance_llm")`(test_acceptance_verifier ×10):
  `_verify_acceptance` 体内自 import 原样保留 → patch 点继续命中。**不改**。
- `from app import _verify_acceptance_rule / _session_model_app_view / _execute_rules_action / ...`
  (test_retest_qa_5_bugs、test_click_retest_existing_card、test_deterministic_rules_routing、
  test_move_canonicalize_and_gm_constraint、test_session_model_app_view):shim 覆盖。**不改**。
- `platform_app/api/saves.py`(3 处)、`platform_app/frontend_routes.py`、
  `tools_dsl/command_tools_saves.py`(4 处)的 `import app as _ui; _ui._invalidate_user_cache(...)`:
  shim 覆盖;且 test_continue_picker_uses_commit_activate 文本断言这些 handler 体内含
  `import app` 字样 → **这些调用方保持 import app,不要“顺手”改成 import runtime_cache**。
- `core/startup.py` L140 `from app import _bootstrap_init_db`:留在 app.py。**不改**。
- `scripts/run_postproc_worker.py` `from app import _acceptance_verifier_mode, _verify_acceptance`:shim 覆盖。**不改**。
- `scripts/gen_openapi.py` / `tests/integration/test_rebuild_endpoints.py` `from app import app`:组装根不动。**不改**。
- `tests/helpers.py` L39 `import app # 触发路由注册`:app.py 仍是组装根。**不改**。

## 7. Path(__file__) / 相对路径逐处清单 — 陷阱②

| 位置 | 代码 | 处置 |
|---|---|---|
| app.py L29 | `_APP_DIR = Path(__file__).parent`(dotenv + sys.path) | 留在 app.py,不动 |
| app.py L78-79 | `APP_DIR = Path(__file__).parent; UPLOAD_DIR = APP_DIR/"uploads"` | 随迁 `chat_helpers.py`;**chat_helpers.py 必须直接位于 rpg/ 根目录**,`Path(__file__).parent` 才仍解析为 `rpg/` → `rpg/uploads` 不漂移。若未来挪进子包,必须改写为锚定 rpg 根。app.py 不保留本地定义,经 re-export 提供 `UPLOAD_DIR`(外部无消费者,仅防御) |
| app.py L530 | `_FRONTEND_ROOT = Path(__file__).resolve().parent.parent/"frontend"` | 留在 app.py(静态挂载),不动 |
| `_backup_save` | `SAVE_FILE.parent/"backups"` | SAVE_FILE 来自 state 模块常量,与 __file__ 无关,安全随迁 |
| 其余被搬函数 | 无 `Path(__file__)`/相对路径(已逐簇核查) | — |

## 8. 五大陷阱对照 + 额外核查

| 陷阱 | 处置 |
|---|---|
| ① patch 命名空间穿透 | app.py 100% re-export(§5.9);仅 9 个 patch 站点因「patcher 与被测同迁」必须改目标(§6.A);3 个源码 grep 测试改读新路径(§6.B);其余 30+ 处 import/setattr 实查不受影响(§6.C) |
| ② Path(__file__) 错位 | §7 逐处列出;唯一风险点 UPLOAD_DIR 已用「新模块必须在 rpg/ 根」约束消解 |
| ③ 顺手简化 | §5 给出符号→目标文件→源行号的逐字搬运清单;执行规则明令「函数体一个字符不许动、体内惰性 import 不许上提」;执行代理用 sonnet 时把本节作为系统约束注入 |
| ④ 并行中间状态 | app.py 每批都被改(删区间+加 re-export)→ **批次严格串行**(§9),同一文件绝不出现在两个并行批次 |
| ⑤ 孤儿/死代码 | app.py 明确「保留为组装根 + re-export shim,不删除」;被搬区间在各批内同步删除;批次 5 终检 `grep -n "def _" rpg/app.py` 确认无残留实现体 |
| 循环导入 | §3 依赖图:8 个新模块均不 import app;modules/rules_bridge/agents/console_assistant 等被依赖包均已 grep 核实不反向 import app;platform_app/tools_dsl 对 app 的引用全在函数体内(运行时 app 必已加载) |
| 模块级单例/副作用 | ① 7 个 OrderedDict + 2 Lock + contextvar 迁移后仍是单实例(只有 runtime_cache/user_prefs 定义,app 仅 re-export 同对象);② `import modules` 注册副作用随迁 rules_actions 且 app 顶部 import 它,时机从「路由 include 后」提前到「import 链头」— modules 是纯数据目录包(无注册顺序依赖,已核)安全;③ `_startup_auth_banner()` 调用保持在 app.py,且在 auth_gate import 之后;④ load_dotenv/sys.path.insert 仍是 app.py 最前(新模块不依赖 dotenv 时序 — 它们由 app import,时序不变) |

## 9. 串行批次划分(每批 = 搬运 + 同步测试修改 + 验证闸)

| 批次 | 内容 | 同步测试修改 | 验证闸 |
|---|---|---|---|
| 1 | `user_prefs.py` + `agents/acceptance_verifier.py` 追加;app.py 删 L94-240/243-378 加 re-export | §6.A #1-8(test_chat_max_tokens、test_black_swan_toggle) | `python -m compileall rpg/`;pytest:test_chat_max_tokens、test_black_swan_toggle、test_acceptance_verifier、test_clarify_threshold、test_retest_qa_5_bugs、test_click_retest_existing_card |
| 2 | `auth_gate.py` + `runtime_cache.py`;app.py 删 L85-91/381-457/546-951 加 re-export | §6.A #9(test_sub_agent_separation);§6.B #10-11(branch_runtime_switch、state_repository_single_source 路径行) | pytest:test_sub_agent_separation、test_branch_runtime_switch、test_state_repository_single_source、test_e2e_memory_invariant、test_rules_api、test_security_batch2 |
| 3 | `state_views.py` + `chat_helpers.py`;app.py 删 L658-665/954-1601(去除 _check_probe 外延)/1194-1569 加 re-export,L74/L82 APP_TITLE 改源 | 无 | pytest:test_session_model_app_view、test_chat_field_contract、test_opening_no_default_leak、test_e2e_narrative_guard_chat_flow、test_set_persists_on_gm_failure、test_rebuild_endpoints |
| 4 | `rules_actions.py` + `console_assistant/backend_resolver.py`;app.py 删 L1605-2218 加 re-export | §6.B #12(test_multi_consume_same_turn 路径行) | pytest:test_deterministic_rules_routing、test_multi_consume_same_turn、test_move_canonicalize_and_gm_constraint、test_rules_chat_pipeline、test_console_assistant、test_combat_no_gm_hallucination |
| 5 | app.py 整形终检(re-export 块归并注释、确认无残留 `def _` 实现) | 无 | **全量** pytest(rpg_env venv,本机一次性 PG 配方见 project_rpg_local_testdb)+ `scripts/gen_openapi.py` 跑通 + `import app` 冒烟(uvicorn 起服 → GET /api/state 200) |

回滚策略:每批一个 commit;任一批验证闸失败,`git revert` 该批,前序批不受影响(shim 保证每批后 app 对外形状不变)。

## 10. 风险

1. **最大风险 = monkeypatch 契约破坏的长尾**:§6 已实查列全,但 838+ 测试里可能有未扫到的动态 `getattr(app, name)` 用法 → 以批次 5 全量 pytest 兜底;任何新失败先对照 §6.C 红线判断是不是「同迁分离」类。
2. 测试以 rpg/ 为 import 根(conftest 强制 sys.path[0]),新扁平模块名(user_prefs/runtime_cache/...)若与任何已安装第三方包重名会被本地遮蔽/被遮蔽 —— 已选名均无 PyPI 常见冲突;执行时再 `python -c "import user_prefs"` 验证解析到 rpg/ 根。
3. `import modules` 副作用提前(§8)理论上安全,但若有隐藏的「modules 读 env 且 dotenv 未加载」时序问题,批次 4 冒烟会暴露 —— dotenv 在 app.py L32-33 先于一切 re-export import,实际时序不变。
4. 并行的另一审计工作流正在读源码:**本方案执行必须等该工作流结束后开工**(本轮零源码改动)。
5. 执行代理务必用 sonnet + 本清单逐字搬运(feedback_delegate_to_sonnet 铁律);opus 只做批后验证与冲突裁决。
