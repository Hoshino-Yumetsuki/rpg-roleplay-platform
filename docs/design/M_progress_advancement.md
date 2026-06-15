# M — 进度推进信号重设计(progress_chapter)

状态:设计待审(2026-06-15)。用户:行者无疆(`1027403637@qq.com`,id 115)反复踩进度卡死。
关联:[[D_gm_serving]] [[L_progress_aware_cards]]、`ba640f414`(本次回归来源)、`cca51bc69`(reconciler)。

---

## 1. 问题(prod 实证)

`game_sessions.worldline->>'progress_chapter'` 是**单一进度真源**,驱动两件事:
- 时间线面板「当前」节点高亮([game-panels.jsx](../../frontend/src/game-panels.jsx) `ch_min ≤ 当前 ≤ ch_max`)。
- 剧透门控 / 实体召回天花板([retrieval.py](../../rpg/retrieval.py) `_progress_chapter`、canon `_reveal_clause`)。

**现象**:用户 115 的 save 139(script 143「无限流_最终版」)玩了 15 回合、故事已深入「生化危机·蜂巢」线(B2 实验室/激光通道/丧尸),进度表却死在**第 1 章**;面板把第 1 章两个「序章」节点都标「当前」(后者是 Bug A 重复锚点,已另修)。

**实证数据(prod, script 143):**

| 章 | story_time_label | events 数 |
|---|---|---|
| 1 | 序章 | 10 |
| 2–8 | 名为生化 / 醒来 / 死亡擦肩而过 / 活下去的欲望 / 救命的激光通道 / 活着的证明 / 强化 | **全 0** |
| 9 | 准备完毕 | 1 |
| 11 | 极限恐怖 | 7 |

`save_anchor_states` 只在 ch1/ch9/ch11 有锚点(与 events 密度一致)。ch2–8(整段蜂巢线)**有完整 summary、0 event → 0 锚点 → 进度全盲**。

## 2. 根因链

1. `ba640f414` 把进度改成「只认已确认锚点的最大原著章」(`max(source_chapter where status in occurred/variant)`),`advance_progress` max-only 单调。**可靠但稀疏**。
2. 锚点来自 `chapter_facts.events`,密度极不均(本书 ch2–8 抽取 0 event)。玩家走完事件空白章,无任何锚点可标 → 进度冻结。
3. 历史:`ba640f414` 之前进度由 `get_progress_window.chapter_min`(含 world.time→timeline 映射)物化 → 因 `story_time_label` 不是可靠「时间」→ 早期标签误命中远章 → bogus jump 到 ch77。所以那条信号被**整条砍掉** → 矫枉过正成今天的冻结。
4. world.time 标签信号实测**不可用**:GM 自编自由标签(save 139 = "无限历元年·任务初始·进入蜂巢")与抽取标签("第①部 第一集 名为生化")**零 token 重叠**,`resolve_timeline_anchor` 返回 None(实测「进入蜂巢/蜂巢/任务初始」全 no-match;只有「名为生化」「序章」命中)。

## 3. 可用信号盘点

| 信号 | 可靠性 | 密度 | 备注 |
|---|---|---|---|
| 已确认锚点 occurred/variant | 高(地面真值) | 稀疏 | 当前唯一信号;空事件章冻结 |
| world.time 标签 → 锚点 | 低 | — | GM 自由标签 resolve 不到,**弃用** |
| reconciler judge 读本回合正文 | 中(LLM) | 每回合 | **已在每回合跑**,读真实剧情 |
| `chapter_facts.summary` | 高(数据) | 每章(密) | 每章都有 label+summary(ch2–8 实测 100–240 字、内容真实) |
| `save_phase_digests` | 中 | 每 phase | 太粗,本例仍停"序章·不明时段" |

## 4. 设计:有界叙事章估计(judge)+ 锚点地板 + 确定性 clamp

核心:**LLM 提供平滑(读真实剧情估当前章),确定性 clamp 提供安全(钳在地面真值附近,杜绝乱跳)**。符合 [[feedback_harness_determinism]]——失败模式由确定性 clamp 兜死,LLM 只在安全区间内补平滑,**不可能再 catastrophic 乱跳**。

### 4.1 三个量

1. **地板 `floor`(可靠,不可回退)**:`max(source_chapter where status in ('occurred','variant'))`。即当前行为,绝不低于它。
2. **叙事估计 `est`(平滑)**:扩展现有每回合 `anchor_reconcile` 判定器,**顺带**返回 `estimated_chapter` —— 「本回合正文最接近原著第几章」。判定器本就读 turn 正文 + 窗口内 pending 锚点;额外喂窗口章的 `chapter_facts.summary` 作参照,让它挑最接近的章。**读真实剧情,不依赖 GM 标签是否匹配**。无 key / 判定器不可用 → `est=None` → 回退纯锚点地板(零回归)。
3. **上限 clamp(确定性护栏)**:
   ```
   ceiling   = max(floor, prev_progress) + LOOKAHEAD_CAP
   candidate = clamp(est, prev_progress, ceiling)          # est 为 None 时跳过
   new       = max(prev_progress, floor, candidate)        # 单调,经 advance_progress
   ```
   - `LOOKAHEAD_CAP`(待定,建议 8–12):叙事估计最多越过「已确认地面真值」N 章。
   - bogus 兜底:floor=0 时 ceiling=CAP,即使 judge 误估 77 也被钳到 CAP(根治 ch77,blast radius = CAP 章而非整书)。
   - 锚点确认后 floor 升 → ceiling 升 → 进度自然跟着往前放。

### 4.2 对 save 139 的效果(验证设计正确性)
- floor=1、prev=1、CAP=10 → ceiling=11。
- judge 读第 15 回合正文(B2/激光通道/蜂巢)+ ch2–11 summary → 估 ≈ ch6(「救命的激光通道」)。
- candidate=clamp(6,1,11)=6 → new=max(1,1,6)=**6**。进度推到 6,面板高亮 ch6。**下一回合即修复,无需回填**。

### 4.3 对 ch77 历史 bug 的效果
- floor=0、prev=1、ceiling=0+CAP=10。即使 judge 误估 77 → clamp 到 10。**有界**;用户仍可用 rewind 端点下修。

## 5. 成本 / 回退 / 开关
- **零新增 LLM 调用**:复用 `anchor_reconcile` 每回合已有的 judge call,只在其输出 schema 加 `estimated_chapter` + 喂窗口章 summary。
- 判定器无 key / 异常 → `est=None` → 纯锚点地板(= 当前行为,零回归)。
- env `RPG_PROGRESS_NARRATIVE_ESTIMATE`(默认开),可一键关。沿用 `anchor_reconcile` 既有 gating(窗口内无 pending 也照样能估当前章——估计不依赖 pending 锚点,需把这条放在 pending 短路之前)。

## 6. 存量存档影响
- judge-估章:**无需回填**;存量卡死存档(如 139)下一回合自然推进。
- 不动 `save_anchor_states` 结构。

## 7. 备选(评估后不作首选)
**按章补播种锚点**:给空事件章从 `chapter_facts`(label+summary)确定性补一个粗粒度章级锚点,reconciler 逐章标。
- 优点:锚点是真实数据,更"确定性"。
- 缺点:① 要改播种逻辑 ② 要**回填存量存档**的 `save_anchor_states`(prod 写)③ reconciler 的"事件满足"语义被迫变成"章满足"——其实和 judge 估章是同一份 LLM 工作,却多出一堆行。
- 结论:judge-估章用更少改动达成同效 + 立即救存量;按章播种可作**二级加密**(可选,后续)。

## 8. 回归测试
- clamp 单元:est>ceiling→钳;est<prev→地板赢;est=None→纯锚点;单调不回退。
- ch77 场景:floor=0、误估 77 → 进度 ≤ CAP。
- save 139 场景:floor=1、估 6 → 进度 6。
- judge schema:加 `estimated_chapter` 不破坏既有 anchor 命中解析。

## 9. 待用户拍板
1. `LOOKAHEAD_CAP` 取值(8 / 12 / 15)?越大越平滑、bogus 上限越松。
2. 是否允许「零确认锚点时也靠估计推进」(floor=0 仍放行到 CAP)?——**需要**,否则事件稀疏的开局章永远不动(正是本 bug)。
3. 备选「按章补播种」要不要一起做(双保险),还是先只上 judge-估章?
