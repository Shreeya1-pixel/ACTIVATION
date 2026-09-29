"""Process the two AutoStack logo PNGs into web-ready assets.

Inputs (user-provided, 1024x1024-ish, both with dark backgrounds):
  - light logo: dark metallic "A" + dark-gray wordmark (for LIGHT theme surfaces)
  - dark logo:  glowing white "A" + white wordmark (for DARK theme surfaces)

Outputs (frontend/src/assets/, committed to the repo):
  - autostack-mark-light.png / autostack-mark-dark.png   (mark only, transparent)
  - autostack-lockup-light.png / autostack-lockup-dark.png (mark + wordmark, transparent)

Method: background = black -> alpha via luminance-derived matte for the dark
logo (glow must stay semi-transparent, so we do proper un-premultiply against
black), and alpha-keying for the metallic logo, then autocrop + downscale.
"""
from PIL import Image
import numpy as np

SRC_LIGHT = r"C:\Users\prady\Downloads\ChatGPT Image Sep 26, 2026, 12_20_02 AM.png"
SRC_DARK = r"C:\Users\prady\Downloads\ChatGPT Image Sep 26, 2026, 12_19_57 AM.png"
OUT = "frontend/src/assets"

import os
os.makedirs(OUT, exist_ok=True)


def autocrop(im, threshold=8):
    a = np.array(im)
    alpha = a[..., 3]
    ys, xs = np.where(alpha > threshold)
    if len(xs) == 0:
        return im
    box = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
    return im.crop(box)


def unmix_against_black(rgb, strength):
    """Given pixels composited over black with additive glow, recover the
    emission color and alpha: alpha ≈ max_channel, color = rgb / max_channel.
    `strength` scales how aggressively dim pixels become opaque."""
    mx = rgb.max(axis=-1)
    alpha = np.clip(mx * strength, 0, 255).astype(np.uint8)
    safe = np.maximum(mx, 1)[..., None]
    color = np.clip(rgb / safe * 255.0, 0, 255).astype(np.uint8)
    return color, alpha


def process_light():
    """Metallic 'A' on near-black. v2: the mark must render fully opaque and
    clearly visible — the old half-keyed alpha (mean ~95/255) made it a faint
    smudge on glass surfaces. Floor-key the background, then make every
    content pixel fully opaque and stretch its luminance into a readable
    metallic range so it holds up on white cards AND mid-tone glass."""
    im = Image.open(SRC_LIGHT).convert("RGB")
    rgb = np.array(im).astype(np.float64)
    floor = 26.0
    lum = rgb.max(axis=-1)
    # background keying: below floor -> transparent, smooth ramp to opaque
    alpha_f = np.clip((lum - floor) / (60.0 - floor), 0.0, 1.0)
    # content pixels (anything not background) become fully opaque
    content = lum >= floor
    alpha_f[content] = 1.0
    # luminance contrast stretch on content: map [floor..255] -> [55..205]
    lo, hi = floor, 255.0
    stretched = (rgb - lo) / max(hi - lo, 1.0)
    stretched = np.clip(stretched, 0.0, 1.0) * 150.0 + 55.0
    out_rgb = np.where(content[..., None], stretched, rgb)
    out = np.dstack([out_rgb.clip(0, 255).astype(np.uint8),
                     (alpha_f * 255).astype(np.uint8)])
    img = Image.fromarray(out, "RGBA")
    return autocrop(img)


def process_dark():
    """White glowing lockup on black -> emission matte (glow keeps soft alpha)."""
    im = Image.open(SRC_DARK).convert("RGB")
    rgb = np.array(im).astype(np.float64)
    color, alpha = unmix_against_black(rgb, strength=1.35)
    out = np.dstack([color, alpha])
    img = Image.fromarray(out, "RGBA")
    return autocrop(img, threshold=6)


def split_mark(im):
    """Mark = top ~72% of lockup height (the A glyph sits above the wordmark)."""
    w, h = im.size
    a = np.array(im)[..., 3]
    rows = np.where(a.max(axis=1) > 10)[0]
    # find the biggest vertical gap between content rows -> separates mark/word
    gaps = []
    prev = rows[0]
    start = rows[0]
    for r in rows[1:]:
        if r - prev > 12:
            gaps.append((prev, r))
        prev = r
    end = rows[-1]
    if gaps:
        g = max(gaps, key=lambda p: p[1] - p[0])
        mark_bottom = g[0]
    else:
        mark_bottom = int(h * 0.72)
    mark = im.crop((0, 0, w, mark_bottom + 2))
    return autocrop(mark)


light = process_light()
dark = process_dark()

for name, im in (("light", light), ("dark", dark)):
    lock = im.copy()
    lock.thumbnail((420, 260), Image.LANCZOS)
    lock.save(f"{OUT}/autostack-lockup-{name}.png", optimize=True)
    mark = split_mark(im)
    mark.thumbnail((160, 160), Image.LANCZOS)
    mark.save(f"{OUT}/autostack-mark-{name}.png", optimize=True)
    print(name, "lockup", lock.size, "mark", mark.size)
