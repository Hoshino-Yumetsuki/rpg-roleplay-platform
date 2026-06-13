"""core.outbound_ua —— 统一出站 OpenAI 兼容请求的 User-Agent。

背景(确定性,已实测):不少用户自建中转站(中国区尤甚)挂在 Cloudflare 后,WAF 规则
按 User-Agent 拦截。实测某中转站对:
  · `OpenAI/Python x.y.z`(openai SDK 默认 UA) → 403 "Your request was blocked"
  · `Python-urllib/3.x`                        → 403 error 1010
而浏览器 / `curl` / `python-httpx` 的 UA 能正常到达源站(401 Invalid token = 已穿透 WAF)。

openai SDK 默认带 `OpenAI/Python <ver>` UA → 对这类中转站「校验连接 / 拉取模型 / 聊天」
**全部不可用**(表现为「不可访问」)。故对所有出站 OpenAI 兼容请求统一覆盖 UA。

可用环境变量 `RPG_OUTBOUND_UA` 覆盖默认值(自托管用户若想用别的签名)。
"""
from __future__ import annotations

import os

# 浏览器 UA 最稳:实测能穿透按「已知 AI SDK / 爬虫签名」拦截的 WAF。
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def outbound_user_agent() -> str:
    return (os.environ.get("RPG_OUTBOUND_UA") or "").strip() or _DEFAULT_UA


def openai_default_headers() -> dict[str, str]:
    """传给 openai SDK 的 `default_headers`,覆盖其内置的 `OpenAI/Python` UA。

    openai SDK 把构造期传入的 default_headers 合并在 `default_headers` 属性最后一位,
    会覆盖内置 User-Agent(已对 openai==2.38 实测验证)。
    """
    return {"User-Agent": outbound_user_agent()}
