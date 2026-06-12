"""
test_history_no_empty_assistant.py
==================================

回归:某些 provider(moonshot/kimi 等)对**空 assistant 消息**直接 400
「the message at position N with role 'assistant' must not be empty」→ 整轮失败。
且历史一旦混入空 assistant(上一轮空回复/失败被记进 history),之后每轮重放都炸
(生产实证:user 114 拾酒「继续推进剧情」反复失败)。

两道防线:
  · record_turn:空回复(且无 tool_ops/reasoning)不记进历史。
  · history_messages:喂给 backend 前再过滤一道空 content 消息(兼修已污染存档)。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]  # rpg/
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from state import GameState


class HistoryMessagesFiltersEmpty(unittest.TestCase):
    def test_poisoned_history_empty_assistant_filtered(self):
        g = GameState.new()
        # 模拟已被污染的存档:中间混入一条空 assistant
        g.data["history"] = [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": ""},          # ← 毒
            {"role": "user", "content": "继续推进剧情"},
        ]
        msgs = g.history_messages(save_id=None)
        self.assertTrue(all(str(m.get("content") or "").strip() for m in msgs),
                        f"空 content 消息未被过滤: {msgs!r}")
        self.assertEqual([m["content"] for m in msgs], ["你好", "继续推进剧情"])

    def test_whitespace_and_none_content_filtered(self):
        g = GameState.new()
        g.data["history"] = [
            {"role": "assistant", "content": "   \n  "},
            {"role": "user", "content": None},
            {"role": "assistant", "content": "真实正文"},
        ]
        msgs = g.history_messages(save_id=None)
        self.assertEqual([m["content"] for m in msgs], ["真实正文"])


class RecordTurnGuardsEmpty(unittest.TestCase):
    def test_empty_response_not_recorded(self):
        g = GameState.new()
        before = len(g.data["history"])
        g.record_turn("玩家输入", "")          # 空回复
        g.record_turn("玩家输入2", "   ")       # 纯空白
        self.assertEqual(len(g.data["history"]), before)  # 一条都没记

    def test_normal_turn_recorded(self):
        g = GameState.new()
        before = len(g.data["history"])
        g.record_turn("玩家输入", "GM 的正文回复")
        self.assertEqual(len(g.data["history"]), before + 2)  # user + assistant
        self.assertEqual(g.data["history"][-1], {"role": "assistant", "content": "GM 的正文回复"})

    def test_tool_only_turn_still_recorded(self):
        g = GameState.new()
        # 工具轮:正文空但有 tool_ops → 仍应记录(供前端显示),不被空回复闸拦掉
        g.data["_turn_tool_ops"] = [{"tool": "set_flag", "args": {}}]
        before = len(g.data["history"])
        g.record_turn("玩家输入", "")
        self.assertEqual(len(g.data["history"]), before + 2)
        self.assertIn("tool_ops", g.data["history"][-1])


if __name__ == "__main__":
    unittest.main()
