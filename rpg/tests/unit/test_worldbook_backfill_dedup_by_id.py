"""世界书常驻基线 backfill 必须按 entry 唯一 id 去重,而非 title。
按 title 去重时,同名(或空 title)条目一旦其一激活,其余高优先同名条目会被排除出
backfill → keys 为空、只能靠基线出场的核心设定漏注入('世界书是摆设'残留变体)。"""
import re
import unittest
from pathlib import Path

SRC = (Path(__file__).resolve().parents[2] / "context_engine" / "formatters.py").read_text(encoding="utf-8")


def _func(name: str) -> str:
    i = SRC.find(f"def {name}(")
    assert i != -1, name
    end = SRC.find("\ndef ", i + 1)
    return SRC[i: end if end != -1 else len(SRC)]


class WorldbookBackfillDedupById(unittest.TestCase):
    def setUp(self):
        self.body = _func("_active_worldbook")

    def test_dedup_uses_id_not_title(self):
        # backfill 过滤与激活/补足时的 seen 集合都应按 id
        self.assertIn("seen_ids", self.body, "去重集合应改名为 seen_ids(按 id)")
        self.assertNotIn("seen_titles", self.body, "仍残留 seen_titles(按 title 去重)")

    def test_seen_set_keyed_by_entry_id(self):
        self.assertTrue(re.search(r'seen_ids\.add\(str\(entry\.get\(\s*[\'"]id', self.body),
                        "激活时未把 entry id 加入 seen_ids")
        self.assertTrue(re.search(r'str\(e\.get\(\s*[\'"]id[\'"]\s*,\s*[\'"]{2}\)\)\s+not in seen_ids', self.body),
                        "backfill 过滤未按 id")

    def test_backfill_still_gated_on_min_constant(self):
        # 修复不应破坏 MIN_CONSTANT 补足门槛
        self.assertIn("MIN_CONSTANT", self.body)
        self.assertIn("len(active) < MIN_CONSTANT", self.body)


if __name__ == "__main__":
    unittest.main()
