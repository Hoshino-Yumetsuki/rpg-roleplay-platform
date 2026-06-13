"""OSS issue #22 回归：换/删 APIKey 后游戏控制台模型列表不刷新。

根因：per-user 模型 overlay(user_model_entries)不随凭据变化清理 —
  · delete_credential 删了 key 却不清 overlay → 旧 key 同步来的模型残留；
  · set_credential 换 key 后若新 key 的 /models 列不出(失败/空)，旧 overlay 留着。

这里用真实 DB 验证两条修复路径 + happy-path 不回归。
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("RPG_DEPLOYMENT_MODE", "local")  # 本地模式 → 加密走文件 fallback


class TestCredentialOverlaySync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from platform_app.db import connect, init_db
        init_db()
        with connect() as db:
            row = db.execute(
                """
                insert into users(username, display_name, password_hash, email)
                values (%s, %s, %s, %s)
                returning id
                """,
                ("overlay_sync_uat", "Overlay UAT", "x", "overlay_sync_uat@example.com"),
            ).fetchone()
            cls.uid = int(row["id"])

    @classmethod
    def tearDownClass(cls):
        from platform_app.db import connect
        with connect() as db:
            db.execute("delete from user_model_entries where user_id = %s", (cls.uid,))
            db.execute("delete from user_api_credentials where user_id = %s", (cls.uid,))
            db.execute("delete from users where id = %s", (cls.uid,))

    def setUp(self):
        # 每个用例前清干净 overlay + 凭据
        from platform_app.db import connect
        with connect() as db:
            db.execute("delete from user_model_entries where user_id = %s", (self.uid,))
            db.execute("delete from user_api_credentials where user_id = %s", (self.uid,))

    def _seed_overlay(self):
        """模拟「旧 key 拉取远程模型」写进 overlay 的状态。"""
        from platform_app.user_models import load_overlay, replace_synced_models
        replace_synced_models(self.uid, "deepseek", [
            {"id": "old-model-a", "real_name": "old-model-a", "display_name": "Old A"},
            {"id": "old-model-b", "real_name": "old-model-b", "display_name": "Old B"},
        ])
        overlay = load_overlay(self.uid)
        self.assertIn("deepseek", overlay)
        self.assertEqual(len(overlay["deepseek"]), 2)

    def test_delete_credential_clears_overlay(self):
        from platform_app import user_credentials
        from platform_app.user_models import load_overlay
        self._seed_overlay()
        user_credentials.delete_credential(self.uid, "deepseek")
        overlay = load_overlay(self.uid)
        self.assertNotIn(
            "deepseek", overlay,
            "删 key 后该 provider 的 overlay 应被清空，否则旧模型残留在模型列表",
        )

    def test_set_credential_clears_overlay_when_sync_fails(self):
        """换新 key 但新 key /models 列不出(ok=False)→ 必须清掉旧 overlay。"""
        import model_probe
        from platform_app import user_credentials
        from platform_app.user_models import load_overlay
        self._seed_overlay()
        orig = model_probe.list_remote_models
        model_probe.list_remote_models = lambda *a, **k: {"ok": False, "error": "no /models"}
        try:
            user_credentials.set_credential(self.uid, "deepseek", "sk-new-key-xyz")
        finally:
            model_probe.list_remote_models = orig
        overlay = load_overlay(self.uid)
        self.assertNotIn(
            "deepseek", overlay,
            "换 key 后新 key 列不出模型时，旧 key 的 overlay 应被清空(回退全局菜单)",
        )

    def test_set_credential_replaces_overlay_on_successful_sync(self):
        """happy path 不回归：新 key 能列出模型 → overlay 被新清单替换。"""
        import model_probe
        from platform_app import user_credentials
        from platform_app.user_models import load_overlay
        self._seed_overlay()
        orig = model_probe.list_remote_models
        model_probe.list_remote_models = lambda *a, **k: {
            "ok": True,
            "models": [{"id": "new-model-z", "real_name": "new-model-z", "display_name": "New Z"}],
        }
        try:
            user_credentials.set_credential(self.uid, "deepseek", "sk-new-key-xyz")
        finally:
            model_probe.list_remote_models = orig
        overlay = load_overlay(self.uid)
        self.assertIn("deepseek", overlay)
        names = {m.get("real_name") or m.get("id") for m in overlay["deepseek"]}
        self.assertEqual(names, {"new-model-z"}, "应只剩新 key 同步来的模型，旧模型被移除")


if __name__ == "__main__":
    unittest.main()
