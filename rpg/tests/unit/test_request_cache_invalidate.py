"""core.request_cache.invalidate_user_prefs_cache 单测(issue #22 第四层:死代码补实)。

routes/models.py 写完 prefs 后调 invalidate_user_prefs_cache,使同一请求内后续
resolve_preferred_* 读到刚写的新值。此前该函数不存在,import 被 try/except 静默吞掉。
"""
from __future__ import annotations

from core import request_cache


def test_invalidate_clears_request_scoped_entry() -> None:
    request_cache.reset_request_caches()
    cache = request_cache._user_prefs_cache.get()
    assert cache is not None
    cache[42] = {"gm.api_id": "deepseek"}
    request_cache.invalidate_user_prefs_cache(42)
    assert 42 not in request_cache._user_prefs_cache.get(), "写后失效:本请求该 user 缓存应被清"


def test_invalidate_is_noop_outside_request_context() -> None:
    # 非请求上下文(cache=None):不抛、无副作用
    request_cache._user_prefs_cache.set(None)
    try:
        request_cache.invalidate_user_prefs_cache(7)  # 不应抛
    finally:
        request_cache.reset_request_caches()


def test_invalidate_exported() -> None:
    assert "invalidate_user_prefs_cache" in request_cache.__all__


if __name__ == "__main__":
    test_invalidate_clears_request_scoped_entry()
    test_invalidate_is_noop_outside_request_context()
    test_invalidate_exported()
    print("ok")
