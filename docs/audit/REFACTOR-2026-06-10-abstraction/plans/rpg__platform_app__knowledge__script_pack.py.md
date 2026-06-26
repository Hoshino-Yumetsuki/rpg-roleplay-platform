# 体检结论:rpg/platform_app/knowledge/script_pack.py(898 行)

- **判定**:acceptable(虽大但单一职责 —— 一个 pack 格式的序列化/反序列化契约,不应做模块级拆分)
- **优先级**:low
- **工作量**:S(当前无需动;本文档附一份"将来 v3 再加表时"的同文件内阶段函数拆分清单备用)
- **方案日期**:2026-06-10
- **本方案只是计划,未做任何源码改动**(并行审计约束)

---

## 1. 现状结构图(精读结论)

```
script_pack.py (898 行) —— 剧本 export/import pack(zip 格式)单一职责模块
│
├── 模块头:格式 docstring(zip 成员清单 v1+v2)+ 6 个常量
│   FORMAT_VERSION=2 / CHUNKS_VERSION=1 / MAX_ZIP_BYTES / MAX_EXPANDED_BYTES
│   / MAX_MEMBER_BYTES / MAX_JSONL_ROWS        @33-38(纯常量,无副作用)
│
├── _safe_member_read(zf, name)                @41   10 行  有界解压(CWE-409 双重防护)
│                                                     ⚠ 被 account_io.py 以 script_pack._safe_member_read
│                                                       跨模块调用 3 处(私名外用)
│
├── export_script_pack(script_id, user_id, …)  @55   212 行 导出流水线:
│       ownership 校验 → 13 张表 SELECT(chapters/facts/cards/worldbook/docs/
│       overrides/v2 五张世界树表/可选 chunks)→ 构 zip(manifest + 12 个成员)
│       每段 = 一张表的"显式列 SELECT + dict 化",5-25 行,数据表型
│
├── import_script_pack(zip_bytes, user_id)     @271  559 行 导入流水线(全文件重量级):
│       §1-3  zip 大小/zip-slip/解压炸弹预检 + manifest 版本闸(v1/v2 双兼容)
│       §4    逐成员 _read_jsonl(v1 缺 v2 成员 → 容错返 [])
│       §5a-5m 单个 `with connect()` 事务内逐表 INSERT:
│         5a scripts(owner 强制覆写为 user_id)
│         5b script_chapters(建 old_id→new_id 映射)
│         5b' _ensure_book(懒 import platform_app.knowledge._sync)
│         5c chapter_facts(FROM books 子查询拿 book_id)
│         5d 第二次 _ensure_book(5b' 加入后已基本冗余,容错保留)
│         5e-5h cards / worldbook / documents / chunks(均 per-row try/except → warnings)
│         5i-5m v2 五张表(kb_canon/anchors/digests/worldlines/nodes,自然键 ON CONFLICT)
│       §6    overrides(懒 import script_overrides.upsert_overrides,须在事务提交后)
│       末尾  warnings 聚合(warnings_count / warnings_summary)
│
├── _dump_jsonl / _read_jsonl / _dump_script_row @834/@840/@855  序列化助手(4/13/5 行)
│
└── clone_public_script(src, dst_user)         @862  36 行  组合函数:
        is_public 闸 → export(以原 owner)→ import(给当前用户)→ clone_count+1
```

无 `Path(__file__)`、无相对路径、无模块级单例/注册表/装饰器注册;import 副作用为零。
函数体内有 3 处**刻意的懒 import**(`_sync._ensure_book` ×2、`script_overrides.upsert_overrides` ×1),
反查确认 `_sync.py` / `script_overrides.py` 均不 import 本模块,无循环导入。

## 2. 调用面与 patch 点(Grep 实查)

### 2.1 patch 点:**0 个**

`grep -rn "patch.*script_pack|patch.*export_script_pack|patch.*import_script_pack|patch.*clone_public_script|patch.*_safe_member_read|monkeypatch.*script_pack|setattr.*script_pack"` 全仓零命中。
`rpg/tests/` 内唯一引用者是 `tests/integration/test_script_pack_chunks.py`,全部是真实直接 import 调用(无 mock)。

### 2.2 符号消费者(全量)

| 符号 | 消费者 | 引用方式 |
|---|---|---|
| `export_script_pack` | save_bundle.py:63 · federation.py:345,476 · account_io.py:136 · api/scripts.py:856 · 测试 ×6 | 模块属性 / 函数内直接 import |
| `import_script_pack` | save_bundle.py:127 · federation.py:357,468 · account_io.py:286 · api/scripts.py:896 · 测试 ×5 | 同上 |
| `clone_public_script` | api/scripts.py:1093(函数内 import) | 直接 import |
| `MAX_ZIP_BYTES` | federation.py:66(`script_pack.MAX_ZIP_BYTES`)· api/scripts.py:896 | 模块属性 / 直接 import |
| `CHUNKS_VERSION` | tests/integration/test_script_pack_chunks.py:215 | 直接 import |
| `_safe_member_read` | **account_io.py:267,286,309**(`script_pack._safe_member_read`) | 模块属性(私名外用) |

`platform_app/knowledge/__init__.py` **不** re-export 本模块任何符号 —— 无经包层的间接依赖。
save_bundle.py / federation.py / account_io.py 一律 `from .knowledge import script_pack` 后取属性,
意味着模块路径 `platform_app.knowledge.script_pack` 本身就是对外契约。

## 3. 内聚簇分析 → 为何判 acceptable

**只有一个簇。** 全文件围绕同一份格式契约:zip 成员名、FORMAT_VERSION 升级语义、
每张表导出哪些列 ↔ 导入写哪些列,export 与 import 是这份契约的左右两半,必须逐字段对账演进
(v1→v2 加 5 张表时就是两边同步改)。`clone_public_script` 是这两半的 6 行组合 + 计数,
`_safe_member_read`/`_dump_jsonl`/`_read_jsonl` 是格式的安全/序列化原语。

**898 行的来源是"13 张表 × 每表两段字段映射"的宽度,不是职责混杂。**
每段都是 5-50 行的"显式列清单 + 类型保底转换 + ON CONFLICT 策略"——典型数据表型代码,
拆走任何一半都会把"改格式要同步两处"的对账面从同屏拉长为跨文件,违背本审计"拆是为了内聚"的初衷。

**两个 ≥80 行巨型函数单独评估:**
- `export_script_pack`(212 行):流水线型但每阶段是纯 SELECT 列清单,无控制流交织、无共享可变状态
  (除最终聚合进 zip)。拆阶段函数收益≈0,徒增 14 个传参签名。**不拆。**
- `import_script_pack`(559 行):流水线型、阶段边界清晰(注释 5a-5m),**理论上值得**拆阶段函数;
  但阶段间有 4 份共享状态(`old_chapter_id_to_new` / `book_row→book_id` / `doc_key_to_new_id` /
  `warnings`)+ 全程单事务 `with connect()`,拆分必须原样穿参。当前零 patch 点、测试为黑盒
  round-trip(拆内部不破测试),**风险可控但无现实收益触发点** —— 该函数自 task 67 后稳定,
  无近期改动压力。结论:**现在不动;留待 v3 加表时顺手做同文件内拆分**(见 §5 备用清单)。

**反方向证据核查(避免误判 acceptable):**
- 不是追加式账本(migrations 那类),但格式版本演进同样是"两半对账"模式,模块边界已是最优;
- 体量在本包内并非孤例(embedding.py 769 行),且无任何调用方抱怨面(API 层只取 3 个入口函数);
- 安全硬化(zip-slip/CWE-409/owner 覆写/insertion_position 白名单)散布在两条流水线内,
  拆散反而提高漏带安全检查的回归风险——这是"动它风险>收益"的主要分量,但因函数内拆分
  仍可安全做,不至于 leave-as-is。

## 4. 五大陷阱对照(对"不拆"决定的反向验证 + 将来若动的红线)

| 陷阱 | 本文件现状 | 将来若动的红线 |
|---|---|---|
| ① patch 命名空间穿透 | **0 patch 点**(§2.1 实查),风险面为零 | 即便如此,`account_io.py` 用 `script_pack._safe_member_read`、`federation.py` 用 `script_pack.MAX_ZIP_BYTES`,任何符号搬迁必须在 `script_pack.py` 留 re-export,缺一即炸 3 个生产模块 |
| ② Path(__file__) 错位 | 全文件无 `__file__`/相对路径(Grep 实查 0 命中) | 无 |
| ③ 执行代理顺手简化 | — | §5 备用清单已按"逐字搬运、禁止改写逻辑"写成符号级指令;尤其 5e 的 insertion_position 白名单、5a 的 owner 覆写、§1-3 的炸弹预检一个字符都不能动 |
| ④ 并行中间状态 | — | 备用方案全部在**单文件内**进行,天然单批次串行,无并行冲突面 |
| ⑤ 孤儿文件/死代码 | 无孤儿;唯一冗余 = 5d 第二次 `_ensure_book`(@455-466,5b' 加入后基本不可达其增量语义,但保留为容错无害) | 备用方案不产生新文件,无 shim/删除决策 |
| 循环导入 | 懒 import `_sync`/`script_overrides`,反查无回边,无环 | 若将来把阶段函数移出本模块(不建议),`_ensure_book` 懒 import 必须保持懒(`_sync` → `_utils`/`chapter_fact_indexer` 的 import 链较重) |
| 单例/注册副作用 | 仅纯常量,import 零副作用 | 无 |

## 5. 备用清单(非本次执行)— v3 加表时的同文件内拆分

触发条件:下次 FORMAT_VERSION 升 3 / 再加表,`import_script_pack` 将破 600 行时执行。
**全部在 script_pack.py 文件内进行,不新建模块、不动任何对外符号,零 shim 需求。**

逐字搬运(函数体原样剪切为模块级私有函数,签名穿透共享状态;禁止改写任何 SQL/转换/异常逻辑):

| 新私有函数(同文件) | 逐字搬自 import_script_pack 的段落 | 签名(穿透状态) |
|---|---|---|
| `_import_validate_zip(zip_bytes) -> (manifest, 各 rows…)` | §1-4(@273-343) | 返回元组,不接 db |
| `_import_chapters(db, chapters, new_script_id) -> old_to_new` | 5b(@366-389) | 返回映射 |
| `_import_facts(db, facts, new_script_id, old_to_new, warnings)` | 5c(@405-451) | warnings 原地 append |
| `_import_cards(db, cards, book_id, new_script_id, warnings)` | 5d 主体(@474-510) | book_row 判定留在主函数 |
| `_import_worldbook(db, wb, book_id, new_script_id, warnings)` | 5e(@512-558) | 含 insertion_position 白名单,逐字 |
| `_import_documents(db, docs, …) -> doc_key_to_new_id` | 5g(@560-596) | 返回映射 |
| `_import_chunks(db, chunks, doc_key_to_new_id, …, warnings)` | 5h(@598-645) | — |
| `_import_worldtree_v2(db, 五组 rows, new_script_id, warnings)` | 5i-5m(@649-804) | v1 警告分支留主函数 |

主函数收敛为 ~80 行编排器;事务边界(单 `with connect()`)与 §6 overrides 在事务外的顺序**不得改变**。
验证:`tests/integration/test_script_pack_chunks.py` 全绿(黑盒 round-trip,内部拆分不需改测试)+
save_bundle / federation / account_io 三个消费者冒烟。

## 6. 顺手发现(不在本方案范围,记录给后续审计)

1. **5d 冗余 ensure**:@455-466 的第二次 `_ensure_book` 在 5b'(@393-403)无条件 ensure 之后
   语义重复(except 分支也只是 pass)。无害,可在下次触碰该文件时顺手删,带 round-trip 测试。
2. **私名跨模块**:`account_io.py` 三处调用 `script_pack._safe_member_read`。建议某次顺手把它
   升格为公名 `safe_member_read`(原名留 alias),消除"下划线私名是内部契约"的误导。
3. `_read_jsonl` 对缺失成员吞 `KeyError` 返 `[]` 是 v1 兼容的承重设计(@323 注释),
   任何"清理裸 except"的 lint 化改动不得触碰此处语义。
