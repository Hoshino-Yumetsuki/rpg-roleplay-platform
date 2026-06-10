"""core.llm_backend — LLM backend resolver helpers (共享给 agents/)。

抽出来的目的: command_agent / extractor / 其他 agent 不再各自实现。

用法示例:
    from core.llm_backend import (
        resolve_preferred_model as _resolve_preferred_model,
        resolve_preferred_api  as _resolve_preferred_api,
        detect_default_api     as _detect_default_api,
    )
"""
from __future__ import annotations

from typing import Optional


def detect_default_api() -> str:
    """启动时检测可用 backend: 优先 vertex_ai (SA 文件), 然后 anthropic (env key)."""
    import os as _os
    from pathlib import Path as _Path

    sa_path = _Path(__file__).parent.parent / "vertex_sa.json"
    if sa_path.exists():
        return "vertex_ai"
    if _os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "vertex_ai"  # 默认仍兜底 vertex,失败时调用方走 fallback


def first_user_model(user_id: Optional[int], api_id: str | None = None) -> tuple[str, str] | None:
    """Return the first model backed by this user's own credential.

    Production must not fall back to the global selected model if the user has
    not configured that provider. This helper keeps the default path BYOK-only.
    """
    if not user_id:
        return None
    try:
        from model_registry import load_catalog_for_user, normalize_api_id
        from platform_app.db import connect, init_db

        target_api = normalize_api_id(api_id) if api_id else ""
        init_db()
        with connect() as db:
            rows = db.execute(
                """
                select api_id
                from user_api_credentials
                where user_id = %s and enabled = true and length(encrypted_key) > 0
                """,
                (int(user_id),),
            ).fetchall()
        credential_api_ids = {normalize_api_id(row["api_id"]) for row in rows}
        # 每用户视图:含该用户同步到的模型 + 自建中转站,BYOK 默认才能命中
        catalog = load_catalog_for_user(int(user_id))

        # 用户的 GM 模型偏好 = 他们实际在用、已验证可用的模型。优先返回它(在有凭证的
        # provider 下)。否则盲取"第一个 enabled" 会撞上 catalog 里排最前的过期/已下线模型
        # —— 例如平台 vertex provider 的首个模型 gemini-1.5-pro-002 早已 404 NOT_FOUND,
        # 导致子代理(身份生成 / phase compact 等)对没设专用偏好的用户一律失败。
        gm_pref = None
        try:
            with connect() as _dbp:
                _pr = _dbp.execute(
                    "select preferences->>'gm.model_real_name' as m from user_preferences where user_id = %s",
                    (int(user_id),),
                ).fetchone()
            gm_pref = (_pr or {}).get("m") if _pr else None
        except Exception:
            gm_pref = None
        if gm_pref:
            for api in catalog.get("apis", []):
                aid = normalize_api_id(api.get("id") or api.get("api_id"))
                if target_api and aid != target_api:
                    continue
                if aid not in credential_api_ids:
                    continue
                for model in api.get("models", []) or []:
                    if model.get("enabled") is False:
                        continue
                    rn = model.get("real_name") or model.get("id")
                    if rn and str(rn) == str(gm_pref):
                        return aid, str(rn)

        # 回退:有凭证 provider 的第一个 enabled 模型(原逻辑)
        for api in catalog.get("apis", []):
            aid = normalize_api_id(api.get("id") or api.get("api_id"))
            if target_api and aid != target_api:
                continue
            if aid not in credential_api_ids:
                continue
            for model in api.get("models", []) or []:
                if model.get("enabled") is False:
                    continue
                real_name = model.get("real_name") or model.get("id")
                if real_name:
                    return aid, str(real_name)
        # 兜底:用户有凭证但 provider 既不在全局 catalog、也没同步模型(自定义中转站,
        # 如 火山口/gg)→ 上面 catalog 循环匹配不到 → 之前返回 None,导致所有 BYOK 守卫
        # 无从回退、子代理落 vertex 失败。这里用"第一个启用凭证 + 用户 gm 模型偏好"兜底:
        # 玩家既然在用这个自定义 provider 玩,gm.model_real_name 偏好就是可用的模型名。
        with connect() as db2:
            cred = db2.execute(
                "select api_id from user_api_credentials where user_id=%s and enabled=true "
                "and length(encrypted_key)>0 order by updated_at desc",
                (int(user_id),),
            ).fetchall()
            pref = db2.execute(
                "select preferences->>'gm.model_real_name' as m from user_preferences where user_id=%s",
                (int(user_id),),
            ).fetchone()
        pref_model = (pref or {}).get("m") if pref else None
        for c in cred:
            aid = normalize_api_id(c["api_id"])
            if target_api and aid != target_api:
                continue
            if pref_model:
                return aid, str(pref_model)
    except Exception:
        return None
    return None


def _model_in_catalog(user_id: int, model_real_name: str) -> bool:
    """用户视图 catalog 里是否存在该 model_real_name。
    替代已删除的 KNOWN_OFFLINE_MODELS 黑名单:用"是否在真实 catalog 里"校验偏好有效性。
    任何异常视为"不确定,允许通过"(返回 True),避免过度拦截。
    """
    try:
        from model_registry import load_catalog_for_user
        catalog = load_catalog_for_user(int(user_id))
        for api in catalog.get("apis", []):
            for m in api.get("models", []) or []:
                rn = m.get("real_name") or m.get("id")
                if rn and str(rn) == str(model_real_name):
                    return True
        return False
    except Exception:
        return True  # 查询失败 → 保守放行


def resolve_preferred_model(
    user_id: Optional[int],
    pref_key: str = "set_parser.model_real_name",
) -> Optional[str]:
    """从用户偏好推断该用户应该用的 model。

    Args:
        user_id:  用户 ID，None 时直接返回 None。
        pref_key: user_preferences.preferences 字典里的键名，
                  不同 agent 使用不同命名空间，如:
                  - command_agent: "set_parser.model_real_name"
                  - extractor:     "extractor.model_real_name"

    内部使用 request-scoped cache（core.request_cache），一个请求内
    相同 user_id 只查一次 DB；非请求上下文每次直接查。

    catalog 校验:取到偏好的 model_real_name 后，用 load_catalog_for_user 验证该模型
    是否存在于用户视图 catalog 里；不存在则视为无效偏好（下线/迁移），回退到
    first_user_model(user_id)。替代已删除的 KNOWN_OFFLINE_MODELS 黑名单职责。
    """
    if not user_id:
        return None
    try:
        from core.request_cache import get_user_prefs_cached

        prefs = get_user_prefs_cached(int(user_id))
        model_name = prefs.get(pref_key) or None
        if not model_name:
            return None
        # catalog 存在性校验:偏好的模型不在用户 catalog 里 → 回退
        if not _model_in_catalog(int(user_id), model_name):
            result = first_user_model(int(user_id))
            return result[1] if result else None
        return model_name
    except Exception:
        return None


def resolve_preferred_api(
    user_id: Optional[int],
    pref_key: str = "set_parser.api_id",
) -> Optional[str]:
    """从用户偏好推断该用户应该用的 API provider。

    Args:
        user_id:  用户 ID，None 时直接返回 None。
        pref_key: user_preferences.preferences 字典里的键名，
                  不同 agent 使用不同命名空间，如:
                  - command_agent: "set_parser.api_id"
                  - extractor:     "extractor.api_id"

    内部使用 request-scoped cache，同一请求内 user_id 相同时复用
    preferences dict，不重复 SELECT。

    catalog 校验:若对应 model_real_name 偏好不在 catalog 里（已由
    resolve_preferred_model 判为无效），api_id 偏好也应一并回退。
    model_key 由调用方命名空间推断（将 pref_key 的 api_id 替换为 model_real_name）。
    """
    if not user_id:
        return None
    try:
        from core.request_cache import get_user_prefs_cached

        prefs = get_user_prefs_cached(int(user_id))
        api_id = prefs.get(pref_key) or None
        if not api_id:
            return None
        # 同步校验对应 model 偏好是否有效（model key = 同命名空间下的 model_real_name）
        model_key = pref_key.replace("api_id", "model_real_name")
        model_name = prefs.get(model_key) or None
        if model_name and not _model_in_catalog(int(user_id), model_name):
            result = first_user_model(int(user_id))
            return result[0] if result else None
        return api_id
    except Exception:
        return None


__all__ = [
    "detect_default_api",
    "first_user_model",
    "resolve_preferred_model",
    "resolve_preferred_api",
]
