"""test_security_batch3.py — 安全审计 Batch 3 回归测试(认证凭据生命周期)。

无 DB 依赖的纯逻辑校验:
- H-7: _pending_store_set/get round-trip(Redis 不可用时回退进程内 dict)+ consume 语义;
       且 _encode/_decode_pending_register 往返保真。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class PendingRegisterStore(unittest.TestCase):
    def test_set_get_roundtrip_inmemory(self):
        from platform_app import auth
        payload = {"username": "alice", "password_hash": "$argon2id$xxx", "birthday": "2000-01-01"}
        pj = auth._encode_pending_register(payload)
        auth._pending_store_set("alice@example.com", pj)
        got = auth._pending_store_get("alice@example.com")
        self.assertEqual(got, pj)
        decoded = auth._decode_pending_register(got)
        self.assertEqual(decoded["username"], "alice")
        self.assertEqual(decoded["password_hash"], "$argon2id$xxx")

    def test_consume_removes_from_store(self):
        from platform_app import auth
        pj = auth._encode_pending_register(
            {"username": "bob", "password_hash": "h", "birthday": "1999-12-31"}
        )
        auth._pending_store_set("bob@example.com", pj)
        first = auth._pending_store_get("bob@example.com", consume=True)
        self.assertEqual(first, pj)
        # consume 后再取应为空(进程内已 pop;Redis 不可用)
        second = auth._pending_store_get("bob@example.com")
        self.assertIsNone(second)

    def test_decode_rejects_incomplete(self):
        from platform_app import auth
        # 缺 password_hash → None(防半残 payload)
        bad = auth._encode_pending_register({"username": "x", "birthday": "2000-01-01"})
        self.assertIsNone(auth._decode_pending_register(bad))


if __name__ == "__main__":
    unittest.main()
