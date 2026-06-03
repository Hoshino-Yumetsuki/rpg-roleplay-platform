"""骰子 seed 策略:外部不可信来源(玩家 REST body / LLM 工具 args)的 seed 默认忽略,
防玩家穷举 seed 刷暴击/必胜。测试期(PYTEST_CURRENT_TEST 在)或显式 RPG_ALLOW_CLIENT_SEED
才接受,保留可复现性。"""
import os
import unittest
from unittest import mock

from rules.seed_policy import coerce_external_seed


class SeedPolicy(unittest.TestCase):
    def test_pytest_env_allows_seed(self):
        # 跑测试时 PYTEST_CURRENT_TEST 必然存在 → 接受 seed(保测试确定性)
        self.assertIn("PYTEST_CURRENT_TEST", os.environ)
        self.assertEqual(coerce_external_seed(7), 7)
        self.assertEqual(coerce_external_seed("42"), 42)
        self.assertEqual(coerce_external_seed("-3"), -3)

    def test_production_ignores_seed(self):
        # 模拟生产:无 pytest 环境、无显式开关 → 外部 seed 一律丢弃
        env = {k: v for k, v in os.environ.items()
               if k not in ("PYTEST_CURRENT_TEST", "RPG_ALLOW_CLIENT_SEED")}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertIsNone(coerce_external_seed(7))
            self.assertIsNone(coerce_external_seed("42"))
            self.assertIsNone(coerce_external_seed(99999))

    def test_explicit_flag_allows_seed(self):
        env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
        env["RPG_ALLOW_CLIENT_SEED"] = "1"
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(coerce_external_seed(7), 7)

    def test_non_numeric_seed_is_none(self):
        self.assertIsNone(coerce_external_seed("abc"))
        self.assertIsNone(coerce_external_seed(None))
        self.assertIsNone(coerce_external_seed({"x": 1}))


if __name__ == "__main__":
    unittest.main()
