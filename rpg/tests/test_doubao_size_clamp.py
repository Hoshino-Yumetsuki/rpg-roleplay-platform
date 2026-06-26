"""doubao 尺寸下限钳制 —— 小于 3_686_400 px 的尺寸放大到下限,保持宽高比、对齐 16。"""
from agents.image_gen.doubao import _clamp_doubao_size

MIN_AREA = 3_686_400

def _area(s):
    w, h = s.lower().split("x"); return int(w) * int(h)

def test_small_square_scaled_up():
    out = _clamp_doubao_size("1024x1024")
    assert _area(out) >= MIN_AREA, out
    w, h = (int(x) for x in out.lower().split("x"))
    assert abs(w - h) <= 16   # 仍近似正方形
    assert w % 16 == 0 and h % 16 == 0

def test_small_landscape_keeps_aspect():
    out = _clamp_doubao_size("1024x768")  # 4:3
    assert _area(out) >= MIN_AREA, out
    w, h = (int(x) for x in out.lower().split("x"))
    assert 1.2 < w / h < 1.45   # 仍约 4:3(1.333)

def test_already_large_unchanged():
    assert _clamp_doubao_size("2048x2048") == "2048x2048"
    assert _clamp_doubao_size("1920x1920") == "1920x1920"

def test_ratio_form_passthrough():
    assert _clamp_doubao_size("1:1") == "1:1"
    assert _clamp_doubao_size("16:9") == "16:9"

def test_garbage_passthrough():
    assert _clamp_doubao_size("auto") == "auto"
    assert _clamp_doubao_size("") == ""
