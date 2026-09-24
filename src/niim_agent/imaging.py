"""Görsel hazırlama (§6): prepare_image ve deneme etiketi."""

import io
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from niim_agent.printer.models import PrinterModel

DPI = 203
DEFAULT_ROTATE = 270
ROTATIONS = (0, 90, 180, 270)


def mm_to_px(mm: float) -> int:
    return round(mm * DPI / 25.4)


def prepare_image(png_bytes: bytes, rotate: int, model: PrinterModel) -> Image.Image:
    """PNG'yi açar, saat yönünde `rotate` derece döndürür, genişliği model
    sınırıyla karşılaştırır ve L moduna çevirir. Hatalı girdide ValueError."""
    if rotate not in ROTATIONS:
        raise ValueError(f"Döndürme 0, 90, 180 ya da 270 olmalı: {rotate}")
    try:
        image = Image.open(io.BytesIO(png_bytes))
        image.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ValueError(f"Görsel açılamadı: {e}") from e

    if rotate:
        # PIL saat yönünün tersine döndürür; eksi işaretiyle saat yönüne döner.
        image = image.rotate(-rotate, expand=True)
    if image.width > model.head_width:
        raise ValueError(f"Görsel genişliği {image.width}px; "
                         f"{model.name.upper()} için sınır {model.head_width}px")
    if image.has_transparency_data:
        # Saydam pikseller beyaz zemine oturtulur; yoksa convert("L") onları siyah basabilir.
        image = Image.alpha_composite(Image.new("RGBA", image.size, "white"), image.convert("RGBA"))
    return image.convert("L")


def build_test_label(now: datetime | None = None) -> bytes:
    """40×12 mm (320×96 px) deneme etiketi, PNG. Yatay çizilir; 270° döndürülüp basılır."""
    now = now or datetime.now()
    width, height = mm_to_px(40), mm_to_px(12)
    margin = mm_to_px(1.2)  # D110 en uçtaki pikselleri basmıyor

    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    draw.fontmode = "1"  # kenar yumuşatma yok; termal baskıda keskin kalır
    draw.rectangle((margin, margin, width - margin - 1, height - margin - 1), outline=0, width=2)

    lines = [
        ("NIIM-AGENT", ImageFont.load_default(size=30)),
        (now.strftime("%Y-%m-%d %H:%M:%S"), ImageFont.load_default(size=16)),
    ]
    gap = 6
    boxes = [draw.textbbox((0, 0), text, font=font) for text, font in lines]
    total = sum(b[3] - b[1] for b in boxes) + gap * (len(lines) - 1)
    y = (height - total) / 2
    for (text, font), (left, top, right, bottom) in zip(lines, boxes, strict=True):
        draw.text(((width - (right - left)) / 2 - left, y - top), text, font=font, fill=0)
        y += bottom - top + gap

    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()
