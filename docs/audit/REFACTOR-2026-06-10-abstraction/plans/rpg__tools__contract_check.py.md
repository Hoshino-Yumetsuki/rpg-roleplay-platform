# 体检报告:rpg/tools/contract_check.py(838 行)

> REFACTOR-2026-06-10-abstraction 函数抽象层体检
> 结论:**acceptable — 不拆**。优先级 none,工作量 S(零)。

---

## 0. 一句话结论

838 行的独立 CLI 审计工具(API 契约漂移检查器),**零导入方、零测试 patch 点、零 CI 引用、零 import 副作用**,内部已按九段注释分区线性组织;拆成包唯一确定会发生的事是触发 `Path(__file__)` 锚点错位(陷阱②)和 `python -m tools.contract_check` 入口语义变化,而收益为零。判 **acceptable,保持原样**。

---

## 1. 现状结构图

模块 = 一条经典「scan → analyse → render」单向流水线,无分叉、无状态共享(全部通过 `Scan` 数据类传递):

```
rpg/tools/contract_check.py  (838 行, 仅 import 标准库)
│
├─ [A] 路径常量 + 扫描目标清单            L32–52
│      THIS_FILE = Path(__file__).resolve()   ← ⚠️ 锚点,见 §5-②
│      RPG_DIR = THIS_FILE.parent.parent      (…/rpg)
│      PROJECT_ROOT / FRONTEND_SRC / REPORT_PATH
│      BACKEND_FILES / FRONTEND_CORE_FILES / DOC_FILES
│
├─ [B] 数据类                              L59–83
│      Endpoint(frozen) / Hit / Scan
│
├─ [C] 通用 helpers + 路径规范化正则       L89–141
│      PLACEHOLDER_RE, PYTHON_PATH_PARAM_RE, JS_INTERP_RE, JS_*_CONCAT_RE
│      _rel(5) / _read(7) / _norm_path(25)
│
├─ [D] 后端路由扫描                        L150–180
│      ROUTE_DECORATOR_RE, scan_backend_routes(23)
│
├─ [E] 前端调用扫描(最重的簇,~270 行)    L191–457
│      FE_WRAPPER_START_RE / FE_BASE_CONCAT_RE / FE_API_BASE_CONCAT_RE
│      / FE_METHOD_KV_RE / FE_EVENTSOURCE_RE
│      _extract_first_arg(59)   平衡括号取首参(手写小解析器)
│      _normalize_arg_expression(41)  JS 拼接表达式 → 规范化路径
│      _strip_calls(70)         IDENT(...) → {arg}(手写小解析器)
│      _record_call(9) / scan_frontend_calls(55)
│      ⚠️ FE_INLINE_API_RE(L384)定义后从未使用 → 死正则
│
├─ [F] 文档扫描 + cookie 扫描              L465–509
│      DOC_TABLE_RE / COOKIE_NAME_RE / COOKIE_KW_RE
│      scan_docs(24) / _scan_cookies(7)
│      ⚠️ DOC_INLINE_RE(L469)定义后从未使用 → 死正则
│
├─ [G] 漂移分析                            L516–617
│      Drift 数据类 / _match_endpoint(10) / analyse(81)
│
├─ [H] 渲染                                L624–816
│      SEV_RANK / _group_for_report(5)
│      render_report(133)  → Markdown 报告(中文)
│      print_summary(44)   → stdout 摘要
│
└─ [I] main(12) + __main__ guard           L823–838
       唯一写副作用点:REPORT_PATH.write_text(…)
```

依赖方向严格单向:`[C]helpers ← [D][E][F]scanners ← [G]analyse ← [H]render ← [I]main`,无回边,无环。

## 2. 外部耦合面(Grep 实查,2026-06-10)

| 查项 | 命令要点 | 结果 |
|---|---|---|
| Python 导入方 | `grep -rn "tools.contract_check\|from tools\b" --include=*.py`(全仓) | **0 个**(仅自身 docstring 与 `rpg/tools/__init__.py` docstring 提及) |
| 测试 patch 点 | `grep -rn "contract" rpg/tests/` | **0 个**(命中的 `test_*_contract.py` 是无关的 API 字段契约回归测试,不 import 本模块) |
| CI / 脚本 | `grep -rn contract .github/workflows/ scripts/` | **0 个** |
| 前端 / 文档反向引用 | 全仓 grep | 仅 `docs/audit/...frontend_routes.py.md`(并行审计文件,**反向**:是别人的方案要改本文件 L41 的字面路径,不是依赖本文件符号) |
| 调用方式 | docstring | 手动 `python -m tools.contract_check`(顶层包名 `tools`,需在 `rpg/` 目录下跑) |
| 产物 | `rpg/docs/api_contract_drift.md` | 存在,最后生成 2026-05-26 |

**patch_points = 0。** 这是整个判定的决定性事实。

## 3. 内聚簇分析与 verdict 论证

### 3.1 簇划分(若硬拆,边界长这样)

| 簇 | 内容 | 行数 | 内聚性 |
|---|---|---|---|
| model | Endpoint / Hit / Scan / Drift | ~40 | 高 |
| pathnorm | _norm_path + 6 个正则 + _rel/_read | ~55 | 高 |
| scan_backend | [D] | ~35 | 高 |
| scan_frontend | [E] 含两个手写括号解析器 | ~270 | 高 |
| scan_docs | [F] | ~50 | 高 |
| analyse | [G] | ~100 | 高 |
| report | [H] | ~190 | 高 |

每个簇内聚性都不差——但**簇间是一条线性流水线的相邻阶段,不是「混杂的多职责」**。模块粒度上的职责是单一的:「对前后端/文档做一次只读 grep 式扫描并产出漂移报告」。这正是任务定义里 acceptable 的标准画像(单一职责的工具脚本,虽大可不动)。

### 3.2 为什么不拆(收益侧 ≈ 0)

1. **没有任何复用诉求**:0 导入方。拆出的 `pathnorm`/`model` 子模块没有第二个消费者。
2. **没有测试隔离诉求**:0 测试、0 patch 点。拆分通常为可测性服务,这里无此需求。
3. **没有协作冲突诉求**:dev 工具,改动频率极低(产物停留在 5 月 26 日),不存在多人同文件冲突。
4. **阅读导航已解决**:文件自带 9 段 `# ---` 分区注释,段内函数 docstring 齐全,839 行单文件的导航成本低于 7 文件包的跳转成本。
5. **可执行入口最简**:单文件 `python -m tools.contract_check` 即可跑;拆成包必须补 `__main__.py`,纯增维护面。

### 3.3 为什么不拆(风险侧 > 0,虽小但全是净亏)

- **陷阱②直接命中**:L32 `THIS_FILE = Path(__file__).resolve()` + `parent.parent` 推导 `RPG_DIR`/`PROJECT_ROOT`/`REPORT_PATH` 及全部扫描目标清单。若 `contract_check.py` → `contract_check/` 包,`__file__` 深一层,`RPG_DIR` 会错指到 `rpg/tools/`,**所有扫描目标静默落空**——本工具对缺失文件的策略是记入 `files_missing` 继续跑,报告会"成功生成"一份空对账,属最危险的静默失败形态。
- **入口语义**:包形态下 `python -m tools.contract_check` 需要 `__main__.py` 才能跑,漏了就直接 break 唯一使用方式。
- **并行审计约束**:本轮另一审计流正在读源码,任何源码改动都违反本次任务边界。

### 3.4 ≥80 行巨型函数单独评估(2 个)

| 函数 | 行数 | 类型 | 是否值得拆阶段函数 |
|---|---|---|---|
| `render_report` | 133 | **模板/数据表型**:顺序拼接 Markdown 段落(覆盖表→汇总表→四个分类节→图例),`sections` 已是声明式数据表驱动循环 | **不拆**。它的长来自字面量模板行,抽成 `_render_coverage()` 等只会把模板撕碎,降低「报告长什么样」的可读性 |
| `analyse` | 81 | 4 个编号检查(frontend_only / backend_only / doc_orphan / cookie_drift)顺序追加 | 形式上可拆 4 个 `_check_*`,但 81 行刚过线、四段各 ~15-25 行且互不纠缠,拆与不拆阅读成本持平。**随整体 verdict 一并不动** |

`_extract_first_arg`(59)与 `_strip_calls`(70)是两个手写字符级解析器,**逻辑致密、单一目的,绝不能让执行代理"顺手简化"**(陷阱③高危区)——这也是不主动碰这个文件的又一理由。

### 3.5 循环导入 / 单例 / import 副作用核查

- import 仅标准库(`re/sys/collections/dataclasses/datetime/pathlib`),不 import 任何 `rpg.*`/`tools_dsl.*` → **不存在引入 import 环的可能**。
- 模块级对象 = 路径常量 + 预编译正则,无注册表、无装饰器注册、无 I/O;唯一写副作用收敛在 `main()` 内 → **无 import 副作用问题**。

## 4. Verdict

**acceptable(可不动)/ priority: none / effort: S**

不是 leave-as-is(那意味着"动它风险远大于收益"且风险显著)——这里真实情况是风险小而收益为零,纯粹不值得动。维持单文件。

## 5. 五大陷阱对照(对「假如有人执意拆」的契约式约束)

| 陷阱 | 本文件情况 | 结论/约束 |
|---|---|---|
| ① patch 命名空间穿透 | Grep 实查 rpg/tests **0 个** patch/import 点 | 不构成阻力;若拆仍应保留原模块 re-export shim(零成本保险) |
| ② Path(__file__) 错位 | **L32 唯一锚点,全模块路径常量的根**;扫描目标缺失时静默记 `files_missing` 不报错 | 拆包必须把 [A] 段常量留在同深度模块,或改 `parents[2]` 并以「报告中 coverage 表 7 个文件全部'找到'」为验收闸 |
| ③ 顺手简化 | `_extract_first_arg`/`_strip_calls` 两个手写解析器是重灾区 | 任何搬运必须「逐字搬运、禁止改写逻辑」,搬后 `git diff --stat` 行数对账 |
| ④ 并行中间状态 | 单文件、单批次即可完成 | 不构成问题;若拆,一个串行批次 |
| ⑤ 孤儿文件 | 若拆,旧 `contract_check.py` 必须显式决定:转 shim(re-export + main 转发)或删除并补包 `__main__.py` | 不许悬空;同时顺手清掉 L384/L469 两个死正则 |

## 6. 目标布局 / 搬运清单 / 批次

**无(verdict=acceptable,不产生搬运动作)。**

仅为完整性给出契约式备用布局——**触发条件**:未来本工具获得了导入方或测试覆盖(条件不满足前禁止执行):

```
rpg/tools/contract_check/        (仅在触发条件满足后)
├─ __init__.py      ← re-export 全部公共符号(Endpoint/Hit/Scan/Drift/
│                      scan_*/analyse/render_report/print_summary/main)
├─ __main__.py      ← `from . import main; sys.exit(main())`,保住 -m 入口
├─ _paths.py        ← [A] 段;Path(__file__) 改 parents[2],coverage 表全"找到"为验收
├─ _model.py        ← [B] + Drift
├─ _pathnorm.py     ← [C] 段正则 + _rel/_read/_norm_path
├─ _scanners.py     ← [D][E][F] 全部(含 _extract_first_arg/_strip_calls 逐字搬运)
├─ _analyse.py      ← _match_endpoint/analyse
└─ _report.py       ← SEV_RANK/_group_for_report/render_report/print_summary
```

单批次串行执行;验收 = `python -m tools.contract_check` 产出的报告与拆分前 byte 级一致(除生成时间行)。

## 7. 顺手发现(不在本次动作范围,记录备查)

1. **死正则 ×2**:`FE_INLINE_API_RE`(L384)、`DOC_INLINE_RE`(L469)定义后从未被引用。
2. **docstring 小误**:L15-16 称"from project root: `python -m tools.contract_check`",但 `tools` 包位于 `rpg/` 下,实际须在 `rpg/` 目录运行。
3. **外部联动提醒**:并行审计的 `rpg__platform_app__frontend_routes.py.md` 方案若落地(frontend_routes.py 改包),需同步更新本文件 L41 的字面扫描路径——该依赖已记录在对方方案批次 2 中。
