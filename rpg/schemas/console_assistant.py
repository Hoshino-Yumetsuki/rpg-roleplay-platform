"""schemas.console_assistant — 侧栏控制台助手路由请求模型。"""
from __future__ import annotations

from typing import Any

from schemas._common import _BaseRequest


class ConsoleAssistantDeleteConversationRequest(_BaseRequest):
    conversation_id: str | None = ""


class ConsoleAssistantChatRequest(_BaseRequest):
    message: str | None = ""
    conversation_id: str | None = None
    page_context: dict[str, Any] | None = None


class ConsoleAssistantConfirmRequest(_BaseRequest):
    conversation_id: str | None = ""
    call_id: str | None = ""
    decision: str | None = ""
    page_context: dict[str, Any] | None = None


class ConsoleAssistantContinueRequest(_BaseRequest):
    """MD 编辑器「AI 续写/改写正文」流式端点请求体。

    本端点只负责流式产出要插入/替换进正文的纯文本(像 Cursor 写代码),
    不带任何工具,前端自行决定插入位置。
    """

    before: str | None = ""          # 光标前正文(可能很长,后端截断到末尾)
    after: str | None = ""           # 光标后正文(后端截断到开头)
    instruction: str | None = ""     # 用户指令,可空
    selection: str | None = ""       # 改写模式下被选中要替换的原文
    mode: str | None = "continue"    # 'continue' | 'rewrite'
    script_id: int | None = None     # 用于严格 owner 鉴权 + 用量归属
    api_id: str | None = None        # 前端选模型(优先)
    model: str | None = None         # 前端选模型 real_name(优先)
