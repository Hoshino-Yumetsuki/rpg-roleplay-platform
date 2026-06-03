"""compact 写 phase 浓缩档锚点须幂等:同 phase 多次 compact 不得累积重复
save_history_anchors,否则 list_recent_history 被重复浓缩档挤占、玩家真实历史被挤出。"""
import unittest
from pathlib import Path

SRC = (Path(__file__).resolve().parents[2] / "agents" / "phase_digest_agent.py").read_text(encoding="utf-8")


def _func(name: str) -> str:
    i = SRC.find(f"def {name}(")
    assert i != -1, name
    end = SRC.find("\ndef ", i + 1)
    return SRC[i: end if end != -1 else len(SRC)]


class CompactDigestAnchorIdempotent(unittest.TestCase):
    def setUp(self):
        self.body = _func("_persist_digest")

    def test_deletes_old_phase_digest_anchor_before_insert(self):
        self.assertIn("delete from save_history_anchors", self.body,
                      "未先删旧 phase_digest 锚点 → 重复 compact 会累积重复浓缩档")

    def test_delete_scoped_to_this_phase_and_system_source(self):
        # 删除必须限定 source='system' + phase_digest tag + 本 phase_index(不误删玩家历史)
        self.assertIn("source = 'system'", self.body)
        self.assertIn('phase_digest', self.body)
        self.assertIn("metadata->>'phase_index'", self.body)

    def test_delete_before_record(self):
        del_pos = self.body.find("delete from save_history_anchors")
        rec_pos = self.body.find("record_history_anchor(")
        self.assertGreater(del_pos, -1)
        self.assertGreater(rec_pos, del_pos, "删除必须在重新 record_history_anchor 之前")


if __name__ == "__main__":
    unittest.main()
