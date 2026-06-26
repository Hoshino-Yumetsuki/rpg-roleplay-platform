# 拆分方案:rpg/agents/gm/master.py(889 行)

- **判定**:needs-refactor(轻量级,prompt 数据与编排逻辑混居;核心类本身内聚)
- **优先级**:low(纯可维护性,无正确性问题;该文件是聊天热路径,动它要挑安静窗口)
- **工作量**:S(批次 1 单独可完成)~ M(含批次 2)
- **日期**:2026-06-10 · 审计工作流产物,未做任何源码改动

---

## 1. 现状结构图

```
rpg/agents/gm/master.py (889 行)
├─ 模块头 (L1-15)
│   ├─ import: backends(_AnthropicBackend/_OpenAICompatBackend/_VertexBackend), helpers
│   └─ BASE = Path(__file__).parent.parent.parent        ← ⚠️ Path(__file__),勿动
├─ _WORLD 加载 (L17-23)  ← import 副作用:读 rpg/indexes/world.json
├─ Prompt 模板常量 (L25-318, ≈293 行 ≈ 全文件 33%)
│   ├─ _SYSTEM_BASE          (L26-249, 224 行) — 通用 GM system prompt
│   ├─ _SYSTEM_TAVERN        (L255-282) — 酒馆模式角色扮演 system
│   ├─ _SYSTEM_TAVERN_BOOTSTRAP (L288-291) — 酒馆空起手自举
│   ├─ _DYNAMIC_CONTEXT      (L293-299) — 动态上下文壳模板
│   └─ _OPENING_PROMPT       (L301-318) — 开场白指令
└─ class GameMaster (L324-888, 565 行)
    ├─ __init__ (45)                    — backend 选型路由(catalog/kind/中转站降级)
    ├─ ── system prompt 装配簇 ──
    │   ├─ _build_system (57)           — 通用/酒馆/自举三分支 + style_block 渲染
    │   ├─ _active_script_id (34)       — content_pack.id / save_id→DB 兜底
    │   ├─ _world_section_for_active_content (34) — worldbook_entries 高优先级注入
    │   ├─ _world_section_berlin_fallback (30)    — 经 sys.modules["agents.gm"]._WORLD 读
    │   ├─ _ORIGIN_NOTES (类属性, 24 行) — 出身 4 档机制模板(纯数据表)
    │   ├─ _resolve_player_origin (20)
    │   ├─ _dynamic_context (17)
    │   └─ _turn_message (5)
    ├─ ── LLM 调用门面簇 ──
    │   ├─ curate_context (20)          — 子代理结构化调用(native tool_use / JSON mode)
    │   ├─ generate_opening (5) / generate_opening_stream (8)
    │   └─ respond (6) / respond_stream (6)
    └─ ── MCP 工具循环簇 ──
        ├─ respond_stream_with_tools (186) — text-marker 流式状态机 + token 记账
        └─ _respond_stream_native_tools (44) — native 路径 dispatcher
```

包既有惯例(平铺模块 + backends/ 子包):

```
rpg/agents/gm/
├─ __init__.py      — re-export: GameMaster, 三 backend, _WORLD
├─ master.py        — 本文件
├─ helpers.py       — _format_tools_for_prompt / _anthropic_curator_tool_use / _openai_text_marker_loop
├─ style_harness.py — 叙事风格 6 维旋钮渲染
├─ style_config.py  — 三层 profile 解析
└─ backends/        — anthropic.py / vertex.py / openai_compat.py / _effort.py
```

## 2. 内聚簇分析

| 簇 | 行数 | 内聚性 | 处置 |
|---|---|---|---|
| A. Prompt 模板常量(5 个字符串 + `_ORIGIN_NOTES`) | ≈317 | 纯数据,与逻辑零耦合;历史上被 task 131/133/136 反复独立编辑 | **搬出 → prompts.py** |
| B. `_WORLD` 加载 + `BASE` | 9 | import 副作用 + 测试 monkeypatch 契约挂在 `agents.gm._WORLD` 包属性上 | **原地不动** |
| C. backend 选型 `__init__` | 45 | 单一职责,引用 model_registry/user_credentials | 原地不动 |
| D. system prompt 装配簇(8 个方法) | ≈220 | 互相调用紧密;`test_gm_active_script_id.py` 以**未绑定方法** `GameMaster._active_script_id(fake_self)` 直接调用 | 原地不动(若将来要拆,只能用 mixin 继承保住类属性,收益低) |
| E. LLM 调用门面(respond/opening/curate) | ≈45 | 5-20 行薄壳 | 原地不动 |
| F. text-marker 工具循环(`respond_stream_with_tools` 后半) | ≈122 | **与 helpers.py `_openai_text_marker_loop`(L108-203)是 ~95% 重复的双胞胎状态机**(差异:stop_event 支持、last_context token 记账、错误文案、mcp_call 内联 import) | 批次 2 可选搬出;长期应与孪生函数合一(非机械改动,另立任务) |
| G. `_respond_stream_native_tools` | 44 | 纯 dispatcher,逻辑都在 backend.stream_with_mcp_loop | 原地不动 |

**巨型函数评估**:
- `respond_stream_with_tools`(186 行)= 流水线型(准备段 L681-718 → 状态机循环 L720-842)。值得拆,但**只能在"准备段 / 循环体"这一条天然缝上切**;状态机内部(buffer/in_tool/tail_keep)不可再分段,strawman 式拆成多个阶段函数反而毁掉它经 task 61/66 修过的边界语义。
- `_SYSTEM_BASE`(224 行字符串)= 纯数据,不拆内部,整体搬走即可。
- `__init__`(45)/`_build_system`(57)低于阈值且各自单一职责,不拆。

## 3. 目标布局

```
rpg/agents/gm/
├─ prompts.py        ← 新建(批次 1)。纯常量,零 import 依赖(只需模块 docstring)
│     _SYSTEM_BASE / _SYSTEM_TAVERN / _SYSTEM_TAVERN_BOOTSTRAP
│     _DYNAMIC_CONTEXT / _OPENING_PROMPT / _ORIGIN_NOTES
│     (≈330 行)
├─ helpers.py        ← 批次 2(可选)增量:+ _gm_text_marker_loop(原 respond_stream_with_tools 循环体逐字搬入)
│     (203 → ≈330 行)
└─ master.py         ← 保留 GameMaster + _WORLD 加载 + re-export shim
      批次 1 后 ≈580 行;批次 1+2 后 ≈460 行
```

## 4. 可机械执行的搬运清单(逐字搬运、禁止改写逻辑)

### 批次 1:prompts.py(独立可交付,推荐必做)

| # | 符号 | 源位置(master.py) | 目标 | 动作 |
|---|---|---|---|---|
| 1 | `_SYSTEM_BASE` | L26-249 | prompts.py | 逐字剪切 |
| 2 | `_SYSTEM_TAVERN` | L251-282(含前导注释) | prompts.py | 逐字剪切 |
| 3 | `_SYSTEM_TAVERN_BOOTSTRAP` | L284-291(含前导注释) | prompts.py | 逐字剪切 |
| 4 | `_DYNAMIC_CONTEXT` | L293-299 | prompts.py | 逐字剪切 |
| 5 | `_OPENING_PROMPT` | L301-318 | prompts.py | 逐字剪切 |
| 6 | `_ORIGIN_NOTES` dict 字面量 | L531-557(类属性) | prompts.py 模块常量 `_ORIGIN_NOTES` | 逐字剪切 dict 字面量(含 L531-533 注释) |
| 7 | master.py 顶部加 | — | — | `from agents.gm.prompts import (_DYNAMIC_CONTEXT, _OPENING_PROMPT, _ORIGIN_NOTES, _SYSTEM_BASE, _SYSTEM_TAVERN, _SYSTEM_TAVERN_BOOTSTRAP)  # noqa: F401 — re-export shim,测试经 agents.gm.master 访问` |
| 8 | GameMaster 类内原 `_ORIGIN_NOTES` 位置 | L534 | — | 替换为类属性别名 `_ORIGIN_NOTES = _ORIGIN_NOTES`(保住 `self._ORIGIN_NOTES` / `GameMaster._ORIGIN_NOTES` 访问路径,语义零变) |

**明确不搬**(留在 master.py):`BASE`、`_WORLD_FILE`、`_WORLD` 及其 try/except 加载块(L15-23)——理由见 §6 陷阱②/单例。

### 批次 2(可选):text-marker 循环抽出

| # | 符号 | 源位置 | 目标 | 动作 |
|---|---|---|---|---|
| 9 | `respond_stream_with_tools` 的循环体 L720-842(自 `START = "<<TOOL_CALL>>"` 起至 max_iterations 收尾 yield 止) | master.py | helpers.py 新增 `def _gm_text_marker_loop(backend, system, messages, max_iterations, max_tokens, stop_event) -> Iterator[dict[str, Any]]` | 逐字剪切;`self._backend.stream(...)` 改 `backend.stream(...)` 共 1 处,`return`/`yield` 语义不变;循环内 `from mcp_broker import call_tool as _mcp_call_tool`(L789)**原样保留在函数体内**(惰性 import,避免 helpers→mcp_broker 顶层依赖) |
| 10 | master.py `respond_stream_with_tools` 残段 | L681-718 保留 | — | 末尾改为 `yield from _gm_text_marker_loop(self._backend, system, messages, max_iterations, max_tokens, stop_event)`;并在 master 顶部 helpers import 行追加该名字 |

注意:**不要**顺手把它与 helpers.`_openai_text_marker_loop` 合并——两者差异(stop_event、错误文案长短、记账)是真实行为差异,合并属于行为级重构,须单独立项带回归测试,不属于本机械搬运范围。

## 5. patch 点清单(Grep 实查,2026-06-10)

受影响(依赖 master.py 自身命名空间或包 re-export,共 **4** 处,本方案下**全部零改动**):

| # | 文件:行 | 形式 | 本方案下的保障 |
|---|---|---|---|
| 1 | `rpg/tests/unit/test_gm_style_harness.py:72` | `from agents.gm.master import _SYSTEM_BASE` | 批次 1 第 7 步 re-export shim 保住 |
| 2 | `rpg/tests/unit/test_gm_active_script_id.py:10` | `from agents.gm.master import GameMaster` + 未绑定调用 `GameMaster._active_script_id(fake_self)` | GameMaster 不搬家,装配簇方法留在类内 |
| 3 | `rpg/tests/integration/test_rules_chat_pipeline.py:292-324` | `import agents.gm as gm_mod; gm_mod._WORLD = {...}`(包属性热替换) | `_WORLD` 不搬家;`_world_section_berlin_fallback` 经 `sys.modules.get("agents.gm")._WORLD` 的动态读路径不动;`__init__.py` 不动 |
| 4 | `rpg/tests/test_vertex_user_sa.py:169` | `patch("agents.gm.GameMaster", ...)` | 依赖 `__init__.py` re-export,不动 |

确认不受影响(列出以备查):
- `rpg/tests/test_vertex_user_sa.py:99` — `patch("agents.gm.backends.vertex.load_sa_credentials")`(backends 子包,本方案不触)
- `rpg/tests/integration/test_sub_agent_separation.py:79` — `patch("app.GameMaster")`(app 命名空间)
- `rpg/tests/integration/test_import_pipeline_model_resolution.py:51-52` — 用 `types.ModuleType("agents.gm")` 整包替换 sys.modules,内部布局无关
- 生产侧直连 master 的 import:`rpg/extract/llm.py:57`、入口们均 `from agents.gm import GameMaster`(包级),不受影响
- `rpg/claude_design_upload/current_code/gm.py` — 冻结上传副本,含同名 `_SYSTEM_BASE` 等,**不是**本模块,勿误改

## 6. 五大陷阱逐项核对

1. **patch 命名空间穿透**:见 §5,4 个受影响点全部由「master.py 留 re-export shim + `_WORLD`/GameMaster 不搬家」覆盖,无需改任何测试。
2. **Path(__file__) 错位**:全文件仅 1 处 — L15 `BASE = Path(__file__).parent.parent.parent`(gm/ 上跳三级到 rpg/)。本方案**不搬它**;搬运的 prompt 常量与循环体内无任何 `__file__`/相对路径(已逐处核过)。若将来有人把 `_WORLD` 加载挪去 gm/ 之外的目录,BASE 会指错根 — 方案明令禁止。
3. **执行代理顺手简化**:§4 清单逐符号给出源行号与目标;执行时**逐字剪切粘贴**,唯一允许的文本差异是批次 2 第 9 步标注的 `self._backend`→`backend` 一处替换;`_SYSTEM_BASE` 内的字面 JSON 大括号绝不可过 `str.format()`(原文件 L422-423 注释已警告,搬运后该注释随 `_build_system` 留在 master)。
4. **并行中间状态**:批次 1(动 master.py + 新建 prompts.py)与批次 2(动 master.py + helpers.py)**都触 master.py,必须串行**:批次 1 → 跑测试 → 批次 2。且当前另有审计工作流并行读源码,本方案仅为文档,执行须等该工作流结束。
5. **孤儿文件/死代码**:master.py **保留**,角色 = GameMaster 宿主 + `_WORLD` 加载 + prompt 常量 re-export shim(shim 行加 `# noqa: F401` 注释说明测试契约);不删除任何文件;`agents/gm/__init__.py` 一字不改。

**循环导入核查**:prompts.py 零依赖(纯字符串/dict)→ 无环;helpers.py 批次 2 不新增顶层 import(mcp_broker 维持函数体内惰性 import)→ 无环;master 新增 `import prompts` 单向。`__init__ → backends → (无 master)`、`__init__ → master → prompts/helpers` 拓扑仍是 DAG。

**模块级单例 / import 副作用**:`_WORLD` 在 import 时读 world.json(FileNotFoundError 容错)——保持留在 master.py,且 `agents.gm.__init__` 的 `from agents.gm.master import _WORLD` 不变,import 顺序与副作用时点零变化。本文件无装饰器注册表。

## 7. 验证步骤(执行批次后)

```bash
# 包内全量编译
python -m py_compile rpg/agents/gm/*.py
# 直接受影响的测试(见 §5)
pytest rpg/tests/unit/test_gm_style_harness.py rpg/tests/unit/test_gm_active_script_id.py \
       rpg/tests/unit/test_gm_tool_use.py rpg/tests/integration/test_rules_chat_pipeline.py \
       rpg/tests/test_vertex_user_sa.py -x -q
# 热路径冒烟:chat_pipeline import 链
python -c "import sys; sys.path.insert(0,'rpg'); from agents.gm import GameMaster, _WORLD; from agents.gm.master import _SYSTEM_BASE; print(len(_SYSTEM_BASE), type(_WORLD))"
```

## 8. 残留观察(不属本方案,供后续立项)

- helpers.`_openai_text_marker_loop` 与 `respond_stream_with_tools` 循环体的双胞胎重复:批次 2 完成后两者同居 helpers.py,差异一目了然,适合再立一个**带回归测试**的合并任务(统一 stop_event 与错误文案后删一个)。
- `_SYSTEM_BASE` 224 行单字符串若继续膨胀,可在 prompts.py 内按段落拆成具名片段再拼接——属内容重构,与本次机械搬运分离。
