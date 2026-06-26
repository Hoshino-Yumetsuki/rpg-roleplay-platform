# 体检报告:rpg/chat_pipeline.py(1699 行)

- 日期:2026-06-10
- 审计类型:函数抽象层体检 + 拆分方案(只出方案,不动源码——并行审计期间禁改)
- **verdict: needs-refactor(priority: medium / effort: M)**

---

## 1. 现状结构图

该文件是 task #51 从 app.py `/api/chat` 的 stream() 拆出来的 **5-phase 聊天回合流水线**。
orchestrator 在 `rpg/routes/game.py:606` 按序调 5 个 phase(async generator,yield SSE event tuple),
phase 间通过 `PipelineContext` 传可变状态,`ctx.early_return` 短路。

```
rpg/chat_pipeline.py (1699 行)
│
├── [SSE 摘要工具]                                         ── 簇 A:无状态小工具
│   ├── _summarize_tool_args            6行  @34
│   └── _snippet_tool_result           11行  @42
│
├── [模块级 env 配置 + 判定纯函数]                          ── 簇 A
│   ├── _POSTPROC_MODE                 (env, @57)          ⚠ 被测试直接 rebind
│   ├── _SHORT_INPUT_CHARS / _SHORT_INPUT_DIRECTIVE (@62/66) ⚠ 被测试 importlib.reload
│   ├── _should_inject_short_input_directive  9行 @79
│   ├── _gm_max_iters                   9行  @90
│   └── _should_route_to_curator_clarify 3行 @101
│
├── _sync_active_entities_from_bundle  44行 @110           ── 簇 A(state 同步工具)
│
├── class PipelineContext              31行 @157           ── 簇 B:phase 间共享数据
│   └── SSEEvent 类型别名               @191
│
├── apply_player_directives_phase     306行 @199  Phase 1  ── 簇 C:玩家 directive
│   ├── step1 expire_stale_gm_questions
│   ├── step2a /compact 命令(早退)
│   ├── step2b 重写型 /set 软回滚 rewind
│   ├── step2 /set 工具化 (command_agent + ToolDispatcher)
│   ├── step3 正则 fallback
│   ├── step4 set_parser 兜底
│   └── step5 timeline anchor 解析
│
├── run_context_phase                  88行 @512  Phase 2  ── 簇 D:context agent 桥接
├── run_rules_phase                   212行 @607  Phase 3  ── 簇 E:5E preflight + 规则裁定
│   ├── (a) combat gate(早退)
│   ├── (b) rule candidates → bundle["prompt"]
│   ├── (c) context_run 记账 + sub-agent usage
│   └── (d) curator 低 confidence audit(已不短路)
│
├── _apply_gm_json_ops                 40行 @826           ── 簇 F:GM 主响应
├── run_gm_phase                      550行 @868  Phase 4  ── 簇 F ★ 最大热点
│   ├── Phase D 注入 (gm_serving.assemble_gm_context)
│   ├── 短输入镜头指令注入
│   ├── unified_tools + tool_call_router 构造
│   ├── 流式 loop(text/reasoning/tool_call/tool_result/打断/schema-echo/酒馆 first_mes)
│   ├── async 模式:enqueue postproc + 内联确定性后处理(timeline_guard/cliche/json_ops)
│   └── sync 模式:_run_post_gm_parallel + acceptance verify + retry once
│
├── _bridge_sync_generator_to_async    65行 @1425          ── 簇 G:并发基础设施
├── _run_post_gm_parallel             124行 @1492          ── 簇 F(后处理三 worker)
└── persist_turn_phase                 81行 @1618  Phase 5 ── 簇 H:落档 + 可见文本清洗
```

模块顶层 import 只有 `agents.context_agent.run_context_agent`、`core.logging`、`state`;
其余 20+ 依赖(platform_app.db / tools_dsl / gm_serving / agents.* / state_write_context …)
全部 **lazy 在函数体内 import** —— 这是搬运时的重大利好(不改任何顶层依赖关系)。

**文件内无任何 `Path(__file__)` / `__file__` 引用**(grep 实查为零)。

---

## 2. 调用方与 patch 点清单(Grep 实查)

### 2.1 运行时 import 位点(8 处)

| # | 位置 | 用法 | 拆分后是否需要改 |
|---|------|------|----|
| R1 | `rpg/routes/game.py:606` | `from chat_pipeline import (PipelineContext, apply_player_directives_phase, persist_turn_phase, run_context_phase, run_gm_phase, run_rules_phase)`(函数内 lazy import) | **免改**(经 `__init__.py` re-export) |
| R2 | `rpg/tests/test_postproc_queue.py:260` | `from chat_pipeline import PipelineContext` | 免改(re-export) |
| R3 | `rpg/tests/test_postproc_queue.py:286-288` | `import chat_pipeline as _cp` + `assertIn("_POSTPROC_MODE", dir(_cp))` | 免改(`__init__` re-export `_POSTPROC_MODE` 名字即可通过 `dir()` 检查) |
| R4 | `rpg/tests/test_postproc_queue.py:309-310 + 355/356/377` | `import chat_pipeline as _cp` + **`_cp._POSTPROC_MODE = "async"` 直接 rebind 模块全局** | **必改** → `import chat_pipeline.gm_phase as _cp`。re-export 救不了 rebind:`run_gm_phase` 读的是其定义模块的全局,改包命名空间属性不穿透(陷阱①的变体) |
| R5 | `rpg/tests/unit/test_curator_clarify_routing.py:5` | `from chat_pipeline import _should_route_to_curator_clarify` | 免改(re-export) |
| R6 | `rpg/tests/unit/test_short_input_directive.py:9 + 38/43` | `import chat_pipeline as cp` + **`importlib.reload(cp)`** 依赖 `_SHORT_INPUT_CHARS` 的 import-time env 读取 | **必改** → `import chat_pipeline.helpers as cp`。reload 包 `__init__` 不会重执行 helpers 模块,阈值不会刷新 |
| R7 | `rpg/tests/integration/test_black_swan_toggle.py:90` | `from chat_pipeline import _run_post_gm_parallel` | 免改(re-export) |
| R8 | `rpg/tests/integration/test_black_swan_toggle.py:129` | 同上 | 免改(re-export) |

无任何 `mock.patch("chat_pipeline.X")` 字符串形式的 patch(grep 实查为零);
`run_context_phase` 的 `run_context_agent_fn` 等可测试缝全部走参数注入,不受搬运影响。

### 2.2 源码文本断言位点(read_text 型回归锁,8 处)——本文件特有的高风险耦合

这批测试用 `Path(__file__)... / "chat_pipeline.py").read_text()` **把回归锁钉在源文件字面内容上**。
拆分(无论改成包还是搬走任何段落)都会让它们找不到文件或找不到锚串,**必须逐个改指向**:

| # | 位置 | 锚定内容 | 拆分后新指向 |
|---|------|----------|----|
| S1 | `rpg/tests/unit/test_context_phase_passes_save_id.py:8` | `run_context_phase` 体内 `_bridge_sync_generator_to_async(` + `save_id=ctx.early_active_save_id` | `chat_pipeline/context_phase.py` |
| S2 | `rpg/tests/unit/test_compact_reopens_phase.py:8` | `_is_compact_command:` 后 4000 字符窗口内 `compact_phase(` + `open_new_phase` + `turn_index=_cur_turn + 1` | `chat_pipeline/directives_phase.py`(逐字搬运则窗口逻辑原样可用) |
| S3 | `rpg/tests/unit/test_script_timeline_anchors.py:231` | `from script_timeline import resolve_timeline_anchor`、`anchor_chapter`、`state.data["world"]["timeline"]`、`时间线锚点` | `chat_pipeline/directives_phase.py` |
| S4 | `rpg/tests/unit/test_chat_pipeline_acceptance_retry_context.py:6` | `if _retry_response:` 与 `_retry_ctx = ChatWriteContext` 之间须含 `import secrets as _ctx_secrets` + `from state_write_context import` 等 | `chat_pipeline/gm_phase.py` |
| S5 | `rpg/tests/unit/test_user_set_time_jump_guard.py:229` | `timeline_narrative_guard import` + `detect_time_jump_violations` + `record_violations_to_audit` + `"phase": "timeline_guard"` | `chat_pipeline/gm_phase.py`(async 内联分支四个锚串齐全) |
| S6 | `rpg/tests/unit/test_deterministic_rules_routing.py:158` | `expire_stale_gm_questions` 出现位置 **早于** `apply_player_directives`(同文件内 find 索引比较) | `chat_pipeline/directives_phase.py`(两锚都在 Phase 1 内,顺序保持) |
| S7 | `rpg/tests/unit/test_deterministic_rules_routing.py:314` | `apply_chat_rule_candidates`、`rule_results_prompt(rule_results`、`bundle["prompt"]` | `chat_pipeline/rules_phase.py` |
| S8 | `rpg/tests/unit/test_game_policy_layer.py:184` | `get_game_policy`、`.preflight(message_for_model` | `chat_pipeline/rules_phase.py` |

**合计 16 个受影响位点;其中必须同步修改 11 个(R4、R6 + S1~S8),其余 5 个经 re-export shim 免改。**

注释级引用(不需要改,列出备查):`save_phase_manager.py:14`、`tools_dsl/command_dispatcher.py:203`、
`gm_serving/serve.py:1,4,28`、`agents/_harness.py:529`、`state/core.py:600`、`scripts/run_cron.py:88`、
`scripts/phase_digest_worker.py:8`、`routes/game.py:601`。

---

## 3. 内聚簇分析与判定

### 为什么不是 acceptable

文件确实"名义上单一职责"(一个聊天回合的流水线),且 5 个 phase 已经各自成函数、依赖注入做得不错。
但它不是追加式账本/纯数据表,而是**八个内聚簇平铺在一个 1699 行文件里**,其中:

1. `run_gm_phase` 550 行 = Phase D 注入 + 工具表构造 + 流式 loop(7 种 event 分支 + 酒馆特判)+
   async/sync 两条后处理分叉 + acceptance retry,**至少 5 个独立变更轴**挤在一个函数里。
   近期改动史(W1 容量优化、酒馆 first_mes、schema-echo 防御、反馈 #28…)全都打在这个函数上,
   每次 diff 审查面都是 550 行。
2. `apply_player_directives_phase` 306 行 = 6 个顺序 step + 2 个早退命令 handler,/compact 和
   重写型 /set 各自是完整子功能。
3. 基础设施(`_bridge_sync_generator_to_async`)、纯判定函数、SSE 摘要工具和业务 phase 混居。

### 为什么不是 leave-as-is

风险可控:模块顶层依赖极薄(3 个 import),重依赖全部 lazy 在函数体内;文件内无 `Path(__file__)`;
runtime 调用方只有 1 处(routes/game.py,且是函数内 lazy import);phase 函数之间零互调
(只通过 ctx 传值),天然按 phase 切。真正的成本集中在 **测试侧 16 个位点**(上表),全部可机械枚举。

### 判定

**needs-refactor**,但方案分两层:
- **第一层(本方案主体,机械可执行):按内聚簇把单文件改成 `chat_pipeline/` 包**,逐字搬运,零逻辑改写。
- **第二层(可选后续,需人工 review):`run_gm_phase` / `apply_player_directives_phase` 函数内阶段化**。
  这一层不是逐字搬运(async generator 切阶段要引入 `async for ... yield` 转发),风险高一档,
  单独成批,不与第一层混做。

---

## 4. 目标布局

仓库惯例:`rpg/` 下子包平铺 snake_case 模块(参照 `gm_serving/{serve,steering,impact}.py`、
`rules_bridge/{intent,combat,suggest}.py`、`state/_mixins/`)。将 `chat_pipeline.py` 原地升级为同名包,
**保住 `from chat_pipeline import X` 全部既有 import 路径**:

```
rpg/chat_pipeline/                       (替代 rpg/chat_pipeline.py)
├── __init__.py        ~60 行   re-export shim(见 §6),保留原模块 docstring
├── context.py         ~80 行   PipelineContext + SSEEvent
├── helpers.py        ~140 行   簇 A:SSE 摘要 + 短输入判定 + 杂项纯函数
├── bridge.py          ~75 行   簇 G:_bridge_sync_generator_to_async
├── directives_phase.py ~330 行  Phase 1
├── context_phase.py   ~110 行  Phase 2
├── rules_phase.py     ~230 行  Phase 3
├── gm_phase.py        ~610 行  Phase 4(含 _POSTPROC_MODE、_apply_gm_json_ops)
├── postproc.py        ~135 行  _run_post_gm_parallel(三 worker)
└── persist_phase.py    ~95 行  Phase 5
```

最大单文件从 1699 → ~610 行(gm_phase),且 gm_phase 的 610 行里只剩一个变更轴系(GM 响应)。

---

## 5. 机械搬运清单(符号 → 目标文件)

**铁律:逐字搬运,禁止任何改写/简化/重排函数体**(陷阱③)。每个符号 = 原文件中连续的源码段
(含其上方紧贴的注释块),剪切粘贴,不动一字。唯一允许新增的代码是各文件头部的 import 行与
`__init__.py` 的 re-export。

| 原行号 | 符号 | 目标文件 | 备注 |
|--------|------|----------|------|
| @1-10 | 模块 docstring | `__init__.py` | 原样保留 |
| @34-39 | `_summarize_tool_args`(含 @32-33 注释) | `helpers.py` | |
| @42-52 | `_snippet_tool_result` | `helpers.py` | |
| @55-57 | `_POSTPROC_MODE`(含注释) | **`gm_phase.py`** | 必须与消费者 `run_gm_phase` 同模块(测试 R4 rebind 它) |
| @59-76 | `_SHORT_INPUT_CHARS` + `_SHORT_INPUT_DIRECTIVE`(含 try/except 与注释) | `helpers.py` | 与消费者 `_should_inject_short_input_directive` 同模块(测试 R6 reload 它) |
| @79-87 | `_should_inject_short_input_directive` | `helpers.py` | |
| @90-98 | `_gm_max_iters` | `helpers.py` | |
| @101-103 | `_should_route_to_curator_clarify` | `helpers.py` | |
| @110-153 | `_sync_active_entities_from_bundle` | `helpers.py` | |
| @156-188 | `class PipelineContext` | `context.py` | |
| @190-191 | `SSEEvent` 别名 | `context.py` | |
| @199-504 | `apply_player_directives_phase`(含 @194-197 分隔注释) | `directives_phase.py` | |
| @512-599 | `run_context_phase`(含 @507-509 注释) | `context_phase.py` | |
| @607-818 | `run_rules_phase`(含 @602-604 注释) | `rules_phase.py` | |
| @826-865 | `_apply_gm_json_ops`(含 @821-823 注释) | `gm_phase.py` | |
| @868-1417 | `run_gm_phase` | `gm_phase.py` | |
| @1425-1489 | `_bridge_sync_generator_to_async`(含 @1420-1422 注释) | `bridge.py` | 注释段写的是 "Phase 5" 分隔线,实际函数是 bridge——分隔注释留在 persist_phase.py 头部或舍弃均可,推荐随 `persist_turn_phase` 走 |
| @1492-1615 | `_run_post_gm_parallel` | `postproc.py` | |
| @1618-1699 | `persist_turn_phase` | `persist_phase.py` | |

### 各新文件需补的头部 import(从原文件顶部 @13-29 按需分配)

- `context.py`:`from __future__ import annotations`; `dataclass/field`; `threading.Event`; `typing.Any`; `from state import GameState`
- `helpers.py`:`from __future__ import annotations`; `json`, `os`; `typing.Any`; `from core.logging import get_logger`(`_sync_active_entities_from_bundle` 不用 log,可省;实际只 `json/os/Any` 必需——**以 pyflakes 实测为准,不凭记忆删**)
- `bridge.py`:`asyncio`; `AsyncIterator, Callable`; `typing.Any`
- `directives_phase.py`:`os`, `re`; `AsyncIterator, Callable`; `Any`; `from core.logging import get_logger`; `from state import GameState`; `from .context import PipelineContext, SSEEvent`
- `context_phase.py`:`AsyncIterator, Callable`; `Any`; `from agents.context_agent import run_context_agent`; `from .bridge import _bridge_sync_generator_to_async`; `from .context import PipelineContext, SSEEvent`
- `rules_phase.py`:`time`; `AsyncIterator, Callable`; `Any`; `get_logger`; `from .context import PipelineContext, SSEEvent`; `from .helpers import _sync_active_entities_from_bundle`
- `gm_phase.py`:`asyncio`, `json`, `os`, `time`; `AsyncIterator, Callable`; `Any`; `get_logger`; `from state import GameState`; `from .context import PipelineContext, SSEEvent`; `from .helpers import _summarize_tool_args, _snippet_tool_result, _should_inject_short_input_directive, _SHORT_INPUT_DIRECTIVE, _gm_max_iters`; `from .bridge import _bridge_sync_generator_to_async`; `from .postproc import _run_post_gm_parallel`
- `postproc.py`:`asyncio`, `json`; `Callable`; `Any`; `get_logger`; `from state import GameState`; `from .context import PipelineContext`
- `persist_phase.py`:`AsyncIterator, Callable`; `Any`; `get_logger`; `from state import strip_json_state_ops, strip_meta_tool_preamble`; `from .context import PipelineContext, SSEEvent`

每个文件都加 `log = get_logger(__name__)`(凡函数体内用到 `log.` 的:directives/context/rules/gm/postproc/persist 六个文件)。

---

## 6. `__init__.py` re-export shim(原模块去向 = 替换为包门面,旧 .py 删除)

```python
"""(原 chat_pipeline.py 模块 docstring 原样保留)…"""
from chat_pipeline.bridge import _bridge_sync_generator_to_async
from chat_pipeline.context import PipelineContext, SSEEvent
from chat_pipeline.context_phase import run_context_phase
from chat_pipeline.directives_phase import apply_player_directives_phase
from chat_pipeline.gm_phase import _POSTPROC_MODE, _apply_gm_json_ops, run_gm_phase
from chat_pipeline.helpers import (
    _SHORT_INPUT_DIRECTIVE,
    _gm_max_iters,
    _should_inject_short_input_directive,
    _should_route_to_curator_clarify,
    _snippet_tool_result,
    _summarize_tool_args,
    _sync_active_entities_from_bundle,
)
from chat_pipeline.persist_phase import persist_turn_phase
from chat_pipeline.postproc import _run_post_gm_parallel
from chat_pipeline.rules_phase import run_rules_phase

__all__ = [...同上全部名字...]
```

- 下划线名也全部 re-export:测试在用 `_should_route_to_curator_clarify`、`_run_post_gm_parallel`、
  `_bridge_sync_generator_to_async`(不直接用但保险)、`dir(_cp)` 检查 `_POSTPROC_MODE`。
- **明确声明(陷阱⑤)**:旧 `rpg/chat_pipeline.py` 文件在 Batch 1 中 `git rm`,由包 `__init__.py`
  接管同名导入路径;不留孤儿副本。`git mv` 不适用(一拆十),用 `git rm` + 新增,commit message 注明映射。

---

## 7. ≥80 行巨型函数逐个评估

| 函数 | 行数 | 类型 | 是否拆阶段 | 理由 |
|------|------|------|-----------|------|
| `apply_player_directives_phase` | 306 | 流水线型(6 step + 2 早退 handler) | **值得拆,但放第二层(Batch 5,可选)** | /compact handler(@256-328)和重写型 /set rewind(@330-368)是完整子功能,可提成同文件内的 `_handle_compact_command(ctx, api_user, state) -> AsyncIterator`(`async for ev in ...: yield ev` 转发)与 `_maybe_rewind_for_rewrite_set(...)`(同步,返回 rewind 事件 payload 或 None)。注意 S2 测试锚定 `_is_compact_command:` 后 4000 字符窗口含 `compact_phase(`——拆出 handler 会破坏窗口,**S2 必须随之改写为锚定新 helper 函数体**。第一层不动 |
| `run_context_phase` | 88 | 桥接 + 分发,单一职责 | 不拆 | 88 行里大半是注释和参数透传,无收益 |
| `run_rules_phase` | 212 | 两段式(combat gate 早退 ~95 行 + 记账) | **可拆可不拆,第二层可选** | gate 段可提 `_yield_combat_gate_events(...)`;收益中等,S8 锚串 `.preflight(message_for_model` 在 gate 段内,拆了仍在同文件,锚不破 |
| `run_gm_phase` | 550 | 典型流水线型,5 个变更轴 | **值得拆(第二层 Batch 5 主目标)** | 推荐切 4 刀,全部留在 gm_phase.py 同文件内(保 S4/S5 锚串仍在同一 read_text 目标里):① `_inject_phase_d_and_short_input(ctx, bundle, message)`(@906-941,同步,无 yield);② `_build_gm_toolchain(ctx, state, api_user, active_script_id) -> (unified_tools, gm_tool_router, _gm_mode)`(@950-994,同步);③ 流式 loop **暂不拆**(7 个 event 分支 + 酒馆 first_mes break + response 累积强耦合,拆出去要带 5 个可变量,得不偿失);④ `_async_postproc_branch(...)`(@1138-1235,async generator)与 ⑤ `_acceptance_gate_with_retry(...)`(@1294-1412,async generator)。注意 ④⑤ 是 yield 型,提取后调用处须 `async for ev in ...: yield ev`,且 `_POSTPROC_FALLBACK` 局部变量的赋值流要原样保持——**这不是逐字搬运,须人工 review,sonnet 子代理不可独自做** |
| `_bridge_sync_generator_to_async` | 65 | 并发基础设施,纯单一职责 | 不拆 | 原样进 bridge.py |
| `_run_post_gm_parallel` | 124 | 三个内嵌 worker + gather | 不拆 | 内嵌 closure 共享 `response/state/ctx`,结构已是"阶段函数"形态 |
| `persist_turn_phase` | 81 | 落档 + 文本清洗 | 微拆(可选) | @1642-1665 的"剥结尾决策反问"regex 块是纯函数,可提 `_strip_trailing_decision_question(text) -> str` 留同文件,顺手可加单测;非必需 |

---

## 8. 五大陷阱逐项核对

1. **patch 命名空间穿透**:§2 已 Grep 实查列全 16 个位点。普通 `from chat_pipeline import X` 由
   `__init__.py` re-export 覆盖(5 处免改)。**两个 re-export 救不了的特例**:
   - R4 `_cp._POSTPROC_MODE = "async"` 模块全局 rebind → 测试必须改 `import chat_pipeline.gm_phase as _cp`;
   - R6 `importlib.reload(cp)` 刷新 env 阈值 → 测试必须改 `import chat_pipeline.helpers as cp`。
   - 另有 8 处 read_text 源码文本断言(S1-S8)必须改指向新文件,见 §2.2 映射表。
2. **`Path(__file__)` 错位**:被搬代码内 **零处**(grep 实查)。但 8 个测试用 `Path(__file__)`
   定位 `chat_pipeline.py` 读源码——包化后该文件消失,测试会**响亮地**失败(好事,不会静默漂移),
   按 §2.2 表改路径即可。
3. **顺手简化**:§5 表即逐字搬运清单(原行号 → 目标文件);执行代理只许剪切粘贴 + 补 §5 列出的
   import;任何"我顺便把这段 try/except 收紧一下"一律禁止。第二层(Batch 5)因涉及 async
   generator 改形,**不交给 sonnet 机械执行**,需 opus 级 + 人工 review。
4. **并行中间状态**:§9 批次全串行;Batch 1 一次 commit 完成"建包 + 删旧文件 + shim",绝不让
   `chat_pipeline.py` 与 `chat_pipeline/` 并存(Python 同名 module/package 共存时行为取决于
   finder 顺序,是真事故源)。
5. **孤儿文件**:旧 `chat_pipeline.py` 在 Batch 1 内 `git rm`(§6 已声明);搬完后跑
   `grep -rn "chat_pipeline.py" rpg/ --include="*.py"` 确认只剩 §2.2 改过的测试路径与注释。

### 循环导入核查

- 新增的包内 import 全部单向:`context ← helpers ← bridge ← (phases) ← __init__`,无环。
- 包外重依赖(`platform_app.*`、`tools_dsl.*`、`gm_serving.serve`、`agents.*`、`state_write_context`、
  `game_policy`、`script_timeline`、`mcp_broker`、`save_phase_manager`、`state_event_bus`、
  `platform_app.branches.deletion`)**全部原样留在函数体内 lazy import**,不上提——上提才会引入
  环(如 `gm_serving.serve` ↔ chat_pipeline 互相提及)和 import 副作用,严禁。
- `routes/game.py` 对 chat_pipeline 的 import 本身就在函数内,包化无感。

### 模块级单例与 import 副作用核查

- 本模块无注册表/装饰器注册;`ensure_registered()`(tools_dsl)是函数内 lazy 调用,搬运不改其时机。
- import-time 副作用仅 3 个 env 读取:`_POSTPROC_MODE`(→ gm_phase.py)、`_SHORT_INPUT_CHARS` +
  `_SHORT_INPUT_DIRECTIVE`(→ helpers.py)。均与消费者同模块,语义不变;对应测试位点 R4/R6 已列必改。
- `log = get_logger(__name__)`:`__name__` 从 `chat_pipeline` 变为 `chat_pipeline.gm_phase` 等,
  日志 logger 名变化(日志聚合若按 logger 名过滤需知悉;grep 生产侧无按此名过滤的配置,可接受)。

---

## 9. 串行批次划分(第一层 = Batch 1-4;第二层可选 = Batch 5)

> 执行模型:Batch 1-3 是机械搬运,可交 sonnet 子代理(单线程串行,一批一 commit);
> Batch 4 验证;Batch 5(可选)必须 opus + 人工 review,另开 PR。

- **Batch 1(单 commit,原子)**:建 `rpg/chat_pipeline/` 包;按 §5 清单逐字搬运全部符号;
  写 `__init__.py`(§6);`git rm rpg/chat_pipeline.py`。期间不碰任何测试文件。
  完成判据:`python -m py_compile rpg/chat_pipeline/*.py` 全过;`python -c "import chat_pipeline; chat_pipeline.run_gm_phase"` 可解析。
- **Batch 2(单 commit)**:改 2 个运行时测试位点——
  `tests/test_postproc_queue.py:309/355-377`(R4 → `chat_pipeline.gm_phase`)、
  `tests/unit/test_short_input_directive.py:9/38/43`(R6 → `chat_pipeline.helpers`)。
- **Batch 3(单 commit)**:改 8 个 read_text 位点(S1-S8)指向 §2.2 映射的新文件;
  其中 S1 的段尾定位逻辑(`find("\nasync def ", i+1)`)在 context_phase.py 中 run_context_phase
  为文件末函数时 end=-1 → `SRC[i:-1]`,断言锚串仍在切片内,无需改逻辑,只改路径。
- **Batch 4(验证,不 commit 代码)**:
  1. `pytest rpg/tests/test_postproc_queue.py rpg/tests/unit/test_short_input_directive.py rpg/tests/unit/test_curator_clarify_routing.py rpg/tests/unit/test_context_phase_passes_save_id.py rpg/tests/unit/test_compact_reopens_phase.py rpg/tests/unit/test_chat_pipeline_acceptance_retry_context.py rpg/tests/unit/test_user_set_time_jump_guard.py rpg/tests/unit/test_deterministic_rules_routing.py rpg/tests/unit/test_game_policy_layer.py rpg/tests/unit/test_script_timeline_anchors.py rpg/tests/integration/test_black_swan_toggle.py rpg/tests/integration/test_rules_chat_pipeline.py`
  2. 全量 pytest(本机一次性 PG 配方见 memory:project_rpg_local_testdb)。
  3. 残留扫描:`grep -rn "chat_pipeline\.py" rpg/ --include="*.py"`(预期只剩注释)+
     `grep -rn "from chat_pipeline import\|import chat_pipeline" rpg/ --include="*.py"` 对照 §2.1。
- **Batch 5(可选,第二层,另开分支/PR)**:按 §7 对 `run_gm_phase`(4 刀)与
  `apply_player_directives_phase`(2 刀)做同文件内阶段化;同步改写 S2(compact 窗口断言)
  与 S4(acceptance retry 切片断言)为锚定新 helper;每刀单独 commit + 跑 Batch 4 测试集。

## 10. 风险汇总

- **最大风险 = 测试侧(11 处必改)而非生产侧(0 处必改)**:routes/game.py 经 shim 无感。
- read_text 型测试是"源码字面回归锁",Batch 1 与 Batch 3 之间存在必然的红灯窗口
  (文件没了)→ 必须连续执行 Batch 1-3 后才跑 CI,不可中途停在 Batch 1。
- 同名 module→package 切换若残留旧 `chat_pipeline.pyc`/`__pycache__`,本地可能 import 到陈旧字节码:
  Batch 4 前清 `find rpg -name __pycache__ -prune -exec rm -rf {} +`。
- 生产部署(ECS06 systemd 裸机,见 memory:project_rpg_deploy)只需正常 `git pull + restart`,
  无迁移、无前端变化;OSS cherry-pick 同步时此重构是纯结构 commit,冲突面 = 未来改动∩gm_phase。
- Batch 5 的 async generator 改形是唯一"非逐字"环节,若不做,第一层收益(1699→最大 610)已达标。
