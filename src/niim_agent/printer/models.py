"""Model tablosu (§6.1). Kaynak: NiimPrintX cli/command.py."""

from dataclasses import dataclass

DEFAULT_DENSITY = 3


@dataclass(frozen=True)
class PrinterModel:
    name: str
    head_width: int  # px; döndürülmüş görselin genişlik sınırı
    max_density: int

    def clamp_density(self, density: int | None) -> int:
        return max(1, min(density or DEFAULT_DENSITY, self.max_density))


MODELS: dict[str, PrinterModel] = {
    m.name: m
    for m in (
        PrinterModel("d110", 240, 3),
        PrinterModel("d11", 240, 3),
        PrinterModel("d11_h", 240, 3),
        PrinterModel("b18", 384, 3),
        PrinterModel("b1", 384, 5),
        PrinterModel("b21", 384, 5),
    )
}


def get_model(name: str) -> PrinterModel:
    try:
        return MODELS[name.lower()]
    except KeyError:
        known = ", ".join(MODELS)
        raise ValueError(f"Bilinmeyen yazıcı modeli: {name!r} (bilinenler: {known})") from None
