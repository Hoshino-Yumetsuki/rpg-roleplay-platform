"""routes._deps_fastapi — FastAPI Depends() dependency functions for routes/."""
from __future__ import annotations

from typing import Any

from fastapi import Request


def get_current_user(request: Request) -> dict[str, Any] | None:
    """返回当前 api_user (本地模式可能返回 None)。"""
    from app import _require_api_user
    return _require_api_user(request)


def get_current_admin(request: Request) -> dict[str, Any] | None:
    """返回当前 api_user，要求 admin 权限。"""
    from app import _require_api_user
    return _require_api_user(request, admin=True)


def get_current_admin_strict(request: Request) -> dict[str, Any] | None:
    """SEC(C-1): 严格 admin —— self-hosted/local 模式也强制 admin,不走免登录短路。

    用于 MCP 注册/启动等「= 以服务进程身份执行代码」的高危端点,防本地端口被探测出 RCE。
    """
    from app import _require_api_user
    return _require_api_user(request, admin=True, strict_admin=True)


def get_payload_fn(request: Request):
    """返回 _payload 函数 (闭包了当前 user)。"""
    from app import _payload
    return _payload
