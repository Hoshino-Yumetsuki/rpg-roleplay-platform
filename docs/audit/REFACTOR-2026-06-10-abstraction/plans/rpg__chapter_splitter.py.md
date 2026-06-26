# rpg/chapter_splitter.py 抽象层体检与拆分方案

- 审计日期:2026-06-10
- 目标文件:`rpg/chapter_splitter.py`(1054 行,1 个 dataclass + 1 个 995 行类 + 1 个模块级函数 + 1 个模块级单例)
- 结论:**needs-refactor(优先级 low,工作量 S)** — 单一领域但三个抽象层混居;拆分机械可行、风险极低(0 patch 点、无 `__file__`、类无状态),仓库已有 `rpg/state/_mixins/` 完全同构的先例可照抄。非紧急:增长压力已被 Phase A.0 引到 `rpg/ingest/`,本文件趋于稳定,可机会主义执行。

---

## 1. 现状结构图

```
rpg/chapter_splitter.py (1054 行)
├── NUMBER_TOKEN (模块常量, 中文数字正则字符集)                      @15
├── @dataclass SplitPattern                                          @19
├── class ChapterSplitter                                            @24
│   ├── [类常量] AUTO_CONFIDENCE_THRESHOLD / SECTION_MARKER_PATTERN
│   │   / PAGINATION_HEADING_PATTERN / ACT_HEADING_PATTERN
│   │   / VOLUME_PATTERN / STRONG_CHAPTER_PATTERNS
│   │   / RULE_PATTERNS / SPLIT_MODE_LABELS                          @27-77
│   │
│   ├── [簇A 编码与清洗委托] decode_bytes / _normalize_encoding
│   │   / _strip_pirate_promo(→ingest.sanitize) / clean_text          ~30 行
│   │
│   ├── [簇B 编排与候选竞争] split_chapters / split_chapters_with_report
│   │   / _split_chapters_internal(112行) / _score_split_candidate
│   │   / split_file / _compact / _to_int                             ~220 行
│   │
│   ├── [簇C 行级切分策略] _split_auto / _split_standard_headings
│   │   / _split_with_volumes / _split_by_pattern / _line_split
│   │   / _position_split / _flatten_volumes
│   │   / _collect_pagination_headings / _collect_numbered_section_headings
│   │   / _is_numbered_section_heading / _split_numbered_sections
│   │   / _extract_act_heading / _next_nonempty_line_index
│   │   / _trim_trailing_act_heading / _is_strong_heading / _is_weak_heading
│   │   / _post_process_chapters / _has_reasonable_chapter_quality
│   │   / _fallback_split                                             ~360 行
│   │
│   ├── [簇D 切分报告与诊断] _build_split_report(98行)
│   │   / _augment_report_v2(67行) / _classify_split_problem
│   │   / _problem_label / _problem_reason / _coefficient_of_variation
│   │   / _dialogue_line_ratio / _heading_candidate_density            ~245 行
│   │
│   └── [簇E 自定义正则安全] build_custom_pattern / is_safe_regex      ~60 行
│
├── def _regex_timeout_probe (簇E 的子进程 ReDoS 探测)                @1021, 30 行
└── chapter_splitter = ChapterSplitter()   ← 模块级单例               @1053
```

依赖方向(已实查,全部单向,无环):

```
chapter_splitter ──(方法内 lazy import)──▶ ingest.sanitize / ingest.filters / ingest.adaptive_split
ingest.*  从不 import chapter_splitter(adaptive_split.py:30 注释明示"self-contained 避免 import 环",
          并刻意复制了一份 NUMBER_TOKEN @ adaptive_split.py:17)
```

## 2. 消费方与 patch 点清单(Grep 实查)

全仓(py/ts/tsx,排除 node_modules 与快照目录)仅 2 个活体导入点:

| 位置 | 导入形式 | 用到的符号 |
|---|---|---|
| `rpg/platform_app/script_import.py:9` | `from chapter_splitter import chapter_splitter`(单例) | `.decode_bytes` / `.clean_text` / `.split_chapters_with_report`(行 110-123、647-657、765-767) |
| `rpg/tests/unit/test_chapter_splitter.py:3` | `from chapter_splitter import ChapterSplitter` | 仅公开 API `split_chapters_with_report` |

**mock.patch 点:0 个。** `grep -rn "patch(.*chapter_splitter|patch(.*ChapterSplitter|monkeypatch.*splitter" rpg/` 无任何命中;测试只构造真实例走公开 API,不打桩内部符号。陷阱①在本文件不存在。

非活体引用(不需处理):
- `rpg/claude_design_upload/current_code/chapter_splitter.py` 及同目录 `script_import.py` — 给设计稿用的**冻结快照**,非运行时代码,禁止裹挟修改。
- `rpg/ingest/adaptive_split.py` / `rpg/ingest/sanitize.py` / `rpg/platform_app/workspace.py` / `rpg/tests/integration/test_new_save_uses_script_opening.py:263` — 仅注释提及,无 import。

`Path(__file__)`/`__file__`:**0 处**(grep 实查 exit 1)。`split_file` 里的 `Path(path)` 是调用方传参,位置无关。陷阱②不存在。

模块级单例与 import 副作用:仅 `chapter_splitter = ChapterSplitter()` 一处;类无 `__init__`、无实例状态,实例化只触发已编译好的类常量,无注册表/装饰器注册顺序问题。三处 `ingest.*` import 全在方法体内(lazy),搬运后语义不变。

## 3. 内聚簇分析与判定

- 簇 C(行级切分策略)、簇 D(报告诊断)、簇 E(正则安全)是三个**互不调用**的独立内聚簇:C 是 lines/text 的纯启发式;D 只消费 `(chapters, split_mode, source_text)`;E 是通用 ReDoS 防护(静态检查 + 子进程超时探测),与切分领域无耦合。
- 簇 B(编排)是唯一的胶水层:调用 C 产生候选、调 ingest.adaptive_split 竞争、调 D 出报告、调 E 编译自定义规则。
- 全类无状态(零实例属性),所有簇间交互都是 `self.方法()` + `self.类常量` — 这正是 `rpg/state/_mixins/` 已验证过的拆法(GameState 多继承 ApplyOpsMixin/RulesGameplayMixin/PendingMixin,"mixin 间通过 self.xxx 互相调用,运行时由 MRO 解析",见 `rpg/state/_mixins/__init__.py`)。
- 为什么不判 acceptable:虽是单一领域,但 995 行类把"切分策略 / 质量诊断 / 正则安全"三个不同抽象层揉在一起,review 切分逻辑的 diff 噪音里混着报告字段变更;且拆分成本异常低(0 patch 点 + 无状态 + 现成 mixin 惯例),收益/风险比成立。
- 为什么优先级只是 low:外部接口面极小(2 个导入点、4 个公开方法),测试全走公开 API;Phase A.0 之后新逻辑(adaptive_split/sanitize/filters)都长在 `rpg/ingest/`,本文件已是"存量编排 + 遗留规则",增长压力小。不动也不会恶化。

### ≥80 行巨型函数逐个评估

| 函数 | 行数 | 类型 | 判定 |
|---|---|---|---|
| `_split_chapters_internal` | 112 | 流水线型(显式规则→候选收集→竞争选优→兜底 四阶段) | **值得拆**,但放二期:拆成 `_try_explicit_rule` / `_collect_auto_candidates` / `_select_auto_candidate` 三个阶段函数。不与一期机械搬运混在同一 commit(违反逐字搬运原则),一期先验绿再做 |
| `_build_split_report` | 98 | 数据表型为主(confidence 字典 + reasons 累加表 + 指标装配) | **不拆**。拆成阶段函数只会把一张表撕成三段,降低可读性 |
| `_augment_report_v2` | 67 | <80,线性装配 | 不动 |

## 4. 目标布局(模块化为同名包,导入路径零变化)

把单文件模块升级为**同名 regular package**——`from chapter_splitter import ChapterSplitter / chapter_splitter` 两个活体导入点**一字不改**,连 re-export shim 都不需要单独留(包 `__init__.py` 即 shim):

```
rpg/chapter_splitter/                    (新包,替换原单文件)
├── __init__.py          (~15 行)  re-export:ChapterSplitter, chapter_splitter,
│                                  SplitPattern, NUMBER_TOKEN;__all__ 锁定
├── patterns.py          (~20 行)  叶子模块:NUMBER_TOKEN + @dataclass SplitPattern
├── core.py             (~280 行)  class ChapterSplitter(SplitStrategiesMixin,
│                                  SplitReportMixin, RegexGuardMixin):
│                                  全部类常量(8 组 pattern/标签表,留在具体类上,
│                                  mixin 经 MRO 解析 self.常量,实现逐字搬运)
│                                  + 簇A + 簇B 方法 + 文件尾单例 chapter_splitter = ChapterSplitter()
└── _mixins/
    ├── __init__.py      (~10 行)  re-export 三个 Mixin(照抄 state/_mixins 风格)
    ├── strategies.py   (~380 行)  class SplitStrategiesMixin —— 簇C 19 个方法
    ├── report.py       (~260 行)  class SplitReportMixin —— 簇D 8 个方法
    └── regex_guard.py  (~110 行)  class RegexGuardMixin —— 簇E 2 个方法
                                   + 模块级 def _regex_timeout_probe
```

原 `rpg/chapter_splitter.py` 单文件:**删除**(被同名包取代,非孤儿;陷阱⑤显式闭环)。

## 5. 可机械执行的搬运清单(符号 → 目标文件;逐字搬运、禁止改写任何函数体)

**执行约束(给执行代理的铁律):每个方法/函数体从旧文件原样剪切粘贴,一个字符都不许"顺手优化";唯一允许新写的代码是:类声明行、import 行、`__init__.py` 的 re-export、docstring。**

### patterns.py
| 符号 | 来源行 | 备注 |
|---|---|---|
| `NUMBER_TOKEN` | @15 | 逐字 |
| `SplitPattern` | @18-21 | 连 `@dataclass` 装饰器一起搬;需 `from dataclasses import dataclass` + `from re import Pattern` |

### _mixins/strategies.py(`class SplitStrategiesMixin:`)
搬 19 个方法(均 `ChapterSplitter.` 前缀,来源行号为方法 def 行):
`_split_auto`@299, `_split_standard_headings`@340, `_split_with_volumes`@360, `_split_by_pattern`@386, `_line_split`@394, `_position_split`@427, `_flatten_volumes`@453, `_collect_pagination_headings`@464, `_collect_numbered_section_headings`@497, `_is_numbered_section_heading`@515, `_split_numbered_sections`@527, `_extract_act_heading`@572, `_next_nonempty_line_index`@580, `_trim_trailing_act_heading`@586, `_is_strong_heading`@594, `_is_weak_heading`@601, `_post_process_chapters`@615, `_has_reasonable_chapter_quality`@643, `_fallback_split`@660。
模块头 import:仅 `import re` + `from re import Pattern`(类型标注用)。方法体内的 `self.SECTION_MARKER_PATTERN / self.PAGINATION_HEADING_PATTERN / self.ACT_HEADING_PATTERN / self.VOLUME_PATTERN / self.STRONG_CHAPTER_PATTERNS / self._compact / self._to_int / self._fallback_split` 等引用全部经 MRO 落到 core.ChapterSplitter,**零改写**。

### _mixins/report.py(`class SplitReportMixin:`)
搬 8 个方法:`_build_split_report`@679, `_augment_report_v2`@778, `_classify_split_problem`@846, `_problem_label`@881, `_problem_reason`@896, `_coefficient_of_variation`@909, `_dialogue_line_ratio`@915, `_heading_candidate_density`@922。
模块头 import:`from statistics import mean, stdev`。`self.SPLIT_MODE_LABELS` 经 MRO 解析。

### _mixins/regex_guard.py(`class RegexGuardMixin:` + 模块级函数)
| 符号 | 来源行 | 备注 |
|---|---|---|
| `build_custom_pattern`(方法) | @930 | 体内用 `NUMBER_TOKEN` → 模块头加 `from chapter_splitter.patterns import NUMBER_TOKEN`(或 `from ..patterns import`,与包内其他文件保持一致风格;rpg 包惯例是顶层绝对导入,如 `from state._mixins import ...`) |
| `is_safe_regex`(方法) | @949 | 逐字;尾部调用模块级 `_regex_timeout_probe`,同文件可见 |
| `_regex_timeout_probe`(模块级 def) | @1021-1050 | 逐字;`import multiprocessing` 在函数体内,无模块级副作用 |

### core.py(`class ChapterSplitter(SplitStrategiesMixin, SplitReportMixin, RegexGuardMixin):`)
| 符号 | 来源行 | 备注 |
|---|---|---|
| 模块 docstring + `AUTO_CONFIDENCE_THRESHOLD` 至 `SPLIT_MODE_LABELS` 全部类常量(含 Phase A.0 注释块@79-80) | @1-13, 27-80 | 逐字;常量必须留在具体类上,这是 mixin 零改写的前提 |
| `decode_bytes`@82, `_normalize_encoding`@90, `_strip_pirate_promo`@98, `clean_text`@103 | 簇A | 体内 lazy `from ingest.sanitize import ...` 原样保留 |
| `split_chapters`@108, `split_chapters_with_report`@126, `_split_chapters_internal`@157, `_score_split_candidate`@270, `split_file`@988, `_compact`@1008, `_to_int`@1012 | 簇B | 体内 lazy `from ingest.filters/adaptive_split import ...` 原样保留 |
| `chapter_splitter = ChapterSplitter()` | @1053 | 文件尾,单例位置不变语义 |

模块头 import:`import re` / `from pathlib import Path` / `from re import Pattern` / `from chapter_splitter.patterns import NUMBER_TOKEN, SplitPattern` / `from chapter_splitter._mixins import SplitStrategiesMixin, SplitReportMixin, RegexGuardMixin`。

### __init__.py
```python
from chapter_splitter.core import ChapterSplitter, chapter_splitter
from chapter_splitter.patterns import NUMBER_TOKEN, SplitPattern

__all__ = ["ChapterSplitter", "chapter_splitter", "SplitPattern", "NUMBER_TOKEN"]
```

### 行数对账
361(C) + 243(D) + 86(E) + 236(A+B+常量) + 13(头注释/NUMBER_TOKEN/SplitPattern) ≈ 939 行正文 = 原 1054 行减去类声明/空行重组,搬完五个新文件合计应在 1050±60 行。偏差大于此值 = 执行代理动了函数体,直接打回。

## 6. 五大陷阱逐条核对 + 其他风险

| 陷阱 | 核查结果 | 对策 |
|---|---|---|
| ① 测试 patch 命名空间穿透 | **0 个 patch 点**(grep 实查,测试只 `from chapter_splitter import ChapterSplitter` 走公开 API) | 同名包保住 `chapter_splitter` 顶层导入路径,`script_import.py` 与测试文件零修改 |
| ② `Path(__file__)` 错位 | **0 处**(grep 实查) | 无需处理;`split_file` 的 `Path(path)` 为调用方参数 |
| ③ 执行代理顺手简化 | 风险存在(`_split_chapters_internal` 112 行诱惑大) | 方案明令"逐字搬运、禁止改写逻辑";§5 给出符号→文件机械清单 + 行数对账;函数体重构一律放二期独立 commit |
| ④ 并行中间状态 | 同名"模块→包"替换期间,`chapter_splitter.py` 与 `chapter_splitter/` 同时存在会产生 module/package 遮蔽歧义 | **全程单代理串行,禁止并行批次**(见 §7);新包建好后同一 commit 内删旧文件,并 `find rpg -name '__pycache__' -path '*chapter_splitter*'` 清理陈旧 pyc |
| ⑤ 孤儿文件/死代码 | 已明确 | 旧 `rpg/chapter_splitter.py` **删除**(被同名包取代);`rpg/claude_design_upload/**` 冻结快照**禁止触碰** |
| 循环导入 | 已核:依赖图为 `patterns ← {core, regex_guard}`,`_mixins/* ← core`,`ingest.*` 仅方法内 lazy import 且 ingest 从不反向 import 本模块(adaptive_split 刻意自含) | 新边界不引入任何环;NUMBER_TOKEN 放叶子 patterns.py 正是为了斩断 regex_guard→core 的潜在环 |
| 单例/import 副作用 | 仅 `chapter_splitter = ChapterSplitter()`,类无状态、无注册表 | 单例随 core.py 搬运并经 `__init__` re-export,所有旧消费方拿到同一对象 |

额外风险:
- pyproject ruff/mypy 若按文件路径配置过 `chapter_splitter.py` 的豁免(执行前 grep `pyproject.toml` 确认),路径要同步成包路径。
- OSS 同步(cherry-pick 到 rpg-roleplay-platform):本次为纯结构移动,冲突面 = 未来改动∩本次移动,建议拆分 commit 单独 cherry-pick,五闸照过。

## 7. 串行批次划分(单代理执行,sonnet 机械搬运 + opus 验收)

- **B1(单 commit,一个代理串行完成)**:建 `rpg/chapter_splitter/` 包五文件(按 §5 清单逐字搬运)→ 同 commit 删除旧 `rpg/chapter_splitter.py` → 清理相关 `__pycache__`。禁止改 `script_import.py`、禁止改任何测试、禁止碰 `claude_design_upload/`、禁止碰 `ingest/`。
- **B2(验证,不改源码)**:`python -m py_compile` 五个新文件;跑 `rpg/tests/unit/test_chapter_splitter.py`(6 个用例)+ `rpg/tests/integration/test_new_save_uses_script_opening.py`;`grep -rn "from chapter_splitter"` 确认导入面不变;行数对账(§5)。
- **B3(可选二期,独立 commit)**:`_split_chapters_internal` 按 §3 拆三阶段函数;先绿后拆,拆完再跑 B2 验证集。

B1/B2/B3 严格串行;不存在可并行的文件批次(单文件源头,强行并行只会制造陷阱④)。
