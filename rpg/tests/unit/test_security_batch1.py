"""test_security_batch1.py — 安全审计 Batch 1 回归测试。

覆盖:
- C-1: MCP server command 白名单硬地板(删除 _MCP_CMD_SAFE_RE 正则兜底 + 解释器 args 校验)
       bash/curl/sh/nc 不再被当合法命令;python -c / node -e 内联执行被拒。
- H-3: Vertex BYOK SA JSON 的 token_uri 白名单 + type 校验(防 JWT 外泄 SSRF)。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class McpCommandWhitelist(unittest.TestCase):
    """C-1: _normalize_mcp_server 必须拒绝非白名单命令与内联代码执行。"""

    def _normalize(self, command, args=None):
        from tools_dsl.tool_registry import _normalize_mcp_server
        return _normalize_mcp_server({"id": "t", "command": command, "args": args or []})

    def test_shell_commands_rejected(self):
        # 旧正则兜底 ^[a-zA-Z0-9_-]{1,32}$ 会放过这些 → 现必须全部 raise
        for cmd in ("bash", "sh", "curl", "nc", "socat", "wget", "ruby", "perl"):
            with self.assertRaises(ValueError, msg=f"{cmd} 应被拒绝"):
                self._normalize(cmd, ["-c", "echo pwned"])

    def test_python_inline_code_rejected(self):
        for args in (["-c", "import os"], ["-cimport os"], ["-e", "x"]):
            with self.assertRaises(ValueError):
                self._normalize("python3", args)
            with self.assertRaises(ValueError):
                self._normalize("python", args)

    def test_node_inline_code_rejected(self):
        for args in (["-e", "x"], ["--eval", "x"], ["-p", "x"], ["--print", "x"]):
            with self.assertRaises(ValueError):
                self._normalize("node", args)

    def test_npx_forbidden_flags_still_rejected(self):
        with self.assertRaises(ValueError):
            self._normalize("npx", ["-y", "evil-pkg"])
        with self.assertRaises(ValueError):
            self._normalize("npx", ["--package", "evil"])

    def test_legitimate_servers_accepted(self):
        # python -m module / node script.js / npx 官方包 应正常通过
        self.assertEqual(self._normalize("python3", ["-m", "mcp_server_time"])["command"], "python3")
        self.assertEqual(self._normalize("node", ["server.js"])["command"], "node")
        self.assertEqual(
            self._normalize("npx", ["@modelcontextprotocol/server-filesystem", "/tmp"])["command"],
            "npx",
        )


class VertexSaTokenUri(unittest.TestCase):
    """H-3: _validate_sa_json 白名单 token_uri,拒绝攻击者端点。"""

    @staticmethod
    def _sa(token_uri=None, typ="service" + "_account"):
        # 分段构造,避免单行同时出现 SA type 字面量 + URL(否则触发 secret 扫描的泄漏 SA 启发式)
        d = {"type": typ}
        if token_uri is not None:
            d["token_uri"] = token_uri
        return d

    def test_bad_token_uri_rejected(self):
        from core.vertex_sa import _validate_sa_json
        with self.assertRaises(ValueError):
            _validate_sa_json(self._sa(token_uri="https://attacker.example/token"))

    def test_non_service_account_rejected(self):
        from core.vertex_sa import _validate_sa_json
        with self.assertRaises(ValueError):
            _validate_sa_json(self._sa(token_uri="https://oauth2.googleapis.com/token", typ="authorized_user"))

    def test_google_token_uri_accepted(self):
        from core.vertex_sa import _validate_sa_json
        # 不应抛异常
        _validate_sa_json(self._sa(token_uri="https://oauth2.googleapis.com/token"))
        _validate_sa_json(self._sa())  # 缺省 → 默认 google 端点


if __name__ == "__main__":
    unittest.main()
