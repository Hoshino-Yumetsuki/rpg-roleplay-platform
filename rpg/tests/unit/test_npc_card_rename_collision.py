"""
test_npc_card_rename_collision.py
=================================

群反馈(晓卡):剧本里 NPC 角色卡点编辑后「保存按钮点了没反应」。prod 日志真因:
  psycopg.errors.UniqueViolation: duplicate key "uq_character_cards_npc_name"
  at character_cards.py upsert_character_card(UPDATE 分支)
即把 NPC 卡改名成**该剧本已有的另一个 NPC 名**,撞 UNIQUE(script_id,name) WHERE npc 约束,
裸 UniqueViolation 冒成 500(端点只 catch ValueError→400),前端表现为「保存没反应」。
普通编辑(不改名)不受影响——行更新自身不撞唯一约束。

不变量(源码级):
- upsert UPDATE 分支:改名前预检「别的 NPC 是否已占用该名」(id<>),命中给可行动 ValueError。
- 端点兜底:任何残留 UniqueViolation(竞态/其它路径)转 400,不再 500。
"""
from __future__ import annotations

import unittest
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]  # rpg/
CARDS_PY = (PROJECT / "platform_app" / "knowledge" / "character_cards.py").read_text(encoding="utf-8")
SCRIPTS_API = (PROJECT / "platform_app" / "api" / "scripts.py").read_text(encoding="utf-8")


class UpdatePreChecksNameCollision(unittest.TestCase):
    def test_rename_clash_precheck_present(self):
        # UPDATE 分支改名前查冲突:别的 NPC(id<>)已占用该 name
        self.assertRegex(
            CARDS_PY,
            r"select 1 from character_cards where script_id = %s and name = %s\s*"
            r"\"?\s*\n?\s*\"?and card_type='npc' and id <> %s",
        )

    def test_clash_raises_actionable_valueerror(self):
        self.assertIn("已存在同名 NPC 角色卡", CARDS_PY)
        # 必须是 ValueError(端点 ValueError→400 可显示),不是裸 raise
        self.assertRegex(CARDS_PY, r'if clash:\s*\n\s*raise ValueError\(')

    def test_same_name_self_update_not_blocked(self):
        # 预检带 id <> %s,确保「不改名的普通编辑」(更新自身)不被误拦
        self.assertIn("id <> %s", CARDS_PY)


class EndpointConvertsUniqueViolationTo400(unittest.TestCase):
    def test_endpoint_catches_unique_violation(self):
        self.assertIn("from psycopg.errors import UniqueViolation", SCRIPTS_API)
        self.assertRegex(SCRIPTS_API, r"isinstance\(exc, UniqueViolation\)")
        # 转 400 + 可行动文案
        self.assertRegex(SCRIPTS_API, r'status_code=400')
        self.assertIn("已存在同名 NPC 角色卡", SCRIPTS_API)


if __name__ == "__main__":
    unittest.main()
