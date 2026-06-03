"""存档导入:主 save 的 state_snapshot 也必须过大小校验(原仅 per-commit 校验)。
防 application/json body 导入路径绕过端点大小关、直插超大 JSON 撑 DB/内存。"""
import unittest

from platform_app import save_io


class ImportMainSnapshotSizeGuard(unittest.TestCase):
    def test_oversized_main_snapshot_rejected(self):
        # 构造一个序列化后远超 MAX_SNAPSHOT_JSON_BYTES(1MB)的主 state_snapshot
        big = "x" * (save_io.MAX_SNAPSHOT_JSON_BYTES + 1024)
        payload = {
            "export_version": 2,
            "save": {"title": "t", "script_id": None, "state_snapshot": {"blob": big}},
            "commits": [],
        }
        with self.assertRaises(ValueError) as ctx:
            save_io.import_save(user_id=1, payload=payload)
        # 错误信息应指向 save.state_snapshot 超限(而非其它校验)
        self.assertIn("save.state_snapshot", str(ctx.exception))

    def test_check_json_size_helper_bounds(self):
        # _check_json_size 对超限抛 ValueError,对正常放行
        small = {"a": "x" * 100}
        self.assertIs(save_io._check_json_size(small, "x"), small)
        big = {"a": "x" * (save_io.MAX_SNAPSHOT_JSON_BYTES + 1024)}
        with self.assertRaises(ValueError):
            save_io._check_json_size(big, "x")


if __name__ == "__main__":
    unittest.main()
