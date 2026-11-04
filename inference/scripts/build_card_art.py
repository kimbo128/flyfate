"""Turn a transparent screenshot of the app's `?snapshot` view into the share-card art and the app icons.

1. Run the web dev server and screenshot http://localhost:<port>/?snapshot at 900x760, device scale 2,
   with a transparent background (Playwright: page.screenshot(omit_background=True)).
2. uv run python scripts/build_card_art.py <screenshot.png>

Output: inference/assets/card-hero.png (Melanie + brain, cropped) and web/public/icon-{180,512}.png.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]
SKY_TOP, SKY_BOTTOM = (168, 219, 255), (255, 227, 199)


def content(img):
    return img.crop(img.getchannel('A').point(lambda a: 255 if a > 8 else 0).getbbox())


def icon(fly, size):
    bg = Image.new('RGBA', (size, size))
    d = ImageDraw.Draw(bg)
    for y in range(size):
        t = y / size
        d.line([(0, y), (size, y)], fill=tuple(round(a * (1 - t) + b * t) for a, b in zip(SKY_TOP, SKY_BOTTOM)))
    scale = size * 0.8 / max(fly.size)
    fly = fly.resize((round(fly.width * scale), round(fly.height * scale)), Image.LANCZOS)
    bg.alpha_composite(fly, ((size - fly.width) // 2, (size - fly.height) // 2))
    return bg.convert('RGB')


def main(path):
    hero = content(Image.open(path).convert('RGBA'))
    hero.save(ROOT / 'inference' / 'assets' / 'card-hero.png', optimize=True)
    # Melanie: the connected shapes that start in the left fifth (her eye overlaps the brain's columns,
    # so a simple vertical cut would not separate them).
    mask = np.asarray(hero.getchannel('A')) > 8
    labels, count = ndimage.label(mask)
    boxes = ndimage.find_objects(labels)
    mine = [i + 1 for i, b in enumerate(boxes) if b[1].start < hero.width * 0.2]
    rgba = np.asarray(hero).copy()
    rgba[..., 3] = np.where(np.isin(labels, mine), rgba[..., 3], 0)  # drop the brain from the icon
    fly = content(Image.fromarray(rgba, 'RGBA'))
    for size in (180, 512):
        icon(fly, size).save(ROOT / 'web' / 'public' / f'icon-{size}.png', optimize=True)
    print('hero', hero.size, 'fly', fly.size)


if __name__ == '__main__':
    main(sys.argv[1])
