"""agents.image_gen.base — shared adapter interface + exception.

Each provider adapter must expose:

    def generate(
        prompt: str,
        params: dict,
        *,
        api_id: str,
        model: str,
        api_key: str,
        base_url: str | None = None,
    ) -> list[bytes]

Returns a list of raw image bytes (one element per generated image).
If the provider returns URLs, the adapter downloads them and returns bytes.
If the provider returns base64, the adapter decodes and returns bytes.

Raises ImageGenError on any provider-level or network error.
"""
from __future__ import annotations

import base64

import httpx


class ImageGenError(Exception):
    """Raised by any image-gen adapter on provider error, network failure,
    or unsupported configuration.  The message includes the provider's raw
    error details where available.
    """


def download_url(url: str, *, timeout: float = 60.0) -> bytes:
    """Fetch image bytes from a URL.  Raises ImageGenError on failure."""
    try:
        resp = httpx.get(url, follow_redirects=True, timeout=timeout)
        resp.raise_for_status()
        return resp.content
    except httpx.HTTPStatusError as exc:
        raise ImageGenError(
            f"image download HTTP {exc.response.status_code}: {url}"
        ) from exc
    except httpx.TimeoutException as exc:
        raise ImageGenError(f"image download timed out: {url}") from exc
    except Exception as exc:
        raise ImageGenError(f"image download error: {exc}") from exc


def decode_b64(b64_str: str) -> bytes:
    """Decode a base64 image string.  Raises ImageGenError on bad input."""
    try:
        return base64.b64decode(b64_str)
    except Exception as exc:
        raise ImageGenError(f"base64 decode error: {exc}") from exc
