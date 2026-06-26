"""个人头像上传魔数校验回归(frontend_routes.api_upload_avatar)。

动机:该端点此前只看客户端 multipart filename 的扩展名,从不校验真实字节,而其余
三个图片上传端点(角色卡头像 / 人设图 / 角色卡导入,见 api/me.py:_detect_image_mime)
都做魔数校验。后果:任意 2MB 字节伪装成 .png 落进头像图床,并被服务路由以 image/*
回发给其它登录用户。本测试锁定:伪造扩展名的非图片被 400 拒绝(在任何 DB/storage 写
之前),真 PNG 通过校验且落盘扩展名取检测结果(不信客户端扩展名)。
"""
from __future__ import annotations

import asyncio
import os
import unittest
from unittest import mock

os.environ.setdefault("RPG_DEPLOYMENT_MODE", "local")


class _FakeUpload:
    def __init__(self, filename: str, data: bytes):
        self.filename = filename
        self._data = data

    async def read(self):
        return self._data


class _FakeForm:
    def __init__(self, file_obj):
        self._file = file_obj

    def get(self, key):
        return self._file if key == "file" else None


class _FakeRequest:
    def __init__(self, form):
        self._form = form

    async def form(self):
        return self._form


def _call_upload(filename: str, data: bytes, *, full_stack: bool = False):
    """调用 api_upload_avatar。full_stack=False 时只验证早期校验(无 DB);
    full_stack=True 时把 DB/storage/资产登记全 mock 掉,验证成功路径。"""
    from platform_app import frontend_routes as fr

    req = _FakeRequest(_FakeForm(_FakeUpload(filename, data)))
    patches = [mock.patch.object(fr, "require_user", return_value={"id": 1})]
    captured: dict = {}
    if full_stack:
        cm = mock.MagicMock()
        cm.__enter__.return_value = mock.MagicMock()
        cm.__exit__.return_value = False

        def _store(d, kind, filename):  # noqa: A002 - 复刻签名
            captured["store_filename"] = filename
            captured["store_kind"] = kind
            return (f"{kind}/{filename}", f"/api/profile/avatar/file/{filename}")

        patches += [
            mock.patch.object(fr, "init_db", return_value=None),
            mock.patch.object(fr, "connect", return_value=cm),
            mock.patch.object(fr, "_storage_store_bytes", side_effect=_store),
            mock.patch("platform_app.assets_registry.register_asset", return_value=None),
        ]
    with patches[0]:
        for p in patches[1:]:
            p.start()
        try:
            resp = asyncio.run(fr.api_upload_avatar(req))
        finally:
            for p in patches[1:]:
                p.stop()
    return resp, captured


class TestAvatarUploadMagicByte(unittest.TestCase):
    def test_non_image_bytes_named_png_rejected(self):
        """伪装成 .png 的 HTML/任意字节 → 400(在任何落盘前)。"""
        resp, _ = _call_upload("evil.png", b"<html><script>alert(1)</script></html>")
        self.assertEqual(resp.status_code, 400)

    def test_truncated_png_signature_rejected(self):
        """扩展名合法但魔数不完整 → 400。"""
        resp, _ = _call_upload("a.png", b"\x89PNGbroken-not-a-real-signature")
        self.assertEqual(resp.status_code, 400)

    def test_real_png_passes_and_uses_detected_ext(self):
        """真 PNG 头通过校验;落盘文件名扩展名取检测结果(png),不取客户端扩展名。"""
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        resp, captured = _call_upload("whatever.jpeg", png, full_stack=True)
        self.assertEqual(resp.status_code, 200)
        # 客户端传 .jpeg,但真实字节是 PNG → 落盘必须是 .png
        self.assertTrue(
            captured.get("store_filename", "").endswith(".png"),
            f"落盘扩展名应取检测结果 .png,实际={captured.get('store_filename')!r}",
        )
        self.assertEqual(captured.get("store_kind"), "avatars")

    def test_jpeg_bytes_named_png_stored_as_jpg(self):
        """真 JPEG 字节但客户端命名 .png → 通过(是图片),落盘按检测结果 .jpg。"""
        jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 64
        resp, captured = _call_upload("a.png", jpeg, full_stack=True)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(captured.get("store_filename", "").endswith(".jpg"))


if __name__ == "__main__":
    unittest.main()
