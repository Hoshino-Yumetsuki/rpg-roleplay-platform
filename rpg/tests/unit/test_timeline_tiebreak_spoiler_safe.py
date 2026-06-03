"""timeline_filter_for_label 打平时取最早章号(剧透安全),而非原来取最高章号。
通用词("宴会"在 ch52..1310 反复出现)全 score 打平时,原取 ch1310(结局)→ 早期场景
检索窗口锚到大结局 → 剧透。修后取最早章。"""
import re
import unittest
from pathlib import Path

SRC = (Path(__file__).resolve().parents[2] / "timeline_index.py").read_text(encoding="utf-8")


class TimelineTieBreakSpoilerSafe(unittest.TestCase):
    def test_source_uses_min_chapter_tiebreak(self):
        i = SRC.find("def timeline_filter_for_label(")
        end = SRC.find("\ndef ", i + 1)
        body = SRC[i:end]
        # 不应再用 reverse=True 的全降序(会按章号降序取最大章)
        self.assertNotIn("scored.sort(reverse=True)", body,
                         "仍用 sort(reverse=True) → 打平取最大章号(剧透)")
        # 应按 score 降序 + 章号升序
        self.assertTrue(re.search(r"scored\.sort\(key=lambda x:\s*\(-x\[0\],\s*x\[1\]\)\)", body),
                        "未改为 score 降序 + 章号升序的剧透安全 tie-break")

    def test_tiebreak_logic_picks_earliest_chapter(self):
        # 复现排序逻辑:同分取最早章
        scored = [(1, 1310, "e", "t"), (1, 52, "e", "t"), (1, 152, "e", "t")]
        scored.sort(key=lambda x: (-x[0], x[1]))
        self.assertEqual(scored[0][1], 52, "打平未取最早章")

    def test_unique_best_unaffected(self):
        # 唯一高分仍胜出(不受 tie-break 影响)
        scored = [(5, 1313, "a", "b"), (1, 52, "c", "d")]
        scored.sort(key=lambda x: (-x[0], x[1]))
        self.assertEqual(scored[0][1], 1313)


if __name__ == "__main__":
    unittest.main()
