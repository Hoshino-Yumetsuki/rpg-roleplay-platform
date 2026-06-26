# 拆分方案:rpg/retrieval.py(1005 行)

- **判定:needs-refactor**(优先级 medium,工作量 M)
- 核心问题不是"文件大",而是 `retrieve_context` 一个函数 477 行(占全文件 47%),由 10 个互相独立的"上下文 section 注入块"以补丁叠补丁方式堆成(task 42/52/53/79/80/117/122/125/131/136、BUG-1/2/3、P0#5、iter#7 全部落在同一个函数体内),每个新需求都在函数中段插一块 try/except。其余 18 个顶层函数本身体量健康(最大 68 行),但分属三类不同数据源职责,混在一个平面命名空间里。
- 本模块是 GM 上下文热路径(每回合调用),后续 KB 提取架构 v5 / Lilith 管线都还会往这里加 section,**不拆则每次迭代都在 477 行函数里做嵌套手术**。

---

## 1. 现状结构图

注意:本仓库 `rpg/` 即 sys.path 根,模块以**顶层名 `retrieval`** 被导入(不是 `rpg.retrieval`)。

```
retrieval.py (1005 行)
│
├─ 模块级常量/单例(L19-28, L230)
│   BASE = Path(__file__).parent          ← ⚠ 陷阱②唯一触点
│   DB_PATH / FACT_DB  (BASE.parent/.webnovel/*.db)
│   CHAR_IDX / WORLD_IDX / SUM_IDX (BASE/indexes/*.json)
│   _CHAR_ALIASES (可变全局, global 重绑)
│   _TIMELINE_READY (可变全局, global 重绑)
│   _DEFAULT_NOVEL_LEAK_TOKENS = get_leak_filter_tokens()  ← import 副作用(读 config json)
│
├─ 簇 A:遗留本地源(默认 MuMu 剧本专用 sqlite/json)
│   _load_aliases @30 / detect_mentioned_characters @35 / load_character_cards @45
│   _sqlite_available @61 / bm25_search @69(68行) / load_recent_summaries @139
│   load_summaries_window @152 / load_chapter_facts @166
│
├─ 簇 B:默认剧本泄漏防护
│   _is_default_mumu_script @210(恒 False,留签名兼容)
│   _strip_default_novel_leakage @233
│
├─ 簇 C:Postgres 剧本域数据源(全部函数内 lazy import platform_app.db)
│   _resolve_active_phase_range @253(61行) / _load_anchor_chapter_text @318
│   _extract_style_sample @364 / _resolve_save_id_from_user @396
│   _entry_chapter_min @893 / _load_worldbook_for_retrieval @913 / _load_script_character_cards @974
│
└─ 簇 D:编排器
    _ensure_timeline_ready @50
    retrieve_context @414(477行)← 10 个顺序注入块,见 §3.2
```

### 外部引用面(Grep 实查,全量)

**运行代码 import(全部只取 `retrieve_context` 一个符号):**

| 文件 | 行 | 形式 |
|---|---|---|
| `rpg/app.py` | 61 | `from retrieval import retrieve_context  # noqa: F401` |
| `rpg/demo.py` | 27 | `from retrieval import retrieve_context` |
| `rpg/agents/context_agent.py` | 30 | `from retrieval import retrieve_context`(再以 `retrieve_fn=` 注入 context_providers) |
| `rpg/context_engine/core.py` | 127 | 函数内 lazy `from retrieval import retrieve_context as _retrieve_fn` |
| `rpg/claude_design_upload/current_code/{ui,context_agent}.py` | — | 设计上传快照,非活代码,**不用管** |

**测试命名空间依赖(陷阱①实查结果):**

整个 `rpg/tests/` 中 **没有任何 `mock.patch("retrieval.*")` / `patch.object(retrieval, ...)` / `monkeypatch.setattr(retrieval, ...)`**(已 grep 验证)。存在的是 `import retrieval` 后的**模块属性直读**,共 9 个引用点 + 1 个 import,全部在 `rpg/tests/unit/test_retrieval_no_default_leak.py`:

| 行 | 引用 |
|---|---|
| 34 | `import retrieval` |
| 48, 51 | `retrieval._is_default_mumu_script(...)` |
| 69 | `retrieval._DEFAULT_NOVEL_LEAK_TOKENS`(读常量,从不重绑 → re-export 安全) |
| 81, 93, 99, 100 | `retrieval._strip_default_novel_leakage(...)` |
| 123, 148 | `retrieval.retrieve_context(...)` |

属性直读只要求符号在 `retrieval` 命名空间**可见**,re-export shim 即可满足,**零测试文件需要改动**。
另有纯注释引用(不影响运行):`platform_app/workspace.py:273`(提及 `retrieval._load_worldbook_for_retrieval`)、`platform_app/db/migrations.py:1388`(提及 `retrieval._entry_chapter_min`)、`kb/canon_repo.py:26`。

---

## 2. 内聚簇分析(为什么这样切)

- **簇 A(遗留本地源)**:统一特征 = 只读 `.webnovel/*.db` + `indexes/*.json` 这套"单一默认书的固化资源",且因 `_is_default_mumu_script` 恒 False,**运行期实际全部死路**(仅 `load_summaries_window`/`load_chapter_facts`/`bm25_search` 在 `is_default=True` 分支被调,而该分支永不进入)。归拢成一个文件后,未来整簇删除只动一处。
- **簇 B(泄漏防护)**:`_strip_default_novel_leakage` 是**活代码**(L832 对 pg_context 无条件防御),`_is_default_mumu_script` 是活的门控(虽恒 False 但被 retrieve_context 和测试调用)。与簇 A 语义相关但生命周期不同(A 可删,B 必留),分开放。
- **簇 C(Postgres 域)**:统一特征 = 函数内 lazy `from platform_app.db import connect`、按 script_id/save_id scope、异常吞掉返空。是当前真正的活数据通道,未来 v5 行级 KB 也会落这里。
- **簇 D(编排)**:`retrieve_context` 是纯流水线——所有块共享 `parts: list[str]` 累加器和少量标量(`timeline_filter`/`_progress_chapter`/`_foreknowledge_mode`/`is_default`),块间无交叉控制流,**流水线型 → 该拆成阶段函数**(详见 §3.2)。

### ≥80 行巨型函数逐个评估

| 函数 | 行数 | 类型 | 结论 |
|---|---|---|---|
| `retrieve_context` | 477 | 顺序流水线(10 个独立注入块,各有独立 try/except) | **拆**,→ 10 个 `_stage_*` 阶段函数 |
| `bm25_search` | 68 | <80,单一查询+评分,内聚 | 不拆 |
| `_resolve_active_phase_range` | 61 | <80,单一解析算法 | 不拆 |
| `_load_worldbook_for_retrieval` | 59 | <80 | 不拆 |

---

## 3. 目标布局

把单文件转为**同名包**(保住顶层导入名 `retrieval` 不变,与 `kb/`、`context_engine/`、`platform_app/knowledge/` 既有包风格一致;私有实现模块用 `_` 前缀,同 `context_engine/_constants.py` 惯例):

```
rpg/retrieval/
├─ __init__.py        (~70 行)  re-export shim,公共 API 唯一入口
├─ _legacy_local.py   (~210 行) 簇 A + 路径常量 + _CHAR_ALIASES
├─ _leak_guard.py     (~55 行)  簇 B + _DEFAULT_NOVEL_LEAK_TOKENS
├─ _pg_sources.py     (~300 行) 簇 C
└─ _compose.py        (~520 行) 簇 D:retrieve_context + 10 个 _stage_* + _ensure_timeline_ready + _TIMELINE_READY
```

依赖方向(无环,见 §5 循环导入核查):
`__init__` → `_compose` → {`_legacy_local`, `_leak_guard`, `_pg_sources`} → 仅 stdlib/`core.logging`/`config.glossary`/`timeline_index` + 函数内 lazy `platform_app.db`。

### 3.1 `__init__.py` shim(原模块的替身,陷阱①⑤的答案)

```python
"""retrieval — 两段式召回(包化重构,对外 API 不变)。"""
from retrieval._legacy_local import (
    BASE, DB_PATH, FACT_DB, CHAR_IDX, WORLD_IDX, SUM_IDX,
    _load_aliases, detect_mentioned_characters, load_character_cards,
    _sqlite_available, bm25_search, load_recent_summaries,
    load_summaries_window, load_chapter_facts,
)
from retrieval._leak_guard import (
    _DEFAULT_NOVEL_LEAK_TOKENS, _is_default_mumu_script, _strip_default_novel_leakage,
)
from retrieval._pg_sources import (
    _resolve_active_phase_range, _load_anchor_chapter_text, _extract_style_sample,
    _resolve_save_id_from_user, _entry_chapter_min,
    _load_worldbook_for_retrieval, _load_script_character_cards,
)
from retrieval._compose import _ensure_timeline_ready, retrieve_context

__all__ = ["retrieve_context", "bm25_search", "load_recent_summaries",
           "load_summaries_window", "load_chapter_facts",
           "detect_mentioned_characters", "load_character_cards"]
```

- 19 个顶层函数 + 6 个路径常量 + `_DEFAULT_NOVEL_LEAK_TOKENS` **全部 re-export**(含下划线私有,因测试直读它们)。
- **不 re-export** `_CHAR_ALIASES` / `_TIMELINE_READY`:二者是会被 `global` 重绑的可变单例,re-export 会产生陈旧绑定假象;Grep 已确认无任何外部读取者,安全。
- 测试 9 个属性直读点、4 个 `from retrieval import retrieve_context` 调用方,经此 shim 全部零改动。

### 3.2 `_compose.py`:retrieve_context 的阶段化(唯一允许"改形不改义"的部分)

拆法 = **按原函数现有的注释分界逐块外提**,每块成为一个 `_stage_*` 函数;主函数退化为 ~50 行的调度骨架。块间共享状态全部走显式参数/返回值,`parts` 以 list 引用传入由 stage 追加(与现状副作用语义一致):

| 阶段函数 | 原 retrieve_context 行范围(@retrieval.py) | 签名(入 → 出) |
|---|---|---|
| `_stage_sync_progress` | 450–470(BUG-3 progress 同步) | `(world, script_id, user_id) → (progress_chapter: int, foreknowledge_mode: str)` |
| `_stage_timeline_fallback` | 471–491(last_transition 回退 + task117 phase fallback,含 phase 摘要 append) | `(timeline_filter, timeline, user_id, script_id, parts) → timeline_filter` |
| `_stage_anchor_text` | 492–548(task125 锚点原文 + task131-B 文风样本) | `(state, world, timeline, timeline_filter, user_id, script_id, parts) → None` |
| `_stage_timeline_anchor_header` | 549–566(时间线检索锚点 section,is_default 双分支) | `(world, pending, label, timeline_filter, is_default, parts) → None` |
| `_stage_chapter_facts` | 568–572(SQLite ChapterFact,仅 is_default) | `(timeline_filter, is_default, parts) → None` |
| `_stage_pending_anchors` | 573–671(task136 世界线收束) | `(world, user_id, script_id, parts) → None` |
| `_stage_player_history` | 673–717(存档独立时间线) | `(user_id, parts) → None` |
| `_stage_hierarchy_tree` | 719–799(P0#5 层级图,复用 canon_repo._reveal_clause) | `(script_id, progress_chapter, foreknowledge_mode, parts) → None` |
| `_stage_pg_runtime` | 801–836(platform_app.knowledge 检索 + task52/53 钳制 + 泄漏清洗) | `(user_input, state, timeline_filter, user_id, is_default, progress_chapter, parts) → None` |
| `_stage_default_sources` | 838–864(簇 A 三连:角色卡/BM25/摘要,仅 is_default) | `(user_input, timeline_filter, parts) → snippets: list[str]`(返回值仅供 L887 verbose 日志) |
| `_stage_script_wb_cards` | 866–885(task80/82 worldbook + 角色卡) | `(user_input, script_id, timeline_filter, parts) → None` |

硬性要求(陷阱③):
- **块体逐字搬运**:每个 stage 函数体 = 原行范围原文,仅允许两类机械改写:(a) 块内读到的外层局部变量改为同名形参;(b) 块内对外层局部变量的赋值改为 return。**所有注释(task 编号/BUG 编号/中文病灶说明)原样保留**,禁止"顺手"合并 try/except、改日志文案、改 SQL、改 limit 数字。
- 原函数里的**冗余/死局部**也原样保留:`is_opening`(L506-507,计算后已无人用)、`char_names = []`(L864,注释"留作 verbose 日志兼容")——它们是历史修复的现场证据,清理属于另一个 PR。
- 多处重复的 `_resolve_save_id_from_user(user_id)`(L452/477/521/577/678 共 5 次独立调用,各有独立容错语义)**不许合并成一次**——每处 try/except 边界不同,合并属于行为变更。

---

## 4. 可机械执行的搬运清单(符号 → 目标文件,逐字搬运)

> 行号均指现 `rpg/retrieval.py`。执行顺序见 §6 批次。

### Batch A-1 → `retrieval/_legacy_local.py`
| 符号 | 原行 |
|---|---|
| 模块头 import(json/re/sqlite3/Path 按需)+ `log = get_logger(__name__)` | 重建 |
| `BASE` / `DB_PATH` / `FACT_DB` / `CHAR_IDX` / `WORLD_IDX` / `SUM_IDX` | 19–24,**⚠ 见陷阱② §5,唯一允许改写处** |
| `_CHAR_ALIASES` + 注释 | 26–27 |
| `_load_aliases` | 30–32 |
| `detect_mentioned_characters` | 35–42 |
| `load_character_cards` | 45–47 |
| `_sqlite_available` | 61–66 |
| `bm25_search` | 69–136 |
| `load_recent_summaries` | 139–149 |
| `load_summaries_window` | 152–163 |
| `load_chapter_facts` | 166–207 |

### Batch A-2 → `retrieval/_leak_guard.py`
| 符号 | 原行 |
|---|---|
| `from config.glossary import get_leak_filter_tokens` | 15 |
| `_is_default_mumu_script`(含 task80 docstring) | 210–221 |
| task42 注释块 + `_DEFAULT_NOVEL_LEAK_TOKENS = get_leak_filter_tokens()` | 224–230(import 副作用原位保留,见 §5) |
| `_strip_default_novel_leakage` | 233–245 |

### Batch A-3 → `retrieval/_pg_sources.py`
| 符号 | 原行 |
|---|---|
| `_resolve_active_phase_range`(含 task117 注释块 248–252) | 248–313 |
| `_load_anchor_chapter_text`(含 task125 注释 316–317) | 316–361 |
| `_extract_style_sample` | 364–393 |
| `_resolve_save_id_from_user` | 396–411 |
| `_entry_chapter_min` | 893–910 |
| `_load_worldbook_for_retrieval` | 913–971 |
| `_load_script_character_cards` | 974–1005 |

(全部函数内 lazy import 原样保留,不上提到模块级——这是现有的防环手段。)

### Batch A-4 → `retrieval/_compose.py`
| 符号 | 原行 |
|---|---|
| `from timeline_index import bootstrap_timeline_from_summaries, timeline_filter_for_label` + `log` | 13–17 |
| `_TIMELINE_READY` | 28 |
| `_ensure_timeline_ready` | 50–58 |
| `retrieve_context`(Batch A 阶段先**整体逐字搬入**,不拆) | 414–890 |
| 跨模块引用改为 `from retrieval._legacy_local import ...` 等显式 import | 重建 |

### Batch A-5 → `retrieval/__init__.py`
按 §3.1 全文新建;原 `retrieval.py` **删除**(git 同 commit 内完成 模块→包 替换,无孤儿,陷阱⑤)。同时清掉 `rpg/__pycache__/retrieval.cpython-*.pyc`(陈旧字节码与新包同名冲突的卫生措施)。

### Batch B → `_compose.py` 内部阶段化
按 §3.2 的 11 行表逐块外提,仅动 `_compose.py` 一个文件。

---

## 5. 五大陷阱 + 环/副作用逐项核查

| # | 陷阱 | 实查结论 / 对策 |
|---|---|---|
| ① | 测试 patch 命名空间穿透 | **零 mock.patch 命中**(grep `patch.*retrieval` 全测试树无果)。仅 `test_retrieval_no_default_leak.py` 9 处属性直读 + 4 个运行方 `from retrieval import retrieve_context`,shim 全覆盖,**测试零改动**。注意:正因无人 patch,shim 的"绑定快照"语义也不构成风险。 |
| ② | `Path(__file__)` 错位 | **全文件唯一触点 = L19 `BASE = Path(__file__).parent`**(派生 L20-24 五个路径)。模块在 `rpg/retrieval.py` 时 BASE=`rpg/`;搬进 `rpg/retrieval/_legacy_local.py` 后 `Path(__file__).parent`=`rpg/retrieval/` → `DB_PATH` 会错成 `rpg/.webnovel`、`CHAR_IDX` 错成 `rpg/retrieval/indexes/`。**必须改写为 `BASE = Path(__file__).resolve().parents[1]`**(=`rpg/`),L20-24 五行原样不动。这是整个 Batch A 唯一一处允许的逻辑改写,验收时 `python -c "import retrieval; print(retrieval.DB_PATH, retrieval.CHAR_IDX)"` 必须与重构前输出逐字相同。簇 C 无 `__file__` 使用(已逐函数核过)。 |
| ③ | 执行代理顺手简化 | §3.2/§4 已写死"逐字搬运、注释保留、死局部保留、5 处 `_resolve_save_id_from_user` 不合并、SQL/limit/文案禁改"。执行用 sonnet 子代理时,每个 Batch 的指令直接引用本表行号。 |
| ④ | 并行中间状态 | 批次严格串行(§6):A-1…A-5 是"同一个原文件的肢解",必须单线程一次 commit 完成;Batch B 只动 `_compose.py`。**禁止** A 与 B 并行,禁止把 A-1/A-2/A-3 分给并行子代理(它们都要从同一份 retrieval.py 删行)。 |
| ⑤ | 孤儿/死代码 | 原 `retrieval.py` **删除**(由包接管名字),不留平行旧文件。已知死代码(簇 A 的 `is_default` 永假死路、`is_opening` 死局部、`detect_mentioned_characters` 恒返空)**本次原样保留**,标记为后续独立清理项(动它们会牵连 `test_retrieval_no_default_leak` 的语义断言,不属于机械搬运)。`claude_design_upload/current_code/` 是快照目录,不碰。 |
| — | 循环导入 | 新增边:`retrieval.__init__ → retrieval._*`、`_compose → _legacy_local/_leak_guard/_pg_sources`,均单向。外部边不变:`agents/context_agent` 顶层 import retrieval,而 retrieval 对 `agents.anchor_seed_agent`/`agents.save_history`/`gm_serving.settings`/`kb.canon_repo`/`platform_app.*` 的引用**全部已是函数内 lazy**(L268/328/454/459/579/621/680/723/802/927/976)——逐字搬运自动保持 lazy,**不得上提**。`context_engine/core.py:127` 与 `platform_app.knowledge` 对 retrieval 的反向引用也是 lazy,无新环。 |
| — | 模块级单例/副作用 | ① `_DEFAULT_NOVEL_LEAK_TOKENS = get_leak_filter_tokens()`:import 时读 `config/novel_glossary.json`。包化后该副作用发生在 `import retrieval` → `_leak_guard` 链上,时机与现在等价(原模块 import 时也执行)。② `_TIMELINE_READY`/`_CHAR_ALIASES` 可变全局:各自与唯一的读写函数同文件(`_compose`/`_legacy_local`),`global` 语义不跨模块,且不 re-export(§3.1)。③ 无装饰器注册表/注册顺序问题(本模块不含)。④ logger 名从 `retrieval` 变为 `retrieval._compose` 等——日志 tag 文案里已自带 `[retrieval]` 前缀(L470/671/717/799),运维 grep 不受影响,可接受。 |

---

## 6. 串行批次与验收

| 批次 | 内容 | 验收闸 |
|---|---|---|
| **Batch A**(一个 commit) | A-1…A-5:包化 + 逐字搬运 + shim + 删原文件 + 清 pyc | ① `python -m compileall rpg/retrieval/`;② `python -c "import retrieval; print(retrieval.DB_PATH, retrieval.FACT_DB, retrieval.CHAR_IDX, retrieval.SUM_IDX)"` 输出与重构前逐字 diff=0;③ `pytest rpg/tests/unit/test_retrieval_no_default_leak.py`;④ `pytest rpg/tests/unit/ rpg/tests/integration/test_opening_no_default_leak.py`(本机一次性 PG 配方见 project_rpg_local_testdb);⑤ `git grep -n "from retrieval import\|import retrieval"` 复核 4 个运行方仍解析。 |
| **Batch B**(一个 commit) | `_compose.py` 内 retrieve_context → 11 stage 外提 | 同上 ③④;另加人工 diff 审查:每个 `_stage_*` 函数体与原行范围逐字对比(仅形参化/return 化差异)。 |
| 不做 | 死代码清除、`is_default` 永假分支删除、5 处 save_id 解析去重 | 留作独立后续任务,需要测试语义决策,非机械。 |

回滚:两批各自独立 commit,`git revert` 即可;Batch A 回滚后文件树还原为单文件模块,无状态残留。

---

## 7. 风险汇总

1. **最大风险 = 陷阱②那一行**:`BASE` 改写错了不会炸 import,只会让 sqlite/json 路径静默落空(函数全是吞异常返空设计),表现为"GM 上下文悄悄变薄"。所以验收②是逐字 diff 路径输出,不是只看测试绿。
2. Batch B 的形参化若漏传一个标量(如 `_progress_chapter`),层级图/实体召回的剧透钳制会静默退化——验收时对 `_stage_hierarchy_tree`/`_stage_pg_runtime` 的签名按 §3.2 表逐项核对。
3. 并行审计工作流正在读本仓库:**本方案为纯文档产出,未动任何源码**;实际执行需等审计工作流(task #1/#4)收尾后再排。
