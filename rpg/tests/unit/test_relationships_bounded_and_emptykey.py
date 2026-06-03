"""关系系统两处修复:
- short_summary 注入关系只取最近 N 条(原全量,长局 token 膨胀,同 known_events 类)。
- relationship op 空名守卫(/set relationships.=X 不再写空 key 关系条目)。
"""
import copy
import unittest

from state import DEFAULT_STATE, GameState


class RelationshipsInjectionBounded(unittest.TestCase):
    def test_short_summary_caps_relationships(self):
        st = GameState(copy.deepcopy(DEFAULT_STATE))
        for i in range(30):
            st.data["relationships"][f"NPC{i:03d}"] = "中立"
        summary = st.short_summary()
        # 最近 20 条 = NPC010..NPC029;更早的 NPC000..NPC009 不应注入
        self.assertIn("NPC029", summary)
        self.assertIn("NPC010", summary)
        self.assertNotIn("NPC009", summary, "注入了超过最近 20 条关系(token 无界)")
        self.assertNotIn("NPC000", summary)


class RelationshipEmptyKeyGuard(unittest.TestCase):
    def test_empty_name_relationship_op_skipped(self):
        st = GameState(copy.deepcopy(DEFAULT_STATE))
        # 模拟 /set relationships.=信任 → apply_state_write_typed kind=relationship, name=""
        # 直接调底层 typed write 路径(force 绕过 dispatcher 的 fallthrough)
        try:
            st.apply_state_write_typed("relationships.", "信任")
        except Exception:
            pass
        # 空 key 不应被写入
        self.assertNotIn("", st.data["relationships"], "空名关系被写入(/set 空 key 噪声)")
        # 正常名仍能写
        st.apply_state_write_typed("relationships.斯雷因", "信任")
        self.assertEqual(st.data["relationships"].get("斯雷因"), "信任")


if __name__ == "__main__":
    unittest.main()
