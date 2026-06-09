"""
test_qa_fixes_birthpoint_protagonist.py — QA 回归(用户实测 bug 的后端部分)

① 出生锚点(birthpoint):选了非首章的出生点,新存档的情境字段(地点/known_events/
   last_retrieval/anchor_chapter_range)必须从【锚点章节】派生,而不是恒定第 1 章。
   修复前:_apply_script_opening 恒锁第 1 章 → world.time 被改成锚点标签但地点/事件仍是
   第 1 章,GM 拿到自相矛盾的状态照第 1 章开场(用户实测:选了后段锚点仍从第一章开始)。

② 主角标签手动指定 + 锁定:canon importance 误判把配角标成主角,用户手动改正后,
   重新提取(canon 重排)不能再覆盖回去。set_character_card_protagonist 写 protagonist_locked,
   _rerank_cards_by_canon_importance 见锁跳过。
"""
from __future__ import annotations

import json
import unittest

from tests.helpers import cleanup_test_users, make_client, random_suffix

CH1_TITLE = "第一章 雾港入夜"
CH1_CONTENT = """申时三刻,雾港码头的铜钟敲了六下。

当前地点:雾港码头。
当前目标:确认蓝色罗盘是否能打开灯塔星门。
时间锚点:申时三刻。
"""

CH5_TITLE = "第五章 落日大漠"
CH5_CONTENT = """黄沙漫天,大漠的落日把驼队的影子拉得很长,远处有狼烟升起。

当前地点:玉门关外大漠。
当前目标:追上西去的商队,找回失落的玉佩。
时间锚点:黄昏。
"""


def _mk_user():
    from platform_app.db import connect
    uname = f"integtest_{random_suffix()}@example.test"
    with connect() as db:
        row = db.execute(
            "insert into users(username, display_name, role, email, "
            "email_verified, terms_accepted_at, age_confirmed) "
            "values (%s,'integ','user',%s,true,now(),true) returning id",
            (uname, uname),
        ).fetchone()
    return int(row["id"])


class BirthpointReanchor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cleanup_test_users()
        cls.client = make_client()  # 触发路由注册 + init_db

    @classmethod
    def tearDownClass(cls):
        cleanup_test_users()

    def _mk_script_two_chapters(self, uid):
        from platform_app.db import connect
        with connect() as db:
            scr = db.execute(
                "insert into scripts(owner_id, title, review_status) "
                "values (%s,%s,'reviewed') returning id",
                (uid, "integtest_birthpoint_script"),
            ).fetchone()
            sid = int(scr["id"])
            for idx, title, content in (
                (1, CH1_TITLE, CH1_CONTENT),
                (5, CH5_TITLE, CH5_CONTENT),
            ):
                db.execute(
                    "insert into script_chapters(script_id, chapter_index, title, content, word_count) "
                    "values (%s,%s,%s,%s,%s)",
                    (sid, idx, title, content, len(content)),
                )
        return sid

    def _snapshot(self, save_id):
        from platform_app.db import connect
        with connect() as db:
            row = db.execute(
                "select state_snapshot from game_saves where id=%s", (save_id,)
            ).fetchone()
        snap = row["state_snapshot"]
        return json.loads(snap) if isinstance(snap, str) else snap

    def test_birthpoint_reanchors_opening_to_anchor_chapter(self):
        from platform_app import workspace
        uid = _mk_user()
        sid = self._mk_script_two_chapters(uid)

        save = workspace.create_save(
            uid, sid, "birthpoint save",
            new_card={"name": "测试旅人", "role": "锚点测试者", "background": "B"},
            birthpoint={
                "phase_label": "大漠篇",
                "anchor_id": 9001,
                "chapter_min": 5,
                "chapter_max": 5,
                "story_time_label": "落日大漠",
            },
        )
        save_id = int(save.get("id") or 0)
        self.assertGreater(save_id, 0, save)

        snap = self._snapshot(save_id)
        world = snap.get("world") or {}
        player = snap.get("player") or {}
        memory = snap.get("memory") or {}
        timeline = world.get("timeline") or {}
        events_blob = " | ".join(str(e) for e in (world.get("known_events") or []))
        last_retrieval = str(memory.get("last_retrieval") or "")

        # anchor_chapter_range 落库
        self.assertEqual(
            timeline.get("anchor_chapter_range"), [5, 5],
            f"anchor_chapter_range 应=[5,5];实际 {timeline.get('anchor_chapter_range')!r}")
        # world.time = 锚点标签
        self.assertEqual(world.get("time"), "落日大漠")
        # 情境字段来自第 5 章,不是第 1 章
        self.assertIn("落日大漠", events_blob, f"known_events 应含第5章标题;实际 {events_blob!r}")
        self.assertNotIn("雾港入夜", events_blob, f"known_events 不应含第1章;实际 {events_blob!r}")
        self.assertIn("大漠", last_retrieval, f"last_retrieval 应是第5章正文;实际 {last_retrieval[:120]!r}")
        self.assertNotIn("雾港", last_retrieval, f"last_retrieval 不应是第1章;实际 {last_retrieval[:120]!r}")
        # 第 5 章有 inline meta → current_location 从第 5 章派生
        self.assertEqual(
            player.get("current_location"), "玉门关外大漠",
            f"current_location 应从第5章派生;实际 {player.get('current_location')!r}")

    def test_no_birthpoint_still_uses_first_chapter(self):
        """没选 birthpoint 时行为不变:仍锚定第 1 章(回归保护)。"""
        from platform_app import workspace
        uid = _mk_user()
        sid = self._mk_script_two_chapters(uid)
        save = workspace.create_save(
            uid, sid, "no birthpoint",
            new_card={"name": "旅人2", "role": "R", "background": "B"},
        )
        save_id = int(save.get("id") or 0)
        snap = self._snapshot(save_id)
        player = snap.get("player") or {}
        self.assertEqual(
            player.get("current_location"), "雾港码头",
            "无 birthpoint 时仍应锚定第 1 章雾港码头")


class ProtagonistManualOverride(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cleanup_test_users()
        cls.client = make_client()

    @classmethod
    def tearDownClass(cls):
        cleanup_test_users()

    def _setup_script_with_cards(self):
        from platform_app.db import connect
        uname = f"integtest_{random_suffix()}@example.test"
        with connect() as db:
            owner = db.execute(
                "insert into users(username, display_name, role, email, "
                "email_verified, terms_accepted_at, age_confirmed) "
                "values (%s,'integ','user',%s,true,now(),true) returning id",
                (uname, uname),
            ).fetchone()
            uid = int(owner["id"])
            scr = db.execute(
                "insert into scripts(owner_id, title) values (%s,%s) returning id",
                (uid, "integtest_protagonist_script"),
            ).fetchone()
            sid = int(scr["id"])
            book = db.execute(
                "insert into books(owner_id, script_id, slug, title) "
                "values (%s,%s,%s,%s) returning id",
                (uid, sid, f"integtest_protag_book_{uid}", "b"),
            ).fetchone()
            bid = int(book["id"])
            cards = {}
            for name in ("红姑", "白苏玖"):
                row = db.execute(
                    "insert into character_cards(book_id, script_id, name, card_type, "
                    "source, scope, priority, metadata) "
                    "values (%s,%s,%s,'npc','extracted','script',100,'{}'::jsonb) returning id",
                    (bid, sid, name),
                ).fetchone()
                cards[name] = int(row["id"])
            # canon: 红姑 importance 高 → rk=1(模拟 LLM 误判把配角排第一)
            for name, imp in (("红姑", 95), ("白苏玖", 80)):
                db.execute(
                    "insert into kb_canon_entities(script_id, logical_key, name, type, importance) "
                    "values (%s,%s,%s,'character',%s)",
                    (sid, name, name, imp),
                )
        return uid, sid, cards

    def _meta(self, card_id):
        from platform_app.db import connect
        with connect() as db:
            row = db.execute(
                "select metadata, priority from character_cards where id=%s", (card_id,)
            ).fetchone()
        return dict(row["metadata"] or {}), int(row["priority"])

    def test_manual_protagonist_survives_reextraction(self):
        from platform_app import import_pipeline, knowledge
        uid, sid, cards = self._setup_script_with_cards()

        # 1) 初始 canon 重排 → 红姑(rk=1) 成主角(复现 bug:误判)
        import_pipeline._rerank_cards_by_canon_importance(sid)
        red_meta, _ = self._meta(cards["红姑"])
        su_meta, _ = self._meta(cards["白苏玖"])
        self.assertTrue(red_meta.get("is_protagonist"), "初始:红姑应被 canon 标为主角")
        self.assertFalse(su_meta.get("is_protagonist"), "初始:白苏玖不应是主角")

        # 2) 用户手动把 白苏玖 设为主角
        knowledge.set_character_card_protagonist(uid, sid, cards["白苏玖"])
        red_meta, red_pri = self._meta(cards["红姑"])
        su_meta, su_pri = self._meta(cards["白苏玖"])
        self.assertTrue(su_meta.get("is_protagonist"), "白苏玖应成为主角")
        self.assertTrue(su_meta.get("protagonist_locked"), "白苏玖应被锁定")
        self.assertEqual(su_pri, 110)
        self.assertFalse(red_meta.get("is_protagonist"), "红姑主角标记应被清掉")
        self.assertLess(red_pri, 110, "红姑不应再占 110 主角位")

        # 3) 重新提取(canon 重排再跑一次) → 锁定的白苏玖不被覆盖
        import_pipeline._rerank_cards_by_canon_importance(sid)
        red_meta, _ = self._meta(cards["红姑"])
        su_meta, su_pri = self._meta(cards["白苏玖"])
        self.assertTrue(su_meta.get("is_protagonist"), "重新提取后:白苏玖仍应是主角(锁定生效)")
        self.assertTrue(su_meta.get("protagonist_locked"))
        self.assertEqual(su_pri, 110, "重新提取后:白苏玖仍占 110 主角位")
        self.assertFalse(red_meta.get("is_protagonist"), "重新提取后:红姑仍不是主角")

    def test_set_protagonist_owner_only(self):
        from platform_app import knowledge
        _uid, sid, cards = self._setup_script_with_cards()
        other_uid = 2_000_000_001  # 非 owner(不存在的用户 id)
        with self.assertRaises(ValueError):
            knowledge.set_character_card_protagonist(other_uid, sid, cards["红姑"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
