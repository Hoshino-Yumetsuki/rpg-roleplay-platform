"""resolve_and_write 全链集成(连真 DB):RC1 主角融合 + RC4 非人名降级
→ character_cards → _rerank_cards_by_canon_importance → is_protagonist。
"""
from __future__ import annotations

import unittest

from extract.per_chapter import ChapterExtract
from extract.resolve import resolve_and_write
from platform_app import import_pipeline
from tests.helpers import cleanup_test_users, make_client, random_suffix


def _ent(name, typ="character", identity="", aliases=None):
    return {"canonical_guess": name, "type": typ, "identity": identity,
            "aliases_in_chapter": aliases or []}


class ResolveProtagonistIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cleanup_test_users()
        cls.client = make_client()

    @classmethod
    def tearDownClass(cls):
        cleanup_test_users()

    def _setup(self):
        from platform_app.db import connect
        uname = f"integtest_{random_suffix()}@x.test"
        with connect() as db:
            uid = int(db.execute(
                "insert into users(username,display_name,role,email,email_verified,terms_accepted_at,age_confirmed) "
                "values (%s,'i','user',%s,true,now(),true) returning id", (uname, uname)).fetchone()["id"])
            sid = int(db.execute(
                "insert into scripts(owner_id,title) values (%s,'大漠谣') returning id", (uid,)).fetchone()["id"])
            bid = int(db.execute(
                "insert into books(owner_id,script_id,slug,title) values (%s,%s,%s,'大漠谣') returning id",
                (uid, sid, f"b_{uid}")).fetchone()["id"])
        return uid, sid, bid

    def _extracts(self):
        exs = []
        # 红姑(奶娘配角):只在第 1-3 章高频出现,跨度窄
        for ch in (1, 2, 3):
            exs.append(ChapterExtract(
                chapter=ch,
                entities=[_ent("红姑", identity="金玉的奶娘"), _ent("玉儿")],
                relationships=[{"from": "玉儿", "to": "红姑"}],
                events=[{"participants": ["玉儿", "红姑"]}]))
        # 玉儿(主角):贯穿全书 1..40 章 + 关系/事件中心;将军=非人名无佐证
        for ch in (10, 20, 30, 40):
            exs.append(ChapterExtract(
                chapter=ch,
                entities=[_ent("玉儿"), _ent("将军", identity="")],
                relationships=[{"from": "玉儿", "to": "霍去病"}, {"from": "玉儿", "to": "李妍"}],
                events=[{"participants": ["玉儿"]}]))
        return exs

    def test_full_chain_protagonist_and_non_person_drop(self):
        from platform_app.db import connect
        _uid, sid, bid = self._setup()
        with connect() as db:
            resolve_and_write(db, sid, self._extracts(), embedder=None, book_id=bid)

        with connect() as db:
            cards = db.execute(
                "select name, importance from character_cards where script_id=%s and card_type='npc'",
                (sid,)).fetchall()
        names = {c["name"]: int(c["importance"]) for c in cards}
        # RC4:非人名『将军』不建卡
        self.assertNotIn("将军", names, f"非人名『将军』不应建 NPC 卡: {list(names)}")
        self.assertIn("玉儿", names)
        self.assertIn("红姑", names)
        # RC1:主角玉儿(贯穿全书+中心)importance 高于贴身配角红姑
        self.assertGreater(names["玉儿"], names["红姑"], f"玉儿应高于红姑: {names}")

        # rerank → is_protagonist 落到玉儿,不落红姑
        import_pipeline._rerank_cards_by_canon_importance(sid)
        with connect() as db:
            rows = db.execute(
                "select name, (metadata->>'is_protagonist')::boolean as prot, priority "
                "from character_cards where script_id=%s and card_type='npc'", (sid,)).fetchall()
        prot = {r["name"]: r["prot"] for r in rows}
        self.assertTrue(prot.get("玉儿"), f"玉儿应被标主角: {prot}")
        self.assertFalse(prot.get("红姑"), f"红姑不应是主角: {prot}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
