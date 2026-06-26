"""core/json_parse.py — 通用鲁棒 LLM JSON 解析(单一实现,多入口共用)。

LLM 输出的 JSON 常被散文、```json 围栏、前后噪声包裹。本模块提供一个最健壮的
解析器:直接解析 → 剥 ```json 围栏 → 带字符串/转义感知的平衡括号扫描(取**最早**
出现的开括号的平衡块,避免 list 响应里的内层 {} 被先抓)。

调用方各自决定失败语义:
- 需要 dict:  parse_llm_json(raw, want=dict) → 拿不到 None
- 需要 list:  parse_llm_json(raw, want=list) → 拿不到 None
- 任意类型:  parse_llm_json(raw)             → 拿不到 None
解析不到统一返回 None;调用方自行 None / [] / raise(见各处 GUARD)。

⚠️ 语义边界:state/json_ops.py 是【不同语义入口】——它从面向玩家的叙事里
**安全剥离 state-ops 块并保留正文 JSON、容忍截断半块**,误并会让玩家看到畸形
ops 或正文被误删。底层平衡括号扫描思路可借鉴,但**入口不合并**。本模块只服务
"整段响应就是一份 JSON(可能裹散文/围栏)"这一通用场景。
"""
from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)
_MISS = object()  # 哨兵:区分「解析失败」与「合法解析出 None/null」


def _balanced_scan(raw: str) -> Any | None:
    """带字符串/转义感知的平衡括号扫描,取**最早**出现的开括号的平衡块。

    取最早的开括号(而非最长/任意),否则 list 响应里的内层 {} 会被先抓。
    扫描时跳过字符串字面量内的括号与转义,保证不被正文里的 } 坑到。
    解析不到返回 None。
    """
    candidates = [
        (raw.find(o), o, c)
        for o, c in (("{", "}"), ("[", "]"))
        if raw.find(o) != -1
    ]
    candidates.sort()
    for start, open_ch, close_ch in candidates:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(raw)):
            ch = raw[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == open_ch:
                    depth += 1
                elif ch == close_ch:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(raw[start:i + 1])
                        except Exception:
                            break  # 该开括号的平衡块解析失败,试下一个候选
    return None


def parse_llm_json(raw: str, *, want: type | None = None) -> Any | None:
    """从 LLM 文本里鲁棒解析 JSON。解析不到返回 None。

    步骤:① 直接 json.loads → ② 剥 ```json 围栏 → ③ 平衡括号扫描(取最早开括号)。

    want=dict / want=list 时做类型过滤:解析出的顶层值类型不符也返回 None。
    want=None 时不限类型。
    """
    if not raw:
        return None
    raw = raw.strip()

    result: Any = _MISS

    # 1. 直接解析
    try:
        result = json.loads(raw)
    except Exception:
        result = _MISS

    # 2. 剥 ```json 围栏
    if result is _MISS:
        m = _FENCE_RE.search(raw)
        if m:
            try:
                result = json.loads(m.group(1).strip())
            except Exception:
                result = _MISS

    # 3. 平衡括号扫描(取最早开括号的平衡块)
    if result is _MISS:
        scanned = _balanced_scan(raw)
        if scanned is None:
            return None
        result = scanned

    if result is _MISS:
        return None

    # 类型过滤
    if want is not None and not isinstance(result, want):
        return None
    return result
