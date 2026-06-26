# 拆分方案:rpg/extract/resolve.py(848 行)

- **判定**:needs-refactor(优先级 medium,工作量 M)
- **结论一句话**:一个文件里塞了 4 条互不相干的产出流水线(规范实体消歧、NPC 卡同步、时间线锚点、constant 世界书),其中世界书簇 ~260 行与实体聚簇簇零内存耦合;按内聚簇拆成 `extract/resolve/` 子包 + `__init__.py` 全量 re-export shim,对外 API(`extract.resolve` 模块路径)零变化,生产/测试调用方一行不用改。
- **本方案为纯规划文档,未改动任何源码**(并行审计约束)。

---

## 1. 现状结构图(AST 实测)

```
rpg/extract/resolve.py  (848 行,模块 docstring 自己就列了 4 个职责)
│
├─ 簇 A:命名/启发式纯函数(无 DB、无 LLM)            ~110 行
│   _slug @42 · _cosine @47 · _clean_name @54 · _norm_name @127
│   _HONORIFIC_SUFFIXES/_PREFIXES @133-134 · _honorific_base @137
│   _NON_PERSON_TITLE_WORDS @273 · _LOC_NAME_SUFFIX @279
│   _looks_like_non_person @282 · _has_person_evidence @294
│
├─ 簇 B:实体消歧核心(纯内存,依赖簇 A)              ~250 行
│   CanonEntity(dataclass) @22 · gather_entity_mentions @64
│   cluster_entities @154(113 行) · compute_protagonist_importance @303
│
├─ 簇 C:DB 落库编排(依赖簇 A+B、kb.canon_repo、Jsonb) ~170 行
│   resolve_and_write @358(102 行) · sync_character_cards_from_canon @462
│   _count_by_type @524
│
├─ 簇 D:时间线锚点(只依赖 db,与 A/B/C 零耦合)        ~55 行
│   build_timeline @532
│
└─ 簇 E:constant 世界书(只依赖 db+Jsonb,读 kb_canon_entities
    表而非内存 CanonEntity,与 A/B/C 零内存耦合)        ~260 行
    _reclassify_canon_type @587 · build_constant_worldbook @621(227 行)
```

跨簇耦合实测:
- C → B:`resolve_and_write` 调 `gather_entity_mentions` / `cluster_entities` /
  `compute_protagonist_importance`,并读函数属性 `cluster_entities._last_stats`(见 §6 风险)。
- C → A:`_slug`(concept 实体 logical_key)、`_looks_like_non_person`、`_has_person_evidence`(RC4 降级闸)。
- B → A:`_clean_name` / `_norm_name` / `_honorific_base` / `_slug` / `_cosine`。
- D、E 不引用 A/B/C 的任何符号(E 的 `_enrich` 读的是 DB 行,不是 CanonEntity)。
- 外部依赖仅 `kb.canon_repo`(C 用)与 `psycopg Jsonb`(C/E 用);`kb/canon_repo.py` 不 import extract.* → **无环**。

## 2. 判定理由

**needs-refactor** 而非 acceptable:
1. 非"单一职责的大文件":模块 docstring 自陈 4 件事,D/E 两簇与消歧核心零内存耦合,只是历史上"Pass 2 收尾都堆这"。
2. 持续高频改动热点:RC1/RC2/RC4/RC9 系列 QA 修复、P0 大改(subtype/parent)、v28/v33 字段透传、phase_backend stats 全落在本文件;待办 L3 haiku 精判(`RPG_EXTRACT_ADJUDICATE`)落地时还会再膨胀簇 B。拆开后改聚簇逻辑不再背着世界书 260 行一起 diff。
3. 拆分风险实测极低:**0 个 mock.patch 命名空间点**、**0 处 `__file__`/相对路径**、生产调用方全部走 `from extract import resolve as R` 的模块属性访问(shim 天然兼容)。

优先级 medium:无 bug、有 838+ 测试锁行为,不紧急;但属于"再不拆会更贵"的热点文件。

## 3. 调用方全景(Grep 实查)

### 3.1 生产代码(3 个文件,全走模块属性访问,shim 后零修改)

| 文件 | 行 | 用法 |
|---|---|---|
| `rpg/extract/pipeline.py` | 12, 168-170 | `from extract import resolve as R`;`R.resolve_and_write` / `R.build_timeline` / `R.build_constant_worldbook` |
| `rpg/extract/arc_pipeline.py` | 27, 282-284 | 同上三个 |
| `rpg/extract/rebuild.py` | 81(函数内 import), 106 | `R.build_constant_worldbook` |

(`rpg/platform_app/import_pipeline.py` 1485-1487 行仅 docstring 提及;其 `_norm_name` @1193 是同名本地函数,非本模块符号。`rpg/script_timeline.py` 的 `rebuild_timeline_anchors`/`resolve_timeline_anchor` 与本文件无关,只是名字相近。)

### 3.2 测试(3 个文件、4 条直接 import 语句,shim 后零修改)

| 文件 | 行 | import 的符号 |
|---|---|---|
| `rpg/tests/unit/test_extract_resolve_offline.py` | 5 | `_slug, cluster_entities, gather_entity_mentions` |
| 同上 | 76(函数内) | `gather_entity_mentions, cluster_entities` |
| `rpg/tests/unit/test_extract_resolve_qa_fixes.py` | 12-19 | `CanonEntity, _has_person_evidence, _looks_like_non_person, cluster_entities, compute_protagonist_importance, gather_entity_mentions` |
| `rpg/tests/integration/test_extract_resolve_protagonist.py` | 9 | `resolve_and_write` |

### 3.3 patch 点(陷阱① 专项 Grep)

`grep -rn 'patch("extract\.' / patch('extract. / patch("rpg.extract / monkeypatch.*extract / setattr(R` 全仓测试目录:**0 命中**。
(`test_embedding_byok.py` 等命中的 `resolve_preferred_api` 是 `core.llm_backend` 的无关同名词。)
→ **patch_points = 0**。真正的兼容面就是上表 4 条直接 import + 3 个 `R.` 模块引用,re-export shim 全覆盖。

## 4. 目标布局

把 `resolve.py` 转成同名子包(公开 import 路径 `extract.resolve` 不变),内部模块用下划线前缀,沿用 `platform_app/knowledge/_utils.py、_sync.py` 的"包内私有模块"既有惯例:

```
rpg/extract/resolve/
├── __init__.py        (~45 行)  shim:保留原模块 docstring,re-export 下表全部符号,定义 __all__
├── _naming.py         (~110 行) 簇 A:纯字符串/启发式,零内部依赖
├── _cluster.py        (~260 行) 簇 B:CanonEntity + 消歧聚簇;import _naming
├── _persist.py        (~185 行) 簇 C:落库编排;import _cluster、_naming、kb.canon_repo、Jsonb
├── _timeline.py       (~60 行)  簇 D:零内部依赖
└── _worldbook.py      (~275 行) 簇 E:import Jsonb;零内部依赖
```

内部依赖 DAG:`_naming ← _cluster ← _persist`;`_timeline`、`_worldbook` 为叶 → **无环**。
`__init__.py` 单向 import 五个内部模块 → 无环。外部 `kb.canon_repo` 不回 import extract → 无环。

兼容性:`from extract import resolve as R`(pipeline/arc_pipeline/rebuild)与 `from extract.resolve import X`(3 个测试文件)在包形态下语义完全不变;`rpg/` 是 sys.path 根、import 名仍为 `extract.resolve`。

## 5. 可机械执行的搬运清单(逐字搬运、禁止改写任何函数体/常量/注释)

> 执行代理铁律:每个符号**整段复制原文**(含注释、含 RC9 修复处的括号、含 `setattr(cluster_entities, "_last_stats", ...)` 这种"看着像能简化"的 hack),只允许改 import 行。不许重命名、不许合并循环、不许"顺手"改 SQL 字符串。

### 批次 B1(唯一必做批次,单串行执行,一个 commit)

| # | 符号(原行号) | 目标文件 |
|---|---|---|
| 1 | `_slug` @42 | `_naming.py` |
| 2 | `_cosine` @47 | `_naming.py` |
| 3 | `_clean_name` @54 | `_naming.py` |
| 4 | `_norm_name` @127 | `_naming.py` |
| 5 | `_HONORIFIC_SUFFIXES` @133 / `_HONORIFIC_PREFIXES` @134(含其上方 RC2 注释)| `_naming.py` |
| 6 | `_honorific_base` @137 | `_naming.py` |
| 7 | `_NON_PERSON_TITLE_WORDS` @273 / `_LOC_NAME_SUFFIX` @279(含 RC4 段注释)| `_naming.py` |
| 8 | `_looks_like_non_person` @282 | `_naming.py` |
| 9 | `_has_person_evidence` @294(签名里的 `"CanonEntity"` 字符串注解保持原样,有 `from __future__ import annotations` 不求值,**不要**为它 import CanonEntity)| `_naming.py` |
| 10 | `CanonEntity` @22 | `_cluster.py` |
| 11 | `gather_entity_mentions` @64 | `_cluster.py` |
| 12 | `cluster_entities` @154 | `_cluster.py` |
| 13 | `compute_protagonist_importance` @303(含其上方 RC1 段注释)| `_cluster.py` |
| 14 | `resolve_and_write` @358 | `_persist.py` |
| 15 | `sync_character_cards_from_canon` @462 | `_persist.py` |
| 16 | `_count_by_type` @524 | `_persist.py` |
| 17 | `build_timeline` @532(含"时间线增量聚合"段注释)| `_timeline.py` |
| 18 | `_reclassify_canon_type` @587(含"constant 世界观骨架"段注释;函数体内的局部 `import re` 保持原样)| `_worldbook.py` |
| 19 | `build_constant_worldbook` @621(三个内嵌闭包 `_is_contaminated`/`_enrich`/`_passes_importance` 原样随函数体走)| `_worldbook.py` |

各文件头部 import(新写的唯一代码):

```python
# _naming.py
from __future__ import annotations
import re

# _cluster.py
from __future__ import annotations
import re
from collections import defaultdict
from dataclasses import dataclass, field
from ._naming import _clean_name, _cosine, _honorific_base, _norm_name, _slug

# _persist.py
from __future__ import annotations
from psycopg.types.json import Jsonb
from kb import canon_repo
from ._cluster import CanonEntity, cluster_entities, compute_protagonist_importance, gather_entity_mentions
from ._naming import _has_person_evidence, _looks_like_non_person, _slug
from collections import defaultdict   # _count_by_type 用

# _timeline.py
from __future__ import annotations
# (build_timeline 不用 re/Jsonb,只要 db 形参,无需其它 import)

# _worldbook.py
from __future__ import annotations
from psycopg.types.json import Jsonb
# 注意:_reclassify_canon_type 函数体内自带局部 import re,模块级不必加;
# build_constant_worldbook 本体不用 re。
```

`__init__.py`(shim,保留原 848 行文件头 docstring 原文):

```python
"""(原 resolve.py 模块 docstring 原文搬入)"""
from __future__ import annotations

from ._naming import (
    _HONORIFIC_PREFIXES, _HONORIFIC_SUFFIXES, _LOC_NAME_SUFFIX,
    _NON_PERSON_TITLE_WORDS, _clean_name, _cosine, _has_person_evidence,
    _honorific_base, _looks_like_non_person, _norm_name, _slug,
)
from ._cluster import (
    CanonEntity, cluster_entities, compute_protagonist_importance,
    gather_entity_mentions,
)
from ._persist import _count_by_type, resolve_and_write, sync_character_cards_from_canon
from ._timeline import build_timeline
from ._worldbook import _reclassify_canon_type, build_constant_worldbook

__all__ = [
    "CanonEntity", "gather_entity_mentions", "cluster_entities",
    "compute_protagonist_importance", "resolve_and_write",
    "sync_character_cards_from_canon", "build_timeline",
    "build_constant_worldbook",
]
```

> 下划线符号也全部 re-export(测试直接 import 了 `_slug/_looks_like_non_person/_has_person_evidence`,其余下划线符号一并保留,防仓里我没 Grep 到的动态引用)。

收尾(陷阱⑤):**删除 `rpg/extract/resolve.py`**(被同名包取代,不留孤儿);同 commit 内完成"建包+删旧文件";顺手 `find rpg/extract -name __pycache__ -exec rm -rf {} +` 清陈旧字节码。

### 批次 B2(可选,B1 验证全绿后另起 commit):`resolve_and_write` 阶段化

102 行、典型顺序流水线,值得拆为 `_persist.py` 内私有阶段函数(纯搬运函数体片段,不改逻辑):
- `_collect_concepts(chapter_extracts) -> list[CanonEntity]`(@371-384 concept 聚合段)
- `_drop_non_person_characters(canon) -> list[CanonEntity]`(@386-397 RC4 段,含 logging)
- `_backfill_parent_keys(canon) -> None`(@412-428 parent 映射段)
主函数保持原签名/返回 dict 原样。

### 不拆的巨型函数(明确豁免)

- `cluster_entities`(113 行):**不拆**。它是单一内聚算法(贪心聚簇),内部阶段共享可变状态(`clusters`/`vecs`/fallback 标志),且布满 RC9 运算符优先级修复、embedder 长度防越界等高危精修;阶段化收益低、改坏风险高。
- `build_constant_worldbook`(227 行):**可拆但放 B3 可选批次**(拆 `_load_canon_maps` / `_build_entries` / `_write_entries` 三阶段,闭包改为显式传 `canon_by_name`)。它是真流水线,但当前无测试直接锁它(只有 pipeline 级间接覆盖),拆它前建议先补 `_build_entries` 的离线单测;没有补测意愿就永久豁免,B1 已把它隔进独立模块,主要收益已拿到。

## 6. 五大陷阱逐项核对 + 其它风险

| 陷阱 | 核查结果 | 对策 |
|---|---|---|
| ① patch 命名空间穿透 | Grep 实查 **0 个** `mock.patch("extract.resolve.*")`;兼容面=4 条直接 import + 3 处 `R.` 属性访问 | `__init__.py` 全量 re-export(含下划线符号)即全覆盖。**遗留语义差异要写进 commit message**:拆后 `resolve_and_write` 绑定的是 `_cluster.cluster_entities`,未来若有人 patch `extract.resolve.cluster_entities` 将不再影响 `resolve_and_write` 内部调用(今天无人这么 patch);正确 patch 目标是 `extract.resolve._persist.cluster_entities` |
| ② `Path(__file__)` 错位 | Grep 实查:resolve.py 内 **0 处** `__file__`/`Path(`/`os.path`/相对路径 IO | 不适用 |
| ③ 执行代理顺手简化 | 高危点:`setattr(cluster_entities, "_last_stats", ...)` 函数属性 hack、RC9 括号、SQL `on conflict ... where card_type='npc'` 局部唯一索引、`_enrich` 闭包 | §5 清单逐符号"整段复制原文";执行用 sonnet 子代理时把"禁止改写逻辑、只许改 import 行"写进任务首行;搬完 `git diff --stat` 应显示纯移动(新增行≈删除行+import 差量) |
| ④ 并行中间状态 | 6 个新文件全部源自同一个旧文件 | B1 整体**单代理串行**执行,一个 commit;B2/B3 各自独立 commit、互不并行 |
| ⑤ 孤儿文件 | — | 旧 `resolve.py` **删除**(同名包取代,import 路径不变,无需平级 shim 文件);清 `__pycache__` |
| 循环导入 | `_naming←_cluster←_persist`,`_timeline`/`_worldbook` 为叶;`kb/canon_repo.py` 仅 import psycopg/typing,不回 import extract | 无环。新代码禁止在 `_cluster`/`_naming` 里 import `_persist` 或包 `__init__` |
| 模块级单例/副作用 | 唯一状态是 `cluster_entities._last_stats` **函数属性**(运行期 setattr,非 import 期);无注册表/装饰器注册 | re-export 不复制对象,`_persist` 与 `__init__` 引用同一函数对象,`getattr(cluster_entities, "_last_stats")` 行为不变。无 import 顺序敏感点 |

额外风险:`extract/__init__.py` 有包级 docstring 但无显式子模块 import(Grep 验证),对子模块形态无感知,无需改动。

## 7. 验证清单(每批次后跑)

```bash
# 1. 编译闸
python -m py_compile rpg/extract/resolve/__init__.py rpg/extract/resolve/_*.py
# 2. 离线单测(无 DB/LLM,直测兼容面)
cd rpg && python -m pytest tests/unit/test_extract_resolve_offline.py tests/unit/test_extract_resolve_qa_fixes.py -q
# 3. import 烟雾(模块属性访问面,即 pipeline/arc_pipeline/rebuild 的用法)
cd rpg && python -c "from extract import resolve as R; \
  assert all(hasattr(R, n) for n in ('resolve_and_write','build_timeline','build_constant_worldbook','cluster_entities','CanonEntity','_slug')); print('shim ok')"
# 4. 有本机测试 DB 时(配方见 project_rpg_local_testdb):
cd rpg && python -m pytest tests/integration/test_extract_resolve_protagonist.py -q
# 5. 全量回归(并行审计修复合流后):cd rpg && python -m pytest -q
```

## 8. 批次划分汇总

| 批次 | 内容 | 必做? | 依赖 |
|---|---|---|---|
| B1 | 建 `extract/resolve/` 包 + 5 内部模块 + shim `__init__.py` + 删旧 `resolve.py`(§5 清单逐字搬运) | 必做 | 等并行审计工作流结束、工作区干净后执行 |
| B2 | `_persist.resolve_and_write` 阶段化(3 个私有阶段函数) | 可选 | B1 验证全绿 |
| B3 | `_worldbook.build_constant_worldbook` 阶段化(先补 `_build_entries` 离线单测) | 可选 | B1 验证全绿;无补测意愿则豁免 |
