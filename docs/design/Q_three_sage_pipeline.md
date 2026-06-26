# Q — 三贤者流水线 + 环境描述符 + 分层缓存

状态:设计定稿,分阶段施工中。
关联:[[D_gm_serving]]、[[O_temporal_kb_unification]]、[[K_model_layer_and_image_gen]]。
适用三表面:游戏 GM(novel/module/freeform)、酒馆(tavern)、剧本编辑器(md-editor / console_assistant)。

---

## 0. 一句话

把「单体 GM(又胖又不缓存还自带 16 轮工具循环)」拆成 **司命 / 文宗 / 史官** 三贤者,
三者是**表面无关**的消费者;每个表面用一张**环境描述符**声明「填什么 / 谁出场 / 缓存到哪层」,
**没有任何「填什么」写死在某个表面里**。token 负担靠四个杠杆下降:分层缓存、砍工具循环、RAG 闸、后处理三合一。

---

## 1. 背景:token 烧在哪(实测口径)

单个玩家回合现状打 3–6 次 LLM,成本极度不均:

| 调用 | 时机 | 输入 | 性质 |
|---|---|---|---|
| context_agent(策展/curator) | 同步,挡住 GM | ~2k | 便宜 |
| **主 GM 叙事** | 同步流式,**工具循环 ≤16 轮重发全量** | **25–40k** | **唯一成本中心** |
| anchor_reconcile | GM 后同步 | ~4k | 便宜 |
| extractor | GM 后异步 | ~3k | 便宜 |
| acceptance_verifier | 后台 | ~3k | 便宜 |
| black_swan(可选) | 后台 | ~1.5k | 便宜 |

三个浪费点(全在主 GM 这根上):

1. **几乎不缓存**。30k 提示里只有 system+tools(~8k)走了 Anthropic `cache_control` / Vertex `cachedContent`。
   剩下 ~22k(人设、世界书、NPC 卡、锚点、RAG 原著、规则)**每回合、每个工具迭代全量重发重计费**。
   `context_engine/core.py:build_context_bundle` 产出**单坨扁平 prompt 字符串**进 user message,**零 cache 断点**。
2. **叙事 + 工具循环耦合在最贵的模型里**。`chat_pipeline.py:_gm_max_iters()`(默认 16)每轮重发增长的消息数组,
   现实 3–6 轮 = 3–6× 输入压在最贵模型上。
3. **RAG 永远全量灌**。`novel_retrieval` 上限 20000 字符(~10k token),纯对话回合也灌。

结论:问题不是「agent 太多」,是「最贵那根又胖、不缓存、带循环乘数」。

---

## 2. 设计目标

- G1 **token 负担量级下降**:主模型单回合从 ~70–140k 等效降到 ~6–10k 等效。
- G2 **环境驱动,非硬编码**:三表面共用同一上下文层 + 同一三贤者;「填什么」全在环境描述符。
- G3 **增量不推倒**:复用现有 ContextProvider 注册表 / GameMaster / extractor / anchor_reconcile;新增的只是
  `cache_tier` 元数据、分层产出、三贤者编排薄层、编辑器收编。
- G4 **优雅降级**:BYOK 中转站/OpenAI-compat 不支持缓存时,杠杆 2/3/4 仍生效。
- G5 **可回退**:每阶段 flag 控制,行为可对照。

---

## 3. 核心抽象:环境描述符(Environment Descriptor)

现状 `registry.py` 的 manifest **已经是半个环境描述符**:它驱动 `context_providers`(填什么)、
`gm_policy.mode`(选系统提示+工具过滤)、`retrieval_policy`。缺的是:**缓存层声明** 和 **三贤者声明**。

把 manifest 扩成完整描述符(向后兼容,旧字段不动,只加可选字段):

```jsonc
{
  "id": "script:123", "kind": "novel_adaptation",
  "context_providers": ["novel_retrieval", "novel_characters", ...],   // 既有:填什么
  "gm_policy": { "mode": "novel_gm", ... },                            // 既有:文宗人格+工具域
  "retrieval_policy": { ... },                                          // 既有
  // ── 新增(全可选,缺省由代码兜底)──
  "sages": {
    "planner":  { "enabled": true,  "rag_gate": true },               // 司命:是否跑、是否闸 RAG
    "narrator": { "tooling": "none" },                                 // 文宗:none|minimal|full(工具循环)
    "recorder": { "tasks": ["ops", "anchors", "acceptance"] }         // 史官:做哪几件
  }
}
```

三表面的 `sages` 声明(预期值):

| 表面 | planner | narrator.tooling | recorder.tasks |
|---|---|---|---|
| 游戏 GM(novel) | on, rag_gate | none(后期)/minimal(过渡) | ops + anchors + acceptance |
| 酒馆 | on, **rag_gate 仅绑剧本时** | none | **ops only**(砍掉现在白跑的 anchors) |
| 剧本编辑器 | on(解析编辑指令+选实体) | minimal(直写工具) | **写入 + canon 校验**(语义不同) |

**关键:三贤者代码一份,行为差异全在 `sages` 字段里 → 即「取决于环境」。**

---

## 4. 三贤者(surface-agnostic)

```
环境  ─→ 司命(Planner,便宜小模型)
描述符   读:玩家/作者输入 + 状态摘要 + 最近 1–2 拍
        出:回合计划(意图 / 要不要检索+查询 / 下一拍 / 激活工具子集)
        合并现有 context_agent(curator) + worldbook 决策。拥有 Tier C + RAG 闸。
     ─→ 文宗(Narrator,贵模型,单次,默认不带工具循环)
        吃:缓存命中的 Tier A+B 前缀 + 司命挑出的瘦 Tier C + 输入
        戴 narrator_persona(gm / tavern_char / editor)→ 只产文(或编辑器直写内容)
        需要的事实由司命预取注入,不自己调 KB 工具(符合 harness 确定性铁律)。
     ─→ 史官(Recorder,便宜模型,单次结构化)
        读:文宗产出。按 recorder.tasks 一次吐:state ops [+ 锚点命中] [+ 验收]
        合并现有 extractor + anchor_reconcile + acceptance_verifier 三个分开调用。
```

角色泛化、任务按环境变。史官在编辑器里做的是「落实体写入 + canon 一致性校验」,语义不同——这是环境驱动的体现,不是 bug。

---

## 5. 分层缓存(cache_tier 分类法)—— G1 命脉

给每个 context 层打 `cache_tier ∈ {A, B, C}`,`build_context_bundle` 由「一坨扁平 prompt」改为**按层分段产出**,
后端在 A、B 段尾各打一个 `cache_control` 断点。

| Tier | 含义 | 缓存命中条件 | 成员(层 id) |
|---|---|---|---|
| **A** 会话级稳定 | 整存档不变(改人设/换剧本/改设定才变) | **逐回合字节恒等 → 真命中** | system+tools(已缓存)、`rules`、`agent_runtime`、`player_card`、`state_schema`、(酒馆)`tavern_card_system`/`tavern_character`/`tavern_persona` |
| **B** 场景级稳定 | 一幕戏内稳定,换场/换章才变 | 取决于「内容激活」是否被场景化(后期 Phase B) | `npc_cards`、`novel_worldbook`、`anchor_pending`、`script_phase_anticipation` |
| **C** 回合动态 | 每回合变 | 永不缓存 | `state`、`fact_groups`、`memory`、`write_results`、`hypotheses`、`context_agent`、`candidate_actions`、`novel_retrieval`(RAG)、`recent_chat`、`timeline_pending`、`user_input` |

**诚实边界**:
- Tier A 逐回合字节恒等 → Anthropic/Vertex **真命中**,这是 Phase 1 能立刻拿到的稳定收益(~2–4k 可靠缓存)。
- Tier B 现在是「按扫词激活」→ 逐回合可能变 → 命中不稳。**给它打断点是免费的**(命中就赚、不中就退化成全价),
  真正让 B 稳定命中要靠 Phase B 把 NPC/世界书**按场景一次性装载**(司命管场景态),那是后续阶段。
- 不要把 RAG 放进可缓存层:查询逐回合变。靠 Phase 3 司命 RAG 闸**减量**,不是靠缓存。

断点放置(每个后端):
- Anthropic:user 消息内容拆成多个 text block,在 A 段尾、B 段尾各挂 `cache_control:{type:ephemeral}`(最多 4 个断点,system+tools 已占 1–2,余量够)。
- Vertex:explicit `cachedContent` 现仅含 system+tools;A 段并入 cachedContent 的可行性 Phase 2 评估(Vertex cache 粒度粗,先保 system+tools)。
- OpenAI-compat / DeepSeek 等:多数中转站不支持显式断点,但 **DeepSeek 原生支持自动前缀缓存**(prompt 前缀命中自动 0.1×),
  Tier A 前置后**自动受益**,无需断点 API。其余不支持的:靠杠杆 2/3/4 降总量。

---

## 6. 接线改造点(具体 delta,文件级)

1. `context_providers/base.py`:`make_layer` + `ContextContribution` 加可选 `cache_tier`(默认 "C")。
2. `context_engine/_constants.py`:加 `LAYER_CACHE_TIER`(层 id → A/B/C 映射),通用层用它,provider 层可被 contribution 覆盖。
3. `context_engine/core.py:build_context_bundle`:
   - 每层带上 cache_tier;
   - 产出新增 `prompt_segments: [{tier, title?, text}]`(A→B→C,段内仍按 priority 降序);
   - `prompt`(扁平)仍返回 = 三段拼接,**向后兼容**所有现有读取方;
   - flag `RPG_CTX_TIERED`(默认 on)控制是否启用分段;off 时退回纯 priority 排序。
4. `agents/gm/master.py` + backends:`_turn_message()` 改为优先用 `prompt_segments` 构造**多 block user 消息**;
   后端 `stream()/stream_with_tools` 接受可选 `user_blocks`,Anthropic 在 A/B 段尾挂 `cache_control`。
   无 segments 时退回单 block(现状)。
5. **史官合并**(Phase 2):新增 `agents/recorder.py`,把 extractor+anchor_reconcile+acceptance 的三个 schema 合一,
   `chat_pipeline` 的 `_run_post_gm_parallel` 改调单次史官;按 `recorder.tasks` 裁剪。
6. **司命 RAG 闸**(Phase 3):curator 输出加 `retrieval_decision{need:bool, query, budget}`;
   `NovelRetrievalProvider` 读它,need=false 直接 skip。
7. **文宗去工具循环**(Phase 4):`narrator.tooling=none` 时 GM 单次纯文;司命预取必要 KB 事实注入 Tier C;
   写操作全交史官。`minimal` 为过渡(保留极小工具集)。
8. **编辑器收编**(Phase 5):`console_assistant/editor_context.py` 的世界书/卡/canon/时间线手拼块**重写成 ContextProvider**,
   定义 `editor` 环境描述符;`prompts.py` 硬编码块退役;复用同一分层缓存 + 三贤者。
9. **前端**(Phase 6):上下文用量/缓存命中可视化(/api/chat/context-breakdown 已有 cache_plan,补真实命中率),
   设置页三贤者模型选择器收口(复用 AgentModelPicker prefPrefix:planner/narrator/recorder),用 **frontend-design skill**。

---

## 7. 分阶段实施 + e2e 闸(每阶段 curl 验证后才进下一阶段)

| Phase | 内容 | 风险 | e2e 验收(curl) |
|---|---|---|---|
| **1** | cache_tier 元数据 + 分层产出 + 后端 A/B 断点 | 低(行为保持,只重排+加断点) | 一回合正常出文;prompt_segments 结构正确;Anthropic 路径含 cache_control;DeepSeek 路径前缀稳定;输出与关闭 flag 对照无质变 |
| **2** | 史官三合一 | 中(合并 schema) | ops/锚点/验收结果与拆分版一致;后处理调用数 3→1 |
| **3** | 司命 RAG 闸 | 中 | 纯对话回合 retrieval skip;查询回合正常检索;无事实缺失 |
| **4** | 文宗去工具循环 | **高**(行为变) | 状态写入不丢(史官兜底);散文不缺事实(司命预取);token 大降实测 |
| **5** | 编辑器收编 provider | 中 | md-editor 右栏 AI 直写正常;走注册表;防剧透截断保持 |
| **6** | 前端可视化 + 模型选择器 | 低 | UI 正常;切模型持久化;用量面板显示真实缓存比 |

阶段 1–3 行为保持/近似保持,可单独上线;阶段 4 是唯一大行为变更,单独充分 e2e。

---

## 8. 风险与回退

- **重排影响输出质量**:Tier 分段改变层顺序(state 后移等)。`RPG_CTX_TIERED` flag 可即时退回纯 priority。e2e 对照。
- **文宗预取不准**(Phase 4):散文缺事实。缓解=司命预取 + 保留 `minimal` 过渡档 + 史官事后补写。
- **缓存命中假象**:命中率以厂商返回 usage 字段为准(Anthropic `cache_read_input_tokens`),不靠估算。
- **编辑器语义错位**:史官在编辑器是「写+校」,与游戏的「抽 ops」不同 schema。环境描述符 `recorder.tasks` 区分,不强行统一。
- **并行中间态**:严格串行分阶段,每阶段独立可编译可 e2e,不留孤儿/半接线(refactor traps 铁律)。

---

## 附:测试基建(本机)

- 本机后端常驻 127.0.0.1:7860(uvicorn),DB 健康;curl 直测。
- 测试 LLM:DeepSeek key(BYOK),base_url `https://api.deepseek.com/v1`,模型 `deepseek-v4-flash`(司命/史官)/`deepseek-v4-pro`(文宗)。
- DeepSeek 原生前缀缓存 → Tier A 前置即受益,适合验缓存效果。
