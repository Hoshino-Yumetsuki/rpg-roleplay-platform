"""agents.image_gen.dispatch — route image generation to the right provider adapter.

Public function:
    generate_image_bytes(
        *,
        api_id: str,
        model: str,
        prompt: str,
        params: dict,
        api_key: str,
        base_url: str | None = None,
    ) -> list[bytes]

Routing is based on the normalized api_id (via model_aliases.normalize_api_id).
Currently supported providers:
    doubao    →  agents.image_gen.doubao
    dashscope →  agents.image_gen.dashscope

All others raise ImageGenError("unsupported image provider: <api_id>").
"""
from __future__ import annotations

from agents.image_gen.base import ImageGenError


def generate_image_bytes(
    *,
    api_id: str,
    model: str,
    prompt: str,
    params: dict,
    api_key: str,
    base_url: str | None = None,
) -> list[bytes]:
    """Route image generation to the correct provider adapter.

    Args:
        api_id:    Provider id string (normalized or raw; this function normalizes it).
        model:     Model id string from catalog.
        prompt:    Text prompt for image generation.
        params:    Provider-specific optional parameters dict.
        api_key:   API key for the provider.
        base_url:  Optional base URL override (used by doubao for custom ARK endpoints).

    Returns:
        list[bytes] — one element per generated image.

    Raises:
        ImageGenError on provider error, network failure, or unsupported provider.
    """
    from model_aliases import normalize_api_id  # lazy import — avoids circular deps

    normalized = normalize_api_id(api_id)

    if normalized == "doubao":
        from agents.image_gen import doubao
        return doubao.generate(
            prompt, params,
            api_id=normalized, model=model, api_key=api_key, base_url=base_url,
        )

    if normalized == "dashscope":
        from agents.image_gen import dashscope
        return dashscope.generate(
            prompt, params,
            api_id=normalized, model=model, api_key=api_key, base_url=base_url,
        )

    raise ImageGenError(f"unsupported image provider: {normalized!r} (from api_id={api_id!r})")
