# 拆分方案:rpg/platform_app/script_import.py(1189 行)

- **日期**:2026-06-10
- **审计人**:函数抽象层体检(abstraction workflow 子代理)
- **verdict**:`needs-refactor`(职责混杂:4 个内聚簇挤在一个文件里)
- **priority**:medium —— 文件能跑、无已知 bug,拆分收益是导航性/复用性,不是正确性;不必抢在功能开发前
- **effort**:M(一次串行批次可完成,约 5 个新文件 + 1 个 facade,纯机械搬运)

---

## 1. 现状结构图(按内聚簇着色)

文件实际上是 **4 个互相独立的子系统** 共享一个命名空间:

```
script_import.py (1189 行)
│
├─ 簇 A:导入/切分/剧本生命周期(≈400 行)
│   _NESTED_QUANTIFIER_RE        @69   (模块级正则常量)
│   _validate_custom_pattern     @72   (ReDoS 防护)
│   import_script                @85   (140 行,主导入流水线)
│   list_chapters                @571
│   _chapter_preview             @599
│   _cursor_index                @612
│   preview_split                @625  (dry-run 预切)
│   delete_script                @676
│   resplit_script               @733  (83 行,重切)
│
├─ 簇 B:DB 持久化后台同步任务(≈330 行,自带单例)
│   _jsonify                     @32   (jsonb 安全序列化,task 23)
│   logging/threading/ThreadPoolExecutor 导入块 @238
│   _SYNC_POOL                   @244  ⚠️ 模块级单例 ThreadPoolExecutor
│   MAX_ACTIVE_JOBS_PER_USER / STALE_RUNNING_SECONDS / SYNC_HEARTBEAT_SECONDS @247-258
│   _schedule_knowledge_sync     @261
│   _claim_pending_job           @345
│   _run_sync_job                @367  (105 行,含嵌套 _heartbeat_loop 闭包)
│   recover_pending_sync_jobs    @474  (startup 恢复)
│   get_sync_status              @531
│
├─ 簇 C:分片上传子系统(≈260 行,自带平台分发)
│   _json/_secrets/_t 导入块      @821
│   fcntl try/except 平台锁分发   @833  ⚠️ 模块级 import 副作用(POSIX/Windows 二选一)
│   _lock_meta_file/_unlock_meta_file(+ _META_FALLBACK_LOCK Windows 分支)
│   init_upload                  @858
│   put_chunk                    @880
│   finish_upload                @909
│   cancel_upload                @944
│   _upload_dir                  @952  (路径越权防护)
│   _read_meta                   @972
│   _consume_upload_chunks       @1138
│   cleanup_stale_upload_chunks  @1160 (startup 调用)
│
├─ 簇 D:章节手动编辑(≈155 行)
│   update_chapter               @982
│   merge_chapters               @1029
│   split_chapter                @1079
│
└─ 共享头部(@1-25)
    BASE = Path(__file__).resolve().parents[1]   ⚠️ 陷阱②高危
    SCRIPT_ROOT / UPLOAD_CHUNK_ROOT(由 BASE 派生)
    MAX_SCRIPT_UPLOAD_BYTES / MAX_UPLOAD_CHUNK_BYTES(import 时读 core.config)
```

**簇间依赖(单向,无环)**:
- A → C:`import_script` / `preview_split` 调 `_consume_upload_chunks`
- A → B:`import_script` 失败回退时调 `_schedule_knowledge_sync`
- B、C、D 互不依赖;D 只依赖 `..db`
- A 懒导入 `.import_pipeline`(函数体内);B 懒导入 `. knowledge`(函数体内)
- **反向核查过**:`import_pipeline.py`、`knowledge/*` 均不 import `script_import` → 拆分不会引入 import 环

## 2. 外部消费面(Grep 实查)

| 消费方 | 用到的符号 | 访问方式 |
|---|---|---|
| `rpg/platform_app/api/scripts.py` | `import_script, list_chapters, update_chapter, merge_chapters, split_chapter, resplit_script, delete_script, preview_split, MAX_SCRIPT_UPLOAD_BYTES, init_upload, put_chunk, finish_upload, cancel_upload` | `from .. import script_import` + 属性访问 |
| `rpg/platform_app/api/imports.py` | `get_sync_status` | 同上 |
| `rpg/core/startup.py` | `recover_pending_sync_jobs`(属性)、`cleanup_stale_upload_chunks`(**from-import**,@190) | 函数体内懒导入 |
| `rpg/tools_dsl/command_tools_imports.py` | `import_script, get_sync_status, resplit_script, delete_script` | 函数体内 `from platform_app import script_import` + 属性访问 |
| 测试(见 §3) | 另含私有符号 `_jsonify, _schedule_knowledge_sync, _claim_pending_job, _run_sync_job, _SYNC_POOL` | 混合 |

属性访问占绝对多数 → 只要 `platform_app.script_import` 这个模块对象上仍有这些属性,所有调用方零改动。唯二的 from-import:`startup.py:190`(`cleanup_stale_upload_chunks`)与 `test_sync_job_jsonify.py:115/139`(`_jsonify`),facade re-export 即可覆盖。

## 3. 测试 patch 点清单(Grep 实查,共 7 处 mock/monkeypatch)

| # | 文件:行 | patch 形式 | 拆分后是否仍生效 |
|---|---|---|---|
| 1 | `rpg/tests/test_script_import_api.py:24` | `monkeypatch.setattr(scripts_api.script_import, "import_script", …)` | ✅ 对包 facade 的属性 setattr;`scripts.py` 调用时属性查找走 facade |
| 2 | `rpg/tests/unit/test_command_tools_misc.py:197` | `patch("platform_app.script_import.import_script")` | ✅ 字符串命名空间落在 facade;tools_dsl 用属性访问 |
| 3 | `rpg/tests/integration/test_sync_job_jsonify.py:79` | `patch.object(script_import._SYNC_POOL, "submit", …)` | ✅ patch 的是**单例对象**的方法,与命名空间无关——前提:facade re-export 的 `_SYNC_POOL` 必须是同一对象(`from ._sync_jobs import _SYNC_POOL`) |
| 4 | `rpg/tests/integration/test_durable_sync.py:53` | 同上 `patch.object(_SYNC_POOL, "submit")` | ✅ 同上 |
| 5 | `rpg/tests/integration/test_durable_sync.py:142` | 同上 | ✅ |
| 6 | `rpg/tests/integration/test_durable_sync.py:172` | 同上 | ✅ |
| 7 | `rpg/tests/integration/test_durable_sync.py:194` | 同上 | ✅ |

另有 **非 patch 但命名空间敏感** 的测试直引(必须进 facade re-export 名单):
- `test_sync_job_jsonify.py:115,139`:`from platform_app.script_import import _jsonify`
- `test_durable_sync.py` 全文 + `test_sync_job_jsonify.py`:`script_import._schedule_knowledge_sync`(11 处)、`_claim_pending_job`(2)、`_run_sync_job`(2)、`recover_pending_sync_jobs`(4)、`get_sync_status`(1)、`_SYNC_POOL`(5)
- `test_upload_import_chain.py`:纯走 HTTP API,命名空间无关 ✅

**结论:7 个 patch 点全部可以靠「facade re-export 同名同对象」零改动存活,无需改任何测试文件。**

⚠️ 唯一的理论缝隙(现在没有测试踩,但要写进 PR 说明防将来):facade 属性 patch **不穿透包内跨模块调用**。例如将来若有人 `patch("platform_app.script_import._consume_upload_chunks")` 想影响 `import_script` 的行为——拆分后 `import_script` 直接绑定 `_uploads._consume_upload_chunks`,patch facade 无效,得 patch `platform_app.script_import._import_ops._consume_upload_chunks`。当前 Grep 确认没有任何测试这样做。

## 4. 目标布局(遵循 `knowledge/` 包的既有惯例:`_` 前缀实现模块 + facade `__init__.py`)

```
rpg/platform_app/script_import/          # 模块 → 同名包,外部 import 路径完全不变
├── __init__.py        (~45 行)  纯 re-export facade,无逻辑
├── _common.py         (~30 行)  BASE/SCRIPT_ROOT/UPLOAD_CHUNK_ROOT/两个 MAX_* 常量
├── _import_ops.py     (~400 行) 簇 A:导入/预切/重切/删除/列章节
├── _sync_jobs.py      (~330 行) 簇 B:_SYNC_POOL 单例 + durable job 全套 + _jsonify
├── _uploads.py        (~215 行) 簇 C:分片上传 + fcntl 平台锁 + 清理
└── _chapter_edit.py   (~165 行) 簇 D:update/merge/split 章节
```

为什么选「模块转包」而不是平铺同级新文件:`platform_app.script_import` 这个点路径是 7 个 patch 点 + 2 个 from-import + 全部属性访问的锚点,转包后锚点不动;`knowledge/` 已确立此风格(`_sync.py/_chunks.py/_utils.py` + facade),不引入新惯例。

### facade `__init__.py` 内容(完整 re-export 名单,缺一不可)

```python
# 簇 A
from ._import_ops import (
    import_script, preview_split, resplit_script, delete_script,
    list_chapters, _chapter_preview, _cursor_index, _validate_custom_pattern,
)
# 簇 B(_SYNC_POOL 必须 re-export 同一对象,5 个 patch.object 依赖它)
from ._sync_jobs import (
    _jsonify, _SYNC_POOL, _schedule_knowledge_sync, _claim_pending_job,
    _run_sync_job, recover_pending_sync_jobs, get_sync_status,
    MAX_ACTIVE_JOBS_PER_USER, STALE_RUNNING_SECONDS, SYNC_HEARTBEAT_SECONDS,
)
# 簇 C
from ._uploads import (
    init_upload, put_chunk, finish_upload, cancel_upload,
    _upload_dir, _read_meta, _consume_upload_chunks, cleanup_stale_upload_chunks,
)
# 簇 D
from ._chapter_edit import update_chapter, merge_chapters, split_chapter
# 共享常量(api/scripts.py:760 直读 MAX_SCRIPT_UPLOAD_BYTES)
from ._common import BASE, SCRIPT_ROOT, UPLOAD_CHUNK_ROOT, MAX_SCRIPT_UPLOAD_BYTES, MAX_UPLOAD_CHUNK_BYTES
```

## 5. 可机械执行的搬运清单(符号 → 目标文件;**逐字搬运、禁止改写逻辑**)

> 执行代理铁律:除下表「允许改动」列明确列出的行外,函数体一个字符都不许动 —— 不许"顺手"改 f-string、合并 import、调整 SQL 缩进、重命名局部变量。

### `_common.py`(源行 @1-25 的拆出部分)

| 源符号 | 源行 | 允许改动 |
|---|---|---|
| `BASE` | @14 | ⚠️ **必改**:`parents[1]` → `parents[2]`(文件深了一层,见 §7 陷阱②) |
| `SCRIPT_ROOT` / `UPLOAD_CHUNK_ROOT` | @15-16 | 无(由 BASE 派生) |
| `from core.config import script_upload_max_bytes/upload_chunk_max_bytes` + `MAX_SCRIPT_UPLOAD_BYTES` / `MAX_UPLOAD_CHUNK_BYTES` | @17-25 | 无 |

### `_import_ops.py`

| 源符号 | 源行 | 允许改动 |
|---|---|---|
| `_NESTED_QUANTIFIER_RE` + `_validate_custom_pattern` | @68-82 | 无 |
| `import_script` | @85-224 | 函数体内 @202 `from .import_pipeline import schedule_full_import` → `from ..import_pipeline import …`(相对层级 +1) |
| `list_chapters` | @571-596 | 无 |
| `_chapter_preview` | @599-609 | 无 |
| `_cursor_index` | @612-619 | 无 |
| `preview_split` | @625-670 | 无 |
| `delete_script` | @676-727 | 无 |
| `resplit_script` | @733-815 | 无 |
| 模块头新增 | — | `from ..db import connect, expose, init_db, limit_value, page_payload`;`from ..library import decode_upload, safe_filename, unique_path`;`from chapter_splitter import chapter_splitter`;`from psycopg.types.json import Jsonb`;`from ._common import BASE, SCRIPT_ROOT, MAX_SCRIPT_UPLOAD_BYTES`;`from ._uploads import _consume_upload_chunks`;`from ._sync_jobs import _schedule_knowledge_sync`;`logger = logging.getLogger(__name__)`(import_script@210、delete_script@707/718 用到 logger;原文件 logger 定义在 @242,晚于 import_script 定义但运行期可见——新模块必须在顶部定义) |

### `_sync_jobs.py`

| 源符号 | 源行 | 允许改动 |
|---|---|---|
| `_jsonify` | @28-65 | 无(连同 @28-31 的 task 23 注释一起搬) |
| `import logging/threading/ThreadPoolExecutor` + `logger` + `_SYNC_POOL` | @238-244 | 无(`_SYNC_POOL` 单例定义只能出现在这一个文件) |
| `MAX_ACTIVE_JOBS_PER_USER` + config 导入 + `STALE_RUNNING_SECONDS` + `SYNC_HEARTBEAT_SECONDS` | @247-258 | 无 |
| `_schedule_knowledge_sync` | @261-342 | 函数体内 @273 `from .db import connect, init_db` → `from ..db import …` |
| `_claim_pending_job` | @345-364 | 函数体内 @350 `from .db import connect` → `from ..db import connect` |
| `_run_sync_job`(含嵌套 `_heartbeat_loop`) | @367-471 | 函数体内 @371 `from . import knowledge` → `from .. import knowledge`;@372 `from .db import connect, init_db` → `from ..db import …` |
| `recover_pending_sync_jobs` | @474-528 | 函数体内 @483 `from .db import connect, init_db` → `from ..db import …` |
| `get_sync_status` | @531-568 | 函数体内 @533 `from .db import connect, init_db` → `from ..db import …` |
| 模块头注释块 | @227-237 | 原样搬(三层防重复跑的设计说明) |

### `_uploads.py`

| 源符号 | 源行 | 允许改动 |
|---|---|---|
| `import json as _json / secrets as _secrets / time as _t` | @821-823 | 无 |
| fcntl try/except 平台分发(`_lock_meta_file`/`_unlock_meta_file`/`_META_FALLBACK_LOCK`)含 @826-832 注释 | @826-856 | 无(模块级 import 副作用,整块原子搬运) |
| `init_upload` | @858-877 | 无 |
| `put_chunk` | @880-906 | 无 |
| `finish_upload` | @909-941 | 无 |
| `cancel_upload` | @944-949 | 无 |
| `_upload_dir` | @952-969 | 无 |
| `_read_meta` | @972-976 | 无 |
| `_consume_upload_chunks` | @1138-1157 | 无 |
| `cleanup_stale_upload_chunks` | @1160-1188 | 无 |
| 模块头新增 | — | `from ..library import safe_filename`;`from ._common import UPLOAD_CHUNK_ROOT, MAX_SCRIPT_UPLOAD_BYTES, MAX_UPLOAD_CHUNK_BYTES`;`from pathlib import Path`;`from typing import Any` |

### `_chapter_edit.py`

| 源符号 | 源行 | 允许改动 |
|---|---|---|
| `update_chapter` | @982-1026 | 无 |
| `merge_chapters` | @1029-1076 | 无 |
| `split_chapter` | @1079-1135 | 无 |
| 模块头新增 | — | `from ..db import connect, expose, init_db`;`from typing import Any` |

### 删除项
- 原 `rpg/platform_app/script_import.py` **整文件删除**(被包取代,非 shim 共存——同名模块与包不能并存)。facade `__init__.py` 即是 shim。
- 搬运后全文件清点:上表行号区间并集应 = @1-1188 全覆盖(@1-13 头部 import 按各新模块需要重建;@622-624、@673-675、@818-820、@979-981 的分节注释横幅随各自簇搬走)。**不允许有任何行"漏在表外"不了了之**。

## 6. ≥80 行巨型函数逐个评估

| 函数 | 行数 | 类型 | 是否拆阶段函数 |
|---|---|---|---|
| `import_script` | 140 | 流水线型(取原文 → 解码切分 → 校验模式 → 落盘 → 双表入库 → 调度任务 → 组响应) | **本次不拆,标记 P2**。理由:阶段间共享 8+ 个局部变量(raw/text/report/chapters/script_title/target_path…),硬拆要么传元组要么造 dataclass,机械搬运批次里做这个违反"禁止改写逻辑"。**真正的收益点在别处**:@168-195 的 script_chapters 12 列 executemany 与 `resplit_script` @780-799 几乎逐字重复 → P2 提一个 `_insert_chapter_rows(db, script_id, chapters, report)`,一处改两处用。这是逻辑变更,必须独立批次 + 独立 review,不混入搬运 |
| `_run_sync_job` | 105 | 流水线型,但 105 行里 ~35 行是嵌套闭包 `_heartbeat_loop`(持有 stop_heartbeat/job_id/consecutive_hb_failures 闭包状态) | **本次不拆,标记 P2 可选**。可抽 `_start_heartbeat(job_id) -> (threading.Event, Thread)`,纯机械度不够(闭包变量重绑),收益一般 |
| `resplit_script` | 83 | 流水线型 | 不拆。83 行里一半是与 import_script 共享的插入 SQL,P2 dedup 后自然降到 ~55 行 |

`_schedule_knowledge_sync`(82 行)恰在阈值边缘:竞态三段式(限流查 → ON CONFLICT 插 → 撞了回查重试)是**一个事务内的原子叙事**,拆开反而读不懂,不动。

## 7. 五大陷阱逐条核对 + 额外风险

1. **patch 命名空间穿透**:§3 已 Grep 实查全部 7 个 patch 点 + 全部私有符号直引,facade re-export 名单(§4)逐一覆盖;`_SYNC_POOL` 是 patch.object 目标,facade 必须 re-export **同一对象**而非新建。**无需改任何测试文件**。
2. **`Path(__file__)` 错位**:全文件唯一一处 @14 `BASE = Path(__file__).resolve().parents[1]`(→ `rpg/`)。搬进包后文件深一层,**必须改为 `parents[2]`**,且只在 `_common.py` 定义一次,其余模块 `from ._common import BASE`。SCRIPT_ROOT/UPLOAD_CHUNK_ROOT 由 BASE 派生,跟着走。验证:拆完后 `python -c "from platform_app.script_import import BASE; print(BASE)"` 必须仍指向 `rpg/`。
3. **执行代理顺手简化**:§5 表格即逐字搬运清单;允许改动的行已穷举(仅 3 类:相对 import 层级 +1、BASE parents 索引、各模块顶部新建 logger/import 头)。执行必须用 sonnet 子代理 + 本表逐行核对(见用户既有规约 feedback_delegate_to_sonnet / feedback_refactor_traps)。
4. **并行中间状态**:本方案**全程单文件来源**,禁止并行——见 §8 批次,Batch 1 一个提交内完成「建包 5 文件 + 删旧文件」,不存在新旧并存的中间提交。
5. **孤儿文件**:旧 `script_import.py` 明确**删除**(facade `__init__.py` 接管命名空间,不是留壳)。附带:清掉 `rpg/platform_app/__pycache__/script_import.cpython-*.pyc`,防 stale 字节码混淆。

额外核查:
- **循环导入**:新包内依赖单向(`_import_ops` → `_uploads`/`_sync_jobs`/`_common`;其余互不依赖);对外:`import_pipeline`、`knowledge` 均为函数体内懒导入且反向无引用(Grep 证实)→ 无环。
- **模块级单例与 import 副作用**:三处——`_SYNC_POOL`(ThreadPoolExecutor,workers=2)、fcntl try/except 平台锁分发、`MAX_*`/`STALE_*` 常量在 import 时读 core.config。三者原本都在 `import script_import` 时执行;转包后 facade `__init__.py` 顶部 eager import 全部子模块,**执行时机不变**(仍是首次 `import platform_app.script_import` 时)。无注册表/装饰器注册顺序问题。
- **`logger` 前向引用坑**:原文件 `import_script`(@210)用 `logger`,但 `logger` 定义在 @242——靠"运行期才解析模块全局"侥幸成立。搬到 `_import_ops.py` 后该模块必须**在顶部**定义自己的 logger,否则 NameError。logger 名从 `platform_app.script_import` 变为 `platform_app.script_import._import_ops` 等,日志归属字段变化,运维 grep 日志时前缀仍匹配 `platform_app.script_import`,可接受。

## 8. 串行批次划分

| 批次 | 内容 | 验证闸 |
|---|---|---|
| **Batch 1(机械搬运,单提交)** | 建 `script_import/` 包:`_common.py` → `_uploads.py` → `_sync_jobs.py` → `_chapter_edit.py` → `_import_ops.py` → `__init__.py`(按依赖序写,`_import_ops` 最后);同提交内 `git rm script_import.py`;清 `__pycache__` | `python -m compileall rpg/platform_app/script_import/`;`python -c "from platform_app import script_import; assert callable(script_import.import_script); from platform_app.script_import import _jsonify, _SYNC_POOL, cleanup_stale_upload_chunks; print(script_import.BASE)"`(BASE 须 = `rpg/`) |
| **Batch 2(回归)** | 不改代码,跑定向测试 | `pytest rpg/tests/integration/test_durable_sync.py rpg/tests/integration/test_sync_job_jsonify.py rpg/tests/integration/test_upload_import_chain.py rpg/tests/test_script_import_api.py rpg/tests/unit/test_command_tools_misc.py`;然后全量 pytest(本机一次性 PG 配方见 project_rpg_local_testdb) |
| **Batch 3(P2,可选、独立 review)** | ① 抽 `_insert_chapter_rows` 去重 import_script/resplit_script 的 12 列插入;② 可选抽 `_start_heartbeat` | 同 Batch 2 测试集;这是逻辑变更,**绝不与 Batch 1 混提交** |

禁止:两个代理同时碰 `script_import/` 任何文件;Batch 1 拆成多提交(会出现"包与旧模块并存/facade 缺符号"的中间态)。

## 9. 风险汇总

- **低**:patch 点全部经属性访问/单例对象,facade 覆盖即活;调用方零改动;无 import 环。
- **中**:`BASE` parents 索引若忘改,SCRIPT_ROOT/UPLOAD_CHUNK_ROOT 会指到 `rpg/platform_app/platform_data/…`,上传与删除源文件功能静默写错目录——Batch 1 验证闸里的 BASE 打印是硬闸,不许跳过。
- **中**:生产部署是 systemd 裸机 git pull(见 project_rpg_deploy),旧 `script_import.py` 在 `git rm` 后若服务器残留未跟踪同名文件会 shadow 包——部署后核 `ls rpg/platform_app/script_import.py` 不存在。
- **提醒**:facade 属性 patch 不穿透包内调用(§3 尾注),写进 PR 描述,给将来写测试的人看。
