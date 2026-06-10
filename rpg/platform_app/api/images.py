"""platform_app.api.images — 生图存储、服务与触发端点。

Phase 1 Agent A 实现：
  - store_image(data, *, user_id, kind, ext) -> str   落盘 + 返回相对 URL
  - ai_images CRUD helpers
  - GET  /api/images/file/{filename}                  静态文件服务
  - POST /api/images/generate                         触发异步生图（入队给 Agent C 的 worker）
"""
from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from ._deps import json_response, require_user
from ..db import connect, init_db

router = APIRouter()

# ── 路径常量 ──────────────────────────────────────────────────────────
# platform_data/ 在项目根（rpg/ 的上一级）——与头像路径 `parent.parent / "platform_data"` 一致。
_IMAGE_ROOT: Path = Path(__file__).resolve().parents[3] / "platform_data" / "ai_images"

# 白名单：允许存储/服务的图片扩展名
_ALLOWED_EXTS: frozenset[str] = frozenset({"png", "jpg", "jpeg", "webp"})


# ══════════════════════════════════════════════════════════════════════
#  存储抽象
# ══════════════════════════════════════════════════════════════════════

def _write_image_bytes(dest: Path, data: bytes) -> None:
    """把字节写入磁盘。
    OSS 替换点：将此函数体改为上传到对象存储即可；调用方 store_image 零改动。
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)


def store_image(data: bytes, *, user_id: int, kind: str, ext: str = "png") -> str:
    """写图片到 platform_data/ai_images/ 并返回相对 URL。

    文件名格式：ai_{user_id}_{random_hex}.{ext}
    返回值：/api/images/file/{filename}

    OSS 替换点在 _write_image_bytes。换成对象存储时：
      1. 将 _write_image_bytes 改为上传调用，返回外部 URL；
      2. store_image 改为直接返回该外部 URL（跳过本地落盘）；
      3. 调用方（image_jobs worker）零改动。
    """
    ext_clean = ext.lstrip(".").lower()
    if ext_clean not in _ALLOWED_EXTS:
        ext_clean = "png"
    filename = f"ai_{int(user_id)}_{secrets.token_hex(12)}.{ext_clean}"
    dest = _IMAGE_ROOT / filename
    _write_image_bytes(dest, data)
    return f"/api/images/file/{filename}"


# ══════════════════════════════════════════════════════════════════════
#  ai_images CRUD helpers
# ══════════════════════════════════════════════════════════════════════

def create_image_record(
    *,
    user_id: int,
    kind: str,
    prompt: str,
    api_id: str | None = None,
    model: str | None = None,
    params: dict | None = None,
) -> int:
    """INSERT 一行 ai_images，返回新行 id。"""
    from psycopg.types.json import Jsonb

    init_db()
    with connect() as db:
        row = db.execute(
            """
            insert into ai_images (user_id, kind, api_id, model, prompt, params, status)
            values (%s, %s, %s, %s, %s, %s, 'pending')
            returning id
            """,
            (
                int(user_id),
                kind,
                api_id or None,
                model or None,
                prompt,
                Jsonb(params or {}),
            ),
        ).fetchone()
    if not row:
        raise RuntimeError("create_image_record: no id returned")
    return int(row["id"])


def update_image_record(
    image_id: int,
    status: str,
    *,
    url: str | None = None,
    error: str | None = None,
) -> None:
    """更新 ai_images 行的 status / url / error。"""
    init_db()
    with connect() as db:
        db.execute(
            """
            update ai_images
               set status = %s,
                   url    = coalesce(%s, url),
                   error  = coalesce(%s, error)
             where id = %s
            """,
            (status, url, error, int(image_id)),
        )


def get_image_record(image_id: int) -> dict[str, Any] | None:
    """按 id 查 ai_images 行，不存在返回 None。"""
    init_db()
    with connect() as db:
        row = db.execute(
            "select * from ai_images where id = %s",
            (int(image_id),),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def list_user_images(
    user_id: int,
    *,
    kind: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """列出某用户的 ai_images，按 created_at desc 排序。"""
    init_db()
    with connect() as db:
        if kind:
            rows = db.execute(
                """
                select * from ai_images
                 where user_id = %s and kind = %s
                 order by created_at desc
                 limit %s
                """,
                (int(user_id), kind, int(limit)),
            ).fetchall()
        else:
            rows = db.execute(
                """
                select * from ai_images
                 where user_id = %s
                 order by created_at desc
                 limit %s
                """,
                (int(user_id), int(limit)),
            ).fetchall()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════════════
#  路由：静态文件服务
# ══════════════════════════════════════════════════════════════════════

@router.get("/api/images/file/{filename}")
async def api_image_file(filename: str) -> FileResponse:
    """服务 platform_data/ai_images/ 下的图片文件。

    安全防护：
      1. 路径穿越：文件名不得含 / \\ .. 或以 . 开头。
      2. 扩展名白名单：只允许 png / jpg / jpeg / webp。
      3. 实际路径必须在 _IMAGE_ROOT 下（resolve() 比较）。
    """
    # 1. 路径穿越检查（严于 avatar 路由，直接拒绝任何非纯文件名字符）
    if (
        "/" in filename
        or "\\" in filename
        or ".." in filename
        or filename.startswith(".")
    ):
        raise HTTPException(status_code=400, detail="非法文件名")

    # 2. 扩展名白名单
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail="不支持的文件类型")

    # 3. 路径限定（防御 symlink 逃逸）
    target = (_IMAGE_ROOT / filename).resolve()
    if not str(target).startswith(str(_IMAGE_ROOT.resolve())):
        raise HTTPException(status_code=400, detail="非法路径")

    if not target.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(str(target))


# ══════════════════════════════════════════════════════════════════════
#  路由：触发生图
# ══════════════════════════════════════════════════════════════════════

@router.post("/api/images/generate")
async def api_generate_image(request: Request):
    """UI 按钮入口：接收生图请求，入队异步 job，立即返回 {image_id, status}。

    body: {prompt, kind, api_id?, model?, ref?}

    worker 由 Agent C 的 platform_app.image_jobs 实现；此处仅按约定签名调用：
        enqueue_image_generation(user_id, prompt, kind, api_id=, model=, origin=, extra=) -> dict
    """
    user = require_user(request)
    user_id: int = int(user["id"])

    try:
        body = await request.json()
    except Exception:
        body = {}

    prompt: str = str(body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt 不能为空")

    kind: str = str(body.get("kind") or "chat").strip()
    api_id: str | None = body.get("api_id") or None
    model: str | None = body.get("model") or None
    ref: str | None = body.get("ref") or None

    # 调用 Agent C 提供的 enqueue_image_generation。
    # 该模块由 Agent C 建（platform_app/image_jobs.py），整合前 import 可能失败——
    # 正常：此文件交付时 Agent C 尚未完成，整合期再对接。
    from platform_app.image_jobs import enqueue_image_generation  # type: ignore[import]

    result: dict = enqueue_image_generation(
        user_id,
        prompt,
        kind,
        api_id=api_id,
        model=model,
        origin="api_direct",
        extra={"ref": ref} if ref else None,
    )
    return json_response({"ok": True, **result})
