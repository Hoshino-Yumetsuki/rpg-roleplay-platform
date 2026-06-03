"""save_io._build_insert 列名 SQL 注入防护:导入 payload 的 row 键来自用户上传 JSON,
原代码把列名 f-string 直拼进 INSERT SQL → 列名注入(可构造 INSERT...SELECT 跨表窃取
他人存档/凭证)。修后列名按该表真实列(DB 目录)白名单过滤,伪造列名一律丢弃。"""
import unittest
from pathlib import Path

from platform_app.save_io import _build_insert

SRC = (Path(__file__).resolve().parents[2] / "platform_app" / "save_io.py").read_text(encoding="utf-8")

ALLOWED = frozenset({"save_id", "anchor_id", "status", "payload"})


class SaveImportColInjection(unittest.TestCase):
    def test_injection_column_name_dropped(self):
        evil = "leaked) select 1, secret from user_credentials --"
        row = {"anchor_id": "a1", "status": "done", evil: "x"}
        sql, vals = _build_insert("save_anchor_states", row, 7, ALLOWED)
        # 注入键不是真实列 → 必须被丢弃,不出现在 SQL
        self.assertNotIn("leaked", sql)
        self.assertNotIn("select 1", sql)
        self.assertNotIn("user_credentials", sql)
        # 合法列仍在
        self.assertIn("anchor_id", sql)
        self.assertIn("status", sql)
        # 值数量 = save_id + 2 合法列
        self.assertEqual(len(vals), 3)

    def test_only_known_columns_emitted(self):
        row = {"anchor_id": "a1", "bogus_col": "y", "status": "ok"}
        sql, vals = _build_insert("save_anchor_states", row, 1, ALLOWED)
        self.assertNotIn("bogus_col", sql)
        self.assertEqual(len(vals), 3)  # save_id + anchor_id + status

    def test_save_id_not_duplicated(self):
        # row 里若混入 save_id,不应产生重复列
        row = {"save_id": 999, "status": "ok"}
        sql, vals = _build_insert("save_anchor_states", row, 5, ALLOWED)
        self.assertEqual(sql.count("save_id"), 1)
        self.assertEqual(vals[0], 5)  # 用 new_save_id,非上传值
        self.assertNotIn(999, vals)

    def test_source_filters_against_table_columns(self):
        # 导入循环必须取该表真实列集合并传入 _build_insert
        self.assertIn("allowed_cols = _table_columns(db, table)", SRC)
        self.assertIn("information_schema.columns", SRC)
        self.assertIn("if k not in allowed_cols", SRC)


if __name__ == "__main__":
    unittest.main()
