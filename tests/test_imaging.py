import io
from datetime import datetime

import pytest
from PIL import Image

from niim_agent.imaging import build_test_label, mm_to_px, prepare_image
from niim_agent.printer.client import encode_image
from niim_agent.printer.models import MODELS, get_model

D110 = get_model("d110")


def png(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_encode_image_matches_vectors():
    # Ek B: 16×2 px; 0. satırın soldaki 8 pikseli siyah, 1. satır tamamen beyaz.
    image = Image.new("L", (16, 2), 255)
    for x in range(8):
        image.putpixel((x, 0), 0)
    rows = [p.to_bytes() for p in encode_image(image)]
    assert rows == [
        bytes.fromhex("55 55 85 08 00 00 00 00 00 01 FF 00 73 AA AA"),
        bytes.fromhex("55 55 85 08 00 01 00 00 00 01 00 00 8D AA AA"),
    ]


def test_mm_to_px():
    assert (mm_to_px(40), mm_to_px(12), mm_to_px(1.2), mm_to_px(30)) == (320, 96, 10, 240)


def test_prepare_image_rotates_clockwise_270():
    image = Image.new("L", (320, 96), 255)
    image.putpixel((0, 0), 0)  # yatay çizimin sol üst köşesi
    out = prepare_image(png(image), 270, D110)
    assert out.size == (96, 320)
    assert out.mode == "L"
    # Saat yönünde 270° = saat yönünün tersine 90°: sol üst köşe sol alta gider.
    assert out.getpixel((0, 319)) == 0
    assert out.getpixel((0, 0)) == 255


def test_prepare_image_rotate_90_is_opposite():
    image = Image.new("L", (320, 96), 255)
    image.putpixel((0, 0), 0)
    out = prepare_image(png(image), 90, D110)
    assert out.getpixel((95, 0)) == 0


def test_prepare_image_rejects_too_wide():
    image = Image.new("L", (320, 96), 255)
    with pytest.raises(ValueError, match="Görsel genişliği 320px; D110 için sınır 240px"):
        prepare_image(png(image), 0, D110)
    # B1'in kafası 384 px.
    assert prepare_image(png(image), 0, get_model("b1")).size == (320, 96)


def test_prepare_image_rejects_bad_input():
    with pytest.raises(ValueError):
        prepare_image(png(Image.new("L", (96, 96))), 45, D110)
    with pytest.raises(ValueError, match="Görsel açılamadı"):
        prepare_image(b"not a png", 270, D110)


def test_prepare_image_flattens_transparency_onto_white():
    image = Image.new("RGBA", (96, 96), (0, 0, 0, 0))  # tamamen saydam siyah
    image.putpixel((5, 5), (0, 0, 0, 255))
    out = prepare_image(png(image), 0, D110)
    assert out.getpixel((0, 0)) == 255
    assert out.getpixel((5, 5)) == 0


def test_model_table():
    assert {m.name: (m.head_width, m.max_density) for m in MODELS.values()} == {
        "d110": (240, 3),
        "d11": (240, 3),
        "d11_h": (240, 3),
        "b18": (384, 3),
        "b1": (384, 5),
        "b21": (384, 5),
    }
    assert get_model("D110") is D110
    with pytest.raises(ValueError, match="Bilinmeyen yazıcı modeli"):
        get_model("q1")


def test_clamp_density():
    b21 = get_model("b21")
    assert [D110.clamp_density(d) for d in (None, 0, 1, 3, 5)] == [3, 3, 1, 3, 3]
    assert [b21.clamp_density(d) for d in (None, 5, 9, -1)] == [3, 5, 5, 1]


def test_test_label():
    label = Image.open(io.BytesIO(build_test_label(datetime(2026, 9, 24, 10, 0))))
    assert label.size == (320, 96)
    gray = label.convert("L")
    margin = 10
    # 1.2 mm kenar payı boş, çerçeve 2 px.
    for x in range(320):
        assert all(gray.getpixel((x, y)) == 255 for y in (*range(margin), *range(96 - margin, 96)))
    assert gray.getpixel((margin, 48)) == 0 and gray.getpixel((margin + 1, 48)) == 0
    assert gray.getpixel((margin + 2, 48)) == 255
    # Çerçevenin içinde yazı var.
    inner = gray.crop((margin + 3, margin + 3, 320 - margin - 3, 96 - margin - 3))
    assert inner.getextrema()[0] == 0
    assert prepare_image(build_test_label(), 270, D110).size == (96, 320)
