"""
command_tools_script_write.py — N (MD 编辑器) §5: script scope 「读 + 直写库」工具。

给 MD 编辑器右栏 agent(console_assistant)读现状 + 端到端直写剧本知识资产的工具。

「列出」读工具(rule 4 同步前先定位现有 entry_id/anchor_id/logical_key):
  · list_worldbook_entries  世界书条目精简清单
  · list_anchors            时间线锚点精简清单
  · list_canon_entities     canon 实体精简清单
  这三个用「读」级闸(owner 或 subscriber 可读),destructive=False。

「直写库」写工具:
  · update_script_chapter   章节正文(覆盖整章 → destructive=True)
  · upsert_worldbook_entry  世界书条目(创建/更新)
  · update_npc_card         NPC 角色卡(复用 character_cards.upsert)
  · update_anchor           时间线锚点(keywords 是原生 text[])
  · upsert_canon_entity     canon 实体(aliases/attrs 是 jsonb)

executor 签名统一为 `(user_id, script_id, args, state) -> str`(script scope)。

读 vs 写鉴权铁律(漏一条 = 越权或过严):
  · 「读」工具用 _user_can_read_script(owner 或订阅者),允许 reader 看清单去定位 id;
    **绝不可用 script_owned 写闸卡读**(订阅者本就有读权,卡死会让 agent 盲目新建)。
  · 「写」工具用 perms.script_owned 严格 owner 闸,**绝不可用 _user_can_read_script**
    (订阅者可读,写会越权)。

Decimal 不可 JSON 序列化:probability 是 numeric → 读时 ::float8(照搬 script_edit 契约)。

安全铁律(每个写工具逐条遵守,漏一条 = 越权漏洞):
  ① sid = script_id or args.get("script_id");缺 → 友好失败。
  ② 进 DB 后第一件事调 perms.script_owned 严格 owner 闸 —— **绝不可用
     _user_can_read_script(订阅者可读,写会越权)**。非 owner 立即返回友好失败串。
  ③ 写成功后尽量 _write_commit 审计(照 script_edit 的 kind)。
  ④ 整个执行 try/except 包裹,返回友好失败串,绝不向 dispatcher 抛异常。

jsonb vs text[] 绑定(照搬 script_edit 的契约,搞反 = 写坏列):
  · worldbook  keys/regex_keys/character_filter/scene_filter = jsonb 字符串数组 → Jsonb([...])
  · canon      aliases = jsonb 字符串数组、attrs = jsonb 开放对象 → Jsonb(...)
  · anchor     keywords = PostgreSQL 原生 text[] → 参数直接绑 Python list,绝不 Jsonb/json.dumps
  · npc card   aliases/sample_dialogue/tags 由 character_cards.upsert 内部 Jsonb 化,本层不碰
"""
from __future__ import annotations

import json
from typing import Any

from tools_dsl.command_dispatcher import ToolSpec, get_registry

# 读工具的 origin:照搬现有 script 读工具(get_script_chapters 等)的 _READ_ANY_ORIGIN。
# console_assistant(MD 编辑器右栏 agent)是 user-driven,所有读工具都对它开放。
_SCRIPT_READ_ORIGINS = frozenset({
    "ui_button", "api_direct", "llm_set", "llm_chat", "mcp_call", "console_assistant",
})

# 写工具的 origin:UI 按钮 / 直连 API / 侧栏控制台助手(MD 编辑器右栏 agent)。
# 不含 llm_chat / llm_chat_json_op / autonomous_agent —— 剧情流式输出和黑天鹅代理不该直写剧本库。
_SCRIPT_WRITE_ORIGINS = frozenset({"ui_button", "api_direct", "console_assistant"})


def _resolve_sid(script_id: int | None, args: dict) -> int | None:
    """sid = script_id(服务端绑定,首选) or args.get("script_id")。返回 int 或 None。"""
    sid = script_id if script_id is not None else args.get("script_id")
    if sid is None:
        return None
    try:
        return int(sid)
    except (TypeError, ValueError):
        return None


def _user_can_read_script(db, sid: int, user_id: int) -> bool:
    """剧本读权限:owner 或订阅者(照搬 command_tools_queries._user_can_read_script)。
    读工具用这个,**不是** script_owned 写闸 —— 订阅者本就有读权。"""
    return db.execute(
        "select 1 from scripts s where s.id = %s and ("
        "  s.owner_id = %s or s.id in (select script_id from user_script_subscriptions where user_id = %s))",
        (int(sid), user_id, user_id),
    ).fetchone() is not None


# ────────────────────────────────────────────────────────────────────────────
# R) script 级「列出」读工具(rule 4 同步前定位现有 id;读级闸,destructive=False)
# 列/表口径照搬 platform_app/api/scripts.py 的 LIST 端点,保证字段与前端文件树一致。
# ────────────────────────────────────────────────────────────────────────────


def _t_list_worldbook_entries(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    """紧凑列出剧本世界书条目(供 rule 4 定位现有 entry_id 去更新)。

    口径照搬 GET /api/scripts/{id}/worldbook(_db_select_worldbook_entries 的列子集);
    probability 是 numeric → ::float8 防 Decimal 不可 JSON 序列化。结果上限 300 防爆。
    """
    sid = _resolve_sid(script_id, args)
    if sid is None:
        return "失败: script_id 必填"
    try:
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            if not _user_can_read_script(db, sid, user_id):
                return f"失败 (权限): 剧本 #{sid} 不属于当前用户或未订阅"
            rows = db.execute(
                "select id as entry_id, title, keys, enabled, "
                "       insertion_position, priority, probability::float8 as probability "
                "from worldbook_entries where script_id = %s "
                "order by priority desc, id desc limit 300",
                (sid,),
            ).fetchall() or []
        if not rows:
            return f"(剧本 #{sid} 暂无世界书条目。要新建用 upsert_worldbook_entry 不传 entry_id。)"
        return json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2, default=str)
    except Exception as exc:
        return f"失败: {type(exc).__name__}: {exc}"


def _t_list_anchors(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    """紧凑列出剧本时间线锚点(供 rule 4 定位现有 anchor_id 去更新)。

    口径照搬 GET /api/scripts/{id}/timeline(script_timeline_anchors)。
    注意:该表是「剧本只读骨架(原著时间线)」,本身没有 anchor_type/satisfied 列
    (kind/satisfied 是 save 级收束机制 kb_* 表的语义,不在 script 级),故不返回这两个字段。
    用 label(=story_time_label)+ story_phase + 章节区间 + 标题/摘要定位即够;
    keywords/confidence 一并返回,便于 update_anchor 增量改(否则改这两项只能盲写覆盖)。
    结果上限 300 防爆。
    """
    sid = _resolve_sid(script_id, args)
    if sid is None:
        return "失败: script_id 必填"
    try:
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            if not _user_can_read_script(db, sid, user_id):
                return f"失败 (权限): 剧本 #{sid} 不属于当前用户或未订阅"
            rows = db.execute(
                "select id as anchor_id, story_time_label as label, story_phase, "
                "       chapter_min, chapter_max, sample_title, sample_summary, "
                "       keywords, confidence "
                "from script_timeline_anchors where script_id = %s "
                "order by chapter_min asc, id asc limit 300",
                (sid,),
            ).fetchall() or []
        if not rows:
            return f"(剧本 #{sid} 暂无时间线锚点。)"
        return json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2, default=str)
    except Exception as exc:
        return f"失败: {type(exc).__name__}: {exc}"


def _t_list_canon_entities(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    """紧凑列出剧本 canon 实体(供 rule 4 按 logical_key 定位去 upsert)。

    口径照搬 GET /api/scripts/{id}/canon-entities(kb_canon_entities,_CANON_LIST_COLS 的列子集)。
    结果上限 300 防爆。
    """
    sid = _resolve_sid(script_id, args)
    if sid is None:
        return "失败: script_id 必填"
    try:
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            if not _user_can_read_script(db, sid, user_id):
                return f"失败 (权限): 剧本 #{sid} 不属于当前用户或未订阅"
            rows = db.execute(
                "select logical_key, name, full_name, type, entity_subtype, importance "
                "from kb_canon_entities where script_id = %s "
                "order by importance desc, id desc limit 300",
                (sid,),
            ).fetchall() or []
        if not rows:
            return f"(剧本 #{sid} 暂无 canon 实体。要新建用 upsert_canon_entity 给 logical_key+name+type。)"
        return json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2, default=str)
    except Exception as exc:
        return f"失败: {type(exc).__name__}: {exc}"


def _t_get_chapter_context(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    """一次性取「该章相关编辑环境」(相关世界书/人物/词条/时点/前情)——编辑前建立设定认知,
    免去逐个 list_*/get_* 多轮往返、也防 agent 凭空写。复用阶段1 build_editor_environment,
    按 chapter_index 防剧透截断(只给 ≤当前章 的设定/历史)。"""
    sid = _resolve_sid(script_id, args)
    if sid is None:
        return "失败: script_id 必填"
    ci_raw = args.get("chapter_index")
    try:
        ci = int(ci_raw) if ci_raw is not None else None
    except (TypeError, ValueError):
        ci = None
    try:
        from platform_app.db import connect, init_db
        init_db()
        scan = ""
        with connect() as db:
            if not _user_can_read_script(db, sid, user_id):
                return f"失败 (权限): 剧本 #{sid} 不属于当前用户或未订阅"
            if ci is not None:
                row = db.execute(
                    "select content from script_chapters where script_id=%s and chapter_index=%s",
                    (sid, ci),
                ).fetchone()
                scan = str((row or {}).get("content") or "")[:12000]
        from console_assistant.editor_context import build_editor_environment
        env = build_editor_environment(sid, scan, ci)
        return env or "(该章未提取到相关设定;可能本章正文为空,或世界书/人物卡/canon 尚未建立。)"
    except Exception as exc:
        return f"失败: {type(exc).__name__}: {exc}"


def _t_get_chapter_text(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    """读取某章【完整正文】(script_chapters.content)。修锚点/核对设定/写作参考前读真正文,而不是只看
    可能被垃圾污染的摘要(群反馈 行者无疆:之前 agent 没有直接读完整章节正文的工具)。owner/订阅可读;
    长章用 offset 分段续读。"""
    sid = _resolve_sid(script_id, args)
    if sid is None:
        return "失败: script_id 必填"
    try:
        ci = int(args.get("chapter_index"))
    except (TypeError, ValueError):
        return "失败: chapter_index 必填(整数章号)"
    try:
        offset = max(0, int(args.get("offset") or 0))
    except (TypeError, ValueError):
        offset = 0
    try:
        max_chars = int(args.get("max_chars") or 12000)
    except (TypeError, ValueError):
        max_chars = 12000
    max_chars = max(500, min(max_chars, 20000))
    try:
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            if not _user_can_read_script(db, sid, user_id):
                return f"失败 (权限): 剧本 #{sid} 不属于当前用户或未订阅"
            row = db.execute(
                "select title, content from script_chapters where script_id=%s and chapter_index=%s",
                (sid, ci),
            ).fetchone()
        if not row:
            return f"失败: 剧本 #{sid} 第 {ci} 章不存在"
        title = str(row.get("title") or "")
        content = str(row.get("content") or "")
        total = len(content)
        if total == 0:
            return f"【第{ci}章 {title}】(本章正文为空)"
        chunk = content[offset:offset + max_chars]
        end = offset + len(chunk)
        head = f"【第{ci}章 {title}】 正文共 {total} 字符,本段 [{offset}, {end})"
        head += (f";还有更多 → 再调本工具传 offset={end} 续读" if end < total else ";(本章已读完)")
        return head + "\n\n" + chunk
    except Exception as exc:
        return f"失败: {type(exc).__name__}: {exc}"


def _t_search_manuscript(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    """全书检索:在剧本所有章节正文里搜一个词/短语/正则,返回命中的【章号 + 标题 + 上下文片段 + 字符偏移】。

    这是「先读后写、避免与全书矛盾」真正落地的关键工具(群反馈 行者无疆:agent 之前只能逐章硬读,
    无法跨全书核对)。审稿查重复、查前文是否已交代过某设定、找某人物/物件上次出场、核对伏笔有没有
    回收 —— 都先用它一次定位,再用 get_chapter_text(chapter_index, offset=@值) 精读上下文。
    默认大小写无关的子串匹配;regex=true 时按 Python 正则。可用 chapter_min/chapter_max 缩范围。
    只读,owner/订阅者可用。"""
    sid = _resolve_sid(script_id, args)
    if sid is None:
        return "失败: script_id 必填"
    query = str(args.get("query") or "").strip()
    if not query:
        return "失败: query 必填(要搜索的词/短语/正则)"
    use_regex = bool(args.get("regex"))

    def _opt_int(key: str, default: int, lo: int, hi: int) -> int:
        try:
            return max(lo, min(int(args.get(key)), hi))
        except (TypeError, ValueError):
            return default

    max_results = _opt_int("max_results", 30, 1, 100)
    ctx_chars = _opt_int("context_chars", 60, 20, 200)

    def _opt_chapter(key: str):
        try:
            return int(args.get(key))
        except (TypeError, ValueError):
            return None
    ch_min, ch_max = _opt_chapter("chapter_min"), _opt_chapter("chapter_max")

    import re as _re
    try:
        pat = _re.compile(query if use_regex else _re.escape(query), _re.I)
    except _re.error as exc:
        return f"失败: 正则无效: {exc}"

    HARD_SCAN_CAP = 1000  # 防病态正则(如匹配每个字符)在 485 万字全书上炸开;到顶即停并提示收窄
    try:
        from platform_app.db import connect, init_db
        init_db()
        where = "script_id=%s"
        params: list[Any] = [sid]
        if ch_min is not None:
            where += " and chapter_index>=%s"
            params.append(ch_min)
        if ch_max is not None:
            where += " and chapter_index<=%s"
            params.append(ch_max)
        # 子串搜索把粗筛下推给 DB(ILIKE 是超集,Python 再精确匹配 → 无漏判);正则则全取在 Python 扫。
        if not use_regex:
            where += " and content ILIKE %s"
            params.append(f"%{query}%")
        with connect() as db:
            if not _user_can_read_script(db, sid, user_id):
                return f"失败 (权限): 剧本 #{sid} 不属于当前用户或未订阅"
            rows = db.execute(
                f"select chapter_index, title, content from script_chapters where {where} order by chapter_index",
                tuple(params),
            ).fetchall()
        hits: list[str] = []
        total_hits = 0
        chapters_with_hits = 0
        capped = False
        for row in rows:
            ci = row.get("chapter_index")
            title = str(row.get("title") or "")
            content = str(row.get("content") or "")
            if not content:
                continue
            ch_hit = False
            for m in pat.finditer(content):
                total_hits += 1
                if len(hits) < max_results:
                    ch_hit = True
                    s = max(0, m.start() - ctx_chars)
                    e = min(len(content), m.end() + ctx_chars)
                    snippet = content[s:e].replace("\n", " ").strip()
                    prefix = "…" if s > 0 else ""
                    suffix = "…" if e < len(content) else ""
                    hits.append(f"【第{ci}章 {title}】@{m.start()}: {prefix}{snippet}{suffix}")
                if total_hits >= HARD_SCAN_CAP:
                    capped = True
                    break
            if ch_hit:
                chapters_with_hits += 1
            if capped:
                break
        if not hits:
            scanned = len(rows) if use_regex else f"{len(rows)} 个含「{query}」的"
            return f"全书检索「{query}」:0 命中(扫了 {scanned} 章)。"
        listed_note = ""
        if len(hits) < total_hits or capped:
            listed_note = (f"(命中较多,只列前 {len(hits)} 条" +
                           ("、且已达扫描上限" if capped else "") +
                           ";可加 chapter_min/chapter_max 收窄或调 max_results)")
        head = (f"全书检索「{query}」:{'≥' if capped else ''}{total_hits} 处命中,分布在 "
                f"{chapters_with_hits} 章{listed_note}。"
                f"用 get_chapter_text(chapter_index, offset=@值) 精读上下文。")
        return head + "\n" + "\n".join(hits)
    except Exception as exc:
        return f"失败: {type(exc).__name__}: {exc}"


def _t_extract_from_selection(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    """对用户选中的一段正文跑结构化提取(复用 extract/per_chapter.extract_chapter 的提取器,含其
    反史实/反编造/中文别名归并铁律),返回提议的人物/势力/地点/概念/事件/摘要 —— 供 agent 按用户意愿
    用 upsert_canon_entity / update_npc_card / upsert_worldbook_entry / create_anchor 落库(经写入权限闸)。
    本工具只产提议、不写库;会调一次提取 LLM(BYOK)。这是「把提取器拆成选区工具」的核心(作者优先)。"""
    sid = _resolve_sid(script_id, args)
    if sid is None:
        return "失败: script_id 必填"
    text = str(args.get("text") or "").strip()
    if not text:
        return "失败: text 必填(要提取信息的选中正文)"
    text = text[:8000]
    try:
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            if not _user_can_read_script(db, sid, user_id):
                return "失败(权限): 剧本不属于当前用户或未订阅"
            known = [r["name"] for r in (db.execute(
                "select name from kb_canon_entities where script_id=%s and coalesce(name,'')<>'' "
                "order by importance desc, id asc limit 200", (sid,)).fetchall() or [])]
        from agents._harness import resolve_api_and_model
        api_id, model_real = resolve_api_and_model(
            user_id, api_pref_key="extractor.api_id", model_pref_key="extractor.model_real_name")
        if not api_id or not model_real:
            return "失败: 未找到可用的提取模型,请到「设置 → 模块模型」配置 extractor(或编辑器/GM)模型后重试。"
        from extract.llm import ExtractLLM
        from extract.per_chapter import extract_chapter
        llm = ExtractLLM(model=str(model_real), api_id=str(api_id), user_id=user_id,
                         script_id=sid, algorithm="editor_selection")
        ex = extract_chapter(llm, 0, text, era="", known_entities=known)
        if not getattr(ex, "raw_ok", False):
            return "提取失败:模型未返回有效结构,可换更强的提取模型或缩短选区后重试。"
        proposal = {
            "summary": getattr(ex, "chapter_summary", ""),
            "entities": getattr(ex, "entities", []),       # type=character/faction/location/...,含 full_name/aliases/identity/background/subtype/parent
            "concepts": getattr(ex, "concepts", []),
            "events": getattr(ex, "events", []),
            "relationships": getattr(ex, "relationships", []),
        }
        body = json.dumps(proposal, ensure_ascii=False, indent=2)[:6000]
        return ("【从选中段提取到的提议(尚未写库)】先一句话向用户说清要建/改哪些,再落库(写入受三级权限闸):"
                "entities 里 type=character → upsert_canon_entity 或 generate_character_card_draft 后建 NPC 卡;"
                "faction/location/concept → upsert_canon_entity 或 upsert_worldbook_entry;events → create_anchor。\n"
                + body)
    except Exception as exc:
        try:
            from agents.provider_errors import classify_provider_error
            k = classify_provider_error(exc)
            if k:
                return f"提取失败:{k[1]}"
        except Exception:
            pass
        return f"提取失败:{type(exc).__name__}: {str(exc)[:120]}"


# ────────────────────────────────────────────────────────────────────────────
# 1) update_script_chapter — 覆盖整章正文(destructive=True)
# ────────────────────────────────────────────────────────────────────────────


def _t_update_script_chapter(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    sid = _resolve_sid(script_id, args)
    if sid is None:
        return "失败: script_id 必填"
    chapter_index = args.get("chapter_index")
    if chapter_index is None:
        return "失败: chapter_index 必填"
    try:
        ci = int(chapter_index)
    except (TypeError, ValueError):
        return "失败: chapter_index 必须是整数"
    title = args.get("title")
    content = args.get("content")
    volume_title = args.get("volume_title")
    if title is None and content is None and volume_title is None:
        return "失败: 至少要传 title / content / volume_title 之一"
    try:
        from platform_app.db import connect, init_db
        from platform_app.perms import script_owned
        init_db()
        # ② 严格 owner 闸(在 update_chapter 内部也会再查一次 script_owned,这里前置一道
        #    给出统一的工具友好失败串;update_chapter 自身的 ValueError 兜底捕获)。
        prior: dict | None = None
        with connect() as db:
            if not script_owned(db, sid, user_id):
                return "失败(权限): 剧本不属于当前用户"
            # 撤销快照:落库前抓本章当前值,存进 commit.payload.before,让作者一键撤销 AI 改动。
            prior = db.execute(
                "select title, content, volume_title from script_chapters where script_id=%s and chapter_index=%s",
                (sid, ci),
            ).fetchone()
        # ③ 复用现成写函数 platform_app.script_import.update_chapter(自带 owner 校验 + word_count 同步)。
        from platform_app.script_import import update_chapter
        update_chapter(
            user_id, sid, ci,
            title=(str(title) if title is not None else None),
            content=(str(content) if content is not None else None),
            volume_title=(str(volume_title) if volume_title is not None else None),
        )
        # 审计 + 撤销:章节正文走 script_commits(kind=chapter_edit),payload.before 存改前全文供一键撤销。
        try:
            from platform_app.api.script_edit import _write_commit
            changed = [k for k in ("title", "content", "volume_title") if args.get(k) is not None]
            before_content = str((prior or {}).get("content") or "")
            # 内容护栏:超长正文(>100k)不存 before,撤销不可用(极罕见;避免 commit jsonb 爆炸)。
            undoable = bool(prior) and len(before_content) <= 100000
            before_payload = {
                "title": (prior or {}).get("title"),
                "content": before_content if undoable else None,
                "volume_title": (prior or {}).get("volume_title"),
            } if prior else None
            with connect() as adb:
                if script_owned(adb, sid, user_id):
                    _write_commit(
                        adb, script_id=sid, user_id=user_id,
                        kind="chapter_edit",
                        message=f"编辑章节 #{ci}",
                        payload={
                            "table": "script_chapters", "op": "edit",
                            "ids": {"chapter_index": ci},
                            "fields": changed,
                            "before": before_payload,
                            "undoable": undoable,
                            "is_new": prior is None,
                        },
                    )
                    adb.commit()
        except Exception:
            pass  # 审计失败不影响写主流程
        return f"已更新章节 #{ci}(剧本 #{sid})"
    except ValueError as exc:
        return f"失败: {exc}"
    except Exception as exc:
        return f"失败: {type(exc).__name__}: {exc}"


# ────────────────────────────────────────────────────────────────────────────
# 2) upsert_worldbook_entry — 创建(无 entry_id)/ 更新(有 entry_id)
# ────────────────────────────────────────────────────────────────────────────


def _strlist(v: Any) -> list[str]:
    return [str(x) for x in v] if isinstance(v, list) else []


def _wb_upsert_one(db: Any, sid: int, user_id: int, args: dict) -> dict:
    """单条世界书 create/update 核心:在已开连接 + 已过 owner 闸内执行,**不 commit**(由调用方提交)。
    返回 {ok, id, action:'created'|'updated', title, error}。供单条工具与批量工具共用同一代码路径。"""
    from psycopg.types.json import Jsonb
    from platform_app.api.script_edit import _write_commit
    entry_id = args.get("entry_id")
    title = args.get("title")
    if not entry_id and not (title and str(title).strip()):
        return {"ok": False, "id": None, "action": None, "title": "", "error": "创建世界书条目必须提供 title"}

    if entry_id:
        # ── 更新现有条目 ──
        try:
            eid = int(entry_id)
        except (TypeError, ValueError):
            return {"ok": False, "id": None, "action": None, "title": "", "error": "entry_id 必须是整数"}
        before = db.execute(
            "select id, title, content, priority, token_budget, sticky_turns, cooldown_turns, "
            "probability::float8 as probability, enabled, keys, regex_keys, character_filter, "
            "scene_filter, insertion_position from worldbook_entries where id = %s and script_id = %s",
            (eid, sid),
        ).fetchone()
        if not before:
            return {"ok": False, "id": eid, "action": None, "title": "", "error": f"条目 #{eid} 不存在或不属于剧本 #{sid}"}
        # 撤销快照:存改前全字段,供作者一键撤回 AI 对世界书的改动(与章节撤销同款安全网)。
        _wb_before = {k: before[k] for k in (
            "title", "content", "priority", "token_budget", "sticky_turns", "cooldown_turns",
            "probability", "enabled", "keys", "regex_keys", "character_filter", "scene_filter",
            "insertion_position")}
        sets, params = [], []
        for col in ("title", "content", "insertion_position"):
            if col in args and args[col] is not None:
                sets.append(f"{col}=%s")
                params.append(str(args[col]))
        for col in ("priority", "token_budget", "sticky_turns", "cooldown_turns"):
            if col in args and args[col] is not None:
                sets.append(f"{col}=%s")
                params.append(int(args[col]))
        if args.get("probability") is not None:
            sets.append("probability=%s")
            params.append(float(args["probability"]))
        if args.get("enabled") is not None:
            sets.append("enabled=%s")
            params.append(bool(args["enabled"]))
        for col in ("keys", "regex_keys", "character_filter", "scene_filter"):
            if col in args and isinstance(args[col], list):
                sets.append(f"{col}=%s")
                params.append(Jsonb(_strlist(args[col])))
        if not sets:
            return {"ok": False, "id": eid, "action": None, "title": before["title"], "error": "没有要更新的字段"}
        sets.append("updated_at=now()")
        params.extend([eid, sid])
        db.execute(
            f"update worldbook_entries set {', '.join(sets)} where id=%s and script_id=%s",
            tuple(params),
        )
        try:
            _write_commit(db, script_id=sid, user_id=user_id, kind="worldbook_edit",
                          message=f"编辑 worldbook #{eid}",
                          payload={"table": "worldbook_entries", "op": "edit", "ids": {"entry_id": eid},
                                   "before": _wb_before, "undoable": True})
        except Exception:
            pass
        return {"ok": True, "id": eid, "action": "updated", "title": (args.get("title") or before["title"]), "error": None}

    # ── 创建新条目 ──
    t = str(title).strip()
    # book_id 是遗留可空列(migration 85);归属看 script_id,没有 books 行就 NULL。
    book = db.execute("select id from books where script_id = %s", (sid,)).fetchone()
    book_id = int(book["id"]) if book else None
    new_row = db.execute(
        """
        insert into worldbook_entries
          (book_id, script_id, title, content, priority, enabled, metadata,
           keys, regex_keys, character_filter, scene_filter,
           token_budget, sticky_turns, cooldown_turns, probability, insertion_position)
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        on conflict (script_id, title) do nothing
        returning id
        """,
        (
            book_id, sid, t,
            str(args.get("content") or ""),
            int(args["priority"]) if args.get("priority") is not None else 50,
            bool(args["enabled"]) if args.get("enabled") is not None else True,
            Jsonb({"source": "editor"}),  # 标记编辑器写入,重建保留不删(harness 审计 P1)
            Jsonb(_strlist(args.get("keys"))),
            Jsonb(_strlist(args.get("regex_keys"))),
            Jsonb(_strlist(args.get("character_filter"))),
            Jsonb(_strlist(args.get("scene_filter"))),
            int(args["token_budget"]) if args.get("token_budget") is not None else 600,
            int(args["sticky_turns"]) if args.get("sticky_turns") is not None else 0,
            int(args["cooldown_turns"]) if args.get("cooldown_turns") is not None else 0,
            float(args["probability"]) if args.get("probability") is not None else 100.0,
            str(args.get("insertion_position") or "worldbook"),
        ),
    ).fetchone()
    if not new_row:
        # title 已存在(unique(script_id,title) 冲突 → do nothing)→ 幂等不重复建。
        return {"ok": False, "id": None, "action": None, "title": t,
                "error": f"剧本 #{sid} 已有同名条目「{t}」(要改它请带 entry_id)"}
    new_id = int(new_row["id"])
    try:
        _write_commit(db, script_id=sid, user_id=user_id, kind="worldbook_add",
                      message=f"新增 worldbook: {t}",
                      payload={"table": "worldbook_entries", "op": "add", "ids": {"entry_id": new_id}})
    except Exception:
        pass
    return {"ok": True, "id": new_id, "action": "created", "title": t, "error": None}


def _t_upsert_worldbook_entry(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    sid = _resolve_sid(script_id, args)
    if sid is None:
        return "失败: script_id 必填"
    try:
        from platform_app.db import connect, init_db
        from platform_app.perms import script_owned
        init_db()
        with connect() as db:
            if not script_owned(db, sid, user_id):  # ② 严格 owner 闸
                return "失败(权限): 剧本不属于当前用户"
            r = _wb_upsert_one(db, sid, user_id, args)
            db.commit()
        _invalidate_worldbook_cache(sid)
        if not r["ok"]:
            extra = "。要改它请带 entry_id(先用 list_worldbook_entries 拿 entry_id),不要重复新建。" if "同名" in (r.get("error") or "") else ""
            return f"失败: {r['error']}{extra}"
        return f"已{'更新' if r['action'] == 'updated' else '创建'}世界书条目 #{r['id']}(剧本 #{sid})"
    except ValueError as exc:
        return f"失败: {exc}"
    except Exception as exc:
        return f"失败: {type(exc).__name__}: {exc}"


def _t_upsert_worldbook_entries(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    """批量创建/更新世界书条目 —— **一次工具调用、一次确认、一并落库**。
    根因:审查模式下 LLM 逐条调 upsert_worldbook_entry 时,只有第一条会被确认执行(确认流在首条 break),
    其余被静默丢弃但 LLM 误报已成功。改由本工具一次传 entries 数组,每条独立 savepoint(一条失败不连累其余),
    返回逐条真实结果,杜绝「只成功第一条却说全成功」。"""
    sid = _resolve_sid(script_id, args)
    if sid is None:
        return "失败: script_id 必填"
    entries = args.get("entries")
    if not isinstance(entries, list) or not entries:
        return ("失败: 没收到 entries(可能单次条数过多,整个工具调用超输出长度被截断了)。"
                "请每次只传 ≤6 条,把更多条目分成多次调用。每项是一条世界书条目对象(新建带 title、改带 entry_id)。")
    if len(entries) > 12:
        return "失败: 单次条数过多易被截断,请每次 ≤6 条、分多次调用"
    try:
        from platform_app.db import connect, init_db
        from platform_app.perms import script_owned
        init_db()
        results: list[dict] = []
        with connect() as db:
            if not script_owned(db, sid, user_id):
                return "失败(权限): 剧本不属于当前用户"
            for i, e in enumerate(entries):
                if not isinstance(e, dict):
                    results.append({"ok": False, "title": f"#{i}", "error": "条目不是对象"})
                    continue
                try:
                    with db.transaction():   # 每条一个 savepoint:一条失败回滚自身,不连累其他
                        results.append(_wb_upsert_one(db, sid, user_id, e))
                except Exception as ex:
                    results.append({"ok": False, "title": str(e.get("title") or f"#{i}"), "error": f"{type(ex).__name__}: {ex}"})
            db.commit()
        _invalidate_worldbook_cache(sid)
        ok = [r for r in results if r.get("ok")]
        bad = [r for r in results if not r.get("ok")]
        lines = [f"批量世界书:成功 {len(ok)}/{len(results)} 条(剧本 #{sid})"]
        for r in ok:
            lines.append(f"- {'更新' if r.get('action') == 'updated' else '创建'} #{r.get('id')} {r.get('title', '')}")
        for r in bad:
            lines.append(f"- 失败「{r.get('title', '')}」:{r.get('error')}")
        return "\n".join(lines)
    except ValueError as exc:
        return f"失败: {exc}"
    except Exception as exc:
        return f"失败: {type(exc).__name__}: {exc}"


def _invalidate_worldbook_cache(script_id: int) -> None:
    """worldbook 改动后清 constant 层缓存(照 script_edit 的做法)。"""
    try:
        from gm_serving.context_inject import invalidate_constant_cache
        invalidate_constant_cache(script_id)
    except Exception:
        pass


# ────────────────────────────────────────────────────────────────────────────
# 3) update_npc_card — 复用 character_cards.upsert(传 id=card_id)
# ────────────────────────────────────────────────────────────────────────────


def _t_update_npc_card(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    sid = _resolve_sid(script_id, args)
    if sid is None:
        return "失败: script_id 必填"
    card_id = args.get("card_id")
    if not card_id:
        return "失败: card_id 必填(先用 list_script_npcs 拿到角色卡 id)"
    try:
        cid = int(card_id)
    except (TypeError, ValueError):
        return "失败: card_id 必须是整数"
    try:
        from platform_app.db import connect, init_db
        from platform_app.perms import script_owned
        init_db()
        # ② 严格 owner 闸(upsert_character_card 内部用 _require_script_owner 也会再查,
        #    这里前置一道给统一友好失败串)。
        with connect() as db:
            if not script_owned(db, sid, user_id):
                return "失败(权限): 剧本不属于当前用户"
            # 取现有卡作为基底:upsert_character_card 是「全量覆盖式」,缺省字段会被清空,
            # 故先读现卡、再用 args 里出现的字段叠加,避免漏传字段被抹掉。name 是必填(空会报错)。
            existing = db.execute(
                "select * from character_cards where id = %s and script_id = %s and card_type='npc'",
                (cid, sid),
            ).fetchone()
            if not existing:
                return f"失败: 角色卡 #{cid} 不存在或不属于剧本 #{sid}"
        base = dict(existing)
        # 撤销快照:存改前全字段(供作者一键撤回 AI 对角色卡的改动)。upsert 是全量覆盖式,
        # 把这些原值喂回即可还原。
        _card_before = {k: base.get(k) for k in (
            "name", "full_name", "aliases", "identity", "appearance", "personality",
            "speech_style", "current_status", "secrets", "background", "sample_dialogue",
            "importance", "first_revealed_chapter", "enabled")}
        _card_before["metadata"] = base.get("metadata") or {}
        # 只接受这些字段(不收 avatar_path —— 头像走专用端点)。
        editable = (
            "name", "full_name", "aliases", "identity", "appearance", "personality",
            "speech_style", "current_status", "secrets", "background", "sample_dialogue",
            "tags", "importance", "first_revealed_chapter", "enabled",
        )
        payload: dict[str, Any] = {"id": cid}
        for k in editable:
            if k in args and args[k] is not None:
                payload[k] = args[k]
            elif k in base and base[k] is not None:
                payload[k] = base[k]
        # name 必填:确保有值(取 args 或现卡)。
        if not (str(payload.get("name") or "").strip()):
            return "失败: name 不能为空"
        # tags 不是 character_cards 直接列(存进 metadata),upsert 不读 tags → 落进 metadata。
        if "tags" in payload:
            meta = dict(base.get("metadata") or {})
            meta["tags"] = _strlist(payload.pop("tags"))
            payload["metadata"] = meta
        # ③ 复用 character_cards.upsert(内部 _require_script_owner + Jsonb 化 aliases/sample_dialogue)。
        from platform_app.knowledge.character_cards import upsert_character_card
        upsert_character_card(user_id, sid, payload)
        # 审计
        try:
            from platform_app.api.script_edit import _write_commit
            with connect() as adb:
                if script_owned(adb, sid, user_id):
                    _write_commit(
                        adb, script_id=sid, user_id=user_id, kind="card_edit",
                        message=f"编辑 NPC 角色卡 #{cid}",
                        payload={"table": "character_cards", "op": "edit",
                                 "ids": {"card_id": cid},
                                 "fields": [k for k in editable if args.get(k) is not None],
                                 "before": _card_before, "undoable": True},
                    )
                    adb.commit()
        except Exception:
            pass
        return f"已更新 NPC 角色卡 #{cid}(剧本 #{sid})"
    except ValueError as exc:
        return f"失败: {exc}"
    except Exception as exc:
        return f"失败: {type(exc).__name__}: {exc}"


# ────────────────────────────────────────────────────────────────────────────
# 4) update_anchor — keywords 是原生 text[](直接绑 Python list)
# ────────────────────────────────────────────────────────────────────────────


def _t_update_anchor(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    sid = _resolve_sid(script_id, args)
    if sid is None:
        return "失败: script_id 必填"
    anchor_id = args.get("anchor_id")
    if not anchor_id:
        return "失败: anchor_id 必填"
    try:
        aid = int(anchor_id)
    except (TypeError, ValueError):
        return "失败: anchor_id 必须是整数"
    try:
        from platform_app.api.script_edit import _write_commit
        from platform_app.db import connect, init_db
        from platform_app.perms import script_owned
        init_db()
        with connect() as db:
            # ② 严格 owner 闸
            if not script_owned(db, sid, user_id):
                return "失败(权限): 剧本不属于当前用户"
            before = db.execute(
                "select id, story_time_label from script_timeline_anchors "
                "where id = %s and script_id = %s",
                (aid, sid),
            ).fetchone()
            if not before:
                return f"失败: 锚点 #{aid} 不存在或不属于剧本 #{sid}"
            sets, params = [], []
            # story_summary 在 script_timeline_anchors 里列名是 sample_summary;这里直接收 sample_summary。
            for col in ("story_phase", "story_time_label", "sample_title", "sample_summary"):
                if col in args and args[col] is not None:
                    sets.append(f"{col}=%s")
                    params.append(str(args[col]))
            for col in ("chapter_min", "chapter_max"):
                if col in args and args[col] is not None:
                    sets.append(f"{col}=%s")
                    params.append(int(args[col]))
            if args.get("confidence") is not None:
                sets.append("confidence=%s")
                params.append(float(args["confidence"]))
            if "keywords" in args and isinstance(args["keywords"], list):
                # keywords 是 PostgreSQL 原生 text[]:参数直接绑 Python list,
                # psycopg 按数组写回;绝不 Jsonb / json.dumps(那会写坏 text[] 列)。
                sets.append("keywords=%s")
                params.append([str(x) for x in args["keywords"]])
            if not sets:
                return "失败: 没有要更新的字段"
            sets.append("updated_at=now()")
            params.extend([aid, sid])
            db.execute(
                f"update script_timeline_anchors set {', '.join(sets)} "
                f"where id=%s and script_id=%s",
                tuple(params),
            )
            # ③ 审计
            try:
                _write_commit(
                    db, script_id=sid, user_id=user_id, kind="anchor_edit",
                    message=f"编辑 anchor #{aid}",
                    payload={"table": "script_timeline_anchors", "op": "edit",
                             "ids": {"anchor_id": aid}},
                )
            except Exception:
                pass
            db.commit()
        return f"已更新时间线锚点 #{aid}(剧本 #{sid})"
    except ValueError as exc:
        return f"失败: {exc}"
    except Exception as exc:
        return f"失败: {type(exc).__name__}: {exc}"


def _t_create_anchor(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    """新建时间线锚点 —— 编辑器续写出「全新事件/时间节点」时用。

    与 update_anchor(只改已有)互补:本工具 INSERT 一行 source='editor' 的锚点,
    **时间线重建不会删它**(原著骨架 source='novel' 才会被删后重建)。
    唯一键 (script_id, story_phase, story_time_label):撞了 → do nothing + 提示改用 update_anchor。
    必填 story_time_label + chapter_min + chapter_max(该事件大致章节);story_phase 默认空。
    """
    sid = _resolve_sid(script_id, args)
    if sid is None:
        return "失败: script_id 必填"
    label = str(args.get("story_time_label") or "").strip()
    if not label:
        return "失败: story_time_label 必填(新事件的时间/节点名)"
    if args.get("chapter_min") is None or args.get("chapter_max") is None:
        return "失败: chapter_min / chapter_max 必填(该事件大致所处章节)"
    try:
        cmin = int(args["chapter_min"]); cmax = int(args["chapter_max"])
    except (TypeError, ValueError):
        return "失败: chapter_min / chapter_max 必须是整数"
    if cmax < cmin:
        cmax = cmin
    phase = str(args.get("story_phase") or "")
    summary = str(args.get("sample_summary") or "")[:1900]
    title = str(args.get("sample_title") or "")[:200]
    try:
        confidence = float(args["confidence"]) if args.get("confidence") is not None else 0.7
    except (TypeError, ValueError):
        confidence = 0.7
    # keywords 是 PostgreSQL 原生 text[]:直接绑 Python list(绝不 Jsonb)。
    keywords = [str(x) for x in args["keywords"]] if isinstance(args.get("keywords"), list) else []
    try:
        from platform_app.api.script_edit import _write_commit
        from platform_app.db import connect, init_db
        from platform_app.perms import script_owned
        init_db()
        with connect() as db:
            # ② 严格 owner 闸(写)
            if not script_owned(db, sid, user_id):
                return "失败(权限): 剧本不属于当前用户"
            row = db.execute(
                """
                insert into script_timeline_anchors
                  (script_id, story_phase, story_time_label, chapter_min, chapter_max,
                   chapter_count, sample_title, sample_summary, keywords, confidence, source)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'editor')
                on conflict (script_id, story_phase, story_time_label) do nothing
                returning id
                """,
                (sid, phase, label, cmin, cmax, max(1, cmax - cmin + 1),
                 title, summary, keywords, confidence),
            ).fetchone()
            if not row:
                return (
                    f"失败: 剧本 #{sid} 已有同名节点「{label}」(阶段「{phase or '未分阶段'}」)。"
                    "要改它请用 update_anchor(先 list_anchors 拿 anchor_id),不要重复新建。"
                )
            aid = int(row["id"])
            try:
                _write_commit(
                    db, script_id=sid, user_id=user_id, kind="anchor_add",
                    message=f"新增 anchor「{label}」",
                    payload={"table": "script_timeline_anchors", "op": "add",
                             "ids": {"anchor_id": aid}, "source": "editor"},
                )
            except Exception:
                pass
            db.commit()
        return (
            f"已新建时间线锚点 #{aid}「{label}」(剧本 #{sid};来源 editor,"
            "时间线重建不会删它)"
        )
    except Exception as exc:
        return f"失败: {type(exc).__name__}: {exc}"


# ────────────────────────────────────────────────────────────────────────────
# 5) upsert_canon_entity — aliases/attrs 是 jsonb;按 logical_key upsert
# ────────────────────────────────────────────────────────────────────────────


def _t_upsert_canon_entity(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    sid = _resolve_sid(script_id, args)
    if sid is None:
        return "失败: script_id 必填"
    logical_key = (args.get("logical_key") or "")
    logical_key = str(logical_key).strip()
    if not logical_key:
        return "失败: logical_key 必填"
    try:
        from psycopg.types.json import Jsonb

        from platform_app.api.script_edit import _write_commit
        from platform_app.db import connect, init_db
        from platform_app.perms import script_owned
        init_db()
        with connect() as db:
            # ② 严格 owner 闸
            if not script_owned(db, sid, user_id):
                return "失败(权限): 剧本不属于当前用户"
            existing = db.execute(
                "select id from kb_canon_entities where script_id = %s and logical_key = %s",
                (sid, logical_key),
            ).fetchone()

            if existing:
                # ── 更新 ──
                sets, params = [], []
                for col in ("name", "full_name", "type", "summary", "identity",
                            "background", "entity_subtype", "parent_logical_key"):
                    if col in args and args[col] is not None:
                        sets.append(f"{col}=%s")
                        params.append(str(args[col]))
                if args.get("importance") is not None:
                    sets.append("importance=%s")
                    params.append(int(args["importance"]))
                if args.get("first_revealed_chapter") is not None:
                    sets.append("first_revealed_chapter=%s")
                    params.append(int(args["first_revealed_chapter"]))
                if args.get("public_knowledge") is not None:
                    sets.append("public_knowledge=%s")
                    params.append(bool(args["public_knowledge"]))
                # aliases = jsonb 字符串数组;attrs = jsonb 开放对象。
                if "aliases" in args and isinstance(args["aliases"], list):
                    sets.append("aliases=%s")
                    params.append(Jsonb(_strlist(args["aliases"])))
                if "attrs" in args and isinstance(args["attrs"], dict):
                    # 用户传了 attrs → jsonb 合并(保留既有键)+ 标 source='editor'。
                    sets.append("attrs = coalesce(attrs,'{}'::jsonb) || %s::jsonb")
                    params.append(Jsonb({**args["attrs"], "source": "editor"}))
                if not sets:
                    return "失败: 没有要更新的字段"
                # 有真实字段更新但没动 attrs → 仍标 source='editor',让重建保留这条用户编辑过的实体(harness 审计 P1)。
                if not any(s.startswith("attrs") for s in sets):
                    sets.append("attrs = coalesce(attrs,'{}'::jsonb) || '{\"source\":\"editor\"}'::jsonb")
                params.extend([sid, logical_key])
                db.execute(
                    f"update kb_canon_entities set {', '.join(sets)} "
                    f"where script_id=%s and logical_key=%s",
                    tuple(params),
                )
                try:
                    _write_commit(
                        db, script_id=sid, user_id=user_id, kind="canon_edit",
                        message=f"编辑 canon entity: {logical_key}",
                        payload={"table": "kb_canon_entities", "op": "edit",
                                 "ids": {"logical_key": logical_key}},
                    )
                except Exception:
                    pass
                db.commit()
                return f"已更新 canon 实体「{logical_key}」(剧本 #{sid})"
            else:
                # ── 创建 ── name/type 是 NOT NULL,创建时必须给。
                name = str(args.get("name") or "").strip()
                entity_type = str(args.get("type") or "").strip()
                if not name or not entity_type:
                    return "失败: 创建 canon 实体必须提供 name 和 type"
                aliases = args.get("aliases")
                attrs = args.get("attrs")
                new_row = db.execute(
                    """
                    insert into kb_canon_entities
                      (script_id, logical_key, name, full_name, type, summary, identity, background,
                       entity_subtype, parent_logical_key, importance,
                       aliases, attrs, first_revealed_chapter, public_knowledge)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (script_id, logical_key) do nothing
                    returning id
                    """,
                    (
                        sid, logical_key, name,
                        str(args.get("full_name") or ""),
                        entity_type,
                        str(args.get("summary") or ""),
                        str(args.get("identity") or ""),
                        str(args.get("background") or ""),
                        str(args.get("entity_subtype") or ""),
                        str(args.get("parent_logical_key") or ""),
                        int(args["importance"]) if args.get("importance") is not None else 0,
                        Jsonb(_strlist(aliases)) if isinstance(aliases, list) else Jsonb([]),
                        # 标 source='editor':重建保留不删(harness 审计 P1,attrs 是 canon 的开放 jsonb)
                        Jsonb({**(attrs if isinstance(attrs, dict) else {}), "source": "editor"}),
                        int(args["first_revealed_chapter"]) if args.get("first_revealed_chapter") is not None else 0,
                        bool(args["public_knowledge"]) if args.get("public_knowledge") is not None else False,
                    ),
                ).fetchone()
                if not new_row:
                    return f"失败: canon 实体「{logical_key}」已存在(并发创建?)"
                try:
                    _write_commit(
                        db, script_id=sid, user_id=user_id, kind="canon_add",
                        message=f"新增 canon entity: {logical_key}",
                        payload={"table": "kb_canon_entities", "op": "add",
                                 "ids": {"logical_key": logical_key}},
                    )
                except Exception:
                    pass
                db.commit()
                return f"已创建 canon 实体「{logical_key}」(剧本 #{sid})"
    except ValueError as exc:
        return f"失败: {exc}"
    except Exception as exc:
        return f"失败: {type(exc).__name__}: {exc}"


# ────────────────────────────────────────────────────────────────────────────
# 6) 新建 / 删除 缺口工具(create_script_chapter / create_npc_card /
#    delete_worldbook_entry / delete_anchor)—— 与 update_* 互补,补齐编辑器 agent 的增删能力。
# ────────────────────────────────────────────────────────────────────────────


def _t_create_script_chapter(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    """在剧本末尾「新增」一章(title 必填,content 可选)。续写新章时用。
    要改已有章用 update_script_chapter(先 get_script_chapters 看现有章号)。"""
    sid = _resolve_sid(script_id, args)
    if sid is None:
        return "失败: script_id 必填"
    title = str(args.get("title") or "").strip()
    if not title:
        return "失败: title 必填(新章标题)"
    content = str(args.get("content") or "")
    try:
        from platform_app.db import connect, init_db
        from platform_app.perms import script_owned
        init_db()
        with connect() as db:
            if not script_owned(db, sid, user_id):
                return "失败(权限): 剧本不属于当前用户"
            mx = db.execute(
                "select coalesce(max(chapter_index),0) as m from script_chapters where script_id=%s",
                (sid,),
            ).fetchone()
            ci = int(mx["m"]) + 1
            db.execute(
                "insert into script_chapters(script_id, chapter_index, title, content, word_count, "
                "volume_title, source_marker, confidence) values (%s,%s,%s,%s,%s,%s,'manual',1.0)",
                (sid, ci, title[:200], content, len(content), str(args.get("volume_title") or "")),
            )
            db.execute(
                "update scripts set chapter_count=(select count(*) from script_chapters where script_id=%s),"
                " updated_at=now() where id=%s", (sid, sid),
            )
            try:
                from platform_app.api.script_edit import _write_commit
                _write_commit(db, script_id=sid, user_id=user_id, kind="chapter_add",
                              message=f"新增章节 #{ci}「{title[:40]}」",
                              payload={"table": "script_chapters", "op": "add",
                                       "ids": {"chapter_index": ci}})
            except Exception:
                pass
            db.commit()
        return f"已新建章节 #{ci}「{title}」(剧本 #{sid},{len(content)} 字)"
    except Exception as exc:
        return f"失败: {type(exc).__name__}: {exc}"


def _t_create_npc_card(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    """为剧本「新建」一张 NPC 角色卡(name 必填)。可基于别的剧本/正文情节创建新角色。
    要改已有卡用 update_npc_card(先 list_script_npcs 拿 id)。"""
    sid = _resolve_sid(script_id, args)
    if sid is None:
        return "失败: script_id 必填"
    name = str(args.get("name") or "").strip()
    if not name:
        return "失败: name 必填(角色名)"
    try:
        from platform_app.db import connect, init_db
        from platform_app.perms import script_owned
        init_db()
        with connect() as db:
            if not script_owned(db, sid, user_id):
                return "失败(权限): 剧本不属于当前用户"
            dup = db.execute(
                "select id from character_cards where script_id=%s and card_type='npc' and name=%s limit 1",
                (sid, name),
            ).fetchone()
            if dup:
                return (f"失败: 剧本 #{sid} 已有同名 NPC「{name}」(#{dup['id']})。"
                        "要改它用 update_npc_card,不要重复新建。")
        payload: dict[str, Any] = {"name": name}
        for k in ("full_name", "aliases", "identity", "appearance", "personality",
                  "speech_style", "current_status", "secrets", "background",
                  "sample_dialogue", "importance", "first_revealed_chapter"):
            if k in args and args[k] is not None:
                payload[k] = args[k]
        if isinstance(args.get("tags"), list):
            payload["metadata"] = {"tags": _strlist(args["tags"])}
        from platform_app.knowledge.character_cards import upsert_character_card
        row = upsert_character_card(user_id, sid, payload)
        cid = int(row["id"]) if isinstance(row, dict) and row.get("id") else None
        try:
            from platform_app.api.script_edit import _write_commit
            with connect() as adb:
                if script_owned(adb, sid, user_id):
                    _write_commit(adb, script_id=sid, user_id=user_id, kind="card_add",
                                  message=f"新增 NPC 角色卡「{name}」",
                                  payload={"table": "character_cards", "op": "add",
                                           "ids": {"card_id": cid}})
                    adb.commit()
        except Exception:
            pass
        return f"已新建 NPC 角色卡「{name}」(#{cid},剧本 #{sid})" if cid else \
            f"已新建 NPC 角色卡「{name}」(剧本 #{sid})"
    except ValueError as exc:
        return f"失败: {exc}"
    except Exception as exc:
        return f"失败: {type(exc).__name__}: {exc}"


def _t_delete_worldbook_entry(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    """删除一条世界书条目(entry_id 必填,先 list_worldbook_entries 拿 id)。不可逆,删前向用户确认。"""
    sid = _resolve_sid(script_id, args)
    if sid is None:
        return "失败: script_id 必填"
    try:
        eid = int(args.get("entry_id"))
    except (TypeError, ValueError):
        return "失败: entry_id 必填且为整数(先 list_worldbook_entries 拿 id)"
    try:
        from platform_app.db import connect, init_db
        from platform_app.perms import script_owned
        init_db()
        with connect() as db:
            if not script_owned(db, sid, user_id):
                return "失败(权限): 剧本不属于当前用户"
            row = db.execute(
                "select title from worldbook_entries where id=%s and script_id=%s", (eid, sid),
            ).fetchone()
            if not row:
                return f"失败: 世界书条目 #{eid} 不存在或不属于剧本 #{sid}"
            db.execute("delete from worldbook_entries where id=%s and script_id=%s", (eid, sid))
            try:
                from platform_app.api.script_edit import _write_commit
                _write_commit(db, script_id=sid, user_id=user_id, kind="worldbook_delete",
                              message=f"删除世界书条目 #{eid}「{row['title']}」",
                              payload={"table": "worldbook_entries", "op": "delete",
                                       "ids": {"entry_id": eid}})
            except Exception:
                pass
            db.commit()
        return f"已删除世界书条目 #{eid}「{row['title']}」(剧本 #{sid})"
    except Exception as exc:
        return f"失败: {type(exc).__name__}: {exc}"


def _t_delete_anchor(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    """删除一个时间线锚点(anchor_id 必填,先 list_anchors 拿 id)。不可逆,删前向用户确认。
    注意:若它是原著骨架(source=novel),时间线重建可能会再生成;作者新增的(source=editor)删了不再生。"""
    sid = _resolve_sid(script_id, args)
    if sid is None:
        return "失败: script_id 必填"
    try:
        aid = int(args.get("anchor_id"))
    except (TypeError, ValueError):
        return "失败: anchor_id 必填且为整数(先 list_anchors 拿 id)"
    try:
        from platform_app.db import connect, init_db
        from platform_app.perms import script_owned
        init_db()
        with connect() as db:
            if not script_owned(db, sid, user_id):
                return "失败(权限): 剧本不属于当前用户"
            row = db.execute(
                "select story_time_label, source from script_timeline_anchors where id=%s and script_id=%s",
                (aid, sid),
            ).fetchone()
            if not row:
                return f"失败: 锚点 #{aid} 不存在或不属于剧本 #{sid}"
            db.execute("delete from script_timeline_anchors where id=%s and script_id=%s", (aid, sid))
            try:
                from platform_app.api.script_edit import _write_commit
                _write_commit(db, script_id=sid, user_id=user_id, kind="anchor_delete",
                              message=f"删除锚点 #{aid}「{row['story_time_label']}」",
                              payload={"table": "script_timeline_anchors", "op": "delete",
                                       "ids": {"anchor_id": aid}})
            except Exception:
                pass
            db.commit()
        _note = "(原著骨架,重建可能再生成)" if str(row.get("source") or "") == "novel" else "(作者新增,删了不再生)"
        return f"已删除时间线锚点 #{aid}「{row['story_time_label']}」(剧本 #{sid}){_note}"
    except Exception as exc:
        return f"失败: {type(exc).__name__}: {exc}"


# ────────────────────────────────────────────────────────────────────────────
# 7) 拖入文档(txt/md)→ 确定性拆章 / 读片段。原文存服务端,LLM 只凭 doc_id 编排,不啃正文。
# ────────────────────────────────────────────────────────────────────────────


def _t_read_uploaded_document(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    """读取用户拖入的暂存文档的一段(offset/limit 分片读)。用于「按文档某段改写/建角色」等指令。"""
    doc_id = str(args.get("doc_id") or "").strip()
    if not doc_id:
        return "失败: doc_id 必填(用户拖入文档后会给到)"
    from platform_app.agent_docs import load_doc
    doc = load_doc(user_id, doc_id)
    if not doc:
        return f"失败: 文档 {doc_id} 不存在或已过期(请用户重新拖入)"
    try:
        offset = max(0, int(args.get("offset") or 0))
    except (TypeError, ValueError):
        offset = 0
    try:
        limit = min(20000, max(1, int(args.get("limit") or 6000)))
    except (TypeError, ValueError):
        limit = 6000
    text = doc["content"] or ""
    seg = text[offset:offset + limit]
    nxt = offset + len(seg)
    tail = f"\n…(还有 {len(text) - nxt} 字,继续 offset={nxt})" if nxt < len(text) else ""
    return f"文档「{doc.get('filename') or 'doc'}」[{offset}:{nxt}]/共{len(text)}字:\n{seg}{tail}"


def _split_doc_or_err(user_id: int, args: dict):
    """共用:取暂存文档 + 跑确定性拆分器。返回 (chapters, report, doc) 或 (None, 错误串, None)。"""
    doc_id = str(args.get("doc_id") or "").strip()
    if not doc_id:
        return None, "失败: doc_id 必填", None
    from platform_app.agent_docs import load_doc
    doc = load_doc(user_id, doc_id)
    if not doc:
        return None, f"失败: 文档 {doc_id} 不存在或已过期(请用户重新拖入)", None
    rule = str(args.get("split_rule") or "auto").strip() or "auto"
    custom = str(args.get("custom_pattern") or "")
    if rule == "custom" and not custom.strip():
        return None, "失败: split_rule=custom 时必须给 custom_pattern", None
    try:
        from chapter_splitter import chapter_splitter as _splitter
        chapters, report = _splitter.split_chapters_with_report(
            doc["content"], split_rule=rule, custom_pattern=custom,
            source_name=doc.get("filename") or "doc.txt", title="",
        )
    except Exception as exc:  # noqa: BLE001
        return None, f"失败: 拆分出错: {type(exc).__name__}: {exc}", None
    return chapters, report, doc


def _t_preview_document_split(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    """预览:把拖入文档按规则拆成几章、章节标题是什么(只读,不落库)。确认后再 import_document_as_chapters。"""
    chapters, report, doc = _split_doc_or_err(user_id, args)
    if chapters is None:
        return report  # 错误串
    if not chapters:
        return "拆不出任何章节 —— 文档可能没有章节标记。可换 split_rule(chapter_cn/chapter_en/number_dot/custom)再试。"
    titles = [str((c.get("title") or f"第{i + 1}章"))[:50] for i, c in enumerate(chapters)]
    head = "、".join(f"#{i + 1}「{t}」" for i, t in enumerate(titles[:30]))
    more = f" …(共 {len(titles)} 章)" if len(titles) > 30 else ""
    mode = (report or {}).get("split_mode") or (report or {}).get("split_rule") or "auto"
    words = sum(len(c.get("content") or "") for c in chapters)
    return (f"文档「{doc.get('filename') or 'doc'}」按[{mode}]可拆成 {len(chapters)} 章、共 {words} 字。"
            f"章节:{head}{more}。确认后用 import_document_as_chapters(doc_id, split_rule, "
            f"mode=append|replace) 落库。")


def _t_import_document_as_chapters(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    """把拖入文档【确定性】拆章并写入剧本。mode=append(默认,末尾追加)/replace(清空现有章再导入)。"""
    sid = _resolve_sid(script_id, args)
    if sid is None:
        return "失败: script_id 必填"
    chapters, report, doc = _split_doc_or_err(user_id, args)
    if chapters is None:
        return report
    if not chapters:
        return "失败: 拆不出任何章节(换个 split_rule 试,或文档无章节标记)"
    mode = str(args.get("mode") or "append").strip().lower()
    if mode not in ("append", "replace"):
        mode = "append"
    try:
        from platform_app.db import connect, init_db
        from platform_app.perms import script_owned
        init_db()
        with connect() as db:
            if not script_owned(db, sid, user_id):
                return "失败(权限): 剧本不属于当前用户"
            if mode == "replace":
                db.execute("delete from script_chapters where script_id=%s", (sid,))
                start = 1
            else:
                mx = db.execute(
                    "select coalesce(max(chapter_index),0) m from script_chapters where script_id=%s",
                    (sid,),
                ).fetchone()
                start = int(mx["m"]) + 1
            n = 0
            for i, c in enumerate(chapters):
                ci = start + i
                title = str((c.get("title") or f"第{ci}章"))[:200]
                content = str(c.get("content") or "")
                db.execute(
                    "insert into script_chapters(script_id, chapter_index, title, content, word_count,"
                    " volume_title, source_marker, confidence) values (%s,%s,%s,%s,%s,%s,'doc_import',%s)",
                    (sid, ci, title, content, len(content),
                     str(c.get("volume_title") or ""), float(c.get("confidence") or 0.8)),
                )
                n += 1
            db.execute(
                "update scripts set chapter_count=(select count(*) from script_chapters where script_id=%s),"
                " word_count=(select coalesce(sum(word_count),0) from script_chapters where script_id=%s),"
                " updated_at=now() where id=%s", (sid, sid, sid),
            )
            try:
                from platform_app.api.script_edit import _write_commit
                _write_commit(db, script_id=sid, user_id=user_id, kind="doc_import_chapters",
                              message=f"文档「{doc.get('filename') or 'doc'}」导入 {n} 章({mode})",
                              payload={"table": "script_chapters", "op": "import",
                                       "count": n, "mode": mode})
            except Exception:
                pass
            db.commit()
        rng = f"第{start}–{start + n - 1}章" if n > 1 else f"第{start}章"
        label = "替换为" if mode == "replace" else "追加"
        return f"已把文档「{doc.get('filename') or 'doc'}」拆成 {n} 章{label}剧本 #{sid}({rng})。"
    except Exception as exc:  # noqa: BLE001
        return f"失败: {type(exc).__name__}: {exc}"


# ────────────────────────────────────────────────────────────────────────────
# 8) delegate_writing_task —— 派一个【用户自己配置的(BYOK)】子模型去写一段/做一个特定写作任务。
#    铁律(用户明确要求):只用用户自己的 BYOK 模型,绝不平台兜底;调用失败必须明确回报主 agent。
# ────────────────────────────────────────────────────────────────────────────


def _t_delegate_writing_task(user_id: int, script_id: int | None, args: dict, state: Any) -> str:
    task = str(args.get("task") or "").strip()
    if not task:
        return "失败: task 必填(要委派子模型做的写作任务,如『以冷峻文风写第5章开头300字』)"
    api_id_in = str(args.get("api_id") or "").strip()
    model_in = str(args.get("model") or args.get("model_real_name") or "").strip()
    # 1) 解析模型:显式优先 → 用户 writer/gm 偏好。
    api_id = model = ""
    try:
        from agents._harness import resolve_api_and_model
        api_id, model = resolve_api_and_model(
            user_id, api_pref_key="writer.api_id", model_pref_key="writer.model_real_name",
            api_id_override=(api_id_in or None), model_override=(model_in or None),
        )
    except Exception:
        api_id = model = ""
    if not (api_id and model):
        try:
            from core.llm_backend import first_user_model
            fu = first_user_model(user_id)
            if fu:
                api_id, model = fu
        except Exception:
            pass
    if not (api_id and model):
        return ("委派失败: 没找到可用模型。本工具只用【你自己配置的模型】(不走平台兜底);"
                "请到「设置 → API 与模型」配置并测试一个你自己的模型后重试。")
    # 2) 强制 BYOK:用户必须持有该 provider 的 key —— 不走 env/平台兜底(用户铁律)。
    try:
        from platform_app.user_credentials import resolve_api_key
        if not resolve_api_key(user_id, api_id, env_fallback="").get("key"):
            return (f"委派失败: 模型 {api_id}/{model} 没有你自己的 API Key。本工具只用你自己配置的模型,"
                    "请去「设置 → API 与模型」配置该 provider 的 key,或改用一个已配置的模型。")
    except Exception as exc:  # noqa: BLE001
        return f"委派失败(凭据校验出错): {type(exc).__name__}: {exc}"
    # 3) 构造后端 + 纯文本生成;任何失败都明确回报(让主 agent 转述/换模型重试)。
    try:
        from agents.gm import GameMaster
        backend = GameMaster(api_id=str(api_id), model=str(model), user_id=user_id)._backend
    except Exception as exc:  # noqa: BLE001
        from agents.provider_errors import classify_provider_error
        known = classify_provider_error(exc)
        return f"委派失败(后端初始化 {api_id}/{model}): {known[1] if known else f'{type(exc).__name__}: {exc}'}"
    try:
        max_tokens = min(6000, max(400, int(args.get("max_tokens") or 2500)))
    except (TypeError, ValueError):
        max_tokens = 2500
    ctx = str(args.get("context") or "")[:8000]
    sys_p = ("你是中文小说写作助手。严格按用户要求直接产出【成稿正文/内容】,"
             "不要解释、不要加前后缀说明、不要复述任务。")
    user_p = (f"【参考上下文】\n{ctx}\n\n" if ctx else "") + f"【写作任务】\n{task}"
    try:
        parts: list[str] = []
        for chunk in backend.stream(sys_p, [{"role": "user", "content": user_p}], max_tokens=max_tokens):
            if chunk:
                parts.append(chunk)
        out = "".join(parts).strip()
    except Exception as exc:  # noqa: BLE001
        from agents.provider_errors import classify_provider_error
        known = classify_provider_error(exc)
        return (f"委派失败(模型 {api_id}/{model} 调用出错): "
                f"{known[1] if known else f'{type(exc).__name__}: {exc}'}。可换一个你已配置的模型重试。")
    if not out:
        return (f"委派失败: 模型 {api_id}/{model} 返回空内容(可能是推理模型 max_tokens 不够、"
                "或中转站拒绝)。可调大 max_tokens、换模型或重试。")
    return (f"[子模型 {api_id}/{model} 产出 · 仅供参考,需你确认后再落库]\n{out}")


# ────────────────────────────────────────────────────────────────────────────
# 注册
# ────────────────────────────────────────────────────────────────────────────


def register_script_write_tools() -> None:
    registry = get_registry()
    specs: list[ToolSpec] = [
        ToolSpec(
            name="update_script_chapter",
            description=(
                "更新剧本某一章的正文/标题/分卷名(覆盖整章正文,destructive)。"
                "chapter_index 必填;title/content/volume_title 至少传一个。"
                "改前先向用户说清要改哪一章、改成什么。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "chapter_index": {"type": "integer", "description": "章序号(1-based)"},
                    "title": {"type": "string"},
                    "content": {"type": "string", "description": "整章正文(会覆盖原正文)"},
                    "volume_title": {"type": "string"},
                },
                "required": ["chapter_index"],
            },
            executor=_t_update_script_chapter,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=True,
        ),
        ToolSpec(
            name="upsert_worldbook_entry",
            description=(
                "创建或更新世界书条目。传 entry_id = 更新该条目;不传 = 新建(新建需 title)。"
                "keys/regex_keys/character_filter/scene_filter 是字符串数组。"
                "改前先向用户说清要改什么。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "entry_id": {"type": "integer", "description": "有=更新,无=创建"},
                    "title": {"type": "string"},
                    "content": {"type": "string"},
                    "priority": {"type": "integer"},
                    "enabled": {"type": "boolean"},
                    "keys": {"type": "array", "items": {"type": "string"}},
                    "regex_keys": {"type": "array", "items": {"type": "string"}},
                    "character_filter": {"type": "array", "items": {"type": "string"}},
                    "scene_filter": {"type": "array", "items": {"type": "string"}},
                    "token_budget": {"type": "integer"},
                    "sticky_turns": {"type": "integer"},
                    "cooldown_turns": {"type": "integer"},
                    "probability": {"type": "number"},
                    "insertion_position": {"type": "string"},
                },
                "required": ["title"],
            },
            executor=_t_upsert_worldbook_entry,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="upsert_worldbook_entries",
            description=(
                "批量创建/更新世界书条目 —— 一次要建/改多条时用本工具(一次调用一并落库),"
                "不要逐条调用 upsert_worldbook_entry(逐条在审查模式下只会成功第一条)。"
                "entries 是条目数组,每项字段与 upsert_worldbook_entry 相同(新建带 title、改带 entry_id)。"
                "**每次最多放 6 条**:条数太多整个调用会超输出长度被截断导致失败;超过 6 条请分多次调用。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "entries": {
                        "type": "array",
                        "description": "世界书条目数组(≤50 条);每项:新建带 title,更新带 entry_id",
                        "items": {
                            "type": "object",
                            "properties": {
                                "entry_id": {"type": "integer", "description": "有=更新,无=创建"},
                                "title": {"type": "string"},
                                "content": {"type": "string"},
                                "priority": {"type": "integer"},
                                "enabled": {"type": "boolean"},
                                "keys": {"type": "array", "items": {"type": "string"}},
                                "regex_keys": {"type": "array", "items": {"type": "string"}},
                                "character_filter": {"type": "array", "items": {"type": "string"}},
                                "scene_filter": {"type": "array", "items": {"type": "string"}},
                                "token_budget": {"type": "integer"},
                                "sticky_turns": {"type": "integer"},
                                "cooldown_turns": {"type": "integer"},
                                "probability": {"type": "number"},
                                "insertion_position": {"type": "string"},
                            },
                        },
                    },
                },
            },
            executor=_t_upsert_worldbook_entries,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="update_npc_card",
            description=(
                "更新剧本内某张 NPC 角色卡。card_id 必填(先用 list_script_npcs 拿 id)。"
                "只传要改的字段(其余保留)。不收 avatar_path(头像走专用端点)。"
                "改前先向用户说清要改什么。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "card_id": {"type": "integer"},
                    "name": {"type": "string"},
                    "full_name": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "identity": {"type": "string"},
                    "appearance": {"type": "string"},
                    "personality": {"type": "string"},
                    "speech_style": {"type": "string"},
                    "current_status": {"type": "string"},
                    "secrets": {"type": "string"},
                    "background": {"type": "string"},
                    "sample_dialogue": {"type": "array"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "importance": {"type": "integer"},
                    "first_revealed_chapter": {"type": "integer"},
                    "enabled": {"type": "boolean"},
                },
                "required": ["card_id"],
            },
            executor=_t_update_npc_card,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="update_anchor",
            description=(
                "更新时间线锚点。anchor_id 必填。keywords 是字符串数组。"
                "改前先向用户说清要改什么。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "anchor_id": {"type": "integer"},
                    "story_phase": {"type": "string"},
                    "story_time_label": {"type": "string"},
                    "chapter_min": {"type": "integer"},
                    "chapter_max": {"type": "integer"},
                    "sample_title": {"type": "string"},
                    "sample_summary": {"type": "string"},
                    "confidence": {"type": "number"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["anchor_id"],
            },
            executor=_t_update_anchor,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="create_anchor",
            description=(
                "为剧本「新增」一个时间线锚点 —— 当续写引入了原著时间线里没有的全新事件/时间节点时用。"
                "必填 story_time_label(节点名)+ chapter_min/chapter_max(该事件大致所处章节);"
                "story_phase 可选。新增的锚点来源标记为 editor,时间线重建不会删它。"
                "要改已有锚点用 update_anchor(不要用本工具重复新建)。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "story_time_label": {"type": "string", "description": "新事件/时间节点名"},
                    "chapter_min": {"type": "integer", "description": "该事件大致起始章"},
                    "chapter_max": {"type": "integer", "description": "该事件大致结束章"},
                    "story_phase": {"type": "string", "description": "所属阶段(可空)"},
                    "sample_title": {"type": "string"},
                    "sample_summary": {"type": "string"},
                    "confidence": {"type": "number"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["story_time_label", "chapter_min", "chapter_max"],
            },
            executor=_t_create_anchor,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="create_script_chapter",
            description=(
                "在剧本【末尾】新增一章。title 必填,content 可选(新章正文,可留空之后再写)。"
                "续写出全新一章时用。要改已有章用 update_script_chapter。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "新章标题"},
                    "content": {"type": "string", "description": "新章正文(可空)"},
                    "volume_title": {"type": "string", "description": "所属卷名(可空)"},
                },
                "required": ["title"],
            },
            executor=_t_create_script_chapter,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="create_npc_card",
            description=(
                "为剧本【新建】一张 NPC 角色卡。name 必填,其余字段(identity/appearance/personality/"
                "background/aliases/importance/first_revealed_chapter 等)可选。可结合别的剧本或正文情节"
                "创建新角色。要改已有卡用 update_npc_card(先 list_script_npcs)。同名会被拒(改用 update)。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "角色名(必填)"},
                    "full_name": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "identity": {"type": "string"},
                    "appearance": {"type": "string"},
                    "personality": {"type": "string"},
                    "speech_style": {"type": "string"},
                    "current_status": {"type": "string"},
                    "secrets": {"type": "string"},
                    "background": {"type": "string"},
                    "sample_dialogue": {"type": "array"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "importance": {"type": "integer"},
                    "first_revealed_chapter": {"type": "integer"},
                },
                "required": ["name"],
            },
            executor=_t_create_npc_card,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="delete_worldbook_entry",
            description=(
                "删除一条世界书条目。entry_id 必填(先 list_worldbook_entries 拿 id)。不可逆,删前向用户确认。"
            ),
            input_schema={
                "type": "object",
                "properties": {"entry_id": {"type": "integer"}},
                "required": ["entry_id"],
            },
            executor=_t_delete_worldbook_entry,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=True,
        ),
        ToolSpec(
            name="delete_anchor",
            description=(
                "删除一个时间线锚点。anchor_id 必填(先 list_anchors 拿 id)。不可逆,删前向用户确认。"
                "原著骨架锚点(source=novel)删后时间线重建可能再生成。"
            ),
            input_schema={
                "type": "object",
                "properties": {"anchor_id": {"type": "integer"}},
                "required": ["anchor_id"],
            },
            executor=_t_delete_anchor,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=True,
        ),
        ToolSpec(
            name="read_uploaded_document",
            description=(
                "读取用户【拖入】的暂存文档的一段(分片 offset/limit)。用户拖入 txt/md 后会给到 doc_id。"
                "用于按文档内容执行指令(如「据这段建角色/改写」)。原文不在上下文里,要看就用本工具读。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "offset": {"type": "integer", "description": "起始字符偏移(默认0)"},
                    "limit": {"type": "integer", "description": "读取字符数(默认6000,上限20000)"},
                },
                "required": ["doc_id"],
            },
            executor=_t_read_uploaded_document,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="preview_document_split",
            description=(
                "预览:把用户拖入的文档按规则【确定性】拆成几章、标题是什么(只读不落库)。"
                "split_rule:auto(默认)/chapter_cn(第N章)/chapter_en(Chapter N)/number_dot(1.)/custom(配 custom_pattern)。"
                "先预览给用户看,确认后再 import_document_as_chapters 落库。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "split_rule": {"type": "string"},
                    "custom_pattern": {"type": "string"},
                },
                "required": ["doc_id"],
            },
            executor=_t_preview_document_split,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="import_document_as_chapters",
            description=(
                "把用户拖入的文档【确定性】拆章并写入当前剧本。mode=append(默认,末尾追加)/"
                "replace(清空现有章再导入,慎用)。建议先 preview_document_split 给用户确认章数/标题。"
                "纯确定性拆分(不消耗 LLM token),适合整段/整章/整本导入。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string"},
                    "split_rule": {"type": "string"},
                    "custom_pattern": {"type": "string"},
                    "mode": {"type": "string", "enum": ["append", "replace"]},
                },
                "required": ["doc_id"],
            },
            executor=_t_import_document_as_chapters,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=True,
        ),
        ToolSpec(
            name="delegate_writing_task",
            description=(
                "把一段写作/特定任务【委派】给一个用户自己配置的(BYOK)子模型来做 —— 例如用一个更强/"
                "更擅长某文风的模型写某章某段。可显式指定 model(api_id+model),否则用用户的写作/默认模型。"
                "【只用用户自己配置的模型,不用平台兜底】;调用失败会明确返回失败原因。"
                "产出是【草稿】,需你向用户确认后再用 update_script_chapter/create_script_chapter 落库。"
                "context 可放参考正文(如相邻章节片段)。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "委派的写作任务(越具体越好)"},
                    "api_id": {"type": "string", "description": "指定子模型 provider(可空=用默认写作模型)"},
                    "model": {"type": "string", "description": "指定子模型名(可空)"},
                    "context": {"type": "string", "description": "参考上下文/相邻正文(可空)"},
                    "max_tokens": {"type": "integer", "description": "产出长度上限(默认2500)"},
                },
                "required": ["task"],
            },
            executor=_t_delegate_writing_task,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="get_chapter_text",
            description=(
                "读取某章【完整正文】(章节原著 content)。修锚点 / 核对设定 / 写作参考前,"
                "用它读真正文 —— 不要只看可能被污染的摘要(summary/sample_summary)。"
                "必填 chapter_index;长章用 offset 分段续读(返回会提示下一段 offset)。只读,owner/订阅者可用。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "chapter_index": {"type": "integer", "description": "章号"},
                    "offset": {"type": "integer", "description": "起始字符偏移(分段读长章,默认 0)"},
                    "max_chars": {"type": "integer", "description": "本段最多字符(默认 12000,上限 20000)"},
                },
                "required": ["chapter_index"],
            },
            executor=_t_get_chapter_text,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="search_manuscript",
            description=(
                "全书检索:在剧本所有章节正文里搜一个词/短语/正则,返回命中的【章号 + 标题 + 上下文片段 + 字符偏移】。"
                "这是『先读后写、避免与全书矛盾』的核心工具 —— 审稿查重复、查前文是否已交代过某设定、找某人物/"
                "物件上次出场、核对伏笔是否回收,都先用它一次定位,再用 get_chapter_text(chapter_index, offset=@值) 精读。"
                "默认大小写无关子串匹配;regex=true 走 Python 正则;可用 chapter_min/chapter_max 收窄。只读,owner/订阅者可用。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "要搜索的词/短语;regex=true 时为正则"},
                    "regex": {"type": "boolean", "description": "是否按正则匹配(默认 false=子串)"},
                    "chapter_min": {"type": "integer", "description": "只搜该章号及以后(可空)"},
                    "chapter_max": {"type": "integer", "description": "只搜该章号及以前(可空)"},
                    "max_results": {"type": "integer", "description": "最多列出多少条命中(默认 30,上限 100)"},
                    "context_chars": {"type": "integer", "description": "每条命中前后各取多少字符上下文(默认 60)"},
                },
                "required": ["query"],
            },
            input_examples=(
                {"query": "重力控制"},
                {"query": "蜜特·托蕾特", "chapter_min": 1, "chapter_max": 20},
            ),
            executor=_t_search_manuscript,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=False,
        ),
        ToolSpec(
            name="upsert_canon_entity",
            description=(
                "创建或更新 canon 实体(按 logical_key)。logical_key 必填;"
                "创建时还需 name 和 type。aliases 是字符串数组,attrs 是开放对象。"
                "改前先向用户说清要改什么。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "logical_key": {"type": "string"},
                    "name": {"type": "string"},
                    "full_name": {"type": "string"},
                    "type": {"type": "string"},
                    "summary": {"type": "string"},
                    "identity": {"type": "string"},
                    "background": {"type": "string"},
                    "entity_subtype": {"type": "string"},
                    "parent_logical_key": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "attrs": {"type": "object"},
                    "first_revealed_chapter": {"type": "integer"},
                    "public_knowledge": {"type": "boolean"},
                    "importance": {"type": "integer"},
                },
                "required": ["logical_key"],
            },
            executor=_t_upsert_canon_entity,
            scope="script",
            origins=_SCRIPT_WRITE_ORIGINS,
            destructive=False,
        ),
    ]
    for spec in specs:
        if not registry.has(spec.name):
            registry.register(spec)


__all__ = ["register_script_write_tools"]
