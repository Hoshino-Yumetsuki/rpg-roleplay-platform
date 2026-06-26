# 开源准备 · 自包含存档导出 + 打包方案

> 状态（2026-06-02 更新）：
> - **安全审计**：通过（§0 八项 + 近期所有提交复扫无新增密钥）。
> - **自包含导出/导入/即时算大小**：**已实现 + 部署 + 往返实测通过**（§8）。full/no_vectors 两档,lite 缓。
> - **开源仓代码同步**：**未做** —— origin/main 落后生产 ~170 提交;按决策走「干净快照」(§5.1),翻公开时一次性快照,不逐条 replay。
> - **打包(README/LICENSE/.env.example/剥服务器专属配置)**：用户自理(开源仓基本就绪)。
> - **建议**：翻公开前对快照跑一次 gitleaks(已有 pre-commit 钩子,升成 CI 硬关卡)。

## 0. 安全边界（已验证，硬约束）

用户头号约束：**开源软件不可成为攻击生产服务器的工具**。审计结论 = 通过，8 项全清：

1. 全分支全历史**从未提交任何密钥文件**（含 159 个待回流提交）；
2. HMAC / admin 口令 / `master.key` 全 **env 来源** → 开源实例各用各的，**不共享信任**；
3. 前端 API base **同源相对**，无硬编码生产 URL（无回连）；
4. 无默认管理员口令，引导 = 首个注册用户成 admin（每实例独立）；
5. CORS 配置驱动 + 带凭据时 header 明确枚举；
6. 会话 cookie 强制 HttpOnly+Secure+SameSite=Lax（CSRF 挡）；
7. 用户 API key AES-GCM 加密存库；
8. 全历史字符串深扫唯一命中 = UI 占位符 + 伪造测试夹具（且已有 pre-commit 密钥钩子）。

**本设计的所有改动都不得破坏上述边界**（尤其：导入端处理不可信存档包时，不得引入注入/越权/资源耗尽）。

---

## 1. 问题：指针导出 → 无法脱离服务器

当前 `save_io.export_save`（EXPORT_VERSION=2）只打包 **per-save** 数据：
`game_saves / branch_commits(含快照) / branch_refs / messages / memories` + 9 张 per-save 状态表
（`save_anchor_states / kb_entities / kb_events / kb_relationships / kb_worldline_vars / kb_checkpoints / identity_cards / save_character_identities / save_history_anchors`）。

但存档只带 **`save.script_id` 一个指针**，导出包**不含剧本本体与知识库**。`import_save` 导入时
（save_io.py:162-186）若 `script_id` 不在当前账户，**回退挂到"用户第一个剧本"**——导入到别的实例 =
一个挂着断指针的空壳：剧本正文、章节、人物谱、世界观、时间线、向量全丢。

### 缺失的"剧本级"表（script_id 外键）
| 表 | 内容 | 体量特征 |
|---|---|---|
| `scripts` | 剧本元信息（标题/字数/指纹…，**不含 import_report**） | 小（KB） |
| `document_chunks` | 章节切片正文 + `embedding` 向量 | **大**：正文∝字数；向量∝块数×维度 |
| `kb_canon_entities` | 人物谱（canon） | 中 |
| `worldbook_entries` | 世界观条目 | 中 |
| `script_timeline_anchors` | 时间线锚点 | 小~中 |
| `script_worldlines` / `script_worldline_nodes` | 世界线脊柱/节点 | 小 |
| `script_overrides` | 剧本级覆盖 | 小 |

---

## 2. 导出 v3：用户可选档位 + 即时算大小

`EXPORT_VERSION 2 → 3`。v3 在 v2 基础上增加 `script_bundle` 段 + `tier` 字段。

### 2.1 三档（导出时用户选，UI 即时显示该存档该档的真实 MB）
| 档位 | 打包内容 | 导入端 | 包大小 | 适用 |
|---|---|---|---|---|
| **完整** `full` | 剧本 + 章节正文 + **向量** + 全部知识库 + per-save | 即用，RAG 立即可检索 | 最大（向量最肥） | 跨实例搬家、长期归档 |
| **标准** `no_vectors` | 剧本 + 章节正文 + 全部知识库 + per-save（**去向量**） | 后台**重嵌入**（需配嵌入模型） | 中（砍掉向量，常省一半以上） | 默认推荐 |
| **精简** `lite` | 剧本 + 章节正文 + per-save（**无剧本级知识库**） | 重嵌入 + 可选重抽取知识 | 最小 | 只想搬进度、知识库到端上重建 |

> per-save 状态表（v2 已含）三档都带——那是"当前世界状态"，离了它续不上游戏。
> 剧本级知识库（canon/worldbook/anchors）是"源真值"，`lite` 省掉、到端上可重抽。

### 2.2 即时算大小（替代静态预估）
新端点 `GET /api/saves/{id}/export/estimate`：
```
→ { ok, tiers: { full: <bytes>, no_vectors: <bytes>, lite: <bytes> },
    breakdown: { chapters_text, embeddings, knowledge, per_save } }
```
实现：对该存档的 script_id 跑 `sum(pg_column_size(...))` 聚合（按档位取列子集）。
前端导出弹窗调它，三档实时标 MB；切档即变。**不预先静态测，按真实存档算。**

### 2.3 限自有剧本（版权 + 安全）
导出端点先判 `scripts.owner_id == user.id`：
- **自有剧本** → 三档全开。
- **订阅的公开剧本**（别人版权内容）→ **拒绝完整导出**（403「只能完整导出自己拥有的剧本」），
  仅保留 v2 指针导出（同服务器内可用）。
> 两边（托管 + 开源自托管）都启用完整导出，但都受此门控。

---

## 3. 导入 v3：重建 + 去重 + 重映射

`import_save` 增加 v3 分支（v1/v2 旧包继续走原指针逻辑，向后兼容）：

1. **剧本去重/重建**：按 `scripts.content_fingerprint` 查当前用户是否已有同一剧本。
   - 已有 → 复用其 script_id（不重复占库）；
   - 没有 → 新建 script（owner=导入者）+ 灌 `document_chunks` + 知识库各表，拿到新 script_id。
2. **重映射**：`save.script_id` → 新/复用的 script_id；`branch_commits / kb_* / *_anchor_*` 的
   save_id、script_id 全部重映射到新分配的 id（沿用 v2 的 `old_to_new` 机制扩展到剧本级）。
3. **向量处理**：
   - `full` 包 → 向量随章节灌入，但记录**来源嵌入模型**；与本实例嵌入模型不一致 → 警告 + 提供"重嵌入"。
   - `no_vectors` / `lite` 包 → chunks 标 `embedding IS NULL` → 触发**后台重嵌入任务**（需端上配好嵌入模型，否则 RAG 暂不可用，给提示）。
4. **知识库**（仅 full/no_vectors 带）→ 按 script 重建；`lite` 包导入后提示"可在剧本页一键重抽知识库"。

### 3.1 导入端硬化（安全要点，不可省）
处理不可信存档包必须守住：
- 现有上限沿用并扩展：`_MAX_SAVE_IMPORT_BYTES`、`MAX_COMMITS`、`_check_json_size`；新增 `MAX_CHUNKS`、单包总字节上限（防 zip/JSON 炸弹）。
- 全部 INSERT 走**参数化**（沿用 `_build_insert`，禁拼接）。
- 列白名单：v3 导入只接受已知列，丢弃未知列（防越权写 owner_id/role 等敏感列——**强制覆写 owner_id=导入者**，绝不信包里的 owner/user_id/role）。
- 嵌入向量维度校验（防畸形向量撑爆 pgvector）。

---

## 4. 格式与兼容
- 包结构：`{ export_version:3, tier, save, commits, refs, messages, memories, state_tables{...}, script_bundle:{ script, chunks, knowledge:{canon,worldbook,anchors,worldlines,overrides} } }`。
- 导入按 `export_version` 分流：≤2 走旧逻辑，==3 走新逻辑。旧客户端拿到 v3 包 → 明确报"需升级"。
- 包建议 **gzip**（章节正文压缩比高），`.json.gz`；导入兼容裸 json 与 gz。

---

## 5. Part B：开源打包（待 Part A 后或并行）

### 5.1 仓库回流策略（159 提交）
deploy/production 领先 origin/main 159 提交，历史含大量 hotfix。**建议不逐条 replay**，而是：
以当前 production 树为准，在 origin 开 `release/oss-1.0` 分支做**一次干净快照提交**（或 squash），
避免把内部 hotfix 噪音 + 任何潜在风险逐条带进公开历史。保留 deploy 私有仓做内部部署。

### 5.2 自托管配置（多数已就绪）
代码已支持 `RPG_DEPLOYMENT_MODE=self_hosted`。开源版需：
- `.env.example`（DATABASE_URL / 嵌入&GM 模型 BYOK / 可选 RPG_REQUIRE_AUTH / master.key 生成指引）；
- **默认关掉托管专属**：内测白名单（auth.py:318）、email 验证（RESEND）→ 改为 env 可选、self_hosted 默认 off；
- `master.key`：首次启动自动生成（已 gitignore），文档强调备份。

### 5.3 开源仓基建
- `README`（架构图 / 一键起：postgres + .env + `migrate up` + run / BYOK 配置 / 自包含存档导入说明）；
- `LICENSE`（**待你定**：AGPL-3.0 防闭源 SaaS 抄 vs MIT/Apache 宽松——影响别人能否拿去商用）；
- `CONTRIBUTING` + `.env.example` + 截图；
- **CI 加 gitleaks/secret-scan**（把你现有 pre-commit 钩子升级成 CI 关卡，防今后误提交密钥进公开仓）。

---

## 6. 实施阶段（建议顺序）
- **A1** 后端 `export_save` v3 + `/export/estimate`（即时算）+ 自有剧本门控 → 单测。
- **A2** 后端 `import_save` v3（重建/去重/重映射/硬化）→ 单测（导出→导入 round-trip 等价性断言）。
- **A3** 前端导出弹窗：档位选择 + 即时大小 + 进度；导入兼容 v3。
- **A4** 跨实例端到端验证：本机起第二个 self_hosted 实例，导出→导入→开局可玩 + RAG。
- **B1** `.env.example` + 自托管默认 + README/LICENSE。
- **B2** release/oss-1.0 干净快照 + CI secret-scan → 翻公开。

## 7. 决策（用户已拍板，2026-06-02）
1. **LICENSE / 打包**：**开源仓已基本就绪，用户自理**。我的职责收敛为"确保代码安全"（见 §8）。
2. **默认导出档位**：**标准（去向量）**。✓
3. **回流策略**：**干净快照**（不逐条 replay）。✓
4. **嵌入不一致**：**导入时给用户抉择**（让用户自行决定重嵌还是其它），不自动花 token。✓

## 8. 当前状态 / 落地范围
- **用户当前只要"确保代码安全"——已完成**（见 §0 八项 + API 鉴权抽查一致严谨）。用户结论："够了不用再深审"。
- **自包含导出（§2–§4）= 设计就绪、实施暂缓**，待用户需要时按 §6 阶段动手（默认档位/重嵌策略已按上方决策定）。
- 安全审计**未做**穷尽式逐端点渗透（用户选择不做）；如将来大版本发布前想要，多代理穷尽审计的方案随时可起。
