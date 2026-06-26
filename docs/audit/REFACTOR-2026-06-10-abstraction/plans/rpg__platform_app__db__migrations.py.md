# 体检报告:rpg/platform_app/db/migrations.py(1749 行)

- **结论(verdict):acceptable — 不拆**
- **优先级:none · 工作量:S(无需动作)**
- 审计日期:2026-06-10 · 审计人:抽象层体检子代理

---

## 1. 现状结构图

文件 1749 行,但结构极其单一,只有三层:

```
rpg/platform_app/db/migrations.py
├── L1-36    导入 + 模块级配置(~36 行)
│   ├── _get_connect()            4 行  动态取 platform_app.db.connect(为测试 patch 设计)
│   ├── _get_migrations()         4 行  动态取 platform_app.db.MIGRATIONS(同上)
│   ├── MIGRATION_ADVISORY_LOCK_ID     常量(advisory lock ID)
│   ├── MIGRATION_LOCK_TIMEOUT_MS      常量(从 core.config 读)
│   └── _EMBED_DIM                     env EMBED_DIM 读取(默认 768)
│
├── L46-1610 MIGRATIONS 数据账本(~1565 行,占全文 89%)
│   └── list[tuple[int, str, list[str]]]
│       v1..v61 + v65, v66(v62-64 显式预留给 living-world-engine 分支)
│       纯声明式 SQL 字符串;唯一的"逻辑"是 4 处 f-string 插值 _EMBED_DIM
│       (v10 / v19 / v40 / v60 的 pgvector 列维度)
│
└── L1613-1749 迁移框架(~137 行,7 个函数全部 ≤38 行)
    ├── _assert_migrations_monotonic()  15 行  账本单调性自检
    ├── (模块级调用 _assert_migrations_monotonic() @ L1631 — import 副作用,故意的)
    ├── _migration_advisory_lock()      24 行  @contextmanager,pg_advisory_lock 串行化 DDL
    ├── _assert_schema_up_to_date()     25 行  生产 fail-fast 版本检查
    ├── _apply_versioned_migrations()   22 行  建 schema_migrations 表 + 增量应用
    └── list_migrations()               38 行  诊断接口(migrate status 用)
```

**没有 ≥80 行的巨型函数**——最大的 `list_migrations` 仅 38 行。文件之"大"100% 来自数据账本,
不来自逻辑堆叠。

## 2. 内聚簇分析:为什么这是单一职责

任务定义里 acceptable 的标准原文是"虽大但单一职责,**如追加式迁移账本**、纯数据表、声明式注册"
——本文件正是这个定义的教科书原型:

1. **账本是追加式(append-only)的**。文件头注释明确铁律:"新增 schema 变更请添加新条目,
   不要修改已发布的旧条目"。增长模式 = 永远在列表尾部 append 一个 tuple,旧条目冻结。
   这种文件不会产生"中部修改冲突",阅读时按 version 号导航,行数不构成理解负担。
2. **框架与账本强耦合且极小**。7 个函数的唯一存在理由就是驱动这份账本:
   单调性自检在 import 时直接吃 `MIGRATIONS`;applier 遍历它;status 列它。
   拆出去得到的"框架模块"只有 ~137 行,反而把一个自洽闭环切成两半。
3. **账本不是纯静态数据**。v10/v19/v40/v60 四处 f-string 插值 `_EMBED_DIM`
   (模块加载时读 env)。任何拆分必须把 `_EMBED_DIM` 与账本绑在同一模块,
   否则语义漂移(维度在两个模块各读一次 env 的时序差)。
4. **动态间接层是测试契约**。`_get_connect()`/`_get_migrations()` 刻意在运行时从
   `platform_app.db` 包命名空间取符号,使 `patch.object(_db, "MIGRATIONS", stub)` /
   `patch.object(_db, "connect", ...)` 能穿透到框架函数内部
   (test_migration_cli.py 的全部测试都建立在这个契约上)。动这个文件 = 动这个契约。

## 3. 引用面与测试 patch 点清单(Grep 实查)

### 3.1 直接 import 本模块路径的(3 处)

| 文件 | 引用方式 |
|---|---|
| `rpg/platform_app/db/__init__.py` L6-13 | re-export 6 符号:`MIGRATIONS, _apply_versioned_migrations, _assert_migrations_monotonic, _assert_schema_up_to_date, _migration_advisory_lock, list_migrations`(均列入 `__all__`) |
| `rpg/platform_app/db/init.py` L7-11 | import 3 符号:`_apply_versioned_migrations, _assert_schema_up_to_date, _migration_advisory_lock` |
| `rpg/tests/integration/test_phase_digests_table.py` L24 | **函数内直接 `from platform_app.db.migrations import _apply_versioned_migrations`**——钉死模块路径,任何改名/搬移都会炸此测试 |

其余消费方(`rpg/platform_app/migrate.py` 的全部 5 个子命令、
`rpg/tests/integration/test_baseline.py` L29、`test_sse_module_field.py` L13、
`test_migration_cli.py`)一律走 `platform_app.db` 包命名空间(`_db.xxx`),不直接碰模块路径。

### 3.2 mock.patch 点(6 处,全在 `rpg/tests/integration/test_migration_cli.py`)

| 行号 | patch 目标命名空间 | 符号 |
|---|---|---|
| L122 | `platform_app.db`(包) | `MIGRATIONS` |
| L139 | `platform_app.db`(包) | `MIGRATIONS` |
| L191 | `platform_app.db`(包) | `_apply_versioned_migrations` |
| L192 | `platform_app.db`(包) | `_migration_advisory_lock` |
| L209 | `platform_app.db.init`(模块) | `_apply_versioned_migrations` |
| L210 | `platform_app.db.init`(模块) | `_migration_advisory_lock` |

另有 L83 `patch.object(_db, "connect", ...)`(符号属 connection.py,但
migrations 框架经 `_get_connect()` 动态依赖它——是行为依赖,不是搬运点)。

**关键观察**:6 个 patch 点全部打在*包命名空间*或 *init.py 命名空间*上,没有一个直接打
`platform_app.db.migrations` 模块本身。这意味着即便将来拆分,只要
`db/__init__.py` 的 re-export 与 `init.py` 的 import 行原样保留,这 6 处全部免改;
唯一钉死模块路径的是 §3.1 第三行那个测试内 import。

### 3.3 其他陷阱核查

- **Path(__file__) / 相对路径**:Grep 实查,本文件 **0 处**(无 `__file__`、无 `os.path`、无 `Path(`)。陷阱②不适用。
- **模块级副作用**:1 处——L1631 `_assert_migrations_monotonic()` 在 import 时执行
  (部署前自检,故意设计)。任何拆分必须保证"账本定义完成 → 自检执行"的顺序,
  且自检要在任何消费方 import 时仍然触发。
- **循环导入**:现有 `_get_connect`/`_get_migrations` 用函数内 import 正是为了绕
  `db/__init__.py ↔ migrations.py` 的环。新切任何边都要重新核这个环——又一个"不动它"的理由。

## 4. 为什么不拆(对三种候选方案的否决)

### 候选 A:框架 / 账本两文件(`migrations.py` + `_migrations_catalog.py`)
- 收益:framework 文件缩到 ~180 行。**但账本文件依旧 ~1570 行**——文件大的"问题"根本没解决,
  只是把 89% 的体积换了个文件名。
- 代价:`_EMBED_DIM` 与账本要同走;import 时自检的执行时序要重排;
  `test_phase_digests_table.py:24` 的钉死路径要同步改;五闸 OSS cherry-pick 同步
  (memory: project_oss_repo)会在该文件上产生一次大 diff,放大后续每次冲突面。
- 结论:收益≈0,纯增风险。**否决**。

### 候选 B:按版本段切片(`migrations_v01_30.py` / `v31_60.py` / ...)
- 追加式账本天然只在尾部增长,切片对"避免冲突"毫无帮助(冲突本来就只发生在尾部);
  且切片边界是任意的,每过 30 个版本就要新开文件、改聚合 import,纯仪式成本。**否决**。

### 候选 C:Django 式一版本一文件 + 目录扫描发现
- 这是换迁移框架,不是拆文件:要新写发现/排序/加载逻辑,动 advisory lock 与
  schema_migrations 记账的外围,66 个版本要生成 66 个文件。与现网生产
  (ECS06 systemd + `python -m platform_app.migrate up` runbook,memory: project_rpg_deploy)
  的部署链强耦合,风险远大于收益。**否决**(此选项性质上更接近 leave-as-is 的反面教材)。

### 时机性一票否决(独立于上述任何方案)
memory(project_lilith_engine)明确:`living-world-engine` 分支有 10 个未 push commit,
**将占用 v62-64 迁移号并入本文件**(账本内 L1580-1582 注释也写明预留)。此刻重排该文件
形状 = 给那次合并人为制造大面积冲突。另:另一个审计工作流正并行读本仓库源码,本轮也被
明令禁止改源码。即使将来想做候选 A,也应等 living-world 合并落地后再议。

## 5. 给未来维护者的约束清单(若有朝一日必须拆)

仅当账本突破 ~4000 行或框架开始长出真实逻辑(回滚/dry-run/分布式协调)时再考虑,且必须:

1. **唯一可接受形态是候选 A**(框架/账本两文件,账本文件保留 `_EMBED_DIM` 读取与
   f-string 插值,框架文件 re-export `MIGRATIONS` 保持包契约)。
2. **原 `migrations.py` 保留为 re-export shim**(非删除):re-export 全部 6 个公开符号 +
   `MIGRATION_ADVISORY_LOCK_ID` / `MIGRATION_LOCK_TIMEOUT_MS`,保 `db/__init__.py`、
   `init.py`、`test_phase_digests_table.py:24` 三处 import 路径零改动(陷阱①⑤)。
3. **逐字搬运、禁止改写**:账本 1565 行必须 byte-identical 搬移(机械执行,交给 sonnet
   子代理时要在指令里写死"禁止顺手简化 SQL/注释");搬完 diff 校验
   `git diff --stat` 应显示纯移动(陷阱③)。
4. **import 时自检顺序**:`_assert_migrations_monotonic()` 的模块级调用跟框架走,
   但其执行必须发生在账本 import 之后——框架文件 `from ._migrations_catalog import MIGRATIONS`
   后立即调用即可。
5. **单批次串行执行**:本文件 + `db/__init__.py` + 测试,一个批次一个执行者,不并行(陷阱④)。
6. **循环导入核查**:新账本模块不得 import `platform_app.db` 包本身
   (`_EMBED_DIM` 只依赖 os.environ,无环;`MIGRATION_LOCK_TIMEOUT_MS` 依赖 core.config,无环)。
7. 拆完跑 `rpg/tests/integration/test_migration_cli.py`、`test_phase_digests_table.py`、
   `test_baseline.py`、`test_sse_module_field.py` 四个直接消费者测试 + 全量回归。

## 6. 最终判定

| 维度 | 评估 |
|---|---|
| verdict | **acceptable** |
| 理由 | 89% 体积是追加式迁移账本(任务定义中 acceptable 的标准原型);框架仅 137 行、7 函数全 ≤38 行、无巨型函数;增长模式 append-only 不构成维护负担 |
| 拆分收益 | ≈0(账本不可压缩,拆完最大文件依旧 ~1570 行) |
| 拆分风险 | 测试 patch 契约(动态间接层)、import 时自检时序、`_EMBED_DIM` 插值耦合、living-world v62-64 合并冲突、OSS cherry-pick 冲突面放大 |
| 建议动作 | 本轮不动;living-world-engine 合并后亦无需动;触发再议阈值见 §5 |
