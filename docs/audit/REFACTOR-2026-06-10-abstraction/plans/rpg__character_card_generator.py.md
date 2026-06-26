# rpg/character_card_generator.py — 函数抽象层体检

- **体检日期**: 2026-06-10
- **文件**: `rpg/character_card_generator.py`(799 行,21 个顶层定义)
- **结论 (verdict)**: **acceptable — 虽大但单一职责,不建议本轮拆分**
- **优先级**: low · 工作量评估: S(仅当执行文末"可选最小抽取"时)

---

## 1. 现状结构图

文件是 task 87/49 的"角色卡草稿生成"单一特性,模块 docstring 明确声明了 5 层管线设计,
代码用分节注释与之一一对应:

```
character_card_generator.py
│
├─ 模块头: docstring(5 层设计说明)+ _CARD_SCHEMA / _REQUIRED_FIELDS(纯数据常量)
│
├─ Public API(仅 2 个出口,均在 __all__)
│   ├─ generate_character_card_draft  @134  (34行)  入参清洗 → slice → retry 管线
│   └─ refine_character_card_draft    @170  (37行)  previous_draft+feedback → 同管线
│
├─ Layer 1 — 现实切片(DB 读,软降级)
│   ├─ _layer1_reality_slice          @214  (100行) 拉 NPC 名单/phase 样卡/worldbook/用户 PC 卡
│   ├─ _BASELINE_PHASE_TOKENS         @316  (空表,task 80 已去硬编码)
│   └─ _derive_other_phase_tokens     @323  (15行)
│
├─ Layer 2 — 生成(prompt 构建 + LLM 传输)
│   ├─ _build_system_prompt           @345  (41行)
│   ├─ _build_user_message            @388  (19行)
│   ├─ _call_llm_for_card             @409  (24行)  按 backend 分流 tool_use / JSON mode
│   ├─ _anthropic_emit_card           @435  (25行)
│   ├─ _select_backend                @462  (38行)  ★ 被 tools_dsl 跨模块复用(见 §3)
│   ├─ _resolve_preferred_model       @502  (19行)
│   ├─ _resolve_preferred_api         @523  (17行)
│   └─ _parse_json_safely             @542  (19行)
│
├─ Layer 3 — 5 个 validator
│   ├─ _run_validators                @568  (19行)  顺序聚合,无注册表/装饰器
│   ├─ _v_name_uniqueness             @589  / _v_phase_consistency @609
│   ├─ _v_cross_phase_tokens          @630  / _v_critic_score      @652(内部再调 _select_backend role="critic")
│   └─ _v_schema_completeness         @687
│
├─ Layer 4 — Retry 编排
│   ├─ MAX_RETRIES = 2                @711
│   └─ _generate_with_retry           @714  (58行)
│
└─ 尾部小工具: _flatten_validations @774 / _rebuild_brief_from_draft @782
```

Layer 5(不写 DB,只返回 candidate)是行为约定,无代码体。

## 2. 内聚簇分析 → 为什么判 acceptable

按概念可切出 5 个簇(schema+API / DB 切片 / prompt+LLM 传输 / validators / retry 编排),
**但这 5 个簇全部只服务同一条管线**,没有任何一簇被该特性以外的代码消费(唯一例外
`_select_backend`,见 §3)。判 acceptable 的具体依据:

1. **单一特性、层次自文档化**。docstring 的 Layer 1-5 与分节注释逐段对应,新人按头部
   说明顺读即可;不存在"两个不相干职责挤在一个文件"的混杂。
2. **函数粒度健康**。21 个顶层定义里 19 个 ≤ 41 行;唯一过百的 `_layer1_reality_slice`
   (100 行)是顺序数据采集 + 软降级 try/except,各段共享同一个 `slice_` 累积字典与同一个
   DB 连接上下文,拆成 `_fetch_npcs/_fetch_worldbook/...` 收益是化妆品级的(详见 §5)。
3. **测试与模块命名空间强耦合,拆分撞陷阱①的概率极高**。
   `rpg/tests/unit/test_character_card_generator.py` 全部 mock 都是
   `patch.object(ccg, ...)` 形式,且 **恰好打在任何拆分都必然要搬动的两个内部缝上**:
   `_layer1_reality_slice` 与 `_select_backend`(实查清单见 §4)。把这两个符号的
   *调用方*(`generate_character_card_draft`/`_call_llm_for_card`/`_v_critic_score`)搬去新模块后,
   即使原模块留 re-export,`patch.object(ccg, "_select_backend")` 也拦不到新模块内的解析——
   18 处 with 语句的测试语义全部失效,必须同步改写。799 行的体量撑不起这个改造成本。
4. **无巨型 God-file 信号**:无注册表、无装饰器注册、无模块级单例(仅常量 + logger)、
   无 `Path(__file__)`、无 import 副作用——所有重依赖(`platform_app.db`、`agents.gm`、
   `tools_dsl.command_tools_misc`、`core.llm_backend`)全部是**函数内惰性 import**,
   这是刻意的防环设计(§6)。

**复检触发线**:若该文件未来超过 ~1200 行、或 validator 需要插件化注册、或出现第二个
消费 Layer 1/3 的特性,再按 §7 备选布局拆分。

## 3. 真实存在的一处边界异味(与文件大小无关)

`rpg/tools_dsl/command_tools_creative.py:285` 跨模块导入**私有符号**:

```python
from character_card_generator import _select_backend   # 身份推荐工具复用 backend 选择
```

`_select_backend` + `_resolve_preferred_api` + `_resolve_preferred_model`(共约 115 行)
本质是"按 user_preferences 选 LLM backend"的通用逻辑,与角色卡特性无关,且已被第二个
特性消费——这是**消费方依赖私有 API** 的异味。修复属于可选低优先级,方案见 §8。

## 4. 测试 patch 点清单(Grep 实查)

唯一相关测试文件:`rpg/tests/unit/test_character_card_generator.py`
(`import character_card_generator as ccg`,无任何字符串式 `mock.patch("character_card_generator....")`,
全仓也无其他文件 patch 本模块)。

`patch.object(ccg, ...)` 字面出现 **10 处**,涉及 **2 个符号**:

| # | 行号 | 被 patch 符号 | 说明 |
|---|------|--------------|------|
| 1 | 92 | `_select_backend` | 在辅助函数 `_patch_backend()` 内定义,被 9 个测试复用(L130/151/165/184/202/218/237/287/317)|
| 2 | 128 | `_layer1_reality_slice` | 直接 with patch |
| 3 | 150 | `_layer1_reality_slice` | 同上 |
| 4 | 164 | `_layer1_reality_slice` | 同上 |
| 5 | 183 | `_layer1_reality_slice` | 同上 |
| 6 | 201 | `_layer1_reality_slice` | 同上 |
| 7 | 217 | `_layer1_reality_slice` | 同上 |
| 8 | 236 | `_layer1_reality_slice` | 同上 |
| 9 | 286 | `_layer1_reality_slice` | dispatcher 集成测试 |
| 10 | 316 | `_layer1_reality_slice` | dispatcher 集成测试 |

patch 生效的前提:这两个符号的**模块内调用点**
(`generate_character_card_draft` L163 / `refine_character_card_draft` L199 调
`_layer1_reality_slice`;`_call_llm_for_card` L413 / `_v_critic_score` L660 调
`_select_backend`)继续从 `character_card_generator` 模块全局命名空间解析。
任何把"调用方函数"搬出本模块的方案都会打破这一点。

### 模块的外部消费者(Grep 实查)

| 消费方 | 导入内容 |
|--------|----------|
| `rpg/tools_dsl/command_tools_persona.py` L166/L181 | `import character_card_generator as ccg`,调 2 个 public 函数(函数内惰性导入)|
| `rpg/tools_dsl/command_tools_creative.py` L285 | `from character_card_generator import _select_backend`(私有符号,函数内惰性导入)|
| `rpg/tests/unit/test_character_card_generator.py` | 模块整体 + 上表 patch 点 |

## 5. ≥80 行巨型函数评估

只有一个:`_layer1_reality_slice`(100 行)。
- 类型:顺序数据采集(权限闸 → 剧本 NPC → phase 样卡 → worldbook keys → 用户 PC 卡),
  非分支爆炸,非纯数据表。
- 判定:**不值得拆**。各段写入同一个累积字典、共享同一个 `with connect() as db:` 上下文与
  外层"任一失败整体软降级"的 try/except 语义;拆成 4 个子函数要么传 db 句柄+slice_ 字典
  到处走,要么每段各开连接,复杂度净增。且它是 10 个测试 patch 点之一,保持整函数边界
  对测试最友好。

`_generate_with_retry`(58 行,未达 80 线)是标准 retry 循环,结构清晰,不动。

## 6. 五大陷阱 + 环/副作用 核对(针对"如果拆"的任何方案)

| 陷阱 | 本文件的情况 |
|------|--------------|
| ① patch 命名空间穿透 | **致命项**。§4 的 10 处 patch 全是 `patch.object(模块, 符号)`;搬走 `_layer1_reality_slice`/`_select_backend` 的调用方即破坏全部 18 个测试用例。re-export shim 只救 import,救不了已搬走调用点的解析。 |
| ② Path(__file__) 错位 | 无风险:全文件无 `Path(`、无 `__file__`、无相对路径。 |
| ③ 执行代理顺手简化 | 若执行 §8 最小抽取:**逐字搬运 §8 清单中的 3 个函数,禁止改写函数体、签名、docstring、惰性 import 结构**。 |
| ④ 并行中间状态 | §8 仅 2 个批次且必须串行(先建新模块,后改消费方);同一文件不进两个批次。 |
| ⑤ 孤儿/死代码 | §8 明确:原模块**保留 re-export**(非孤儿);不删除任何文件。 |
| 循环导入 | 现状有一个**靠惰性 import 压制的潜在环**:`tools_dsl.command_tools_persona / command_tools_creative` →(函数内)`character_card_generator` →(函数内)`tools_dsl.command_tools_misc._user_can_read_script` 及 `agents.gm`。**任何改动都必须保持这些 import 留在函数体内**;若新模块把 `from agents.gm import ...` 提到模块级,而 `agents.gm` 又(直接或间接)import `core.llm_backend`,即成环。 |
| 模块级单例/副作用 | 无。常量 `_CARD_SCHEMA`/`_REQUIRED_FIELDS`/`_BASELINE_PHASE_TOKENS`/`MAX_RETRIES` + logger,导入零副作用;validator 是 `_run_validators` 里硬编码顺序调用,无注册表顺序问题。 |

## 7. 备选:若未来确需整体拆分(本轮不执行)

仅当触发 §2 复检线时启用。目标布局遵循本包"主题子包"惯例(参照 `tools_dsl/`、`agents/`):

```
rpg/character_card_gen/
├─ __init__.py        # re-export 全部旧符号(含 _ 前缀符号),保 import 兼容
├─ schema.py          # _CARD_SCHEMA, _REQUIRED_FIELDS
├─ reality_slice.py   # _layer1_reality_slice, _BASELINE_PHASE_TOKENS, _derive_other_phase_tokens
├─ prompts.py         # _build_system_prompt, _build_user_message, _rebuild_brief_from_draft
├─ llm.py             # _call_llm_for_card, _anthropic_emit_card, _parse_json_safely
├─ validators.py      # _run_validators, _v_*  (5 个)
└─ pipeline.py        # 2 个 public 函数, _generate_with_retry, _flatten_validations, MAX_RETRIES
rpg/character_card_generator.py   # 保留为纯 re-export shim(from character_card_gen import *)
```

强制配套(缺一不可):同批改写测试中 10 处 patch 点 →
`patch.object(pipeline, "_layer1_reality_slice")` 与 `patch.object(llm, "_select_backend")`
(注意 `_v_critic_score` 也调 `_select_backend`,validators.py 还要二次 patch 或统一经
`llm` 命名空间解析);批次必须串行:B1 建包并逐字搬运 → B2 shim + 改测试 → B3 跑
`pytest rpg/tests/unit/test_character_card_generator.py` 全绿。**当前收益撑不起此成本,故不做。**

## 8. 可选最小抽取(低优先级,修 §3 异味;非本轮必做)

**动机**:消除 `command_tools_creative` 对私有符号的跨模块依赖,而非缩文件。

- **新位置**:追加到现有 `rpg/core/llm_backend.py`(该模块已承载 `first_user_model`
  即用户模型选择逻辑,主题一致;不新建文件)。
- **搬运清单(逐字搬运,禁止改写逻辑)**:

| 符号 | 现位置 | 目标 |
|------|--------|------|
| `_select_backend` | character_card_generator.py @462 | core/llm_backend.py(可公开更名 `select_backend`,但须同时保留旧名别名)|
| `_resolve_preferred_model` | 同 @502 | core/llm_backend.py |
| `_resolve_preferred_api` | 同 @523 | core/llm_backend.py |

- **原模块 shim**:`character_card_generator.py` 在原位置替换为
  `from core.llm_backend import _select_backend, _resolve_preferred_api, _resolve_preferred_model`
  (模块级 re-export)。由于 `_call_llm_for_card` 与 `_v_critic_score` **留在原模块**且
  继续经原模块全局命名空间解析 `_select_backend`,测试的
  `patch.object(ccg, "_select_backend")`(§4 #1)**无需改动仍然生效**——这是该方案与
  §7 全拆方案的本质区别,也是它安全的原因。
- **消费方改造**:`command_tools_creative.py:285` 改为
  `from core.llm_backend import _select_backend`(仍函数内惰性导入)。
- **环检查**:搬运后 `core/llm_backend.py` 内的 `from agents.gm import ...` 必须保持在
  函数体内(`agents.gm` 反向依赖 core 的可能性高);`from platform_app.db import ...` 同理保持惰性。
- **串行批次**:B1 = core/llm_backend.py 追加 3 函数 + ccg 原位换 re-export;
  B2 = command_tools_creative 改 import;B3 = 跑
  `rpg/tests/unit/test_character_card_generator.py`(应零改动全绿)+ creative/persona 相关测试。
- **旧文件去向**:`character_card_generator.py` 保留(仍是特性主文件 + 3 个符号的 re-export),无孤儿。

## 9. 风险汇总

- 本轮结论是"不动",故无执行风险。
- 若执行 §8:风险集中在 (a) 惰性 import 被顺手提升到模块级造成 import 环;
  (b) 执行代理改写 `_select_backend` 的 GameMaster/`_AnthropicBackend`/`_VertexBackend`
  三级回退顺序。两者都已在清单中写死"逐字搬运 + import 留函数内"。
- 若执行 §7(不推荐):10 个 patch 点(18 个用例上下文)需同步改写,且
  `_select_backend` 在 llm.py 与 validators.py 两个新模块各有调用点,patch 命名空间
  必须双覆盖——这是该方案被否的主因。
