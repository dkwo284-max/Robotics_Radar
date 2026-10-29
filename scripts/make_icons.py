"""web/icon.svg 와 같은 그림을 Pillow 로 그려 icon-192.png / icon-512.png 를 만든다 (한 번만 실행).

    pip install pillow && python scripts/make_icons.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

WEB = Path(__file__).resolve().parent.parent / "web"
BG, BLUE, GREEN, WHITE = (15, 23, 32), (47, 91, 234), (52, 196, 127), (233, 238, 243)


def draw(size: int) -> Image.Image:
    s = 4  # 크게 그린 뒤 줄여 계단 현상을 없앤다
    n = 512 * s
    k = lambda v: v * s  # noqa: E731
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, n - 1, n - 1], radius=k(112), fill=BG)
    ring = tuple(int(BG[i] + (BLUE[i] - BG[i]) * 0.55) for i in range(3))
    for r in (190, 130):
        d.ellipse([k(256 - r), k(268 - r), k(256 + r), k(268 + r)], outline=ring, width=k(10))
    d.line([k(256), k(268), k(410), k(150)], fill=GREEN, width=k(12))
    d.rounded_rectangle([k(166), k(190), k(346), k(340)], radius=k(40), fill=WHITE)
    d.rounded_rectangle([k(196), k(236), k(316), k(286)], radius=k(25), fill=BG)
    for cx in (230, 282):
        d.ellipse([k(cx - 12), k(249), k(cx + 12), k(273)], fill=GREEN)
    d.line([k(256), k(190), k(256), k(156)], fill=WHITE, width=k(12))
    d.ellipse([k(242), k(134), k(270), k(162)], fill=WHITE)
    d.rounded_rectangle([k(146), k(240), k(166), k(294)], radius=k(10), fill=WHITE)
    d.rounded_rectangle([k(346), k(240), k(366), k(294)], radius=k(10), fill=WHITE)
    d.ellipse([k(394), k(134), k(426), k(166)], fill=GREEN)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    for size in (192, 512):
        draw(size).save(WEB / f"icon-{size}.png")
        print(f"icon-{size}.png")
