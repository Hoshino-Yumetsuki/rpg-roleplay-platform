# 拆分方案:rpg/state/core.py(1284 行)

- **Verdict: needs-refactor** · Priority: medium · Effort: M
- 结论一句话:core.py 是 state 包重构的"剩余单体"——包内早已确立两套既有惯例(纯函数助手放兄弟叶模块、GameState 方法簇放 `_mixins/`),core.py 里混着 5 类彼此无关的职责,按既有惯例机械外迁即可,无需发明新结构。
- 审计前提:**本方案只是计划,未动任何源码**。并行审计期间不得执行。

---

## 1. 现状结构图

```
rpg/state/core.py (1283 行)
├─ 头部 re-export imports(兼容层,# ruff: noqa: F401)            @1-68
├─ BASE = Path(__file__).parent.parent  ⚠️陷阱②                  @70
│  SAVE_FILE / CURRENT_SCHEMA_VERSION                             @71-72
├─ 簇A 秘密剥离(task 45/138)                                     @74-160 (~90行)
│  _SECRET_SECTION_RE / _META_KEYWORDS_RE(模块级编译正则)
│  _strip_meta_knowledge_sentences / _strip_secret_sections / _extract_secret_sections
├─ 簇B DEFAULT_STATE 纯数据表 + MAX_HISTORY_TURNS                 @162-329 (~168行)
├─ 簇C 剧本 overrides 注册表(@lru_cache 单例 ⚠️)                 @332-365 (~35行)
│  _load_script_overrides / _detect_active_script_key
└─ class GameState(ApplyOpsMixin, RulesGameplayMixin, PendingMixin) @368-1281 (914行)
   ├─ 生命周期/持久化: __init__ load_or_new new _migrate(119) save setup_player record_turn
   ├─ 视图/投影:      history_messages(69) chat_history short_summary(108) status_payload(51) suggestions(81)
   ├─ 记忆:           set_memory_mode add_memory add_memory_item(44) remove_memory
   │                  add_hypothesis list_active_hypotheses confirm_hypothesis reject_hypothesis
   ├─ 世界线/权限/变量: set_permission_mode set_user_variable apply_set_directive remove_user_variable
   │                  set_last_retrieval set_last_context set_last_context_agent
   │                  _scan_worldline_validation _set_worldline_validation _store_worldline_projection
   │                  _user_locked_fields _is_user_locked mark_user_locked
   ├─ 时间线:         update_time request_time_jump confirm_time_jump reject_time_jump _timeline
   └─ 便捷/会话模型:   is_new player_name update_location update_relationship
                      set_session_model clear_session_model get_session_model
```

包内既有惯例(本方案完全沿用,不另起炉灶):
- 纯函数助手 → 兄弟叶模块:`extractors.py / json_ops.py / labels.py / parsers.py / path_ops.py / permissions.py / time_ops.py / utils.py`
- GameState 方法簇 → `_mixins/`:`apply_ops.py(644) / pending.py(187) / rules_gameplay.py(222)`,经 `_mixins/__init__.py` 注册,"mixin 间通过 self.xxx 互相调用"
- 对外门面 `state/__init__.py` 统一 re-export,外部 import 方式不变

## 2. 内聚簇分析(为什么是 needs-refactor)

| 簇 | 内容 | 与 GameState 的耦合 | 判定 |
|---|---|---|---|
| A 秘密剥离 | 2 正则 + 3 纯函数 | 仅 short_summary 调用;外部 workspace.py / formatters.py / 测试直接 import | 纯文本工具,零状态依赖 → 独立叶模块 |
| B DEFAULT_STATE | 纯数据表 + 3 常量 | _migrate/new 只读 deepcopy | 纯数据,目前还是 rules_gameplay.py 延迟 import 绕环的根源 → 独立叶模块后环消失 |
| C 剧本 overrides | lru_cache 单例 + 探测函数 | 仅 suggestions 调用;black_swan_agent 延迟 import | 独立注册表 → 叶模块 |
| D 迁移账本 | _migrate 119 行 | staticmethod,只依赖 B + utils | 追加式账本,适合独立模块但**不拆阶段函数** |
| E 方法簇 4 组 | 记忆/世界线/时间线/视图 ~730 行 | self.data 上的方法 | 与 `_mixins/` 既有三件套完全同构 → 各成一个 mixin |

单一职责的反例齐了:文本正则工具、纯数据表、带缓存的 IO 注册表、schema 迁移、四组业务方法,全挤在一个文件。判 acceptable 不成立——包自己的惯例已经给出了答案,core.py 只是没拆完。

## 3. 目标布局

```
rpg/state/
├─ core.py                ~270 行:GameState 类本体(生命周期+持久化+便捷属性+session_model)
│                          + 头部 re-export shim(陷阱①兼容层,永久保留)
├─ defaults.py            新 ~215 行:BASE / SAVE_FILE / CURRENT_SCHEMA_VERSION /
│                          MAX_HISTORY_TURNS / DEFAULT_STATE(纯数据,只 import pathlib)
├─ secrets.py             新 ~100 行:簇A 全部(只 import re)
├─ script_overrides.py    新 ~55 行:簇C(import json/lru_cache + from state.defaults import BASE)
├─ migrations.py          新 ~135 行:migrate_state(data)->dict = 原 _migrate 函数体逐字
└─ _mixins/
   ├─ memory.py           新 ~160 行:MemoryMixin
   ├─ worldline.py        新 ~150 行:WorldlineMixin
   ├─ timeline.py         新 ~120 行:TimelineMixin
   ├─ views.py            新 ~340 行:ViewsMixin(prompt/UI 投影)
   └─ __init__.py         +4 行注册
```

`state/__init__.py` **不改**(经 core shim 间接成立,最稳);后续如愿可单独一轮改为直连,非本次范围。

## 4. 可机械执行的搬运清单(逐字搬运、禁止改写逻辑)

> 执行代理铁律:所有函数/类/正则/数据**逐字剪切粘贴**,一个字符不许"顺手优化";
> 函数体内的延迟 import(`import os as _os`、`import secrets as _secrets`、
> `from core.config import ...`、`from platform_app.db import connect`、
> `from context_providers import resolve_content_pack`、
> `from platform_app.knowledge.script_overrides import ...`)**必须原样留在函数体内**,
> 严禁提升到模块顶层(那是刻意的防环/防副作用设计)。

### 批次 1:叶模块(先建新文件,后改 core.py 一次)

| 原 core.py 符号(@行) | 目标文件 | 备注 |
|---|---|---|
| `BASE` @70 | state/defaults.py | ⚠️陷阱②:`Path(__file__).parent.parent`,defaults.py 与 core.py 同层(rpg/state/),parent.parent 仍=rpg/,**语义不变**;原注释一并搬。**严禁**放进 _mixins/(多一层,语义就错了) |
| `SAVE_FILE` @71 | state/defaults.py | |
| `CURRENT_SCHEMA_VERSION` @72 | state/defaults.py | |
| `DEFAULT_STATE` @163-327 | state/defaults.py | 纯数据表,含全部注释逐字搬 |
| `MAX_HISTORY_TURNS` @329 | state/defaults.py | |
| `_SECRET_SECTION_RE` @81-83 | state/secrets.py | 含 task 138 注释块 @74-80 |
| `_META_KEYWORDS_RE` @90-102 | state/secrets.py | 含 task 45 注释块 |
| `_strip_meta_knowledge_sentences` @105 | state/secrets.py | |
| `_strip_secret_sections` @139 | state/secrets.py | |
| `_extract_secret_sections` @150 | state/secrets.py | |
| `_load_script_overrides` @332 | state/script_overrides.py | `@lru_cache(maxsize=1)` 装饰器一并搬;头部 `from state.defaults import BASE`;函数体内 platform_app 延迟 import 原样 |
| `_detect_active_script_key` @359 | state/script_overrides.py | |
| `GameState._migrate` 函数体 @393-512 | state/migrations.py | 改名为模块级 `def migrate_state(data: dict) -> dict:`(去 @staticmethod,签名参数不变);头部 import:`copy`、`from datetime import datetime`、`from state.defaults import DEFAULT_STATE, CURRENT_SCHEMA_VERSION`、`from state.parsers import _clean_item`、`from state.utils import _deep_update`;函数体内 `import secrets as _secrets` 原样保留 |

批次 1 收尾(core.py 单次编辑):删除上述定义,头部加:

```python
from state.defaults import (  # noqa: F401  (re-export shim, 陷阱①兼容层)
    BASE, SAVE_FILE, CURRENT_SCHEMA_VERSION, MAX_HISTORY_TURNS, DEFAULT_STATE,
)
from state.secrets import (  # noqa: F401
    _META_KEYWORDS_RE, _SECRET_SECTION_RE,
    _extract_secret_sections, _strip_meta_knowledge_sentences, _strip_secret_sections,
)
from state.script_overrides import _detect_active_script_key, _load_script_overrides  # noqa: F401
from state.migrations import migrate_state
```

并把 `_migrate` 改为薄委托(保留 staticmethod API,`load_or_new`/`__init__` 调用点零改动):

```python
@staticmethod
def _migrate(data: dict) -> dict:
    return migrate_state(data)
```

### 批次 2:四个新 mixin(先建新文件,后改 core.py 一次)

| 方法(@行) | 目标文件 / 类 | 新模块头部 import |
|---|---|---|
| `set_memory_mode` @907, `add_memory` @911, `add_memory_item` @934, `remove_memory` @979, `add_hypothesis` @987, `list_active_hypotheses` @1004, `confirm_hypothesis` @1014, `reject_hypothesis` @1034 | `_mixins/memory.py` → `MemoryMixin` | `from datetime import datetime`;`from state.parsers import _clean_item`;函数体内 `import secrets as _secrets` 原样 |
| `set_permission_mode` @1043, `set_user_variable` @1047, `apply_set_directive` @1063, `remove_user_variable` @1097, `set_last_retrieval` @1101, `set_last_context` @1104, `set_last_context_agent` @1107, `_scan_worldline_validation` @1110, `_set_worldline_validation` @1128, `_store_worldline_projection` @1135, `_user_locked_fields` @1197, `_is_user_locked` @1205, `mark_user_locked` @1211 | `_mixins/worldline.py` → `WorldlineMixin` | `copy`、`from datetime import datetime`;`from state.extractors import _extract_location_override, _extract_set_assignments, _extract_set_directive, _extract_set_time_targets`;`from state.parsers import _clean_item, _split_label`;`from state.permissions import _normalize_permission_mode` |
| `update_time` @1166, `request_time_jump` @1237, `confirm_time_jump` @1251, `reject_time_jump` @1256, `_timeline` @1269 | `_mixins/timeline.py` → `TimelineMixin` | `from timeline_state import clean_time_value`;`from state.time_ops import _phase_for_time` |
| `history_messages` @589, `chat_history` @659, `short_summary` @663, `status_payload` @772, `suggestions` @824 | `_mixins/views.py` → `ViewsMixin` | `copy`、`re`;`from state.defaults import CURRENT_SCHEMA_VERSION, MAX_HISTORY_TURNS`(history_messages 默认参数用到);`from state.secrets import _strip_secret_sections`;`from state.script_overrides import _detect_active_script_key, _load_script_overrides`;`from state.time_ops import _format_pending_timeline`;`from state.permissions import _permission_label`;`from state.utils import _hit_score, _latest_assistant_text, _player_action_text`;函数体内 `from platform_app.db import connect as _connect`、`from context_providers import resolve_content_pack` 原样保留 |

批次 2 收尾(单次编辑两个文件):

1. `_mixins/__init__.py` 注册:
```python
from .memory import MemoryMixin
from .timeline import TimelineMixin
from .views import ViewsMixin
from .worldline import WorldlineMixin
__all__ = [..., "MemoryMixin", "WorldlineMixin", "TimelineMixin", "ViewsMixin"]
```
2. core.py 类签名(新 mixin 追加在尾部;**已 Grep 实查:被搬 31 个方法名与既有三 mixin 零同名冲突**,MRO 安全):
```python
class GameState(ApplyOpsMixin, RulesGameplayMixin, PendingMixin,
                MemoryMixin, WorldlineMixin, TimelineMixin, ViewsMixin):
```
并删除已搬走的方法体。core.py 保留:`__init__ / load_or_new / new / _migrate(薄委托) / save / setup_player / record_turn / is_new / player_name / update_location / update_relationship / set_session_model / clear_session_model / get_session_model` + 全部 re-export shim。

### 批次 3:验证(只读)

1. `python -m py_compile` 全部触及文件
2. pytest:`rpg/tests/unit/test_player_private.py`(13 处直连 import 的主消费者)→ `test_command_dispatcher.py`、`test_gm_json_op_via_dispatcher.py` → 全量 unit 套件
3. Grep 复核:core.py 不再含被搬符号的 `def`/赋值定义;新模块顶层无 `from state.core import`(防环);`_mixins/` 内无 `Path(__file__)`

## 5. ≥80 行巨型函数逐个评估

| 函数 | 行数 | 类型 | 结论 |
|---|---|---|---|
| `_migrate` | 119 | **追加式迁移账本**(per-schema-version 顺序 setdefault 块,共享同一 migrated dict,块间有顺序依赖) | 搬为独立模块 `migrations.migrate_state`,**不拆阶段函数**——拆了只添参数穿线噪音;新 schema 版本继续尾部追加 |
| `short_summary` | 108 | 单一 prompt 模板装配,输出格式即规格 | **不拆**,逐字进 ViewsMixin;拆成 _summary_* 会把模板割裂、收益负 |
| `suggestions` | 81 | 打分流水线,但核心是闭包 `add()` 捕获上下文,数据已外置到 script_overrides | **不拆**,逐字进 ViewsMixin |
| `history_messages` | 69(<80) | digest 注入流水线 | 不在范围,逐字进 ViewsMixin |

## 6. Patch 点清单(Grep 实查)

**mock.patch / monkeypatch 指向 state.core 符号:0 处。**
全测试树仅一处 state 相关 patch:`rpg/tests/unit/test_branch_runtime_switch.py:117` patch `state_repository.load_active_state` —— 不在 core.py,**不受影响**。也无 `state.core.SAVE_FILE` 运行时改写、无 `_load_script_overrides.cache_clear()` 调用方。

直连 import 点(靠 core 头部 re-export shim 全部零改动存活,共 17 处):

| 文件 | 行 | 符号 |
|---|---|---|
| rpg/tests/unit/test_player_private.py | 19, 27, 35(`_strip_secret_sections`)、42(`_extract_secret_sections`)、56, 96, 188, 206, 223, 238, 251(`GameState`)、130, 142(混合) | 13 处 `from state.core import ...` |
| rpg/platform_app/workspace.py | 10 | `_extract_secret_sections, _strip_secret_sections` |
| rpg/context_engine/formatters.py | 30(函数体内) | `_strip_secret_sections` |
| rpg/agents/black_swan_agent.py | 543(函数体内) | `_load_script_overrides` |
| rpg/state/_mixins/rules_gameplay.py | 137(函数体内,防环延迟) | `DEFAULT_STATE` |

`state/__init__.py:7` 的 `from state.core import (...5 符号)` 经 shim 继续成立,53 个 `from state import ...` 下游文件零感知。

## 7. 五大陷阱对照 + 其他风险

- **① patch 穿透**:0 个 mock.patch 点(上节实查);17 处直连 import 全靠 core 永久 re-export shim 覆盖,头部已有 `# ruff: noqa: F401` 不会被 lint 自动清理。**shim 是永久兼容层,不是过渡品**,方案明确不撤。
- **② Path(__file__)**:全文件仅 1 处(@70 `BASE`)。defaults.py 与 core.py 同目录层级 → `parent.parent` 语义不变;清单已标红"严禁搬进 _mixins/"。`save()` 引用的 `SAVE_FILE` 是 def 时绑定的模块全局,经 import 绑定后行为一致(无任何运行时改写方,已实查)。
- **③ 顺手简化**:第 4 节铁律 + 符号→文件映射表;特别点名 6 处函数体内延迟 import 必须原样留在函数体内。
- **④ 并行中间状态**:core.py / `_mixins/__init__.py` 是汇聚点。批内"建新文件"可并行,但**每批对 core.py 只做一次收尾编辑;批次 1→2→3 严格串行**。两批不可合并执行(批 2 的 views.py 依赖批 1 的 secrets/script_overrides/defaults 已存在)。
- **⑤ 孤儿/死代码**:core.py 明确**保留**(GameState 本体 + 永久 shim),无文件删除。新 mixin 若忘记进 `_mixins/__init__.py` + GameState 基类列表即成孤儿——批 3 的 Grep 复核兜底。批 3 还复核 core.py 旧定义已删净(防 shim import 与残留定义双重定义互相遮蔽)。
- **循环导入**:新叶模块依赖方向单向:`secrets→(仅 re)`、`defaults→(仅 pathlib)`、`script_overrides→defaults`、`migrations→defaults/parsers/utils`、新 mixins→叶模块+timeline_state,**全部不回指 state.core**。副产品:rules_gameplay.py 延迟 import DEFAULT_STATE 的防环理由消失(可后续改 `from state.defaults import`,本次不动,shim 保它继续工作)。
- **模块级单例/import 副作用**:`_load_script_overrides` 的 `@lru_cache(maxsize=1)` 随函数整体搬迁,black_swan_agent / suggestions 经 re-export 拿到**同一函数对象**,缓存仍单一;无 cache_clear 依赖。`_SECRET_SECTION_RE/_META_KEYWORDS_RE` 编译正则随簇A 搬,无外部直连引用(已实查)。无注册表/装饰器注册顺序问题(state 包无 import 时注册副作用)。
- **MRO**:已实查被搬 31 方法名与 ApplyOpsMixin/PendingMixin/RulesGameplayMixin 的全部 def 零交集;跨 mixin `self.xxx` 互调(apply_set_directive→update_time/apply_state_write/add_memory)是包内既有约定,运行时 MRO 解析,不受文件位置影响。

## 8. 批次划分汇总(串行)

| 批次 | 动作 | 触及文件 | 验证 |
|---|---|---|---|
| 1 | 建 defaults/secrets/script_overrides/migrations 四叶模块;core.py 删定义+加 shim+_migrate 薄委托(单次编辑) | 新4 + core.py | py_compile + test_player_private.py |
| 2 | 建 memory/worldline/timeline/views 四 mixin;注册 `_mixins/__init__.py`;core.py 改基类+删方法(单次编辑) | 新4 + 2 旧 | py_compile + dispatcher 两测试 |
| 3 | 全量 unit 套件 + Grep 复核(残留定义/防环/Path(__file__)) | 只读 | 全绿后才算完 |

执行建议:机械搬运交 sonnet 子代理(用户既有规则),按本清单逐字执行;opus 只做批间验证。
