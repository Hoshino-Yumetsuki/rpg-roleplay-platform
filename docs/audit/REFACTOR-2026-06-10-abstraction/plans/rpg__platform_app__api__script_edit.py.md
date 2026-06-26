# 体检报告:rpg/platform_app/api/script_edit.py(1038 行)

- **日期**: 2026-06-10
- **审计性质**: 函数抽象层体检 + 拆分方案评估(只读审计,未改任何源码)
- **结论(verdict)**: **acceptable — 虽大但单一职责,不建议拆**
- **优先级**: low(仅 2 处死代码 + 1 个可选的文件内函数阶段化,均非紧急)
- **工作量**: S(若做可选清理)

---

## 1. 现状结构图

模块自述(docstring):「schema v44 剧本 fork / Git 版本控制 / 手动编辑」。
14 个 endpoint + 2 个共享 helper,全部挂在同一个 `router = APIRouter()` 上:

```
script_edit.py (1038 行)
├── 模块头
│   ├── import json as _json          @21   ← ★死代码:全文件无任何使用
│   ├── _VALID_SHARING_MODES          @34   ← ★死代码:全仓库 grep 无任何引用
│   └── router = APIRouter()          @30   ← 唯一被外部 import 的符号
│
├── 共享 helpers(被下面几乎所有 endpoint 复用 → 内聚核心)
│   ├── _require_owner    11行 @37    owner 门控(raise ValueError)
│   └── _write_commit     34行 @50    写 script_commits 流水账 + 推 head_commit_id
│
├── fork 簇
│   └── api_fork_script   230行 @89   9 张表 INSERT..SELECT 线性复制管线 + 初始 commit
│
├── 版本控制簇(读 ledger / pin 指针 / checkout stub)
│   ├── api_list_commits   34行 @324
│   ├── api_pin_script     77行 @363
│   ├── api_unpin_script   17行 @443
│   └── api_checkout_commit 29行 @1009 (501 stub,待回放实现)
│
├── worldbook CRUD 簇(软删=enabled=false;改后清 constant 缓存)
│   ├── api_worldbook_update 78行 @465
│   ├── api_worldbook_add    64行 @546
│   └── api_worldbook_delete 40行 @613
│
├── canon-entities CRUD 簇(软删=importance=-1)
│   ├── api_canon_update 69行 @658
│   ├── api_canon_add    65行 @730
│   └── api_canon_delete 35行 @798
│
└── anchors CRUD 簇(物理 DELETE)
    ├── api_anchor_update 67行 @838
    ├── api_anchor_add    59行 @908
    └── api_anchor_delete 34行 @970
```

每个写 endpoint 都是同一个不变式:**owner 门控(`_require_owner`)→ before 快照 → 变更 → after 快照 → `_write_commit` 记账 → `db.commit()`**。这不是「碰巧放在一起的多职责」,而是同一条 ledger 不变式的 14 个实例。

## 2. 外部耦合面(Grep 实查)

| 维度 | 结果 |
|---|---|
| 谁 import 本模块 | **仅 1 处**:`rpg/platform_app/api/__init__.py:15` `from .script_edit import router as _script_edit_router`(:27 include_router) |
| 被 import 的符号 | 仅 `router`,无任何其他符号被外部引用 |
| 测试 patch 点 | **0 个**。全仓库 grep `mock.patch` / `patch(` × `script_edit`:零命中 |
| 测试覆盖方式 | `rpg/tests/integration/test_script_fork_edit.py` 纯走 HTTP client(`tests.helpers.make_client`)打 endpoint,不 import、不 patch 本模块任何符号 → 对内部重构完全免疫 |
| `Path(__file__)` / 相对路径 | **0 处**(grep 实查) |
| 模块级单例 / import 副作用 | 仅 `router` + 装饰器注册;无注册表、无全局缓存 |
| 函数内 lazy import | 2 处,均位置无关:`platform_app.knowledge._sync._ensure_book`(fork 内)、`gm_serving.context_inject.invalidate_constant_cache`(worldbook 三连内),搬到哪都合法 |

## 3. 内聚簇分析与判定论证

### 为什么判 acceptable 而不是 needs-refactor

1. **单一职责成立**:全模块只做一件事 —— 「带 commit 流水账的剧本编辑面」。三个 CRUD 簇不是泛化 KB CRUD,而是「每次变更必须落 ledger」这一不变式的逐表实例;它们与 `_require_owner`/`_write_commit` 强耦合(14 个 endpoint 里 13 个调 `_require_owner`、10 个调 `_write_commit`)。拆开任何一簇,新模块都要回头 import 这两个 helper,边界并不更干净。
2. **包内惯例容忍此体量**:`api/` 是「一域一平铺 router 文件」风格,admin.py 1463 行、scripts.py 1354 行均大于本文件。单独拆 script_edit.py 反而制造风格不一致;若要治理应是包级统一动作,不属本次范围。
3. **重构收益的最大来源不存在**:本包重构的头号成本历来是测试 patch 命名空间穿透(本仓五大陷阱之①),而本模块 **patch 点 = 0、外部符号引用 = 1(router)**,意味着「拆了没人疼,不拆也没人疼」—— 收益面趋近于零,而任何搬动在当前(另一审计工作流并行读源码)都有非零的协同成本。
4. **CRUD 三连的重复不宜抽象掉**:三簇看似可收敛成泛型 CRUD 工厂,但每簇的删除语义刻意不同(worldbook 软删 `enabled=false` 保 checkout 回放、canon 软删 `importance=-1`、anchor 物理 DELETE),可更新列白名单也逐表手写(防注入:列名永不来自用户输入)。这类安全语义靠「逐 endpoint 平铺直叙」最可审计 —— 文件内多处 IDOR 修复注释说明本文件正处于安全审计热区,泛型化会降低可审计性。
5. **唯一 ≥80 行巨型函数 `api_fork_script`(230 行)**:属流水线型,理论上「该拆成阶段函数」;但它是 9 个 `INSERT..SELECT` 顺序块,每块 15~25 行、有编号注释(1→9)、无分支嵌套,认知负担线性。拆成 `_copy_*` 阶段函数是**文件内**可选美化(见 §5),不构成模块拆分理由。

### 顺带发现(不改判定)

- **死代码 2 处**(陷阱⑤同类项,建议顺手清理但需走正常提交流程,本审计不动源码):
  - `script_edit.py:21` `import json as _json` —— 全文件无使用;
  - `script_edit.py:34` `_VALID_SHARING_MODES` —— 全仓库无引用(`api_pin_script` 用的是字面量二元组,且语义只允许两种 pin 模式,该集合连语义上都对不上)。
- **fork 复制管线与 `knowledge/script_pack.py` 的部分职责重叠**:`api_fork_script` 直 SQL 复制 9 张表;`script_pack.export/import_script_pack`(被 `/api/scripts/public/{id}/fork` 经 `clone_public_script` 使用)走 zip 序列化复制 11 张表(多 chapter_facts/documents/document_chunks)。两者语义不同(库内 fork 保 `forked_from_script_id`/`forked_at_commit_id` 谱系 + 初始 fork commit vs 打包克隆),**不是机械可合并的重复**;但「fork 是否也该带 chapter_facts」是一个值得产品层面确认的差异点,记录在案。

## 4. 五大陷阱核对表(对「不拆」与「可选清理」两种动作)

| 陷阱 | 核查结果 |
|---|---|
| ① patch 命名空间穿透 | patch 点 0 个(Grep 实查全仓 `rpg/tests`)。即使未来拆分,也只需保证 `api/__init__.py` 的 `from .script_edit import router` 继续可用 |
| ② `Path(__file__)` 错位 | 文件内 0 处,无此风险 |
| ③ 执行代理顺手简化 | 本次不搬运。若做 §5 可选项,要求逐字搬运 SQL 文本块,禁止「优化」列清单 / ON CONFLICT 子句 |
| ④ 并行中间状态 | 本次无搬运批次。可选清理全部位于单文件,单批次串行即可 |
| ⑤ 孤儿文件/死代码 | 原文件保留(不产生孤儿);反向发现 2 处既有死代码(§3),应删除而非遗留 |
| 循环导入 | 现依赖仅 `..db` / `._deps` / 2 处函数内 lazy import,无环;不拆则无新增风险 |
| 模块级单例/注册顺序 | 仅 `router` 装饰器注册,path 无重叠,无顺序敏感 |

## 5. 可选清理项(非必须;若执行,单批次、单文件、可机械执行)

> 触发条件建议:等并行审计工作流结束后,搭任意一次常规提交顺手做。**不要为此单开重构分支。**

**批次 1(唯一批次,串行)— 全部在 `rpg/platform_app/api/script_edit.py` 文件内:**

1. 删除 `import json as _json`(行 21)。
2. 删除 `_VALID_SHARING_MODES`(行 34)。
3. (可选,流水线阶段化)把 `api_fork_script` 的 9 个复制块逐字提为同文件模块级私有函数,函数体一字不改,仅缩进调整:
   | 新阶段函数(同文件内) | 原行号块 | 内容 |
   |---|---|---|
   | `_fork_insert_script_row(db, src, user_id, fork_title, script_id, forked_at_commit) -> int` | @126-148 | 新建 scripts 行 |
   | `_fork_copy_chapters(db, new_id, script_id)` | @163-174 | script_chapters |
   | `_fork_copy_worldbook(db, new_book_id, new_id, script_id)` | @184-199 | worldbook_entries |
   | `_fork_copy_canon(db, new_id, script_id)` | @201-215 | kb_canon_entities |
   | `_fork_copy_anchors(db, new_id, script_id)` | @217-231 | script_timeline_anchors |
   | `_fork_copy_cards(db, new_book_id, new_id, script_id)` | @233-248 | character_cards |
   | `_fork_copy_phase_digests(db, new_id, script_id)` | @250-264 | phase_digests |
   | `_fork_copy_worldlines(db, new_id, script_id)` | @266-290 | script_worldlines + nodes(两块可合一函数,保持注释 7c/7d) |

   约束:**逐字搬运 SQL 与参数元组、禁止改写逻辑**;`_ensure_book` 的 try/except 包裹与「非致命」注释原样保留在主函数;IDOR 注释(@103-106)必须留在 `api_fork_script` 源权限查询处不动。
4. 验证:`python -m compileall rpg/platform_app/api/script_edit.py` + 跑 `rpg/tests/integration/test_script_fork_edit.py`(HTTP 级契约,覆盖 fork/worldbook 编辑/403)。

## 6. 若未来仍决意拆分(预案存档,当前不推荐执行)

唯一与包内惯例兼容的拆法是「文件 → 同名子包」,保 import 路径不变:

```
rpg/platform_app/api/script_edit/
├── __init__.py     # 组装:router = APIRouter(); include 各子 router;
│                   # re-export _require_owner/_write_commit(防未来 patch 点)
├── _helpers.py     # _require_owner, _write_commit            (~50 行)
├── fork.py         # api_fork_script                          (~240 行)
├── vcs.py          # api_list_commits/pin/unpin/checkout      (~170 行)
└── entries.py      # worldbook/canon/anchor 三簇 CRUD          (~580 行)
```

- patch 点同步清单:**无**(0 个 patch 点);唯一外部契约 = `api/__init__.py:15` 的 `from .script_edit import router`,子包 `__init__.py` re-export 后零改动。
- 批次:B1=建子包+helpers → B2=fork.py → B3=vcs.py → B4=entries.py → B5=删旧平铺文件(子包取代,无孤儿)。串行,不并行。
- 风险:与平铺惯例冲突(admin/scripts 更大却不拆)、entries.py 仍近 600 行(三簇语义不同不宜再合并抽象)→ 收益存疑,故仅存档。

## 7. 风险与备注

- **当前最大风险是「动它」而非「不动它」**:另一审计工作流正并行读取本仓源码,且本文件是 IDOR/权限修复热区,行号稳定性对审计对账有价值。
- checkout 为 501 stub(@1009),待回放实现落地时本文件会再增长;届时(而非现在)是重评拆分的合适时机 —— 回放引擎应落 `knowledge/` 层而非堆进本 API 文件。
- fork 管线 vs script_pack 管线的表覆盖差异(chapter_facts 等 3 表)建议产品确认,见 §3。
