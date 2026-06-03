"""已下线模型(如 gemini-1.5-pro-002,Vertex 调用返 404 NOT_FOUND)可能残留在
历史存储 catalog(DB model_entries)或用户 overlay(user_model_entries)里。
core.llm_backend.first_user_model 的兜底盲取"第一个 enabled 模型",会撞上它们,
导致身份卡生成 / phase compact 等子代理对无偏好用户一律失败。

测代码层黑名单过滤:_migrate_catalog(全局)+ apply_user_overlay(每用户)统一剔除。
"""
import unittest

import model_registry as mr


class IsOfflineModel(unittest.TestCase):
    def test_matches_known_vertex_dead_by_id(self):
        self.assertTrue(mr._is_offline_model("vertex_ai", {"id": "gemini-1.5-pro-002"}))

    def test_matches_via_api_alias(self):
        # AgentPlatform / vertex 都归一化到 vertex_ai
        self.assertTrue(mr._is_offline_model("AgentPlatform", {"real_name": "gemini-1.5-pro-002"}))

    def test_live_model_not_flagged(self):
        self.assertFalse(mr._is_offline_model("vertex_ai", {"id": "gemini-2.5-flash"}))

    def test_dead_name_under_other_provider_not_flagged(self):
        # 黑名单按 provider 归一化 scope,vertex 专属不误伤别家同名(理论)
        self.assertFalse(mr._is_offline_model("openai", {"id": "gemini-1.5-pro-002"}))


class MigrateCatalogStripsOffline(unittest.TestCase):
    def test_dead_model_removed_live_kept(self):
        catalog = {
            "schema_version": 1,
            "selected": {"api_id": "vertex_ai", "model_id": "gemini-2.5-flash"},
            "apis": [
                {
                    "id": "vertex_ai", "display_name": "Vertex AI", "kind": "vertex_ai",
                    "enabled": True,
                    "models": [
                        {"id": "gemini-1.5-pro-002", "real_name": "gemini-1.5-pro-002",
                         "display_name": "dead", "enabled": True},
                        {"id": "gemini-2.5-flash", "real_name": "gemini-2.5-flash",
                         "display_name": "live", "enabled": True},
                    ],
                },
            ],
        }
        out = mr._migrate_catalog(catalog)
        vertex = mr.find_api(out, "vertex_ai")
        ids = [m["id"] for m in vertex["models"]]
        self.assertNotIn("gemini-1.5-pro-002", ids)
        self.assertIn("gemini-2.5-flash", ids)

    def test_dead_model_first_does_not_become_default(self):
        # gemini-1.5-pro-002 排首且 enabled → 过滤后 selected 兜底不能选它
        catalog = {
            "apis": [
                {
                    "id": "vertex_ai", "kind": "vertex_ai", "enabled": True,
                    "models": [
                        {"id": "gemini-1.5-pro-002", "real_name": "gemini-1.5-pro-002", "enabled": True},
                        {"id": "gemini-2.5-flash", "real_name": "gemini-2.5-flash", "enabled": True},
                    ],
                },
            ],
            "selected": {"api_id": "vertex_ai", "model_id": "gemini-1.5-pro-002"},
        }
        out = mr._migrate_catalog(catalog)
        self.assertNotEqual(out["selected"]["model_id"], "gemini-1.5-pro-002")

    def test_provider_all_dead_keeps_list_no_crash(self):
        # degenerate:某 provider 全是下线模型 → 保留原列表,避免空 models 撑爆 first_enabled_model
        catalog = {
            "apis": [
                {"id": "vertex_ai", "kind": "vertex_ai", "enabled": True,
                 "models": [{"id": "gemini-1.5-pro-002", "real_name": "gemini-1.5-pro-002", "enabled": True}]},
            ],
            "selected": {"api_id": "vertex_ai", "model_id": "gemini-1.5-pro-002"},
        }
        out = mr._migrate_catalog(catalog)  # 不应抛 IndexError
        vertex = mr.find_api(out, "vertex_ai")
        self.assertTrue(vertex["models"])  # 列表非空


class ApplyUserOverlaySkipsEmptyAfterFilter(unittest.TestCase):
    def setUp(self):
        # 不碰 DB:直接注入 overlay
        self._orig = None

    def test_overlay_only_dead_keeps_global_models(self):
        global_catalog = {
            "apis": [
                {"id": "vertex_ai", "kind": "vertex_ai", "enabled": True,
                 "models": [
                     {"id": "gemini-2.5-flash", "real_name": "gemini-2.5-flash", "enabled": True},
                     {"id": "gemini-2.5-pro", "real_name": "gemini-2.5-pro", "enabled": True},
                 ]},
            ],
            "selected": {"api_id": "vertex_ai", "model_id": "gemini-2.5-flash"},
        }
        import platform_app.user_models as um
        orig = um.load_overlay
        # 用户 overlay 的 vertex 清单仅含下线模型 → 过滤后空 → 不能用空清单覆盖全局
        um.load_overlay = lambda uid: {"vertex_ai": [
            {"id": "gemini-1.5-pro-002", "real_name": "gemini-1.5-pro-002", "enabled": True},
        ]}
        try:
            out = mr.apply_user_overlay(global_catalog, 999)
        finally:
            um.load_overlay = orig
        vertex = mr.find_api(out, "vertex_ai")
        ids = [m["id"] for m in vertex["models"]]
        self.assertNotIn("gemini-1.5-pro-002", ids)
        self.assertIn("gemini-2.5-flash", ids)  # 全局好模型保留

    def test_overlay_with_live_models_replaces_and_filters(self):
        global_catalog = {
            "apis": [
                {"id": "vertex_ai", "kind": "vertex_ai", "enabled": True,
                 "models": [{"id": "gemini-2.5-flash", "real_name": "gemini-2.5-flash", "enabled": True}]},
            ],
            "selected": {"api_id": "vertex_ai", "model_id": "gemini-2.5-flash"},
        }
        import platform_app.user_models as um
        orig = um.load_overlay
        um.load_overlay = lambda uid: {"vertex_ai": [
            {"id": "gemini-1.5-pro-002", "real_name": "gemini-1.5-pro-002", "enabled": True},
            {"id": "gemini-2.5-pro", "real_name": "gemini-2.5-pro", "enabled": True},
        ]}
        try:
            out = mr.apply_user_overlay(global_catalog, 999)
        finally:
            um.load_overlay = orig
        vertex = mr.find_api(out, "vertex_ai")
        ids = [m["id"] for m in vertex["models"]]
        self.assertEqual(ids, ["gemini-2.5-pro"])  # 死模型剔除,活模型替换全局


if __name__ == "__main__":
    unittest.main()
