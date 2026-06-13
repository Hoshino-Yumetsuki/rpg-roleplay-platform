"""
test_outbound_ua.py
===================

回归:用户自建中转站挂 Cloudflare 后,WAF 按 User-Agent 拦截。openai SDK 默认 UA
`OpenAI/Python <ver>` 会被 403「Your request was blocked」/ error 1010 直接挡掉
→ 这类中转站「校验连接 / 拉取模型 / 聊天」全部「不可访问」。实测浏览器 UA 能穿透。

不变量(锁死):
  · 所有出站 OpenAI 兼容请求统一覆盖 UA,且**绝不**是 openai SDK / urllib 的默认签名。
  · 两个 SDK 构造点(生成 openai_compat.py、列模型 model_probe.py)都把 default_headers
    传进 OpenAI(...)。
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]  # rpg/
import sys
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from core.outbound_ua import openai_default_headers, outbound_user_agent  # noqa: E402

OPENAI_COMPAT_PY = (PROJECT / "agents" / "gm" / "backends" / "openai_compat.py").read_text(encoding="utf-8")
MODEL_PROBE_PY = (PROJECT / "model_probe.py").read_text(encoding="utf-8")


class OutboundUaHelper(unittest.TestCase):
    def test_default_ua_is_not_a_blocked_signature(self):
        ua = outbound_user_agent()
        self.assertTrue(ua)
        self.assertNotIn("OpenAI/Python", ua)
        self.assertNotIn("urllib", ua.lower())
        # 默认走浏览器签名(最稳穿透 WAF)
        self.assertIn("Mozilla/5.0", ua)

    def test_header_dict_sets_user_agent(self):
        h = openai_default_headers()
        self.assertEqual(set(h), {"User-Agent"})
        self.assertEqual(h["User-Agent"], outbound_user_agent())

    def test_env_override_respected(self):
        prev = os.environ.get("RPG_OUTBOUND_UA")
        try:
            os.environ["RPG_OUTBOUND_UA"] = "my-custom-agent/9.9"
            self.assertEqual(outbound_user_agent(), "my-custom-agent/9.9")
            self.assertEqual(openai_default_headers()["User-Agent"], "my-custom-agent/9.9")
        finally:
            if prev is None:
                os.environ.pop("RPG_OUTBOUND_UA", None)
            else:
                os.environ["RPG_OUTBOUND_UA"] = prev

    def test_blank_env_falls_back_to_default(self):
        prev = os.environ.get("RPG_OUTBOUND_UA")
        try:
            os.environ["RPG_OUTBOUND_UA"] = "   "
            self.assertIn("Mozilla/5.0", outbound_user_agent())
        finally:
            if prev is None:
                os.environ.pop("RPG_OUTBOUND_UA", None)
            else:
                os.environ["RPG_OUTBOUND_UA"] = prev


class BothSdkSitesOverrideUa(unittest.TestCase):
    def test_generation_passes_default_headers(self):
        self.assertIn("from core.outbound_ua import openai_default_headers", OPENAI_COMPAT_PY)
        self.assertIn('"default_headers": openai_default_headers()', OPENAI_COMPAT_PY)

    def test_model_listing_passes_default_headers(self):
        self.assertIn("from core.outbound_ua import openai_default_headers", MODEL_PROBE_PY)
        self.assertRegex(
            MODEL_PROBE_PY,
            r'kwargs[^\n]*=\s*\{[^\n]*"default_headers":\s*openai_default_headers\(\)',
        )


class SdkActuallyOverridesBuiltinUa(unittest.TestCase):
    """行为验证:openai SDK 把我们的 default_headers 合并在最后,确实覆盖内置 UA。"""

    def test_resolved_user_agent_is_overridden(self):
        try:
            from openai import OpenAI
        except Exception as exc:  # pragma: no cover
            self.skipTest(f"openai SDK 不可用: {exc}")
        c = OpenAI(api_key="x", base_url="https://example.com/v1", default_headers=openai_default_headers())
        self.assertEqual(c.default_headers.get("User-Agent"), outbound_user_agent())
        self.assertNotIn("OpenAI/Python", c.default_headers.get("User-Agent", ""))


if __name__ == "__main__":
    unittest.main()
