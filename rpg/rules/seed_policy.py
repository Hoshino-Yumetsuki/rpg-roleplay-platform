"""骰子 seed 策略 —— 不可信外部来源(HTTP body / LLM 工具 args)提供的随机种子一律忽略。

安全背景:`rules/dice.py::_rng(seed)` = `random.Random(seed)`,给定 seed 完全可重现。若把
客户端(玩家 REST body)或 LLM(GM 工具 args)提供的 seed 原样透传到掷骰,玩家可在本地穷举
出能掷出自然 20 / 暴击 / 豁免必过的 seed 再提交,单方面操纵每次检定/攻击结果,整个确定性
骰子系统在直连 API 层失去意义。GM 侧同理(LLM 可被提示注入或幻觉出固定 seed)。

策略:外部 seed 默认丢弃 → 返 None → 掷骰用服务端新鲜随机数。仅在测试(pytest 自动注入
PYTEST_CURRENT_TEST)或显式开 RPG_ALLOW_CLIENT_SEED 时才接受数字 seed,保留测试可复现性。

注意:本函数只用于**外部不可信入口**的 seed 归一化。内部代码 / 测试直接调
`rules_bridge.player_attack(state, seed=123)` 等不经此函数,determinism 不受影响。
"""
from __future__ import annotations

import os
from typing import Any


def _client_seed_allowed() -> bool:
    if "PYTEST_CURRENT_TEST" in os.environ:
        return True
    return os.environ.get("RPG_ALLOW_CLIENT_SEED", "").strip().lower() in ("1", "true", "yes", "on")


def coerce_external_seed(seed: Any) -> int | None:
    """把外部来源 seed 归一化:默认返 None(忽略),仅测试/显式允许时返数字 seed。"""
    if not _client_seed_allowed():
        return None
    if isinstance(seed, (int, float, str)) and str(seed).lstrip("-").isdigit():
        return int(seed)
    return None
