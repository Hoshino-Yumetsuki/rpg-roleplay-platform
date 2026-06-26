# 拆分方案:rpg/platform_app/import_pipeline.py(2673 行)

> 审计日期 2026-06-10 · 函数抽象层体检 · 本文件为唯一产出物,源码未做任何修改。
> 所有引用点/patch 点均经 Grep 实查(命令与行号见正文)。

## 0. 结论速览

| 项 | 值 |
|---|---|
| verdict | **needs-refactor** |
| priority | medium(功能正常、测试绿,痛点是 4 种职责混居 + 导航成本;不阻塞任何在途工作) |
| effort | M(3 个新模块 + shim;2 个测试文件需同步改;4 个串行批次,适合 sonnet 子代理机械执行) |
| 受影响测试 patch 点 | **7 个**(6 个 `patch.object(_pipeline, "connect")` + 1 个 `patch.object(ip, "connect")`);另有 4 个 patch 点因方案刻意把对应函数留在原模块而**零影响** |

一句话:该文件把「任务生命周期/调度」「8 阶段流水线实现」「LLM/嵌入凭证门控」「单模块 rebuild 子系统」四件事塞在一个 2673 行文件里,内聚簇边界清晰、可机械拆分;但有两个测试以**模块命名空间**(monkeypatch `connect`/`init_db`)和**文件路径**(`spec_from_file_location` 直接加载 `import_pipeline.py`)强耦合,必须按本方案的批次同步处理,否则拆完测试静默失效或直接红。

---

## 1. 现状结构图(AST 实测 + 精读)

```
import_pipeline.py (2673 行)
│
├─【簇 A:任务生命周期 + 调度编排】≈ 700 行
│   STAGES                              @35   阶段注册表(仅本模块用)
│   _IMPORT_GLOBAL_SEM/_QUEUE_DEPTH/    @50   模块级单例:全局并发信号量+排队深度
│   _QUEUE_LOCK/_RUNNING                      (account_io.py 经 getattr 读 _IMPORT_GLOBAL_SEM!)
│   estimate_budget            90 行  @88    纯估算,无 DB 写(数据表型)
│   JobController              58 行  @183   import_jobs 行的 DB 状态封装(外部:account_io、extract/job_runner)
│   schedule_full_import       53 行  @246   公共入口
│   get_job_status             73 行  @301   公共入口(SSE 轮询用)
│   cancel_job / list_jobs     21 行  @376   公共入口
│   _run_pipeline             192 行  @404   worker:依次调簇 B 的 _stage_*
│   _finalize_cancelled         6 行  @598
│   finalize_job_if_unterminated 47行 @610   ⚠ 测试 monkeypatch 本模块 connect/init_db
│   reap_zombie_import_jobs    61 行  @659   ⚠ 同上(startup self-heal)
│
├─【簇 C:LLM/嵌入凭证门控】≈ 100 行(被 A、B、D 三簇 + knowledge/card_audit.py 共用)
│   MissingUserCredentialError   8 行 @62    ⚠ api/imports.py、api/scripts.py except 捕获;card_audit raise
│   MissingEmbeddingCredentialError 11行 @72  ⚠ api/imports.py except 捕获
│   _resolve_extractor_llm      19 行 @795   ⚠ card_audit 注释引用;model_resolution 测试直接调
│   _normalize_llm_api_id        6 行 @816   ⚠ card_audit.py:107 调用
│   _credential_api_id_for       2 行 @824   ⚠ card_audit.py:144 调用
│   require_user_llm_credential  9 行 @828   ⚠ api/scripts.py:54 调用
│   _api_kind                    7 行 @839
│   _has_user_llm_credential    15 行 @848
│   _require_user_llm_credential 4 行 @865
│
├─【簇 B:8 阶段流水线实现】≈ 1180 行(只被 _run_pipeline、_run_module_rebuild、2 个集成测试调用)
│   _stage_chunks               31 行 @725
│   _stage_facts                35 行 @758
│   _stage_story_phase_llm     120 行 @871   ⚠ model_resolution 测试 patch.object(connect)
│   _backfill_unphased_with_even_split 12行 @993
│   _even_split_phases          20 行 @1007
│   _stage_phase_digests        78 行 @1029
│   _stage_entities             37 行 @1109
│   _final_stage_status          8 行 @1148  ⚠ partial_failure 测试直接 import
│   _stage_cards               173 行 @1158  ⚠ 同 story_phase;尾部 setattr 函数属性通道
│   _stage_worldbook           144 行 @1333  ⚠ 两个测试都打;setattr(_last_count)
│   _stage_canon_extract       116 行 @1479
│   _stage_npc_voices          140 行 @1597  ☠ 死代码:全仓零调用(grep 实查,见 §7)
│   _backfill_chapter_facts_events_from_canon 122行 @1739
│   _rerank_cards_by_canon_importance 49行 @1863  ⚠ 2 个集成测试直接调(真 DB,无 patch)
│   _count_canon_and_anchors    15 行 @1914
│   _stage_embeddings           69 行 @1931
│   _parse_json                 11 行 @2002
│
└─【簇 D:单模块 rebuild 子系统(phase_backend)】≈ 660 行
    rebuild_chunks_from_db      40 行 @2019
    rebuild_facts_from_db       51 行 @2061
    rebuild_cards_from_canon    65 行 @2114
    rebuild_worldbook_with_llm  44 行 @2181
    REBUILD_MODULES(dict 注册表)     @2230  ⚠ test_rebuild_endpoints 读
    normalize_rebuild_module     7 行 @2241  ⚠ api/imports.py:459 调用
    _embedding_preflight_or_raise 7 行 @2250
    _embedding_prereq           14 行 @2259
    estimate_module_rebuild    145 行 @2275  ⚠ api/imports.py:506 调用
    schedule_module_rebuild     63 行 @2422  ⚠ api/imports.py:461 调用
    _run_module_rebuild        179 行 @2487  ⚠ test_rebuild_endpoints hasattr 断言
    _count                       5 行 @2668
```

簇间依赖(单向,无环,这是可拆的根本依据):
- A._run_pipeline → B._stage_*(以及 getattr 读 `_stage_cards._last_llm_failures` 函数属性)
- A.schedule_full_import → C.require_user_llm_credential
- B 各 LLM 阶段 → C._resolve_extractor_llm
- D → C(凭证门控)、D._run_module_rebuild → B._stage_worldbook、D → A.JobController(唯一的 D→A 边)
- B、D 不依赖 A 的任何东西(JobController 实例只作参数传入,`from __future__ import annotations` 下类型注解不触发运行时导入)

## 2. 引用方全量清单(Grep 实查)

### 2.1 生产代码引用(全部经 `platform_app.import_pipeline` 命名空间,re-export shim 可全覆盖)

| 调用方 | 符号 | 方式 |
|---|---|---|
| `rpg/platform_app/api/imports.py` | estimate_budget / schedule_full_import / get_job_status / cancel_job / list_jobs / normalize_rebuild_module / schedule_module_rebuild / estimate_module_rebuild / MissingUserCredentialError / MissingEmbeddingCredentialError | 属性访问 `import_pipeline.X` |
| `rpg/platform_app/api/scripts.py` :51-75, :586-590 | require_user_llm_credential / MissingUserCredentialError | 属性访问 |
| `rpg/platform_app/script_import.py` :202 | schedule_full_import | from-import(函数级) |
| `rpg/core/startup.py` :178 | reap_zombie_import_jobs | from-import(函数级) |
| `rpg/extract/job_runner.py` :20, :342 | JobController(**模块顶层 from-import**)/ finalize_job_if_unterminated | from-import |
| `rpg/platform_app/account_io.py` :408-410 | JobController / **`getattr(import_pipeline, "_IMPORT_GLOBAL_SEM", None)`** | 属性访问 |
| `rpg/platform_app/knowledge/card_audit.py` :91-144 | _normalize_llm_api_id / MissingUserCredentialError / _credential_api_id_for | 属性访问(函数级 lazy import,无环) |
| `rpg/platform_app/cluster.py` :4 | `_RUNNING`(仅注释提及) | 无运行时引用 |

### 2.2 测试引用与 patch 点(陷阱① 实查结果)

| 文件 | 行 | 内容 | 拆分后影响 |
|---|---|---|---|
| `rpg/tests/unit/test_import_job_finalization.py` | 96 | `monkeypatch.setattr(_ip, "connect", _fake_connect)` | **零影响**(方案把 finalize/reap/JobController 留在原模块) |
| 同上 | 97 | `monkeypatch.setattr(_ip, "init_db", lambda: None)` | 零影响 |
| 同上 | 154 | `monkeypatch.setattr(mod, "init_db", ...)` | 零影响 |
| 同上 | 159 | `monkeypatch.setattr(mod, "connect", _boom)` | 零影响 |
| `rpg/tests/integration/test_import_pipeline_partial_failure.py` | 37 | `patch.object(ip, "connect")` 然后调 `ip._stage_worldbook` | **受影响**:_stage_worldbook 搬走后,其函数体解析 `connect` 走新模块 globals,patch 旧命名空间失效 → 测试会打到真 connect。**必须同批次改**(§5 B2-T2) |
| 同上 | 14 | `from platform_app.import_pipeline import _final_stage_status` | shim 覆盖,零影响 |
| 同上 | 45 | `patch("agents._harness.call_agent_json", ...)` | 真实命名空间,零影响 |
| `rpg/tests/integration/test_import_pipeline_model_resolution.py` | 34-36, 113-115 | **`spec_from_file_location("platform_app.import_pipeline", _PIPELINE_PATH)` 按文件路径直接加载本文件** | **受影响**:加载路径与模块名都要改指向新 stages 模块(§5 B2-T1) |
| 同上 | 213/237/270/290/321/343 | 6 × `patch.object(_pipeline, "connect", ...)` | **受影响**(6 个 patch 点):随加载目标切到新模块后自动恢复有效,无需逐个改 |
| 同上 | 126-129 | 读 `_pipeline._resolve_extractor_llm / _stage_story_phase_llm / _stage_cards / _stage_worldbook` | 受影响,随 B2-T1 一并解决 |
| `rpg/tests/integration/test_rebuild_endpoints.py` | 18/21/33/50/64 | `ip.REBUILD_MODULES`、hasattr 断言 7 个 rebuild 符号、`ip.normalize_rebuild_module` | shim 覆盖,零影响(同一对象被 re-export,hasattr 仍真) |
| `rpg/tests/integration/test_extract_resolve_protagonist.py` | 10, 80 | `import_pipeline._rerank_cards_by_canon_importance(sid)` | shim 覆盖,零影响(真 DB 集成测试,不 patch connect) |
| `rpg/tests/integration/test_qa_fixes_birthpoint_protagonist.py` | 208-229 | 同上 ×2 | shim 覆盖,零影响 |
| `rpg/tests/integration/test_sse_module_field.py` | 21 | 仅注释提及 get_job_status | 零影响 |
| `rpg/conftest.py` | 5 | 文档注释提及 model_resolution 的 stub 历史 | 建议顺手更新注释(非必须) |

**受影响 patch 点合计:7**(6 个 model_resolution + 1 个 partial_failure)。其余 4 个(finalization)因方案刻意不动 finalize/reap 而零影响 —— 这是「finalize_job_if_unterminated / reap_zombie_import_jobs / JobController 必须留在 import_pipeline.py」的硬约束来源。

### 2.3 陷阱② 核查:Path(__file__) / 相对路径

`grep -n "__file__\|os\.path\|Path(" rpg/platform_app/import_pipeline.py` → **零命中**(exit 1)。文件内唯一的 `import os` 在 `reap_zombie_import_jobs` 里读 env 变量,与文件位置无关。**本陷阱不适用,无需逐处迁移。**

### 2.4 模块级单例与 import 副作用核查

- `_IMPORT_GLOBAL_SEM` / `_QUEUE_LOCK` / `_RUNNING`:模块级单例,**必须留在 import_pipeline.py**(account_io 经 `getattr(import_pipeline, "_IMPORT_GLOBAL_SEM")` 取同一信号量对象;搬走后即使 re-export 也只在新旧两模块各留一个名字指向同一对象——对象型可行,但毫无必要,留原地零风险)。
- `_QUEUE_DEPTH`:**int,且被 `global _QUEUE_DEPTH` 重绑定**。绝不能搬、绝不能依赖 re-export(int 重绑定不跨模块传播)。其读写方 schedule_full_import / _run_pipeline 全部留在原模块 → 安全。
- 无装饰器注册表、无 import 时 DB 连接等副作用;`STAGES`/`REBUILD_MODULES` 是纯常量 dict/list。
- `setattr(_stage_cards, "_last_llm_failures", ...)` / `setattr(_stage_worldbook, "_last_count", ...)`:函数对象属性通道。re-export 绑定的是**同一函数对象**,跨模块 getattr/setattr 依旧成立,逐字保留即可(丑,但不在本次机械搬运中改;见 §7)。

## 3. 目标布局

遵循 platform_app 根目录扁平命名惯例(`script_import.py`、`save_io.py` 风格,根目录不用下划线前缀;下划线前缀是 knowledge/ 子包内部惯例):

```
rpg/platform_app/
├── import_pipeline.py     (保留 ≈720 行)  簇 A:STAGES、单例、estimate_budget、JobController、
│                                         schedule_full_import、get_job_status、cancel_job、list_jobs、
│                                         _run_pipeline、_finalize_cancelled、_TERMINAL_STATUSES、
│                                         finalize_job_if_unterminated、reap_zombie_import_jobs
│                                         + 末尾/顶部 re-export shim(§4)
├── import_credentials.py  (新, ≈100 行)  簇 C:2 个异常类 + 7 个凭证/LLM 解析函数
│                                         (注意与 user_credentials.py 区分:那是存储层 CRUD,
│                                          本模块是拆书管线的解析+门控逻辑)
├── import_stages.py       (新, ≈1215 行) 簇 B:17 个阶段函数/helper,顶部
│                                         `from .import_credentials import ...` 单向依赖
└── import_rebuild.py      (新, ≈665 行)  簇 D:rebuild 注册表+4 个 rebuild 函数+estimate/schedule/
                                          worker+_count+2 个 embedding prereq helper
```

### 循环导入审计(必须满足)

```
import_credentials  ← 顶层仅 stdlib/typing;重依赖全部函数级 lazy(model_registry、core.vertex_sa、
                       platform_app.user_credentials、agents._harness)。无出边。
import_stages       → import_credentials(顶层 from-import)、.db(顶层)、psycopg(顶层)。
                       knowledge/agents._harness/.usage/extract.arc_pipeline/.knowledge.embedding
                       维持原文的函数级 lazy import,逐字不动。
import_rebuild      → import_credentials、import_stages(顶层,只为 _stage_worldbook)、.db、psycopg。
                       ⚠ JobController 必须用函数级 lazy:在 _run_module_rebuild 函数体首行加
                       `from .import_pipeline import JobController`(这是全方案唯一一处允许的
                       非逐字差异,原文该 import 在模块顶层语境下隐含可得)。
import_pipeline     → import_credentials、import_stages、import_rebuild(顶层,re-export shim)。
```

加载顺序无论从哪个模块进入都无环:import_rebuild→import_pipeline 的边只在 `_run_module_rebuild` 被调用时触发(那时调度方早已 import 完毕)。验证命令:
`python -c "import platform_app.import_rebuild"` 与 `python -c "import platform_app.import_pipeline"` 各自独立成功。

## 4. re-export shim(陷阱①+⑤ 的处置)

`import_pipeline.py` **不删除**,保留为「簇 A 实体 + 全量 re-export shim」。在 `from .db import connect, expose, init_db` 之后插入:

```python
# ── re-export shim ──────────────────────────────────────────────────
# 外部调用方(api/imports.py、api/scripts.py、knowledge/card_audit.py、tests/)
# 一律经 platform_app.import_pipeline.* 访问下列符号;拆分后在此保持原命名空间可用。
# ⚠ 测试若 monkeypatch DB 缝,patch 目标是符号的【定义模块】:
#    - 簇 A(本文件):patch platform_app.import_pipeline.connect
#    - 阶段函数:patch platform_app.import_stages.connect
#    - rebuild:patch platform_app.import_rebuild.connect
from .import_credentials import (  # noqa: F401
    MissingUserCredentialError, MissingEmbeddingCredentialError,
    require_user_llm_credential, _resolve_extractor_llm, _normalize_llm_api_id,
    _credential_api_id_for, _api_kind, _has_user_llm_credential,
    _require_user_llm_credential,
)
from .import_stages import (  # noqa: F401
    _stage_chunks, _stage_facts, _stage_story_phase_llm,
    _backfill_unphased_with_even_split, _even_split_phases, _stage_phase_digests,
    _stage_entities, _final_stage_status, _stage_cards, _stage_worldbook,
    _stage_canon_extract, _stage_npc_voices,
    _backfill_chapter_facts_events_from_canon, _rerank_cards_by_canon_importance,
    _count_canon_and_anchors, _stage_embeddings, _parse_json,
)
from .import_rebuild import (  # noqa: F401
    REBUILD_MODULES, normalize_rebuild_module,
    rebuild_chunks_from_db, rebuild_facts_from_db, rebuild_cards_from_canon,
    rebuild_worldbook_with_llm, estimate_module_rebuild, schedule_module_rebuild,
    _run_module_rebuild, _count, _embedding_preflight_or_raise, _embedding_prereq,
)
```

要点:
- 异常类 re-export 后 `except import_pipeline.MissingUserCredentialError` 与 card_audit 的 raise 是**同一类对象**,isinstance/except 语义不变。
- `test_rebuild_endpoints` 的 hasattr 断言(含 `_run_module_rebuild`)全部经 shim 通过。
- shim 永久保留(不是过渡期产物):card_audit/api 层继续走 import_pipeline 命名空间,无需追改 8 处调用方。

## 5. 可机械执行的搬运清单(逐字搬运,禁止改写逻辑)

> 执行纪律(陷阱③):每个符号**整函数/整类逐字剪切**,包括函数内注释、`setattr` 尾巴、`import logging as _log` 之类的函数级 import。唯一允许的差异:§3 标注的 `_run_module_rebuild` 函数体首行新增 lazy import JobController 一行。执行代理为 sonnet 时,把本表逐行喂给它,完成后 diff 校验「旧文件删除行数 ≈ 新文件新增行数」。

### 批次 B1 → 新建 `rpg/platform_app/import_credentials.py`

模块头:`from __future__ import annotations` + `from typing import Any`(仅此;不需要 .db/psycopg)。

| 序 | 符号 | 原起始行 |
|---|---|---|
| 1 | `class MissingUserCredentialError` | @62 |
| 2 | `class MissingEmbeddingCredentialError` | @72 |
| 3 | `_normalize_llm_api_id` | @816 |
| 4 | `_credential_api_id_for` | @824 |
| 5 | `_api_kind` | @839 |
| 6 | `_has_user_llm_credential` | @848 |
| 7 | `_require_user_llm_credential` | @865 |
| 8 | `_resolve_extractor_llm` | @795 |
| 9 | `require_user_llm_credential` | @828 |

import_pipeline.py 同批次:删除上述定义,顶部加 §4 的第一段 re-import。

### 批次 B2 → 新建 `rpg/platform_app/import_stages.py`

模块头:`from __future__ import annotations`、`import json`、`import re`、`from collections import Counter`、`from typing import Any`、`from psycopg.types.json import Jsonb`、`from .db import connect, init_db`、`from .import_credentials import _resolve_extractor_llm`。

| 序 | 符号 | 原起始行 | 备注 |
|---|---|---|---|
| 1 | `_stage_chunks` | @725 | |
| 2 | `_stage_facts` | @758 | |
| 3 | `_stage_story_phase_llm` | @871 | 测试 patch 目标,见 B2-T1 |
| 4 | `_backfill_unphased_with_even_split` | @993 | |
| 5 | `_even_split_phases` | @1007 | |
| 6 | `_stage_phase_digests` | @1029 | |
| 7 | `_stage_entities` | @1109 | |
| 8 | `_final_stage_status` | @1148 | |
| 9 | `_stage_cards` | @1158 | 尾部两个 `setattr` 逐字保留;@1180 的无副作用语句 `int(book_row["id"]) if book_row else None` **原样搬,不许"顺手删"** |
| 10 | `_stage_worldbook` | @1333 | `setattr(_stage_worldbook, "_last_count", ...)` 逐字保留 |
| 11 | `_stage_canon_extract` | @1479 | |
| 12 | `_stage_npc_voices` | @1597 | 死代码,**本批原样搬**,删除走 §7 独立 followup |
| 13 | `_backfill_chapter_facts_events_from_canon` | @1739 | |
| 14 | `_rerank_cards_by_canon_importance` | @1863 | |
| 15 | `_count_canon_and_anchors` | @1914 | |
| 16 | `_stage_embeddings` | @1931 | |
| 17 | `_parse_json` | @2002 | |

import_pipeline.py 同批次:删除定义,加 §4 第二段 re-import。

**B2-T1 同步改 `rpg/tests/integration/test_import_pipeline_model_resolution.py`**(陷阱① 的 7 个受影响点中的 6 个):
- L34-36:`_PIPELINE_PATH` 改指 `"..", "..", "platform_app", "import_stages.py"`;
- L113-115:`spec_from_file_location("platform_app.import_stages", _PIPELINE_PATH)`,stub_map 键同步改 `"platform_app.import_stages"`;
- L126-129 与各处 `_pipeline.` 读法不变(新模块顶层绑定了 `_resolve_extractor_llm`,四个符号都在);
- 6 处 `patch.object(_pipeline, "connect", ...)` **一行不用改**——加载目标切换后,`_pipeline` 即 import_stages,patch 恢复对症;
- 模块 docstring/注释中的 "import_pipeline" 提法顺手更正为 import_stages(纯注释)。
- 兼容性依据:conftest.py 已在 collection 前 eager-import 真 `platform_app` 包(含 `__path__`),故按文件路径 exec import_stages 时其顶层相对导入 `from .import_credentials import ...` 可解析;`from .db import ...` 命中 stub_map 里的 `platform_app.db` stub,与现状一致。

**B2-T2 同步改 `rpg/tests/integration/test_import_pipeline_partial_failure.py`**(第 7 个受影响点):
- L34 增 `from platform_app import import_stages as st`(或替换 ip);
- L37:`patch.object(ip, "connect")` → `patch.object(st, "connect")`;
- L46/L48 的 `ip._stage_worldbook` 可保留(同一函数对象)或改 `st._stage_worldbook`,推荐改成 st 以表达真实 patch 缝;
- L14 `from platform_app.import_pipeline import _final_stage_status` 经 shim 仍可用,不必改。

### 批次 B3 → 新建 `rpg/platform_app/import_rebuild.py`

模块头:`from __future__ import annotations`、`import secrets`、`import threading`、`from typing import Any`、`from psycopg.types.json import Jsonb`、`from .db import connect, init_db`、`from .import_credentials import require_user_llm_credential, _resolve_extractor_llm, _has_user_llm_credential, _credential_api_id_for, MissingEmbeddingCredentialError`、`from .import_stages import _stage_worldbook`。

| 序 | 符号 | 原起始行 | 备注 |
|---|---|---|---|
| 1 | `rebuild_chunks_from_db` | @2019 | |
| 2 | `rebuild_facts_from_db` | @2061 | |
| 3 | `rebuild_cards_from_canon` | @2114 | |
| 4 | `rebuild_worldbook_with_llm` | @2181 | |
| 5 | `REBUILD_MODULES` | @2230 | |
| 6 | `normalize_rebuild_module` | @2241 | |
| 7 | `_embedding_preflight_or_raise` | @2250 | |
| 8 | `_embedding_prereq` | @2259 | |
| 9 | `estimate_module_rebuild` | @2275 | |
| 10 | `schedule_module_rebuild` | @2422 | |
| 11 | `_run_module_rebuild` | @2487 | **函数体首行新增** `from .import_pipeline import JobController`(lazy,防环;全方案唯一非逐字点) |
| 12 | `_count` | @2668 | |

import_pipeline.py 同批次:删除定义,加 §4 第三段 re-import。本批**无测试需要改**(test_rebuild_endpoints 全走 shim)。

### 批次 B4 → 全量验证 + 残留清查(陷阱⑤)

1. `python -m py_compile rpg/platform_app/import_pipeline.py rpg/platform_app/import_credentials.py rpg/platform_app/import_stages.py rpg/platform_app/import_rebuild.py`
2. 定向测试(本机一次性 PG 配方见 memory project_rpg_local_testdb):
   `pytest rpg/tests/unit/test_import_job_finalization.py rpg/tests/integration/test_import_pipeline_model_resolution.py rpg/tests/integration/test_import_pipeline_partial_failure.py rpg/tests/integration/test_rebuild_endpoints.py rpg/tests/integration/test_extract_resolve_protagonist.py rpg/tests/integration/test_qa_fixes_birthpoint_protagonist.py rpg/tests/integration/test_sse_module_field.py -x`
3. 全套件回归(基线 838+)。
4. 残留清查:`grep -n "def _stage_\|def rebuild_\|class Missing" rpg/platform_app/import_pipeline.py` 只应命中 re-import 行;新旧文件行数对账(2673 ≈ 720+100+1215+665 − 重复 import 头 + shim 块)。
5. 明确去向声明:import_pipeline.py = **永久 shim + 簇 A 实体**,不删除;无孤儿文件(三个新文件都有唯一职责与调用方)。

### 批次串行性(陷阱④)

B1→B2→B3→B4 **严格串行,单代理执行**:每个批次都要改 `import_pipeline.py` 本体,任何并行都会在同一文件上撞中间态。B2 内部「新建 stages + 改 import_pipeline + 改两个测试」必须同一 commit,否则中间态下 model_resolution/partial_failure 红。每批次后跑 §B4-2 的定向测试再进下一批。

## 6. ≥80 行巨型函数逐个评估(拆/不拆)

| 函数 | 行数 | 判定 | 理由 |
|---|---|---|---|
| `_run_pipeline` | 192 | **不拆**(本轮) | 8 个阶段块结构高度同构,看似可表驱动,但每块的 error/skip/计数语义都有微差(cards 的失败率阈值、canon 双状态返回、anchors 只报告),表驱动化属于**逻辑改写**,违反逐字搬运纪律。保留;若未来要动,先补 _run_pipeline 的端到端测试再做。 |
| `_stage_cards` | 173 | 不拆(本轮) | 单一循环流程(去重→取上下文→LLM→写卡),内部局部函数 `_norm_name` 已是合理抽象;拆 prompt builder 收益低、风险是 sonnet 顺手改写 prompt 文案。 |
| `_run_module_rebuild` | 179 | 不拆(本轮) | module 分发器,if/elif 每支 ≤45 行;表驱动化同样是逻辑改写。注意它含疑似 bug(§7-2),修 bug 时再顺势整,不混入机械搬运。 |
| `estimate_module_rebuild` | 145 | **不拆** | 纯数据表型:counts 采集 + prereq 声明式拼装,无流程分阶段价值。 |
| `_stage_worldbook` | 144 | 不拆(本轮) | seed 构建→LLM→写库一条线;且有 2 个测试盯着它的 except 路径与 setattr,动它的形状=动测试。 |
| `_stage_npc_voices` | 140 | **删除**(独立 followup) | 死代码,见 §7-1。 |
| `_backfill_chapter_facts_events_from_canon` | 122 | 不拆 | 单一数据变换,事件文本模板内聚。 |
| `_stage_story_phase_llm` | 120 | 不拆(本轮) | 采样→LLM→校验→落库+双层 fallback 是一个不可分的容错单元,fallback 注释承载领域知识(5 段枚举跨层共享),拆散反而丢上下文。 |
| `_stage_canon_extract` | 116 | 不拆 | 90% 是委托 extract.arc_pipeline + 错误包装。 |
| `estimate_budget` | 90 | **不拆** | 纯估算数据表型(任务书明示此类不该拆)。 |

结论:本轮**只做模块级搬运,不做任何函数体拆解**——该文件的「巨型函数」多数是流水线容错单元或数据表,真正的问题是四簇混居,搬运即解决主要矛盾。

## 7. 顺手发现(不混入机械批次,各自独立 commit/决策)

1. **死代码 `_stage_npc_voices`(@1597,140 行)**:`grep -rn "npc_voice" rpg/ --include="*"` 除定义处零命中;`_run_pipeline` 的 8 阶段也不含它。判定为某轮设计的遗留(card 结构化字段 backfill 后来走了别的路径)。方案:B2 原样搬入 import_stages 并保留 shim re-export(保持机械性/可回滚),随后**单独 commit 删除**(连同 shim 行)——删除前再跑一次全仓 grep 留证。
2. **疑似真 bug:`_run_module_rebuild` canon 分支复用已退出的连接**(@2513、@2521):`before = _count(db, ...)` 的 `db` 来自 @2494 `with connect() as db:` 块,**该上下文已退出**;若 connect() 归还连接到池,这里在闭/还连接上执行 SQL。机械搬运时逐字保留,修复单列(改成各自 `with connect() as db:` 包裹)。
3. **`_stage_cards` @1180 无副作用语句** `int(book_row["id"]) if book_row else None`:历史残留(book_id 后来不用了),连同上面的 books 查询其实都可删;本轮原样搬,清理单列。
4. `estimate_budget` 的 stages 估算仍是旧 5 阶段口径,与 STAGES 的 8 阶段不一致(canon_extract/anchors/embeddings 未计价)——产品口径问题,仅记录。
5. `setattr` 函数属性通道(cards/worldbook → _run_pipeline):建议未来改为返回值元组,需同步 partial_failure 测试;不在本轮。

## 8. 风险清单

| 风险 | 等级 | 缓解 |
|---|---|---|
| model_resolution 测试按文件路径加载,漏改 → 全模块 ImportError 或 patch 失效 | 高 | B2-T1 与搬运同 commit;B4 定向跑该文件 |
| partial_failure 的 `patch.object(ip, "connect")` 漏改 → 测试打真 DB 缝,CI 环境可能假绿/报错 | 高 | B2-T2 同 commit |
| `_QUEUE_DEPTH` int 重绑定被误搬/误 re-export | 中 | 明确留在簇 A,搬运清单不含它;review diff 时检查 `global _QUEUE_DEPTH` 仍与定义同文件 |
| import_rebuild ↔ import_pipeline 环 | 中 | JobController 函数级 lazy(§3);B4 用两条独立 `python -c import` 验证 |
| sonnet 顺手"简化"prompt 字符串/注释/setattr 尾巴 | 中 | 逐字纪律写进执行 prompt;diff 行数对账;五处 ⚠ 备注点逐一人工复核 |
| OSS fork 同步:三个新文件 + 两个测试改动需随 cherry-pick 走五闸 | 低 | 常规 oss-sync 流程即可,无 secret/无小说内容 |
| account_io 的 `getattr(import_pipeline, "_IMPORT_GLOBAL_SEM")` | 低 | 单例留原模块,零变化 |

## 9. 验证命令汇总

```bash
# 编译闸
python -m py_compile rpg/platform_app/import_{pipeline,credentials,stages,rebuild}.py
# 环导入闸(两条独立进程)
cd rpg && python -c "import platform_app.import_rebuild" && python -c "import platform_app.import_pipeline"
# 定向回归(B1/B2/B3 每批后)
pytest rpg/tests/unit/test_import_job_finalization.py \
       rpg/tests/integration/test_import_pipeline_model_resolution.py \
       rpg/tests/integration/test_import_pipeline_partial_failure.py \
       rpg/tests/integration/test_rebuild_endpoints.py -x -q
# 全量(B4)
pytest rpg/tests -q
# 残留清查(B4)
grep -n "def _stage_\|def rebuild_\|class Missing" rpg/platform_app/import_pipeline.py
```
