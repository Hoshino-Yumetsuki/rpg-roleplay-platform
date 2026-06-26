# L — 进度感知角色卡(Progress-Aware Character Cards)

设计稿 2026-06-15。源:用户(行者无疆,507 章大书)反馈——角色卡是小说中后期/最终态,
序章游玩时人设全错+剧透(早期敌→晚期友直接写成友),「重建角色卡」不可用,只能一个个手修。
目标:卡人设随玩家**当前进度章节**呈现(只显 ≤当前进度已揭示的态,防剧透),并要可用的「按章节区间重建卡」。

## 根因(已逐行核实)
1. **「重建不可用」**:`REBUILD_MODULES['cards']` 曾误标 `needs_llm=True` → 被凭据闸 `require_user_llm_credential` 拦死(没配 key 的用户点了没反应)。**代码已改 `False`**(`import_pipeline.py:2199-2203` 注释记录)——需核对是否已部署生产。次缺陷:`rebuild_cards_from_canon` 的 canon SELECT(`import_pipeline.py:2106-2110`)不取 `first_revealed_chapter` → `_sync_character_cards`(`_sync.py:139`)写成 0,重建后丢防剧透章。
2. **「序章看最终态/敌写成友/剧透」= 双重病灶**:
   - **生成期**:两条卡路径都读全书产最终态单态人设。`resolve.py:289-291` 取「全书最长非空」identity/background;`_stage_cards`(`import_pipeline.py:1136-1308`)读全书 chapter_facts 摘要(1160-1166 无章节上限)+全章原文,prompt 不传进度。
   - **读取期**:GM 卡加载器 `loaders.py:40-82` SELECT 出 `first_revealed_chapter` 却**完全不当 WHERE 闸**(注释 :52 自承「后续可作章节闸」=未接);`novel.py:254` 注入整张最终态卡、不传 progress。
3. **治本数据基础已具备一半**:`chapter_facts.characters / relationships` **逐章存** identity/background/status 与关系 kind(敌对|盟友)——态级 reveal 的现成证据(被 resolve 压扁丢弃);进度信号 `state.data.worldline.progress_chapter` 现成;区间抽取/报价底座(`incremental.py` / `budget.py`)现成。隔壁 canon 层 `canon_repo._reveal_clause`(first_revealed_chapter<=progress)是成熟防剧透机制,可借。

## 分阶段设计(确定性优先 / 零重花钱 / 不推倒)
### Phase 1A — 修「按章节区间重建卡」可用(用户最痛,零 LLM)
- 核对 needs_llm 修复已部署;给 cards 重建加 `chapter_max` 区间参数:`rebuild_cards_from_canon` 的 canon SELECT 加 `where first_revealed_chapter<=:chapter_max` + 补取 `first_revealed_chapter`(修被刷成 0 丢防剧透章)。管线/前端透传已就绪,改动极小。

### Phase 1B — 卡加载接 first_revealed_chapter 闸 + 保护手编(零成本)
- `loaders.py:_load_characters_db` 加 `progress_chapter` 参，WHERE 追加 `(first_revealed_chapter<=%s or first_revealed_chapter=0)`(0=未知,保守放行,同 canon 语义);`novel.py:254` 传 `state.data.worldline.progress_chapter`。→ 立即挡掉「序章看到尚未登场角色」。
- **修 `_sync_character_cards` 无条件覆盖**(`_sync.py:114-119` 改 case-when length>0 才覆盖)→ 保护用户手编 persona,否则重建前功尽弃(正是用户「一个个手修」痛点的反面)。**强烈建议本轮必做**。

### Phase 2 — 态级 reveal-gating(敌→友不提前剧透)· 推荐方案 C
- **方案 C(推荐)运行时投影**:新增聚合层 `project_character_state(script_id, name, progress_chapter)`——从 `chapter_facts.characters` 取该角色 chapter<=progress 各章态,「最近非空」回退合成当前态;relationships 同理取 chapter<=progress 最后一次 kind(敌对→盟友逐章不同)。GM 取卡时投影。**几乎零 LLM、对存量存档天然生效、不放大 KB、不动写库 schema**。代价=运行时投影(可加缓存表消除)。已有先例 `import_pipeline.py:1736-1748`(按章取当章实体)可借鉴。
- 方案 B(备选)分段表 `character_card_states`(chapter 区间多行),提取期写 N 段:语义最干净但 KB 体积×N、要改写库+提取。若走 B 建议 arc 粒度(40 弧≈$0.05)。
- 配套(可选):生成期 `_stage_cards` 按 arc 分段产态 + 回填 first_revealed_chapter,给投影更干净输入。非 Phase 2 必需。

## 待用户拍板(open decisions)
1. **存储策略**:方案 C 运行时投影(推荐,零重花钱)vs 方案 B 分段表(干净但 N× 成本+改 schema)。
2. **重建「可用」标准**:零 LLM 便宜版(canon.summary 当 identity,产物偏简)vs LLM 区间重抽版(走 `run_llm_extraction` 带 chapter_max,产丰富该时期态,序章 1-20 章≈$0.06 BYOK)。
3. **进度感知默认 vs 开关**:默认严格 reveal-gating(契合防剧透)vs 暴露 `foreknowledge_mode`(none 严格/partial 穿越者预知/omniscient 全知,canon_repo 已有三态)给玩家选。推荐默认 none、复用现有 mode。
4. **重建语义**:保留手编/只补空 vs 全量重写(配合 Phase 1B 的覆盖保护)。
5. **first_revealed_chapter 可信度**:NPC 提取有别名/史实问题([[project_npc_extract_fix]]),当硬闸错值会误隐藏/误剧透;0 值保守放行缓解,是否补编辑器手改章节控件(`scripts.jsx:997` 已显章节徽章)。
6. **敌→友关系**:塞 persona/status 文本由投影兜,vs 单建 per-chapter 规范关系投影(chapter_facts.relationships 已按章存 kind)。

## 易误认
`rpg/character_card_generator.py` 是 console 助手「从简述造全新虚构卡」的独立子系统(5 层 validator),**与小说 NPC 提取/重建无关**,不是改动点。
