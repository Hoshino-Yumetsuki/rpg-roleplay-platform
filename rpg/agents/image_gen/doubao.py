"""agents.image_gen.doubao — Doubao / Ark image-generation adapter.

API: OpenAI-compatible images/generations
Endpoint: POST {base_url}/images/generations
Default base_url: https://ark.cn-beijing.volces.com/api/v3
Auth: Authorization: Bearer {api_key}

Request body fields (JSON):
    model          str   required  e.g. "doubao-seedream-4-x-t2i" (from catalog)
    prompt         str   required  text prompt
    size           str   optional  e.g. "1024x1024" / "1:1" / "16:9"
    n              int   optional  number of images (default 1)
    seed           int   optional  for reproducibility
    watermark      bool  optional  whether provider adds watermark (default false)
    response_format str  optional  "url" (default) or "b64_json"

Response shape:
    {
      "data": [
        {"url": "https://...", "b64_json": null},
        ...
      ]
    }

Provider returns URL by default; we download to bytes.
If response_format="b64_json" the URL is null and b64_json is populated.
"""
from __future__ import annotations

from typing import Any

import httpx

from agents.image_gen.base import ImageGenError, decode_b64, download_url

_DEFAULT_BASE = "https://ark.cn-beijing.volces.com/api/v3"
_CONNECT_TIMEOUT = 10.0
_READ_TIMEOUT = 120.0


def generate(
    prompt: str,
    params: dict,
    *,
    api_id: str,
    model: str,
    api_key: str,
    base_url: str | None = None,
) -> list[bytes]:
    """Call Ark images/generations and return image bytes.

    Args:
        prompt:    Text prompt for image generation.
        params:    Optional provider parameters (size, n, seed, watermark,
                   response_format).  Keys match the Ark API field names.
        api_id:    Canonical provider id (e.g. "doubao") — informational only.
        model:     Model id string (e.g. "doubao-seedream-4-x-t2i").
        api_key:   Ark API key (Bearer token).
        base_url:  Override Ark endpoint base.  Defaults to
                   https://ark.cn-beijing.volces.com/api/v3
    Returns:
        list[bytes] — one element per generated image.
    Raises:
        ImageGenError on any provider or network failure.
    """
    base = (base_url or _DEFAULT_BASE).rstrip("/")
    endpoint = f"{base}/images/generations"

    body: dict[str, Any] = {"model": model, "prompt": prompt}
    # Forward supported optional fields from params
    for field in ("size", "n", "seed", "watermark", "response_format"):
        if field in params:
            body[field] = params[field]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = httpx.post(
            endpoint,
            json=body,
            headers=headers,
            timeout=httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT),
            follow_redirects=False,
        )
    except httpx.TimeoutException as exc:
        raise ImageGenError(f"doubao: request timed out ({exc})") from exc
    except Exception as exc:
        raise ImageGenError(f"doubao: network error ({exc})") from exc

    if resp.status_code != 200:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text[:500]
        raise ImageGenError(
            f"doubao: HTTP {resp.status_code} from {endpoint}: {detail}"
        )

    try:
        payload = resp.json()
    except Exception as exc:
        raise ImageGenError(f"doubao: invalid JSON response: {exc}") from exc

    data = payload.get("data")
    if not data or not isinstance(data, list):
        raise ImageGenError(f"doubao: unexpected response shape: {payload}")

    result: list[bytes] = []
    for item in data:
        b64 = item.get("b64_json")
        url = item.get("url")
        if b64:
            result.append(decode_b64(b64))
        elif url:
            result.append(download_url(url))
        else:
            raise ImageGenError(f"doubao: data item has neither url nor b64_json: {item}")

    if not result:
        raise ImageGenError("doubao: response data list is empty")

    return result
