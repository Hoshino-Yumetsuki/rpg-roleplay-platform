"""游戏内手动切换的 per-save session_model 必须反映到 /api/state 的 app.*,
否则前端 Composer 永远显示/高亮全局默认模型,用户以为切换没保存(实际 GM 已用)。

测 _session_model_app_view:把 session_model (real_name, api_id) 解析成 app.* 展示 dict。
"""
import unittest

from app import _session_model_app_view

CATALOG = {
    "apis": [
        {
            "id": "anthropic", "display_name": "Anthropic", "kind": "anthropic",
            "models": [
                {"id": "claude-opus", "real_name": "claude-opus-4-x",
                 "display_name": "Claude Opus", "capabilities": ["tools"]},
            ],
        },
        {
            "id": "deepseek", "display_name": "DeepSeek", "kind": "openai",
            "models": [
                {"id": "ds-v4", "real_name": "deepseek-v4-flash", "display_name": "DeepSeek V4"},
            ],
        },
    ],
    "selected": {"api_id": "anthropic", "model_id": "claude-opus"},
}


class SessionModelAppView(unittest.TestCase):
    def test_none_session_returns_none(self):
        self.assertIsNone(_session_model_app_view(CATALOG, None))

    def test_match_by_real_name(self):
        # session_model 存的是 real_name(routes/models.select 传 model_id=item.real_name)
        view = _session_model_app_view(CATALOG, ("deepseek-v4-flash", "deepseek"))
        self.assertIsNotNone(view)
        self.assertEqual(view["api_id"], "deepseek")
        self.assertEqual(view["real_name"], "deepseek-v4-flash")
        self.assertEqual(view["model_id"], "ds-v4")
        self.assertEqual(view["display_name"], "DeepSeek V4")

    def test_match_by_id_also_works(self):
        view = _session_model_app_view(CATALOG, ("claude-opus", "anthropic"))
        self.assertIsNotNone(view)
        self.assertEqual(view["real_name"], "claude-opus-4-x")

    def test_unknown_model_returns_none(self):
        # 不在该用户 catalog → None,调用方回退全局默认展示
        self.assertIsNone(_session_model_app_view(CATALOG, ("ghost-model", "anthropic")))

    def test_unknown_api_returns_none(self):
        self.assertIsNone(_session_model_app_view(CATALOG, ("deepseek-v4-flash", "no-such-api")))

    def test_shape_matches_selected_model_keys(self):
        from model_registry import selected_model
        ref = set(selected_model(CATALOG).keys())
        view = _session_model_app_view(CATALOG, ("deepseek-v4-flash", "deepseek"))
        self.assertEqual(set(view.keys()), ref, "app.* 形状必须与 selected_model 一致")


if __name__ == "__main__":
    unittest.main()
