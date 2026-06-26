# 体检报告:rpg/tools_dsl/command_tools_anchors.py(903 行)

- 审计日期:2026-06-10
- 审计范围:函数抽象层体检 + 拆分方案评估
- **结论(verdict):acceptable — 虽大但围绕单一状态机,不建议现在拆**
- 优先级:low(给出条件性触发器,涨破阈值再拆)
- 预估工作量:S(现状无需动作;条件性方案若执行约 M)

---

## 1. 现状结构图

```
command_tools_anchors.py (903 行) — task 136 世界线收束机制 · GM 工具
│
├─ 模块头 (1–22)
│   ├─ 顶层 import: json + tools_dsl.command_dispatcher(ToolSpec, get_registry)
│   └─ _ANCHOR_READ_ORIGINS / _ANCHOR_MUTATE_ORIGINS(frozenset 常量)
│
├─ 共享 helper
│   └─ _own_save(db, save_id, user_id)            6 行 @29   — save 归属安全围栏,9 个 executor 全用
│
├─ 簇 A:剧本锚点(canon 未来锚点,世界线收束)
│   ├─ _t_list_pending_anchors                   61 行 @37   — 委托 agents.anchor_seed_agent 读
│   ├─ _t_mark_anchor_satisfied                 108 行 @100  — 写 save_anchor_states(status/drift)+ 级联 advance_progress
│   ├─ _t_mark_anchor_superseded                 68 行 @210  — 写 save_anchor_states(is_fatal 拒绝闸)
│   └─ _t_summarize_anchors                      19 行 @431  — 委托 agents.anchor_seed_agent 汇总
│
├─ 簇 B:存档独立时间线(玩家创造的历史锚点)
│   ├─ _t_record_history_anchor                  87 行 @280  — 委托 agents.save_history 写 + 级联写簇 A 表
│   ├─ _t_check_pending_anchor_drift             28 行 @369  — 委托 agents.save_history 反查 pending↔history
│   └─ _t_list_recent_history                    30 行 @399  — 委托 agents.save_history 读
│
├─ 簇 C:主角 POV 身份覆盖
│   ├─ _t_claim_protagonist_pov                 104 行 @457  — 写 save_anchor_states + game_saves.state_snapshot
│   └─ _t_revoke_protagonist_pov                 80 行 @563  — claim 的镜像逆操作(按 variant_description 签名反查)
│
└─ 声明式注册
    └─ register_anchor_tools                    255 行 @645  — 9 个 ToolSpec(描述/JSON Schema/示例),registry.has 幂等闸
    __all__ = ["register_anchor_tools"]
```

包内同族文件(平铺惯例 `command_tools_<family>.py`,均为「executors + register_<family>_tools」结构,**无** `_mixins/`、`api/` 之类子包先例):misc 706 行、saves 686 行、tavern 632 行、command_tools 591 行。本文件 903 行是族内最大,但同量级。

## 2. 谁在引用(Grep 实查,全量)

| 引用方 | 行号 | 引用方式 | 拆分时的影响 |
|---|---|---|---|
| `rpg/tools_dsl/command_tools_register.py` | 346–347 | 函数内懒 import `register_anchor_tools` 并调用 | re-export / 聚合函数可兜,**可不改** |
| `rpg/tests/unit/test_tavern_tool_user_fencing.py` | 170 | 函数内 `from tools_dsl.command_tools_anchors import _t_record_history_anchor` | re-export shim 可兜 |
| 同上 | 175 | 同上 import `_t_list_recent_history` | re-export shim 可兜 |
| 同上 | 180 | 同上 import `_t_check_pending_anchor_drift` | re-export shim 可兜 |
| `rpg/tests/unit/test_anchor_pov_and_progress_fixes.py` | 11(被 24/25 消费) | **源码文本依赖**:`read_text` 硬编码 `tools_dsl/command_tools_anchors.py` 路径,按 `def _t_claim_protagonist_pov(` / `def _t_revoke_protagonist_pov(` 字符串切函数体断言内容 | **re-export shim 救不了**。若把 claim/revoke 搬走,必须同步改该测试第 11 行的文件路径 |

**受影响测试 patch 点合计:4**(3 个直接 import + 1 个源码文本路径)。

额外确认(五陷阱逐项核查,均 Grep/精读实查):

1. **patch 命名空间穿透**:`grep "patch(" rpg/tests | grep -i anchor` → **0 命中**。没有任何 `mock.patch("tools_dsl.command_tools_anchors.*")`。且本模块对 `platform_app.db` / `agents.anchor_seed_agent` / `agents.save_history` / `gm_serving.settings` / `_get_sync_scope_lock` 的依赖**全部是函数内懒 import**——外部测试 patch 这些源模块时不经过本模块命名空间,搬运不破坏它们。唯一的坑是上表第 5 行的**源码文本依赖**,比 patch 更刁:它断言的是函数体的字面源码(含 `"代入 {name} 的 POV 位置"` 签名、SELECT 块里不得出现 `首次登场`),搬运必须逐字、且测试路径必须同步指向新文件。
2. **Path(__file__) 错位**:本文件 **0 处**(Grep 实查 exit 1)。无相对路径读取。
3. **顺手简化风险**:`_t_mark_anchor_satisfied` 与 `_t_record_history_anchor` 各自内联了一份 `drift >= 0.15 → variant` 规则、claim/revoke 靠字面签名字符串镜像——执行代理极易"顺手合并/提公共函数"而破坏 test_anchor_pov 的源码断言。任何搬运必须**逐字**。
4. **并行中间状态**:见 §6 批次划分(单批串行)。
5. **孤儿文件**:见 §5(原文件保留为本体 + shim,不删除)。

循环导入:新模块只需 import `tools_dsl.command_dispatcher`(ToolSpec/get_registry 顶层,_get_sync_scope_lock 懒),dispatcher 不反向 import 工具模块 → 无环。模块级副作用:仅定义两个 frozenset 常量;注册由外部 `command_tools_register` 显式触发且 `registry.has` 幂等闸保证重复注册无害 → 注册顺序不敏感。

## 3. 内聚簇分析与判定理由

表面上是三个子域(A 剧本锚点 / B 存档历史 / C POV 覆盖),但**横向耦合强于簇间分离收益**:

- **9 个 executor 中 7 个直接读写同一张 `save_anchor_states` 表**(仅 `_t_list_recent_history`、`_t_check_pending_anchor_drift` 走 save_history 侧)。这不是三个领域,而是**一个锚点状态机的三个入口面**。
- 簇 B 的 `_t_record_history_anchor` 内含**级联写簇 A 语义**(linked_pending_anchors → 同款 `drift>=0.15→variant` 规则直写 save_anchor_states),拆开后这段跨簇 SQL 不知归谁。
- 簇 C 的 claim/revoke 与簇 A 的状态机靠 `variant_description` 字面签名(`"代入 {name} 的 POV 位置"`)互为镜像,且有专门的源码级回归测试钉死这对镜像在**同一份源文件**里最易维护。
- `register_anchor_tools`(255 行)是纯声明式数据(ToolSpec 描述/JSON Schema/input_examples),属任务定义中明确"不该拆"的类型;去掉它,真正的逻辑代码约 600 行。
- 全文件统一范式:每个 executor 都是 `parse args → _own_save 围栏 → (锁) → DB 操作 → JSON 返回` 的扁平单事务体,抽象层次一致,无"高低层混杂"。

**≥80 行巨型函数逐个评估**:

| 函数 | 行数 | 类型 | 是否值得拆阶段函数 |
|---|---|---|---|
| `_t_mark_anchor_satisfied` | 108 | 单事务线性体(校验→锁→读→更→级联进度) | **否**。全程在 `_get_sync_scope_lock` + `connect()` 上下文内,拆阶段函数会把锁/事务边界打散,纯增间接层 |
| `_t_claim_protagonist_pov` | 104 | 单事务线性体(5 步编号管线) | **否**。同上,且函数体被源码级测试按字面断言 |
| `_t_record_history_anchor` | 87 | 委托 + 级联块 | **否**。级联块是带注释的刻意设计(iter#5 防双重注入),拆走丧失上下文 |
| `_t_revoke_protagonist_pov` | 80 | 单事务线性体 | **否**。与 claim 镜像,源码级测试钉死 |
| `register_anchor_tools` | 255 | **纯声明式数据表** | **否**(任务定义明确豁免类型) |

**判定:acceptable**。理由汇总:① 单一职责成立(一个状态机);② 近半行数是声明式注册数据;③ 符合包内平铺惯例且与族内最大文件同量级;④ 拆分的真实成本(源码文本测试同步、镜像签名跨文件漂移风险)大于导航收益;⑤ 模块自身懒 import 设计使它对外部重构也最友好。

**顺带发现(非本方案动作,审计期不可改源码,留作后续)**:模块 docstring(1–12 行)仍写"公开 3 个 dispatcher 工具",实际已注册 9 个——陈旧文档,下次碰这个文件时顺手更新。

## 4. 条件性拆分方案(仅当未来触发,现在不执行)

**触发条件**(满足其一才启动):文件涨破 ~1200 行;或新增第 4 个子域(如锚点编辑器/批量导入工具);或 save_history 侧工具脱离 save_anchor_states 表自成体系。

### 4.1 目标布局(遵循包内 `command_tools_<family>.py` 平铺惯例)

| 新文件 | 搬入内容 | 估行数 |
|---|---|---|
| `rpg/tools_dsl/command_tools_save_history.py` | 簇 B:`_t_record_history_anchor`、`_t_check_pending_anchor_drift`、`_t_list_recent_history` + 对应 3 个 ToolSpec → `register_save_history_tools()` + 自带一份 `_own_save`(6 行,刻意复制不共享,见 §6 注 1) | ~290 |
| `rpg/tools_dsl/command_tools_pov.py` | 簇 C:`_t_claim_protagonist_pov`、`_t_revoke_protagonist_pov` + 对应 2 个 ToolSpec → `register_pov_tools()` + `_own_save` 副本 | ~310 |
| `rpg/tools_dsl/command_tools_anchors.py`(瘦身本体,**不删除**) | 保留:模块 docstring(更新)、`_ANCHOR_READ_ORIGINS`/`_ANCHOR_MUTATE_ORIGINS`、`_own_save`、簇 A 4 个 executor、4 个 ToolSpec;`register_anchor_tools()` 改为聚合:注册自家 4 个 spec 后调用 `register_save_history_tools()` + `register_pov_tools()`;**尾部 re-export shim** | ~430 |

origins 常量:两个新文件各自 `from tools_dsl.command_tools_anchors import _ANCHOR_READ_ORIGINS, _ANCHOR_MUTATE_ORIGINS` 会引入 anchors→新文件(聚合注册)→anchors 的环?不会成环死锁(Python 模块级循环只要不在 import 时取未定义名即可),但为零风险起见:**两个新文件各自复制这两个 frozenset 常量定义**(共 4 行),不跨文件 import。

### 4.2 re-export shim(留在 command_tools_anchors.py 尾部)

```python
# ── re-export shim:测试与历史调用方按原命名空间取符号(陷阱① 防护)──
from tools_dsl.command_tools_save_history import (  # noqa: E402,F401
    _t_record_history_anchor, _t_check_pending_anchor_drift, _t_list_recent_history,
)
from tools_dsl.command_tools_pov import (  # noqa: E402,F401
    _t_claim_protagonist_pov, _t_revoke_protagonist_pov,
)
```

注意 shim 的 import 放文件**尾部**(register_anchor_tools 定义之后),避免与聚合注册形成顶层互相依赖;`register_anchor_tools` 内对两个子注册函数用**函数内懒 import**,与本包现有风格一致。

### 4.3 可机械执行的搬运清单(逐字搬运、禁止任何改写/合并/提公共函数)

| # | 符号 | 源位置(行) | 目标文件 | 动作 |
|---|---|---|---|---|
| 1 | `_t_record_history_anchor` | @280–366 | command_tools_save_history.py | 逐字剪切 |
| 2 | `_t_check_pending_anchor_drift` | @369–396 | command_tools_save_history.py | 逐字剪切 |
| 3 | `_t_list_recent_history` | @399–428 | command_tools_save_history.py | 逐字剪切 |
| 4 | ToolSpec `record_history_anchor` / `check_pending_anchor_drift` / `list_recent_history` | @737–774, 775–796, 797–823 | command_tools_save_history.py 内新 `register_save_history_tools()` | 逐字剪切 specs,包同款 `registry.has` 幂等闸 |
| 5 | `_t_claim_protagonist_pov` | @457–560 | command_tools_pov.py | 逐字剪切 |
| 6 | `_t_revoke_protagonist_pov` | @563–642 | command_tools_pov.py | 逐字剪切 |
| 7 | ToolSpec `revoke_protagonist_pov` / `claim_protagonist_pov` | @842–863, 864–895 | command_tools_pov.py 内新 `register_pov_tools()` | 逐字剪切 |
| 8 | `_own_save` | @29–34 | 两个新文件各复制一份 | 复制(不剪切,本体保留) |
| 9 | `_ANCHOR_READ_ORIGINS`/`_ANCHOR_MUTATE_ORIGINS` | @19–21 | 两个新文件各复制一份 | 复制(不剪切) |
| 10 | shim(§4.2) | — | command_tools_anchors.py 尾部 | 新增 |
| 11 | `register_anchor_tools` 聚合改造 | @645–899 | 原地 | 自家 4 spec 保留 + 懒 import 调两个子注册;`__all__` 不变 |
| 12 | 模块 docstring 更新("公开 3 个工具"→ 实情) | @1–12 | 原地 | 文档修正 |

### 4.4 测试同步清单(陷阱① 的非 shim 残余)

| 文件:行 | 改法 |
|---|---|
| `rpg/tests/unit/test_anchor_pov_and_progress_fixes.py:11` | `ANCHORS_PY = (ROOT / "tools_dsl" / "command_tools_anchors.py")` → 改读 `command_tools_pov.py`(claim/revoke 都在同一新文件,改 1 行路径即可;变量名建议同步改 `POV_PY`,行 24/25 跟随) |
| `rpg/tests/unit/test_tavern_tool_user_fencing.py:170/175/180` | **不改**(shim 兜住);可选后续清理改为直 import 新模块 |
| `rpg/tools_dsl/command_tools_register.py:346` | **不改**(聚合 register_anchor_tools 兜住) |

### 4.5 验证闸

1. `python -m compileall rpg/tools_dsl`(语法 + import 环冒烟);
2. `pytest rpg/tests/unit/test_anchor_pov_and_progress_fixes.py rpg/tests/unit/test_tavern_tool_user_fencing.py`;
3. 起 registry 冒烟:调 `register_all()` 后断言 9 个工具名 `registry.has(...)` 全真且无重复注册告警;
4. `git diff --stat` 人工核对:被搬函数体 0 行内容级变更(只允许位置移动)。

## 5. 孤儿文件处置(陷阱⑤)

`command_tools_anchors.py` **保留为瘦身本体 + shim**,永不删除(它仍是簇 A 的实现宿主 + 对外稳定命名空间 + `register_anchor_tools` 聚合入口)。两个新文件为纯新增,无孤儿。

## 6. 批次划分与风险(陷阱④ + 其余)

**单批串行,禁止并行**:三个文件通过 shim/聚合注册互相引用,任何并行批次都会产生 import 失败的中间状态。顺序:建两个新文件(含复制的常量/_own_save)→ 瘦身 anchors 本体 + 加 shim → 改 1 处测试路径 → 验证闸。一个执行代理一次提交完成。

| 风险 | 等级 | 缓解 |
|---|---|---|
| 源码文本测试(test_anchor_pov)被搬运破坏 | 高 | §4.4 必改项;且搬运逐字,签名串 `"代入 {name} 的 POV 位置"` 一字不动 |
| 执行代理顺手提取 `drift>=0.15→variant` 公共函数 | 中 | 方案明令禁止;两处内联重复是刻意保留 |
| origins 常量跨文件 import 成环 | 低 | 各复制一份,不跨 import |
| 注册顺序漂移 | 低 | registry.has 幂等闸 + 聚合函数保持原相对顺序 |

**注 1**:`_own_save` 复制三份(共 18 行)是刻意决策——它是安全围栏(LLM 工具调用用户级围栏审计的一部分),跨文件共享会让"哪个工具有围栏"不可单文件审计;6 行的重复成本远低于安全审计清晰度收益。若坚持共享,放 `tools_dsl/command_dispatcher.py` 也可(它已是公共底座),但不要在三个工具文件间互相 import。

---

**最终建议**:维持现状(acceptable / priority low)。本文件的"大"主要来自 255 行声明式注册数据 + 9 个范式统一的扁平 executor;它是一个状态机的完整账本,拆开反而把镜像签名、级联写、源码级回归测试的耦合面变成跨文件暗耦合。把本方案存档,触发条件满足时再按 §4 机械执行。
