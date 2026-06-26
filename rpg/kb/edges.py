"""kb.edges — 时间感知知识库:统一关系边回填(P2)。设计 docs/design/O §2 / §6 P2。

把散落/闲置的关系信号确定性物化进 kb_edges(剧本级规范边 save_id=NULL):
- parent:   kb_canon_entities.parent_logical_key → 层级边(canon→canon,key 均 logical_key,干净)。
- in_chapter / relationship(共现): chapter_facts.events[].participants —— 事件参与者出现在第 N 章
  → in_chapter 边;同事件参与者两两 → relationship 共现边(对称,排序去向;按事件数封顶防爆)。
- mentions:  worldbook_entries.keys 命中 canon 实体名/别名 → 世界书↔实体边。
- relationship(显式): chapter_facts.relationships(source/target/note),数据有则建,无则跳过。

幂等:全部 on conflict do nothing(命中 P0 的分区唯一索引 uq_kb_edges_canonical,save_id IS NULL)。
参与者是原始名字(未解析成 logical_key),故 kind 用 'entity'(原始名),P5 召回时再解析;canon/worldbook
两端是确定的 key。只写不读(P2 不切召回)。
"""
from __future__ import annotations

from typing import Any

from platform_app.db import connect, init_db

_MAX_PARTICIPANTS_PER_EVENT = 6   # 超过则跳过共现(C(n,2) 防爆);仍建 in_chapter
_MAX_NAME_LEN = 120


def _norm_name(s: Any) -> str:
    return str(s or "").strip()[:_MAX_NAME_LEN]


def backfill_kb_edges(script_id: int) -> dict[str, Any]:
    """P2:回填 kb_edges(剧本级规范边)。幂等。返回各类型计数。"""
    init_db()
    sid = int(script_id)
    counts = {"parent": 0, "in_chapter": 0, "relationship": 0, "mentions": 0}
    with connect() as db:
        def _ins(src_kind, src_key, dst_kind, dst_key, kind, *, label="", weight=1.0, ch=0):
            src_key = _norm_name(src_key); dst_key = _norm_name(dst_key)
            if not src_key or not dst_key or src_key == dst_key:
                return 0
            n = db.execute(
                """
                insert into kb_edges (script_id, save_id, src_kind, src_key, dst_kind, dst_key,
                                      kind, label, weight, first_revealed_chapter, origin)
                values (%s, NULL, %s, %s, %s, %s, %s, %s, %s, %s, 'extracted')
                on conflict (script_id, src_kind, src_key, dst_kind, dst_key, kind)
                  where save_id is null do nothing
                """,
                (sid, src_kind, src_key, dst_kind, dst_key, kind, label[:200], weight, int(ch or 0)),
            ).rowcount
            return 1 if n else 0

        # 1) parent(canon 层级)
        for r in db.execute(
            "select logical_key, parent_logical_key from kb_canon_entities "
            "where script_id=%s and coalesce(parent_logical_key,'')<>''", (sid,),
        ).fetchall():
            counts["parent"] += _ins("canon_entity", r["logical_key"], "canon_entity",
                                      r["parent_logical_key"], "parent")

        # 2) events.participants → in_chapter + 共现 relationship
        for fact in db.execute(
            "select chapter, events from chapter_facts where script_id=%s order by chapter", (sid,),
        ).fetchall():
            ch = int(fact["chapter"])
            for ev in (fact.get("events") or []):
                if not isinstance(ev, dict):
                    continue
                parts = [_norm_name(p) for p in (ev.get("participants") or []) if _norm_name(p)]
                parts = list(dict.fromkeys(parts))  # 去重保序
                for p in parts:
                    counts["in_chapter"] += _ins("entity", p, "chapter", f"chapter:{ch}", "in_chapter", ch=ch)
                if 2 <= len(parts) <= _MAX_PARTICIPANTS_PER_EVENT:
                    for i in range(len(parts)):
                        for j in range(i + 1, len(parts)):
                            a, b = sorted((parts[i], parts[j]))  # 对称边:排序定向去重
                            counts["relationship"] += _ins("entity", a, "entity", b, "relationship",
                                                           label="共现", ch=ch)

        # 3) chapter_facts.relationships(显式,有则建)
        for fact in db.execute(
            "select chapter, relationships from chapter_facts where script_id=%s "
            "and jsonb_array_length(coalesce(relationships,'[]'::jsonb))>0", (sid,),
        ).fetchall():
            ch = int(fact["chapter"])
            for rel in (fact.get("relationships") or []):
                if not isinstance(rel, dict):
                    continue
                src = _norm_name(rel.get("source") or rel.get("from") or rel.get("a"))
                dst = _norm_name(rel.get("target") or rel.get("to") or rel.get("b"))
                note = str(rel.get("note") or rel.get("type") or rel.get("relation") or "")
                if src and dst:
                    counts["relationship"] += _ins("entity", src, "entity", dst, "relationship",
                                                   label=note, ch=ch)

        # 4) worldbook keys 命中 canon 名/别名 → mentions
        canon = db.execute(
            "select logical_key, name, aliases from kb_canon_entities where script_id=%s "
            "and coalesce(importance,0)>=0", (sid,),
        ).fetchall()
        name_to_key: dict[str, str] = {}
        for c in canon:
            nm = _norm_name(c["name"])
            if nm:
                name_to_key.setdefault(nm, c["logical_key"])
            for al in (c.get("aliases") or []):
                an = _norm_name(al)
                if an:
                    name_to_key.setdefault(an, c["logical_key"])
        if name_to_key:
            for wb in db.execute(
                "select title, keys from worldbook_entries where script_id=%s and enabled "
                "and jsonb_array_length(coalesce(keys,'[]'::jsonb))>0", (sid,),
            ).fetchall():
                title = _norm_name(wb["title"])
                seen = set()
                for k in (wb.get("keys") or []):
                    lk = name_to_key.get(_norm_name(k))
                    if lk and lk not in seen:
                        seen.add(lk)
                        counts["mentions"] += _ins("worldbook", title, "canon_entity", lk, "mentions")

    return {"ok": True, "script_id": sid, "edges": counts, "total": sum(counts.values())}
