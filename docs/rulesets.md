# 规则集扩展指南 / Ruleset Extension Guide

本文是给想新增游戏规则系统(如 D&D 5E、Call of Cthulhu 7E、PbtA 等)的贡献者的
架构约定。先读完再动手,能避免被退回。

> TL;DR:**规则用 Python、内容用 JSON;规则集走自注册注册表,不改核心;不要把规则引擎
> 做成 MCP。**

---

## 1. 三层分工(别越界)

| 层 | 放什么 | 形态 | 例子 |
|---|---|---|---|
| **内容 / Modules** | 剧本、房间、NPC、世界书、开场 | **纯 JSON/Markdown 数据**,走通用 loader,**零代码** | `rpg/modules/<name>/{module.json,rooms.json,npcs.json,worldbook.json,opening.md}` |
| **规则引擎 / Rules** | 检定、战斗、伤害、状态、骰子数学 | **Python**,实现规则接口 | `rpg/rules/<ruleset>/` |
| **核心 / Core** | 调度、上下文装配、存档 | **规则集无关**,不得出现 `if ruleset == "X"` | `rpg/rules_bridge/`、`rpg/context_providers/` |

新增一个规则系统 = 新增一个 `rpg/rules/<ruleset>/` 包 + (可选)若干数据模组。
**不应该改核心文件。** 如果你发现必须改 `rules_bridge`、`context_providers`、
`rules/engine.py` 才能让你的规则集生效,说明扩展点还没做好——请在 issue 里提出,
而不是往核心里加 `if/elif` 分支。

---

## 2. 规则集 = 自注册注册表(目标架构)

规则集应通过**注册表自注册**,核心按存档的 `ruleset_id` 查表拿到对应引擎:

- 规则集包在 import 时把自己登记进注册表:`{ruleset_id -> engine factory}`。
- 核心 `get_engine(ruleset_id)` 从注册表解析,并**按 id 缓存**(不是单例),
  这样多 worker / 多规则集并发不会互相覆盖。
- 角色卡的展示交给规则集自带的 **display hook**(如 `engine.character_summary(pc)`),
  核心的 context provider 只调这个 hook,不关心是哪套规则。

> 现状提示:当前 `rpg/rules/engine.py` 仍是面向 dnd5e 的 facade(`dnd5e/` 是一组纯函数),
> 注册表是**约定的方向**。新增规则集请按上面的接口写,核心的注册表 seam 会配合补齐;
> **不要**用硬编码分支临时接通。

### 必做的正确性检查
- **运行时派发要接通**:实际游戏的检定/战斗在 `rpg/rules_bridge/`(`checks.py`、
  `combat.py`)里发生,它们必须按**当前存档的 ruleset** 取引擎,而不是默认 dnd5e。
  只在「建角色」时选对引擎是不够的——那样检定仍会跑成 dnd5e 的 d20-vs-DC。
- **确定性状态要真的落库**:像 CoC 的 San 损失这类机制,必须由确定性规则层
  写入状态(经 `rules_bridge` 的候选动作),不能只写在模组文案里让 LLM 口述
  ——否则违背平台「GM 不可绕过确定性规则结果」的保证(见 `game_policy`)。
- **集成测试,不只单测**:单测直接调 `get_engine("<id>")` 测引擎容易全绿却掩盖
  派发没接通。请至少补一个走 `rules_bridge → module → save` 的集成测试,证明
  你的规则集真的产出该系统的判定(例:CoC 检定确实是 d100 roll-under)。

### 骰子 / RNG 规范
- 用 `rpg/rules/dice.py` 的封装(已做边界保护:`count<=100`、`sides<=1000`)。
- **不要 `random.seed()`** 去动进程全局 RNG(并发污染);需要可复现就用独立的
  `random.Random(seed)` 实例。
- 多次掷骰(命中 / 伤害 / 加值)要相互独立,别复用同一个 seed。

---

## 3. 为什么不用 MCP 承载规则集

平台有成熟的 MCP 集成(`rpg/mcp_broker.py`),但**规则集不适合做成 MCP**:

- **规则引擎是同步、逐回合、微秒级的 in-process 调用**(每回合可能多次)。MCP 会引入
  网络/子进程往返、`server 必须在线`的可用性依赖、30s 超时,并削弱「确定性、低延迟、
  始终可用、GM 不可绕过」的规则契约。
- **上下文 provider 是 prompt 装配,不是 tool 调用**。MCP broker 只暴露 tools,
  **不实现** prompts/resources,无法注入 GM prompt 上下文。
- **模组是纯数据**,本就可插拔,和规则集/MCP 正交。

**MCP 留给外部 / 可选工具**(联网查询、第三方集成),不要用来做同步规则核。

## 4. 为什么不用 JSON-DSL 写规则

声明式 JSON 规则看着可移植,但 d100 成功档、对抗 POW、San 表、伤害加值骰、再生
这类控制流,JSON 得长出一个解释器 = 重新引入本仓刻意避开的 eval 类执行面。
**内容用 JSON(模组),规则用 Python(注册表),保持一套模型。**

---

## 5. 提交清单(Checklist)

- [ ] 规则放在 `rpg/rules/<ruleset>/`,实现规则接口;**未改核心 `if ruleset` 分支**
- [ ] 规则集自注册到注册表,`get_engine` 按 id 解析 + 缓存
- [ ] 角色展示走规则集的 display hook,核心 context provider 保持规则集无关
- [ ] `rules_bridge` 检定/战斗按存档 ruleset 派发(已验证产出本系统判定)
- [ ] 确定性机制(如 San)真正落库,不依赖 LLM 口述
- [ ] 骰子用 `dice.py`,无全局 `random.seed()`,多次掷骰独立
- [ ] 有走 `rules_bridge → module → save` 的**集成测试**,不只引擎单测
- [ ] (可选)配套数据模组放 `rpg/modules/<name>/`,纯 JSON/Markdown
