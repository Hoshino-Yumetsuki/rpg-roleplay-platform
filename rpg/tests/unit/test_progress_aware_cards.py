"""test_progress_aware_cards.py — 进度感知角色卡(L 设计)离线单测。

覆盖 Phase 2 运行时投影(纯函数 + fake DB)的所有铁律:
  · ≤progress 合成(最近非空 identity/background/status)
  · 敌→友逐章演进(relationships 取 ≤ceiling 最后一次 kind)
  · omniscient 全态 / none 严格 ≤progress / partial 近未来缓冲
  · first_revealed=0 / 无数据 → 回退原卡(返回 None / 原样)
  · apply_projection_to_card 防剧透(有投影则丢原卡最终态 current_status)
  · _aggregate_characters_from_facts 记 first_revealed_chapter(重建保防剧透章)

不依赖真 DB(用 fake 连接);真库 e2e 另见 integration。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_RPG = str(Path(__file__).resolve().parents[2])
if _RPG not in sys.path:
    sys.path.insert(0, _RPG)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeChapterFactsDb:
    """最小 fake:execute(select ... chapter_facts ...) → 按 chapter<=ceiling 过滤的行。

    rows_by_chapter: {chapter: {"characters": [...], "relationships": [...]}}
    捕获 SQL 里的 chapter <= 上限(从 params 取),据此过滤;无上限(omniscient)= 全部。
    """
    def __init__(self, rows_by_chapter):
        self.rows = []
        for ch in sorted(rows_by_chapter):
            r = rows_by_chapter[ch]
            self.rows.append({
                "chapter": ch,
                "characters": r.get("characters", []),
                "relationships": r.get("relationships", []),
            })

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        if "from chapter_facts" not in s:
            return _Result([])
        ceiling = None
        if "chapter <= %s" in s and params:
            # params = (script_id, ceiling)
            try:
                ceiling = int(params[1])
            except (IndexError, TypeError, ValueError):
                ceiling = None
        if ceiling is None:
            return _Result(self.rows)
        return _Result([r for r in self.rows if r["chapter"] <= ceiling])


# 一个角色「卡切尔」:第 1 章敌对、第 5 章中立、第 12 章盟友;identity 逐章丰富。
_FIXTURE = {
    1: {
        "characters": [{"canonical_guess": "卡切尔", "identity": "神秘黑袍人",
                        "background": "来历不明", "type": "character"}],
        "relationships": [{"from": "卡切尔", "to": "穆蕾莉娅", "kind": "敌对", "evidence": "拔剑相向"}],
    },
    5: {
        "characters": [{"canonical_guess": "卡切尔", "identity": "异端审判庭检察官",
                        "type": "character"}],
        "relationships": [{"from": "穆蕾莉娅", "to": "卡切尔", "kind": "中立", "evidence": "暂时休战"}],
    },
    12: {
        "characters": [{"canonical_guess": "卡切尔", "identity": "审判庭叛将",
                        "background": "为爱反出审判庭", "type": "character"}],
        "relationships": [{"from": "卡切尔", "to": "穆蕾莉娅", "kind": "盟友", "evidence": "并肩作战"}],
    },
}


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        from context_engine.projection import clear_projection_cache
        clear_projection_cache()

    def _project(self, progress, mode):
        from context_engine.projection import project_character_state
        db = _FakeChapterFactsDb(_FIXTURE)
        return project_character_state(db, script_id=42, name_or_key="卡切尔",
                                       progress_chapter=progress, foreknowledge_mode=mode,
                                       use_cache=False)

    def test_none_strict_chapter1_enemy(self):
        """none @ ch1:只见第 1 章态 → 敌对、identity=神秘黑袍人。"""
        p = self._project(1, "none")
        self.assertIsNotNone(p)
        self.assertEqual(p["identity"], "神秘黑袍人")
        rels = {r["other"]: r["kind"] for r in p["relationships"]}
        self.assertEqual(rels.get("穆蕾莉娅"), "敌对")

    def test_none_strict_chapter5_neutral_latest_identity(self):
        """none @ ch5:≤5 章合成 → 关系取最近(中立)、identity 取最近非空(第 5 章)。"""
        p = self._project(5, "none")
        self.assertEqual(p["identity"], "异端审判庭检察官")
        rels = {r["other"]: r["kind"] for r in p["relationships"]}
        self.assertEqual(rels.get("穆蕾莉娅"), "中立")

    def test_none_enemy_to_ally_progression(self):
        """敌→友逐章:ch12 进度下关系=盟友(最后一次 kind 胜出)。"""
        p = self._project(12, "none")
        rels = {r["other"]: r["kind"] for r in p["relationships"]}
        self.assertEqual(rels.get("穆蕾莉娅"), "盟友")
        # identity 取最近非空,background 取最近非空(第 12 章)
        self.assertEqual(p["identity"], "审判庭叛将")
        self.assertEqual(p["background"], "为爱反出审判庭")

    def test_none_at_chapter3_holds_chapter1_state(self):
        """ch3 进度(第 2-4 章无该角色记录)→ 沿用 ≤3 最近态 = 第 1 章敌对。"""
        p = self._project(3, "none")
        rels = {r["other"]: r["kind"] for r in p["relationships"]}
        self.assertEqual(rels.get("穆蕾莉娅"), "敌对")
        self.assertEqual(p["identity"], "神秘黑袍人")
        # 第 1 章 background 非空被保留(第 5 章 identity 更新但 background 空 → 不抹)
        self.assertEqual(p["background"], "来历不明")

    def test_omniscient_full_book_final_state(self):
        """omniscient:不 gate → 全书最终态 = 盟友 + 第 12 章 identity。"""
        p = self._project(1, "omniscient")  # progress 被 omniscient 忽略
        rels = {r["other"]: r["kind"] for r in p["relationships"]}
        self.assertEqual(rels.get("穆蕾莉娅"), "盟友")
        self.assertEqual(p["identity"], "审判庭叛将")

    def test_partial_lookahead_window(self):
        """partial @ ch1:+20 章缓冲 → 能看到第 12 章盟友态(温和预知)。"""
        p = self._project(1, "partial")
        rels = {r["other"]: r["kind"] for r in p["relationships"]}
        self.assertEqual(rels.get("穆蕾莉娅"), "盟友")

    def test_no_data_returns_none(self):
        """该角色无任何 chapter_facts 记录 → None(回退原卡)。"""
        from context_engine.projection import project_character_state
        db = _FakeChapterFactsDb(_FIXTURE)
        p = project_character_state(db, 42, "查无此人", 12, "none", use_cache=False)
        self.assertIsNone(p)

    def test_empty_db_returns_none(self):
        from context_engine.projection import project_character_state
        db = _FakeChapterFactsDb({})
        p = project_character_state(db, 42, "卡切尔", 12, "none", use_cache=False)
        self.assertIsNone(p)

    def test_db_error_returns_none_not_raise(self):
        """投影读 DB 出错 → 返 None(不抛、不破回合)。"""
        from context_engine.projection import project_character_state

        class _Boom:
            def execute(self, *a, **k):
                raise RuntimeError("db down")
        p = project_character_state(_Boom(), 42, "卡切尔", 12, "none", use_cache=False)
        self.assertIsNone(p)

    def test_heuristic_relationship_shape(self):
        """启发式路径 relationships 用 source/target/note(无 kind)→ note 当 kind 兜底。"""
        from context_engine.projection import project_character_state
        db = _FakeChapterFactsDb({
            2: {"characters": [{"name": "甲", "identity": ""}],
                "relationships": [{"source": "甲", "target": "乙", "note": "保护乙"}]},
        })
        p = project_character_state(db, 42, "甲", 5, "none", use_cache=False)
        self.assertIsNotNone(p)
        rels = {r["other"]: r["kind"] for r in p["relationships"]}
        self.assertEqual(rels.get("乙"), "保护乙")

    def test_status_linked_proposed_not_used_as_current_status(self):
        """LLM status 字段值 linked|proposed 是消歧标记,不当角色现状。"""
        from context_engine.projection import project_character_state
        db = _FakeChapterFactsDb({
            1: {"characters": [{"canonical_guess": "丙", "identity": "侍卫",
                                "status": "linked", "type": "character"}],
                "relationships": []},
        })
        p = project_character_state(db, 42, "丙", 5, "none", use_cache=False)
        self.assertEqual(p["current_status"], "")  # 不把 linked 当现状


class ApplyProjectionTests(unittest.TestCase):
    def test_apply_none_passthrough(self):
        from context_engine.projection import apply_projection_to_card
        card = {"name": "X", "identity": "原态", "current_status": "最终态盟友"}
        out = apply_projection_to_card(card, None)
        self.assertEqual(out["identity"], "原态")
        self.assertEqual(out["current_status"], "最终态盟友")

    def test_apply_drops_final_state_current_status_when_projected(self):
        """有投影 → 绝不保留原卡最终态 current_status(防剧透「敌→友」结局)。"""
        from context_engine.projection import apply_projection_to_card
        card = {"name": "卡切尔", "identity": "最终态盟友身份", "current_status": "与主角并肩作战"}
        proj = {"identity": "神秘黑袍人", "background": "来历不明", "current_status": "",
                "relationships": [{"other": "穆蕾莉娅", "kind": "敌对", "chapter": 1}],
                "_source_chapter": 1}
        out = apply_projection_to_card(card, proj)
        self.assertEqual(out["identity"], "神秘黑袍人")
        self.assertNotIn("并肩作战", out["current_status"])
        self.assertIn("敌对", out["current_status"])

    def test_apply_does_not_mutate_input(self):
        from context_engine.projection import apply_projection_to_card
        card = {"name": "X", "identity": "原", "current_status": "原状"}
        proj = {"identity": "新", "background": "", "current_status": "新状",
                "relationships": [], "_source_chapter": 3}
        apply_projection_to_card(card, proj)
        self.assertEqual(card["identity"], "原")  # 原卡不被改


class FirstRevealedAggregateTests(unittest.TestCase):
    """_aggregate_characters_from_facts 记 first_revealed_chapter(重建保防剧透章)。"""

    def test_first_revealed_recorded_and_chapter_max(self):
        from unittest import mock

        import platform_app.knowledge.session as session

        rows = [
            {"chapter": 3, "characters": [{"name": "早期角色", "count": 10}]},
            {"chapter": 50, "characters": [{"name": "后期角色", "count": 12}]},
            {"chapter": 7, "characters": [{"name": "早期角色", "count": 8}]},
        ]

        class _DB:
            def execute(self, sql, params=None):
                s = " ".join(sql.split())
                # chapter_max 过滤:params=(script_id, cmax)
                if "chapter <= %s" in s and params:
                    cmax = int(params[1])
                    return _Result([r for r in rows if r["chapter"] <= cmax])
                return _Result(rows)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch.object(session, "connect", lambda: _DB()):
            # 全书:两角色都在,first_revealed 取最早出现章
            out = session._aggregate_characters_from_facts(42)
            self.assertIn("早期角色", out)
            self.assertEqual(out["早期角色"]["first_revealed_chapter"], 3)
            self.assertEqual(out["后期角色"]["first_revealed_chapter"], 50)
            # chapter_max=10:后期角色(第 50 章)被区间过滤掉
            out2 = session._aggregate_characters_from_facts(42, chapter_max=10)
            self.assertIn("早期角色", out2)
            self.assertNotIn("后期角色", out2)


if __name__ == "__main__":
    unittest.main()
