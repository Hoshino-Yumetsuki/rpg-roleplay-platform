"""platform_app.image_jobs — Phase 1-C: 生图异步 job 编排。

职责：
  enqueue_image_generation(...)  — 建 ai_images 记录 + 入 chat_postproc_tasks 队列
  handle_image_gen(payload)      — worker handler（由 run_postproc_worker 注册）
  _notify_image_ready(...)       — SSE 回推 image_ready{image_id, url, kind}

worker 集成：在 scripts/run_postproc_worker.py 的 TASK_HANDLERS 里加：
    from platform_app.image_jobs import handle_image_gen
    TASK_HANDLERS["image_gen"] = handle_image_gen
并在 platform_app/postproc_queue.py 的 TASK_KINDS 里追加 "image_gen"。
（整合时由主代理完成，此文件独立可编译）。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

log = logging.getLogger(__name__)

# ── 入队 ────────────────────────────────────────────────────────────────

_INSERT_SQL = """
INSERT INTO chat_postproc_tasks
    (user_id, save_id, commit_id, task_kind, payload, status, scheduled_at)
VALUES
    (%(user_id)s, %(save_id)s, NULL, 'image_gen',
     %(payload)s::jsonb, 'pending', now())
"""

# image 任务没有 game save 归属；用固定占位符满足 NOT NULL 约束。
_IMAGE_SAVE_PLACEHOLDER = "image_job"


def enqueue_image_generation(
    user_id: int,
    prompt: str,
    kind: str,
    *,
    api_id: str | None = None,
    model: str | None = None,
    origin: str = "api_direct",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """建 ai_images 记录(status='pending')，入 postproc_queue，返回 {image_id, status}.

    api_id / model 未传时用用户偏好回退（image_gen 能力优先，可后续细化）。
    origin 透传到 payload 以便 worker 计费/审计区分来源。
    """
    from platform_app.api.images import create_image_record
    from platform_app.db import connect

    # model/api_id 解析：未传则复用偏好回退
    _api_id = api_id
    _model = model
    if not _api_id or not _model:
        try:
            from core.llm_backend import resolve_preferred_api, resolve_preferred_model
            if not _api_id:
                _api_id = resolve_preferred_api(user_id, pref_key="image_gen.api_id") or api_id
            if not _model:
                _model = resolve_preferred_model(user_id, pref_key="image_gen.model_real_name") or model
        except Exception as _pref_exc:
            log.debug("[image_jobs] pref resolve skipped: %s", _pref_exc)

    # 1. 建 ai_images 行
    image_id = create_image_record(
        user_id=int(user_id),
        kind=kind,
        prompt=prompt,
        api_id=_api_id,
        model=_model,
        params=extra or {},
    )

    # 2. 入 chat_postproc_tasks
    payload: dict[str, Any] = {
        "image_id": image_id,
        "user_id": int(user_id),
        "prompt": prompt,
        "kind": kind,
        "api_id": _api_id,
        "model": _model,
        "origin": origin,
        "extra": extra or {},
    }

    with connect() as db:
        db.execute(_INSERT_SQL, {
            "user_id": int(user_id),
            "save_id": _IMAGE_SAVE_PLACEHOLDER,
            "payload": json.dumps(payload, ensure_ascii=False),
        })
        try:
            db.execute("SELECT pg_notify('chat_postproc_new', %s)", (str(user_id),))
        except Exception as _notify_exc:
            log.warning("[image_jobs] NOTIFY failed (worker will poll): %s", _notify_exc)

    log.info("[image_jobs] enqueued image_id=%s user=%s kind=%s origin=%s",
             image_id, user_id, kind, origin)
    return {"image_id": image_id, "status": "pending"}


# ── Worker handler ───────────────────────────────────────────────────────

async def handle_image_gen(payload: dict[str, Any]) -> None:
    """postproc_worker 调用的 handler，在独立进程内跑。

    步骤：
    1. update_image_record(id, 'generating')
    2. resolve_api_key(user_id, api_id) — 缺 key 标 failed
    3. generate_image_bytes(prompt, params, api_id, model, api_key, base_url) — Agent B
    4. store_image(bytes) — Agent A
    5. update_image_record(id, 'done', url=...)
    6. SSE emit image_ready
    """
    from platform_app.api.images import update_image_record, store_image

    image_id: int = int(payload.get("image_id") or 0)
    user_id: int = int(payload.get("user_id") or 0)
    prompt: str = str(payload.get("prompt") or "")
    kind: str = str(payload.get("kind") or "chat")
    api_id: str | None = payload.get("api_id") or None
    model: str | None = payload.get("model") or None
    extra: dict[str, Any] = payload.get("extra") or {}

    if not image_id or not user_id:
        log.warning("[image_jobs] handle_image_gen: missing image_id or user_id in payload")
        return

    # 1. mark generating
    try:
        update_image_record(image_id, "generating")
    except Exception as exc:
        log.warning("[image_jobs] update generating failed image_id=%s: %s", image_id, exc)

    # 2. resolve key
    api_key: str = ""
    base_url: str = ""
    if api_id:
        try:
            from platform_app.user_credentials import resolve_api_key
            cred = resolve_api_key(user_id, api_id)
            api_key = cred.get("key") or ""
            base_url = cred.get("base_url_override") or ""
        except Exception as exc:
            log.warning("[image_jobs] resolve_api_key failed image_id=%s: %s", image_id, exc)

    if not api_key:
        _fail(image_id, "credentials_required")
        return

    # 3. generate
    try:
        from agents.image_gen.dispatch import generate_image_bytes  # type: ignore[import]
        size: str | None = extra.get("size") or None
        params: dict[str, Any] = {k: v for k, v in extra.items() if k != "ref"}
        if size:
            params["size"] = size

        raw_results = await asyncio.to_thread(
            generate_image_bytes,
            prompt,
            params,
            api_id=api_id,
            model=model,
            api_key=api_key,
            base_url=base_url,
        )
    except Exception as exc:
        log.exception("[image_jobs] generate_image_bytes failed image_id=%s", image_id)
        _fail(image_id, f"generation_error: {exc}")
        return

    if not raw_results:
        _fail(image_id, "generation_error: empty result")
        return

    # 4. store
    try:
        url = store_image(raw_results[0], user_id=user_id, kind=kind)
    except Exception as exc:
        log.exception("[image_jobs] store_image failed image_id=%s", image_id)
        _fail(image_id, f"store_error: {exc}")
        return

    # 5. update done
    try:
        update_image_record(image_id, "done", url=url)
    except Exception as exc:
        log.warning("[image_jobs] update done failed image_id=%s: %s", image_id, exc)

    # 6. SSE push
    _notify_image_ready(user_id=user_id, image_id=image_id, url=url, kind=kind)
    log.info("[image_jobs] done image_id=%s user=%s url=%s", image_id, user_id, url)


def _fail(image_id: int, reason: str) -> None:
    """标记 ai_images 为 failed，记录 error。"""
    try:
        from platform_app.api.images import update_image_record
        update_image_record(image_id, "failed", error=reason)
    except Exception as exc:
        log.warning("[image_jobs] _fail update_record failed image_id=%s: %s", image_id, exc)
    log.warning("[image_jobs] image_id=%s failed reason=%s", image_id, reason)


def _notify_image_ready(
    *,
    user_id: int,
    image_id: int,
    url: str,
    kind: str,
) -> None:
    """经 SSE 事件总线发 image_ready{image_id, url, kind}。

    worker 是独立进程，没有 FastAPI event-loop 的 SSE 订阅者 —— _local_emit 会找不到
    任何队列，但 Redis 广播路径会把事件跨进程推给主 FastAPI worker 的订阅者。
    无 Redis 时事件静默丢失（前端可靠性退化到轮询，不影响生图正确性）。
    """
    try:
        from state_event_bus import emit as _emit
        _emit(user_id, "image", "ready", {
            "image_id": image_id,
            "url": url,
            "kind": kind,
        })
    except Exception as exc:
        log.debug("[image_jobs] SSE emit skipped: %s", exc)
