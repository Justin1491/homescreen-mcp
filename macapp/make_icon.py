"""Draw the app icon (four colored rounded squares on a light tile) as an .iconset for iconutil."""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

COLORS = [(255, 159, 10), (48, 209, 88), (10, 132, 255), (191, 90, 242)]  # orange, green, blue, purple


def draw(size: int) -> Image.Image:
    s = size * 4  # draw large, scale down for smooth edges
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = round(s * 0.1)  # macOS icons sit inside a margin
    d.rounded_rectangle([pad, pad, s - pad, s - pad], radius=round(s * 0.18), fill=(250, 250, 252),
                        outline=(225, 225, 232), width=max(1, s // 256))
    inner = s - 2 * pad
    gap = inner * 0.08
    cell = (inner - 3 * gap) / 2
    for i, c in enumerate(COLORS):
        x = pad + gap + (i % 2) * (cell + gap)
        y = pad + gap + (i // 2) * (cell + gap)
        d.rounded_rectangle([x, y, x + cell, y + cell], radius=round(cell * 0.24), fill=c)
    return img.resize((size, size), Image.LANCZOS)


def main(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for base in (16, 32, 128, 256, 512):
        draw(base).save(out / f"icon_{base}x{base}.png")
        draw(base * 2).save(out / f"icon_{base}x{base}@2x.png")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
