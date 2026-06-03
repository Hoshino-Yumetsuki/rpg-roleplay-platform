"""锚点状态机两处逻辑修复(子代理深审发现,逐条核实):
- revoke_protagonist_pov 须按 claim 签名反查,镜像 claim(否则靠 must_preserve 命中的
  锚点被 claim 标 occurred 却永不重置 → POV 切回后原著事件永久吞失)。
- get_progress_window 须把 superseded 计入"已处理最大章"(否则早章绕过后进度窗口冻结在开头)。
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANCHORS_PY = (ROOT / "tools_dsl" / "command_tools_anchors.py").read_text(encoding="utf-8")
SEED_PY = (ROOT / "agents" / "anchor_seed_agent.py").read_text(encoding="utf-8")


def _func(src: str, name: str) -> str:
    idx = src.find(f"def {name}(")
    assert idx != -1, name
    end = src.find("\ndef ", idx + 1)
    return src[idx: end if end != -1 else len(src)]


class RevokePovMirrorsClaim(unittest.TestCase):
    def setUp(self):
        self.claim = _func(ANCHORS_PY, "_t_claim_protagonist_pov")
        self.revoke = _func(ANCHORS_PY, "_t_revoke_protagonist_pov")

    def test_claim_writes_signature(self):
        # claim 给标记锚点统一写 variant_description 含 "代入 {name} 的 POV 位置"
        self.assertIn("代入 {name} 的 POV 位置", self.claim)

    def test_revoke_matches_claim_signature(self):
        # revoke 应按 claim 签名反查
        self.assertIn("代入 {name} 的 POV 位置", self.revoke)

    def test_revoke_no_longer_requires_first_appearance_summary(self):
        # 旧 bug:revoke 的 WHERE 要求 summary like '%X(character)首次登场%'(AND),
        # 把靠 must_preserve 命中的锚点排除 → 修复后不应再用该强制 summary 条件做反查门槛
        select_block = self.revoke[self.revoke.find("select id, anchor_key"):]
        select_block = select_block[:select_block.find(").fetchall()")]
        self.assertNotIn("首次登场", select_block,
                         "revoke 反查仍强制 summary 含'首次登场',会漏掉 must_preserve 命中的锚点")


class ProgressWindowIncludesSuperseded(unittest.TestCase):
    def test_window_max_chapter_includes_superseded(self):
        body = _func(SEED_PY, "get_progress_window")
        # 取"已处理最大章"那条 SQL 的 status 集合
        m = re.search(r"max\(source_chapter\).*?status in \(([^)]*)\)", body, re.S)
        self.assertIsNotNone(m, "未找到 progress window 的 max(source_chapter) 查询")
        status_set = m.group(1)
        for st in ("occurred", "variant", "superseded"):
            self.assertIn(st, status_set,
                          f"进度窗口的已处理最大章未含 {st}(superseded 漏算会冻结进度)")


if __name__ == "__main__":
    unittest.main()
