"""console_assistant.py — 侧栏控制台助手路由 (/api/console_assistant/*)。"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse

from routes._deps_fastapi import get_current_user
from schemas._common import COMMON_ERROR_RESPONSES, GenericOkResponse, OkResponse
from schemas.console_assistant import (
    ConsoleAssistantChatRequest,
    ConsoleAssistantConfirmRequest,
    ConsoleAssistantContinueRequest,
    ConsoleAssistantDeleteConversationRequest,
)

router = APIRouter()


@router.get("/api/console_assistant/ping")
async def api_console_assistant_ping() -> JSONResponse:
    """task 48: 给前端探测后端是否就绪,200 = 真后端可用 (前端切走 mock)。"""
    return JSONResponse({"ok": True, "service": "console_assistant", "version": "1"})


@router.get("/api/console_assistant/conversations")
async def api_console_assistant_conversations(
    api_user: dict[str, Any] | None = Depends(get_current_user),
) -> JSONResponse:
    """task 111: 列当前用户所有对话。"""
    user_id = int((api_user or {}).get("id") or 0)
    if not user_id:
        return JSONResponse({"items": []})
    from console_assistant import list_conversations
    items = list_conversations(user_id)
    return JSONResponse({"items": items})


@router.post("/api/console_assistant/new_conversation", response_model=GenericOkResponse, responses=COMMON_ERROR_RESPONSES)
async def api_console_assistant_new_conversation(
    api_user: dict[str, Any] | None = Depends(get_current_user),
) -> JSONResponse:
    """task 111: 开新对话, 返新 conversation_id。"""
    user_id = int((api_user or {}).get("id") or 0)
    if not user_id:
        return JSONResponse({"ok": False, "error": "需要登录"}, status_code=401)
    from console_assistant import new_conversation
    new_id = new_conversation(user_id)
    return JSONResponse({"ok": True, "conversation_id": new_id})


@router.post("/api/console_assistant/delete_conversation", response_model=OkResponse, responses=COMMON_ERROR_RESPONSES)
async def api_console_assistant_delete_conversation(
    body: ConsoleAssistantDeleteConversationRequest,
    api_user: dict[str, Any] | None = Depends(get_current_user),
) -> JSONResponse:
    """task 111: 删除某对话。"""
    user_id = int((api_user or {}).get("id") or 0)
    if not user_id:
        return JSONResponse({"ok": False, "error": "需要登录"}, status_code=401)
    body_dict = body.model_dump(exclude_none=True)
    cid = str(body_dict.get("conversation_id") or "").strip()
    if not cid:
        return JSONResponse({"ok": False, "error": "conversation_id 必填"}, status_code=400)
    from console_assistant import delete_conversation
    ok = delete_conversation(user_id, cid)
    return JSONResponse({"ok": ok})


@router.post("/api/console_assistant/chat")
async def api_console_assistant_chat(
    body: ConsoleAssistantChatRequest,
    api_user: dict[str, Any] | None = Depends(get_current_user),
) -> StreamingResponse:
    """task 48: 侧栏助手主聊天 SSE endpoint。

    body: { message: str, conversation_id?: str, page_context?: dict }
    SSE: meta / token / tool_call / tool_result / confirmation_required / error / done
    """
    from app import _ensure_loaded, _resolve_console_assistant_backend
    body_dict = body.model_dump(exclude_none=True)
    message = str(body_dict.get("message") or "").strip()
    conversation_id = body_dict.get("conversation_id")
    if isinstance(conversation_id, str):
        conversation_id = conversation_id.strip() or None
    else:
        conversation_id = None
    page_context = body_dict.get("page_context") if isinstance(body_dict.get("page_context"), dict) else None

    if not message:
        return StreamingResponse(
            iter([f"event: error\ndata: {json.dumps({'message':'空消息'}, ensure_ascii=False)}\n\n"]),
            media_type="text/event-stream",
        )

    user_id = int((api_user or {}).get("id") or 0)
    if not user_id:
        return StreamingResponse(
            iter([f"event: error\ndata: {json.dumps({'message':'需要登录'}, ensure_ascii=False)}\n\n"]),
            media_type="text/event-stream",
        )

    # 注意:这里 state_provider 用 _ensure_loaded — 只有 save scope 工具用得到。
    def _sp(env):
        try:
            if env.save_id is None:
                return None
            return _ensure_loaded(api_user)
        except Exception:
            return None

    # 解析 backend
    try:
        backend = _resolve_console_assistant_backend(api_user)
    except Exception as exc:
        return StreamingResponse(
            iter([f"event: error\ndata: {json.dumps({'message':f'backend 初始化失败: {exc}'}, ensure_ascii=False)}\n\n"]),
            media_type="text/event-stream",
        )

    from console_assistant import stream_chat as _stream_chat

    def _gen():
        yield from _stream_chat(
            user_id=user_id,
            message=message,
            conversation_id=conversation_id,
            page_context=page_context,
            backend=backend,
            state_provider=_sp,
        )

    return StreamingResponse(_gen(), media_type="text/event-stream")


@router.post("/api/console_assistant/confirm")
async def api_console_assistant_confirm(
    body: ConsoleAssistantConfirmRequest,
    api_user: dict[str, Any] | None = Depends(get_current_user),
) -> StreamingResponse:
    """task 58: 对一个 pending destructive 工具调用做决策, 返 SSE 流。

    body: { conversation_id: str, call_id: str, decision: 'approve'|'reject',
            page_context?: dict }
    SSE: 与 /chat endpoint 同款 (meta / tool_call / tool_result / token /
         confirmation_required / navigation_required / error / done)

    旧 JSON 协议已弃用 — 修复:用户点确认后 LLM 必须基于工具结果续写,
    否则对话直接断在工具结果。
    """
    from app import _ensure_loaded, _resolve_console_assistant_backend
    body_dict = body.model_dump(exclude_none=True)
    conversation_id = str(body_dict.get("conversation_id") or "").strip()
    call_id = str(body_dict.get("call_id") or "").strip()
    decision = str(body_dict.get("decision") or "").strip().lower()
    page_context = body_dict.get("page_context") if isinstance(body_dict.get("page_context"), dict) else None
    if not conversation_id or not call_id or decision not in {"approve", "reject"}:
        return StreamingResponse(
            iter([f"event: error\ndata: {json.dumps({'message':'conversation_id / call_id / decision 必填; decision ∈ {approve,reject}'}, ensure_ascii=False)}\n\n",
                  "event: done\ndata: {}\n\n"]),
            media_type="text/event-stream",
            status_code=400,
        )

    user_id = int((api_user or {}).get("id") or 0)
    if not user_id:
        return StreamingResponse(
            iter([f"event: error\ndata: {json.dumps({'message':'需要登录'}, ensure_ascii=False)}\n\n",
                  "event: done\ndata: {}\n\n"]),
            media_type="text/event-stream",
            status_code=401,
        )

    def _sp(env):
        try:
            if env.save_id is None:
                return None
            return _ensure_loaded(api_user)
        except Exception:
            return None

    try:
        backend = _resolve_console_assistant_backend(api_user)
    except Exception as exc:
        return StreamingResponse(
            iter([f"event: error\ndata: {json.dumps({'message':f'backend 初始化失败: {exc}'}, ensure_ascii=False)}\n\n",
                  "event: done\ndata: {}\n\n"]),
            media_type="text/event-stream",
        )

    from console_assistant import apply_confirmation_stream as _apply_stream

    def _gen():
        yield from _apply_stream(
            user_id=user_id,
            conversation_id=conversation_id,
            call_id=call_id,
            decision=decision,
            page_context=page_context,
            backend=backend,
            state_provider=_sp,
        )

    return StreamingResponse(_gen(), media_type="text/event-stream")


# ── MD 编辑器:AI 续写/改写正文(流式纯文本,无工具)──────────────────
# 像 Cursor 写代码:LLM 只产正文文本片段,前端决定插哪。本端点只负责流式产文本。

_CONTINUE_BEFORE_CAP = 4000   # before 截到末尾这么多字
_CONTINUE_AFTER_CAP = 1500    # after 截到开头这么多字
_CONTINUE_SELECTION_CAP = 4000

_CONTINUE_SYSTEM_PROMPT = (
    "你是中文小说正文写作助手。**只输出要插入/替换进正文的纯文本片段**,"
    "不要任何解释、不要 markdown 标记、不要把前后文重复出来、不要加引号外壳。\n"
    "\n"
    "【最高优先级】若给了『指令』,严格服从它,它凌驾一切默认做法"
    "(包括默认的「顺势往下续写」)——指令要求什么就写什么、怎么写。"
    "指令未覆盖到的方面,仍然遵守下面的【文风一致】。\n"
    "\n"
    "【文风一致】你的输出必须无缝融入上下文,沿用上下文已有的:\n"
    "  · 人称与时态(第一/第三人称、过去/现在时);\n"
    "  · 叙述视角与叙述距离(全知/限知、贴近内心还是冷静旁观);\n"
    "  · 语气与语域(雅俗、正式/口语、文白程度);\n"
    "  · 用词习惯与句子节奏(长短句搭配、标点密度、段落呼吸);\n"
    "  · 对话风格与标点(引号样式、对白与动作的穿插方式);\n"
    "  · 内容尺度(露骨或含蓄的程度与上下文保持一致,除非『指令』另有要求"
    "——本平台允许成人内容)。\n"
    "不要引入上下文之外的新设定、新人物或新地名;"
    "把 before/after/selection 仅当作可能被截断的上下文。\n"
    "\n"
    "- continue 模式:在『前文』与『后文』之间续写衔接的一段;承接前文、并与后文自然衔接;"
    "若给了『指令』按【最高优先级】执行,否则顺势往下续写,全程守【文风一致】。\n"
    "- rewrite 模式:把『选中原文』按『指令』改写成新版本,只输出新版本正文;"
    "改写后仍要与前后文【文风一致】。"
)


def _build_continue_user_prompt(
    *, before: str, after: str, selection: str, instruction: str, mode: str,
) -> str:
    """把 before/after/selection/instruction 组织进 user_prompt,清楚标注每段。"""
    parts: list[str] = []
    parts.append(f"【模式】{'改写(rewrite)' if mode == 'rewrite' else '续写(continue)'}")
    if before:
        parts.append(f"【前文】(正文光标之前,可能已截断)\n{before}")
    if mode == "rewrite" and selection:
        parts.append(f"【选中原文】(请把这段改写成新版本)\n{selection}")
    if after:
        parts.append(f"【后文】(正文光标之后,可能已截断)\n{after}")
    if instruction:
        parts.append(f"【指令(最高优先级,凌驾默认做法)】\n{instruction}")
    if mode == "rewrite":
        parts.append("请只输出『选中原文』改写后的新版本正文,不要解释、不要重复前后文。")
    else:
        parts.append("请在『前文』与『后文』之间续写衔接的一段正文,只输出新增的这段文字。")
    return "\n\n".join(parts)


@router.post("/api/console_assistant/continue")
async def api_console_assistant_continue(
    body: ConsoleAssistantContinueRequest,
    api_user: dict[str, Any] | None = Depends(get_current_user),
) -> StreamingResponse:
    """MD 编辑器「AI 续写/改写正文」流式端点(纯文本,无工具)。

    body: { before, after, instruction?, selection?, mode?='continue'|'rewrite',
            script_id?, api_id?, model? }
    SSE: token{text} / done{} / error{message}
    """
    body_dict = body.model_dump(exclude_none=True)
    before = str(body_dict.get("before") or "")
    after = str(body_dict.get("after") or "")
    instruction = str(body_dict.get("instruction") or "").strip()
    selection = str(body_dict.get("selection") or "")
    mode = str(body_dict.get("mode") or "continue").strip().lower()
    if mode not in ("continue", "rewrite"):
        mode = "continue"
    script_id = body_dict.get("script_id")
    api_id_in = (str(body_dict.get("api_id")).strip() or None) if body_dict.get("api_id") else None
    model_in = (str(body_dict.get("model")).strip() or None) if body_dict.get("model") else None

    def _err(message: str):
        return StreamingResponse(
            iter([
                f"event: error\ndata: {json.dumps({'message': message}, ensure_ascii=False)}\n\n",
                "event: done\ndata: {}\n\n",
            ]),
            media_type="text/event-stream",
        )

    user_id = int((api_user or {}).get("id") or 0)
    if not user_id:
        return _err("需要登录")

    # 截断:before 取末尾,after 取开头(光标处上下文最相关)
    before = before[-_CONTINUE_BEFORE_CAP:]
    after = after[:_CONTINUE_AFTER_CAP]
    selection = selection[:_CONTINUE_SELECTION_CAP]

    # 严格 owner 鉴权(给了 script_id 才校验):既防滥用又给用量归属
    if script_id is not None:
        try:
            sid = int(script_id)
        except (TypeError, ValueError):
            return _err("script_id 无效")
        try:
            from platform_app.db import connect, init_db
            from platform_app.perms import script_owned
            init_db()
            with connect() as db:
                owned = script_owned(db, sid, user_id)
        except Exception:
            return _err("剧本归属校验失败,请稍后重试")
        if not owned:
            return _err("无权操作该剧本:仅原作者可用 AI 续写/改写。")
        script_id = sid
    else:
        script_id = None

    # 模型解析:body 给了 api_id+model 就用;否则回退到用户编辑器偏好 / 默认 / gm
    try:
        from agents._harness import resolve_api_and_model
        api_id, model_real = resolve_api_and_model(
            user_id,
            api_pref_key="editor.api_id",
            model_pref_key="editor.model_real_name",
            api_id_override=api_id_in,
            model_override=model_in,
        )
    except Exception:
        return _err(
            "未找到可用的模型。请到「设置 → API 设置」配置并测试一个模型后重试。"
        )
    if not api_id or not model_real:
        return _err(
            "未找到可用的模型。请到「设置 → API 设置」配置并测试一个模型后重试。"
        )

    # 构造 backend(复用 GM 的 backend 抽象);纯文本流式只用 backend.stream(无工具)
    try:
        from agents.gm import GameMaster
        backend = GameMaster(
            api_id=str(api_id), model=str(model_real), user_id=user_id,
        )._backend
    except Exception as exc:
        from agents.provider_errors import classify_provider_error
        known = classify_provider_error(exc)
        return _err(known[1] if known else "模型后端初始化失败,请检查 API 设置后重试。")

    system_prompt = _CONTINUE_SYSTEM_PROMPT
    user_prompt = _build_continue_user_prompt(
        before=before, after=after, selection=selection,
        instruction=instruction, mode=mode,
    )

    def _gen():
        try:
            for chunk in backend.stream(
                system_prompt,
                [{"role": "user", "content": user_prompt}],
                max_tokens=2000,
            ):
                if chunk:
                    yield f"event: token\ndata: {json.dumps({'text': chunk}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            import logging
            logging.getLogger("console_assistant").exception(
                "continue stream failed: %s", type(exc).__name__,
            )
            from agents.provider_errors import classify_provider_error
            known = classify_provider_error(exc)
            msg = known[1] if known else "AI 续写出错,请稍后重试。"
            yield f"event: error\ndata: {json.dumps({'message': msg}, ensure_ascii=False)}\n\n"
        else:
            # 用量归属(失败静默,不影响流):scenario=assistant,归到 script_id
            try:
                usage = getattr(backend, "last_usage", None) or {}
                if usage and (usage.get("input_tokens") or usage.get("output_tokens")):
                    from platform_app.usage import record_usage
                    record_usage(
                        user_id=user_id,
                        save_id=None,
                        context_run_id=None,
                        api_id=str(getattr(backend, "api_id", None) or api_id),
                        model_real_name=str(getattr(backend, "model_name", None) or model_real),
                        usage=usage,
                        metadata={"kind": "editor_continue", "mode": mode,
                                  "script_id": script_id},
                        scenario="assistant",
                    )
            except Exception:
                pass
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(_gen(), media_type="text/event-stream")
