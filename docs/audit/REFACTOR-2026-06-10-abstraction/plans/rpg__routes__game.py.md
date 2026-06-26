# 体检报告:rpg/routes/game.py(852 行)

- 日期:2026-06-10
- 审计类型:函数抽象层体检 + 拆分方案(只出方案,不动源码——并行审计期间禁改)
- **verdict: needs-refactor(priority: low / effort: S)**
- 一句话:游戏主流程路由(new/opening/chat/stop/save)本体内聚良好且重活已外迁 chat_pipeline,
  但被后挂的「上下文计量」端点簇(estimate + context-breakdown + 两张颜色映射表,约 200 行)
  和一个与 chat_pipeline 重复实现的异步桥接工具污染;只需一次低风险小切除,不需要大拆。

---

## 1. 现状结构图

```
rpg/routes/game.py (852 行)
│  docstring:"游戏核心流程路由 (new / opening / chat / stop / save)"
│  ⚠ 注意:estimate / context-breakdown 不在 docstring 自述职责内 → 后挂混入的证据
│
├── [错误脱敏常量 + 工具]                                  ── 簇 E:SSE 错误脱敏
│   ├── _CLIENT_SAFE_RUNTIME_PREFIXES          @21
│   ├── _CLIENT_SAFE_AUTH_MARKERS              @26
│   └── _client_safe_error                21行 @34   ⚠ 测试直接 import + 源码文本断言钉死
│
├── _bridge_sync_generator_to_async       49行 @57   ── 簇 F:并发基础设施
│      ⚠ chat_pipeline.py:1425 有一份**实现不同**的同名近重复(详见 §5.3)
│
├── router = APIRouter()                       @107
│
├── api_new                               94行 @111  ── 簇 A:游戏主流程
├── api_opening                          102行 @208  ── 簇 A(SSE 流式开场)
│
├── api_chat_estimate                     71行 @313  ── 簇 B:上下文计量(只读观测)
├── _LAYER_CATEGORY  (数据表, ~39行)            @387  ── 簇 B  ⚠ 测试直接 import ×3
├── _CATEGORY_ORDER  (数据表, ~10行)            @427  ── 簇 B  ⚠ 测试直接 import ×1
├── api_context_breakdown                 62行 @440  ── 簇 B
│
├── api_chat                             299行 @505  ── 簇 A(orchestrator,重活已在 chat_pipeline)
│   ├── 输入校验/长度上限/附件落盘/save_id 冲突检测      (~90 行)
│   ├── stream():/命令短路 + 5 phase 依赖注入串接        (~180 行,内嵌闭包)
│   │   └── ⚠ Phase 2.5 世界书块(@685-728)内联在路由里,是唯一没住进 chat_pipeline 的 phase
│   └── _stream_with_done_guard():done 兜底守卫          (~18 行,内嵌闭包)
│
├── api_stop                              20行 @807  ── 簇 A
└── api_save                              22行 @830  ── 簇 A
```

文件内 **无任何 `Path(__file__)` / 相对路径用法**(逐行读过,陷阱②本文件天然免疫;
但有一处测试用 `Path(__file__)` 定位 game.py 源码做文本断言,见 §3)。

---

## 2. 引用面(Grep 实查,全量)

### 2.1 生产代码

| # | 位置 | 形式 | 拆分后影响 |
|---|------|------|-----------|
| R1 | `rpg/app.py:479` | `from routes.game import router as game_router` + `:489 include_router` | **免改**(router 留在 game.py);新模块需**新增** import + include_router |
| R2 | `frontend/src/api-client.js` | 调 URL `/api/chat/estimate`、`/api/chat/context-breakdown` | **免改**(URL 不变,只换 router 归属) |
| R3 | `rpg/chat_pipeline.py:594`、`rpg/agents/gm/master.py:705` | 注释提及 `/api/chat/context-breakdown` | 免改(纯注释) |

无任何其它生产模块 import `routes.game` 的符号。

### 2.2 测试(= patch 点清单,共 7 处)

**`mock.patch("routes.game.*")` 全仓为 0 处**(Grep `patch(.?["']routes\.game` 无命中)——
patch 命名空间穿透风险只剩「直接 import + 源码文本断言」两类:

| # | 文件:行 | 形式 | 本方案下 |
|---|---------|------|---------|
| P1 | `rpg/tests/unit/test_context_breakdown_attribution.py:20` | `from routes.game import _LAYER_CATEGORY` | **shim 免改**(game.py 留 re-export) |
| P2 | 同上 `:27` | `from routes.game import _LAYER_CATEGORY` | shim 免改 |
| P3 | 同上 `:31` | `from routes.game import _CATEGORY_ORDER` | shim 免改 |
| P4 | 同上 `:41` | `from routes.game import _LAYER_CATEGORY` | shim 免改 |
| P5 | `rpg/tests/unit/test_chat_error_no_leak.py:8` | `from routes.game import _client_safe_error` | 免改(符号不搬) |
| P6 | 同上 `:10` + `:58` | `SRC = routes/game.py 源码文本`;断言 `_sse("error", {"message": str(exc)` **不在** SRC | 免改(api_opening/api_chat 留在 game.py) |
| P7 | 同上 `:60` | 断言 `SRC.count("_client_safe_error(exc)") == 2` | 免改(两处调用点 @306/@783 都留在 game.py;`def _client_safe_error(exc: Exception)` 因带类型标注不计入该字面量) |

> **P6/P7 是本文件最隐蔽的约束**:`test_chat_error_no_leak.py` 用 `Path(__file__).parents[2]/routes/game.py`
> 读**源码文本**做断言。任何把 `api_opening` 或 `api_chat`(或 `_client_safe_error` 的两处调用点)
> 搬离 game.py 的方案,都必须同步改这个测试的 SRC 路径与计数——这正是本方案**不动这三者**的硬理由之一。

---

## 3. 内聚簇分析

| 簇 | 成员 | 行数 | 判定 |
|----|------|------|------|
| A 游戏主流程 | api_new / api_opening / api_chat / api_stop / api_save | ~540 | **留在 game.py**。与 docstring 自述职责一致;api_chat 的重活已在 task #51 外迁 chat_pipeline,剩的是 orchestrator 胶水(依赖注入串接 5 phase),再拆只会把 25 个 `from app import` 注入参数再抄一遍 |
| B 上下文计量 | api_chat_estimate / _LAYER_CATEGORY / _CATEGORY_ORDER / api_context_breakdown | ~185 | **应迁出**。只读观测端点,不写游戏态、不产 SSE 流、不进回合流程;两张颜色映射表是典型声明式数据表(本身不该拆函数);与簇 A 唯一的耦合是同住一个 router |
| E 错误脱敏 | _client_safe_error + 2 常量 | ~35 | **留在 game.py**。被 P5-P7 三重钉死(import + 源码计数);仅 api_opening/api_chat 使用,就地内聚 |
| F 并发桥 | _bridge_sync_generator_to_async | 49 | **本轮不动,挂账**。chat_pipeline.py:1425 有同名近重复但实现**不等价**(见 §5.3),合并属行为级改动,不许混进机械搬运 |

**verdict 论证**:852 行里 ~540 行是名副其实的「游戏主流程路由」,且已经历过一次正确方向的
减肥(chat 流水线外迁)。剩余问题是两个边界污染:① 簇 B 是挂错地方的观测端点(连 docstring
都没认领它们);② 簇 F 是仓内重复实现的基础设施。①可零风险机械切除,②需单独的行为对账。
所以判 **needs-refactor 但 priority: low / effort: S**——不是大手术,是一次 200 行的小切除。
判 acceptable 的理由不充分:簇 B 与簇 A 没有任何共享状态或互调,留下只会让"游戏主流程路由"
这个名字继续撒谎,且 `_LAYER_CATEGORY` 这种纯数据表混在 SSE 流式处理代码中间(@387 插在
estimate 和 breakdown 之间)已经造成阅读断裂。

---

## 4. 目标布局

遵循 routes 包现有惯例:**扁平单文件 = 一个路由域,各自持有自己的 `router = APIRouter()`**
(对照 core.py / sidebar.py / timeline.py 等 14 个兄弟文件)。不建子包。

```
rpg/routes/
├── game.py          ~650 行   簇 A + E + F:游戏主流程 + 错误脱敏 + 并发桥(暂留)
│                              + 簇 B 符号的 re-export shim(1 行)
│                              + docstring 维持 "new / opening / chat / stop / save"(终于名实相符)
└── chat_context.py  ~205 行   簇 B:上下文计量(estimate + context-breakdown + 两张表)
                               自带 router;URL 不变
```

### 4.1 `rpg/routes/chat_context.py` 模块头(新建)

```python
"""chat_context.py — 聊天上下文计量路由 (estimate / context-breakdown)。

从 routes/game.py 迁出的只读观测端点:不写游戏态、不产 SSE 流。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from routes._deps_fastapi import get_current_user
from schemas._common import COMMON_ERROR_RESPONSES, GenericOkResponse
from schemas.game import ChatEstimateRequest

router = APIRouter()
```

(函数体内的 `from app import ...` / `from platform_app.usage import ...` 延迟导入**原样保留**,
与 game.py 现行风格一致,也是无环的保证,见 §5.6。)

---

## 5. 可机械执行的搬运清单(逐字搬运、禁止改写逻辑)

> 执行代理铁律:以下每条都是 **verbatim cut-paste**。不许"顺手"改函数体、不许合并 import、
> 不许重排 `_LAYER_CATEGORY` 的键序或注释、不许把函数内延迟 import 提升到模块级。

### 批次 1 — 新建 `rpg/routes/chat_context.py`(只新增,不碰任何现有文件)

| 源(game.py 行号) | 符号 | 目标 | 备注 |
|---|---|---|---|
| @312-383 | `api_chat_estimate`(含 `@router.post("/api/chat/estimate", ...)` 装饰器) | chat_context.py | 装饰器一并搬,挂到新 router |
| @386-425 | `_LAYER_CATEGORY`(含 @386 的 `# layer id → ...` 注释行) | chat_context.py | 纯数据表,**不得拆/不得重排** |
| @427-436 | `_CATEGORY_ORDER` | chat_context.py | 同上 |
| @439-501 | `api_context_breakdown`(含 `@router.get("/api/chat/context-breakdown", ...)` 装饰器) | chat_context.py | 同上 |
| — | §4.1 给出的模块头 | chat_context.py | 唯一允许"新写"的内容 |

### 批次 2 — 改 `rpg/routes/game.py`(单文件)

1. 删除上表 4 段(@312-383、@386-425、@427-436、@439-501,共约 190 行)。
2. 在模块头 import 区(@14 `from state.parsers import ...` 之后)加 shim:
   ```python
   # re-export shim:tests/unit/test_context_breakdown_attribution.py 仍从 routes.game import(陷阱①)
   from routes.chat_context import _LAYER_CATEGORY, _CATEGORY_ORDER  # noqa: F401
   ```
3. 检查 game.py 头部 import 是否出现孤儿:`GenericOkResponse` 与 `ChatEstimateRequest`
   迁出后在 game.py 不再被引用 → 从 @12/@13 的 import 行**仅移除这两个名字**(其余保留)。
   其它头部 import(asyncio/threading/StreamingResponse/OkResponse/StateResponse/
   ChatRequest/NewGameRequest/_extract_trailing_markdown_options)在簇 A 仍有使用,不动。

### 批次 3 — 改 `rpg/app.py`(单文件)

1. @480 附近(`from routes.game import ...` 之后,保持现有字母序习惯)加:
   `from routes.chat_context import router as chat_context_router`
2. @489 附近 include 区加:`app.include_router(chat_context_router)`

### 批次 4 — 验证(不改文件)

```
python -m py_compile rpg/routes/game.py rpg/routes/chat_context.py rpg/app.py
pytest rpg/tests/unit/test_context_breakdown_attribution.py rpg/tests/unit/test_chat_error_no_leak.py -x
# 端点不 404(陷阱:装饰器注册在新 router 上,app.py 漏 include 就是静默 404):
# TestClient: GET /api/chat/context-breakdown → 200;POST /api/chat/estimate → 200
# 然后全量 pytest(本仓基线 ~838)
```

---

## 6. ≥80 行巨型函数逐个评估

| 函数 | 行数 | 类型 | 是否拆阶段函数 | 理由 |
|---|---|---|---|---|
| `api_chat` | 299 | 流水线 orchestrator | **不拆**(本轮) | 流水线本体已在 chat_pipeline 5 phase;剩余是依赖注入胶水 + 两个闭包(`stream`/`_stream_with_done_guard`),闭包提升到模块级要穿 ~10 个局部变量参数,纯增噪。**例外挂账**:@685-728 的 Phase 2.5 世界书块是内联在路由里的"第六个 phase",正确归宿是 chat_pipeline 的 `run_worldbook_phase`——但搬过去必须把 `yield _sse(evt, data)` 改写成 phase 协议的 `yield (evt, data)` 元组,**是改写不是搬运**(陷阱③),且 chat_pipeline 正有独立拆分方案在排队(见兄弟报告 rpg__chat_pipeline.py.md)。应在 chat_pipeline 包化落地后作为独立小任务做,不混进本次。 |
| `api_opening` | 102 | 线性 SSE 流 | 不拆 | 单一连续流程(检索→组装→流式生成→落库),无可复用阶段;且被 P6 源码断言间接钉在 game.py |
| `api_new` | 94 | 线性优先级解析 | 不拆 | 三级 source 解析(script_card→user_card→persona)是一段自解释的优先级梯子;抽 `_resolve_player_source` 收益边际 |

`_LAYER_CATEGORY`(39 行)是纯数据表型 → 按准则**不该拆成函数**,原样整体搬运。

---

## 7. 五大陷阱逐条核对

1. **测试 patch 命名空间穿透**:`mock.patch("routes.game.*")` 全仓 0 处(Grep 实查);
   直接 import 共 5 处(P1-P5)+ 源码文本断言 2 处(P6/P7),全列于 §2.2。
   方案以「shim 留 game.py + `_client_safe_error`/api_opening/api_chat 不搬」做到 **7 处全部免改**。
2. **`Path(__file__)` 错位**:被搬 4 段代码内 0 处(逐行核过)。测试侧
   `test_chat_error_no_leak.py:10` 用 `Path(__file__)` 定位 game.py——因被断言的内容全部留守,免改。
   (若未来有人搬 api_chat,此处必炸,已在 P6/P7 标红。)
3. **执行代理顺手简化**:§5 已声明逐字搬运铁律 + 给出行号级清单;特别点名
   `_LAYER_CATEGORY` 的注释与键序、函数内延迟 import 不得"优化"。
4. **并行中间状态**:批次 1(新文件)→ 批次 2(game.py)→ 批次 3(app.py)→ 批次 4(验证)
   **严格串行**;无任何文件被两个批次同时触碰。批次 2、3 各只动一个文件。
5. **孤儿/死代码**:game.py **保留**(仍是主流程 router 宿主)+ 1 行 re-export shim,不是孤儿;
   chat_context.py 为新建;批次 2 第 3 步显式清理 game.py 头部因迁出而孤儿化的 2 个 import 名。

### 5.6 循环导入核查
`routes.chat_context` 模块级只依赖 fastapi / routes._deps_fastapi / schemas.*(均为叶子),
对 `app` 与 `platform_app.usage` 的依赖全在函数体内延迟(照搬现状)→ 无环。
`routes.game` 新增模块级 `from routes.chat_context import ...`:chat_context 不 import game → 无环。
`app.py` import 两个 routes 模块(本来就 import game)→ 无新环。

### 5.7 模块级单例与 import 副作用
- 每个 routes 文件的 `router = APIRouter()` + 装饰器注册是**唯一** import 副作用;
  新 router **必须**在 app.py include(批次 3),否则两个端点静默 404——批次 4 第 3 行专测此点。
- `_LAYER_CATEGORY`/`_CATEGORY_ORDER` 是只读常量,无注册顺序问题;include_router 先后不影响不同路径。
- game.py 的 shim import 让「import routes.game ⇒ 顺带 import routes.chat_context」,
  与旧行为(两表随 game 模块加载)等价,测试 P1-P4 语义不变。

### 5.8 挂账(不进本次批次的后续项)
- **`_bridge_sync_generator_to_async` 双实现合并**:game.py@57(`run_in_executor` + 裸 Exception
  透传 + `await fut` 不吞异常)vs chat_pipeline.py@1425(`asyncio.to_thread` + `_Error` 包装 +
  捕 BaseException + finally 吞 runner 异常)。**行为不等价**,合并方向建议以 chat_pipeline 版为准
  (兄弟方案将其落到 `chat_pipeline/bridge.py`),api_opening 切换过去前需对账
  BaseException 语义与 done 事件路径——独立任务,需人工对账,严禁机械合并。
- **Phase 2.5 世界书块迁入 chat_pipeline**:见 §6 api_chat 行,排在 chat_pipeline 包化之后。

---

## 8. 风险与回滚

| 风险 | 等级 | 缓解 |
|---|---|---|
| app.py 漏 include 新 router → 两端点 404 | 中(静默) | 批次 4 显式 TestClient 探活;前端 api-client.js 调这两个 URL,e2e 即暴露 |
| shim 行被执行代理写成 `import routes.chat_context`(非 from-import)| 低 | §5 批次 2 给出精确语句 |
| 与并行审计/兄弟方案撞文件 | 中 | 本方案触碰面 = game.py + app.py + 新文件;chat_pipeline.py **零触碰**(挂账项均后置),与 rpg__chat_pipeline.py.md 方案无文件交集,可独立先后落地 |
| 回滚 | — | 3 个文件、纯移动 + 2 行接线,单 commit 可整体 revert |

**结论**:needs-refactor / priority low / effort S。建议在并行审计窗口结束后、与 chat_pipeline
包化任一先后均可,独立落地;预计 30 分钟内完成(含全量测试)。
