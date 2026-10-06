#!/usr/bin/env python3
"""Renders the Modrinth icon (512x512) and gallery banner (1920x1080) as pixel art.

Edit NAME/TAG and re-run: python3 art/make_art.py
Drawn at low resolution, then nearest-neighbour upscaled so it stays crisp.
"""
import math
import os
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

NAME = "MERIDIAN"
TAG = "SURVIVAL 2027"
DOMAIN = "mullv.studio"
FONT = os.environ.get("PIXEL_FONT", os.path.expanduser("~/.local/share/fonts/GeistPixel-Square.otf"))
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "modrinth")
os.makedirs(OUT, exist_ok=True)

W, H, SCALE = 480, 270, 4
OFF = 28  # lowers the whole landscape so dirt doesn't fill the bottom
HORIZON = 168 + OFF


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def ramp(stops, t):
    for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
        if t <= t1:
            return lerp(c0, c1, (t - t0) / (t1 - t0))
    return stops[-1][1]


def text_mask(size, text, spacing=0):
    font = ImageFont.truetype(FONT, size)
    width = int(sum(font.getlength(c) + spacing for c in text)) + 4
    mask = Image.new("L", (width, size * 2), 0)
    d = ImageDraw.Draw(mask)
    d.fontmode = "1"
    x = 2
    for c in text:
        d.text((x, 2), c, font=font, fill=255)
        x += font.getlength(c) + spacing
    return mask.crop(mask.getbbox())


def paste_gold_text(img, text, size, cx, top, spacing=1):
    mask = text_mask(size, text, spacing)
    w, h = mask.size
    x0 = cx - w // 2
    pad = Image.new("L", (w + 8, h + 8), 0)
    pad.paste(mask, (4, 4))
    outline = pad.filter(ImageFilter.MaxFilter(3)).point(lambda v: 255 if v else 0)
    shadow = ImageChops.offset(outline, 2, 3)
    layer = Image.new("RGBA", pad.size, (0, 0, 0, 0))
    layer.paste(Image.new("RGBA", pad.size, (40, 18, 8, 150)), mask=shadow)
    layer.paste(Image.new("RGBA", pad.size, (62, 30, 10, 255)), mask=outline)
    grad = Image.new("RGBA", pad.size)
    gp = grad.load()
    for y in range(pad.size[1]):
        t = min(max((y - 4) / max(h - 1, 1), 0), 1)
        c = ramp([(0, (255, 244, 170)), (0.45, (250, 200, 70)), (0.55, (226, 150, 30)), (1, (176, 98, 18))], t)
        for x in range(pad.size[0]):
            gp[x, y] = (*c, 255)
    layer.paste(grad, mask=pad)
    img.alpha_composite(layer, (x0 - 4, top - 4))


def sky(img):
    px = img.load()
    stops = [(0, (18, 30, 84)), (0.45, (52, 98, 168)), (0.75, (226, 142, 112)), (1, (255, 196, 110))]
    for y in range(HORIZON + 40):
        t = round(min(y / HORIZON, 1) * 16) / 16  # banded gradient
        for x in range(W):
            px[x, y] = (*ramp(stops, t), 255)


def sun(img):
    cx, cy = 352, 150 + OFF
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for r, a in ((54, 28), (44, 44), (36, 70)):
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 214, 140, a))
    d.ellipse((cx - 27, cy - 27, cx + 27, cy + 27), fill=(255, 240, 190, 255))
    img.alpha_composite(ov)


def globe_lines(img):
    """Big translucent wireframe globe behind the title: the 'meridian'."""
    cx, cy, r = 240, 92, 84
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    col = (255, 236, 190, 70)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=col, width=2)
    for k in (0.28, 0.62):
        rx = int(r * k)
        d.ellipse((cx - rx, cy - r, cx + rx, cy + r), outline=col)
    d.line((cx, cy - r, cx, cy + r), fill=col)
    for k in (0.0, 0.34, 0.66):
        ry = int(r * k)
        d.ellipse((cx - r, cy - ry, cx + r, cy + ry), outline=col)
    img.alpha_composite(ov)


def clouds(img):
    d = ImageDraw.Draw(img)
    random.seed(7)
    for x, y, w in ((30, 60, 46), (400, 40, 52), (120, 118, 38), (300, 104, 34), (210, 134, 30)):
        for i in range(3):
            d.rectangle((x + i * 5, y + i % 2 * -3, x + w - i * 7, y + 3 + i % 2 * -3 + 4), fill=(255, 226, 205, 150))


def ridge(img, base, amps, color, top=None, seed=0):
    d = ImageDraw.Draw(img)
    rnd = random.Random(seed)
    ph = [rnd.random() * 6.28 for _ in amps]
    tops = []
    for x in range(W):
        h = base + sum(a * math.sin(f * x + p) for (a, f), p in zip(amps, ph))
        h = int(h // 3 * 3)  # stepped, voxel-like
        tops.append(h)
        d.line((x, h, x, H), fill=color)
        if top:
            d.line((x, h, x, h), fill=top)
    return tops


def pines(img, tops, seed, every=(5, 11), dark=(26, 60, 52), lite=(46, 96, 70)):
    d = ImageDraw.Draw(img)
    rnd = random.Random(seed)
    x = rnd.randint(2, 8)
    while x < W - 6:
        y = tops[x]
        hgt = rnd.choice((9, 11, 13))
        d.rectangle((x, y - 2, x, y), fill=(70, 44, 28))
        for row in range(hgt):
            half = 1 + (row * 3) // hgt
            yy = y - 2 - hgt + row + 2
            d.line((x - half, yy, x + half, yy), fill=dark if row % 2 else lite)
        x += rnd.randint(*every)


def foreground(img):
    d = ImageDraw.Draw(img)
    rnd = random.Random(3)
    ground = 196 + OFF
    for x in range(W):
        gy = ground + int(2 * math.sin(x / 31.0)) // 1
        d.line((x, gy, x, gy + 5), fill=(92, 146, 60))
        d.line((x, gy, x, gy), fill=(142, 196, 82))
        d.line((x, gy + 6, x, H), fill=(112, 76, 50))
    for x in range(0, W, 16):  # block seams
        d.line((x, ground + 6, x, H), fill=(90, 60, 40))
    for y in range(ground + 6, H, 16):
        d.line((0, y, W, y), fill=(90, 60, 40))
    for _ in range(260):  # dirt speckle
        x, y = rnd.randrange(W), rnd.randrange(ground + 8, H)
        d.point((x, y), fill=rnd.choice(((132, 92, 62), (98, 66, 44))))
    for x in range(0, W, 7):  # grass tufts
        d.point((x, ground - 1 + int(2 * math.sin(x / 31.0))), fill=(142, 196, 82))
    # track
    ty = 214 + OFF
    d.rectangle((0, ty + 2, W, ty + 6), fill=(74, 66, 62))
    for x in range(0, W, 7):
        d.rectangle((x, ty + 1, x + 3, ty + 7), fill=(104, 70, 44))
    d.line((0, ty + 2, W, ty + 2), fill=(188, 190, 196))
    d.line((0, ty + 6, W, ty + 6), fill=(120, 122, 130))
    return ty


def train(img, ty):
    d = ImageDraw.Draw(img)
    brass, dk, hi, steel = (196, 128, 46), (84, 50, 30), (246, 206, 108), (58, 58, 66)
    y1 = ty + 2  # rail top
    # tender + car
    d.rectangle((420, y1 - 22, 478, y1 - 5), fill=(88, 70, 62))  # freight car
    d.rectangle((420, y1 - 22, 478, y1 - 20), fill=(116, 94, 80))
    for xx in range(424, 478, 9):
        d.line((xx, y1 - 19, xx, y1 - 7), fill=(64, 50, 44))
    d.rectangle((410, y1 - 9, 420, y1 - 8), fill=steel)  # coupler
    # locomotive boiler
    d.rectangle((300, y1 - 22, 366, y1 - 8), fill=brass)
    d.rectangle((300, y1 - 22, 366, y1 - 20), fill=hi)
    d.rectangle((300, y1 - 10, 366, y1 - 8), fill=(150, 92, 30))
    for xx in (316, 332, 348):
        d.line((xx, y1 - 22, xx, y1 - 8), fill=dk)
    d.rectangle((292, y1 - 24, 300, y1 - 6), fill=dk)  # smokebox
    d.rectangle((294, y1 - 32, 299, y1 - 24), fill=dk)  # chimney
    d.rectangle((292, y1 - 34, 301, y1 - 32), fill=steel)
    d.rectangle((324, y1 - 28, 330, y1 - 22), fill=hi)  # dome
    d.rectangle((366, y1 - 32, 394, y1 - 6), fill=dk)  # cab
    d.rectangle((364, y1 - 34, 396, y1 - 31), fill=(140, 86, 40))
    d.rectangle((372, y1 - 27, 380, y1 - 19), fill=(255, 226, 150))  # cab window
    d.rectangle((394, y1 - 14, 410, y1 - 6), fill=(112, 76, 50))  # tender
    d.rectangle((394, y1 - 14, 410, y1 - 12), fill=(150, 108, 70))
    d.polygon([(286, y1 - 2), (292, y1 - 12), (292, y1 - 2)], fill=steel)  # cowcatcher
    d.rectangle((284, y1 - 2, 292, y1), fill=steel)
    for wx, r in ((306, 5), (322, 5), (338, 5), (380, 6), (402, 4), (432, 4), (466, 4)):
        d.ellipse((wx - r, y1 - 2 * r + 1, wx + r, y1 + 1), fill=(36, 34, 40))
        d.ellipse((wx - 1, y1 - r, wx + 1, y1 - r + 2), fill=(176, 176, 186))
    d.line((304, y1 - 4, 340, y1 - 4), fill=(190, 190, 198))  # rod
    # headlamp glow
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(ov).ellipse((280, y1 - 21, 294, y1 - 11), fill=(255, 240, 180, 60))
    img.alpha_composite(ov)
    d.rectangle((290, y1 - 17, 292, y1 - 14), fill=(255, 250, 210))
    # steam puffs
    for i, (px_, py_, r) in enumerate(((292, y1 - 40, 3), (284, y1 - 48, 4), (270, y1 - 58, 5), (250, y1 - 66, 6))):
        d.ellipse((px_ - r, py_ - r, px_ + r, py_ + r), fill=(250, 238, 230, 200 - i * 30))


def plane(img):
    d = ImageDraw.Draw(img)
    x, y = 70, 150 + OFF - 14
    body, wing, dk = (200, 70, 52), (236, 218, 190), (60, 30, 28)
    for i in range(0, 56, 4):  # contrail
        d.rectangle((x - 6 - i - 14, y + 4, x - 3 - i - 14, y + 5), fill=(255, 245, 235, 230 - i * 3))
    d.rectangle((x, y, x + 26, y + 6), fill=body)
    d.rectangle((x + 18, y - 1, x + 26, y + 2), fill=(250, 200, 120))  # canopy
    d.rectangle((x - 8, y - 6, x - 3, y + 1), fill=body)  # tail
    d.rectangle((x - 10, y + 1, x - 2, y + 2), fill=wing)
    d.rectangle((x + 4, y - 7, x + 24, y - 5), fill=wing)  # upper wing
    d.rectangle((x + 4, y + 7, x + 24, y + 9), fill=wing)  # lower wing
    for sx in (8, 20):
        d.line((x + sx, y - 5, x + sx, y + 7), fill=dk)
    d.rectangle((x + 27, y - 2, x + 28, y + 8), fill=(170, 170, 178))  # prop
    d.rectangle((x + 4, y + 6, x + 6, y + 7), fill=dk)


def banner():
    img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    sky(img)
    sun(img)
    clouds(img)
    globe_lines(img)
    ridge(img, 150 + OFF, [(20, 0.021), (9, 0.057)], (150, 108, 146), seed=1)
    ridge(img, 164 + OFF, [(14, 0.03), (7, 0.083)], (96, 94, 128), seed=2)
    hills = ridge(img, 182 + OFF, [(10, 0.019), (5, 0.07)], (34, 78, 62), top=(76, 132, 78), seed=4)
    pines(img, hills, seed=5)
    ty = foreground(img)
    plane(img)
    train(img, ty)
    paste_gold_text(img, NAME, 46, W // 2, 34)
    # tagline
    tag = text_mask(12, TAG, 2)
    tl = Image.new("RGBA", (tag.size[0] + 4, tag.size[1] + 4), (0, 0, 0, 0))
    tl.paste((40, 18, 8, 200), (2, 3), tag)
    tl.paste((255, 244, 214, 255), (1, 1), tag)
    img.alpha_composite(tl, ((W - tag.size[0]) // 2 - 1, 34 + 46 + 16))
    dm = text_mask(14, DOMAIN)
    dl = Image.new("RGBA", (dm.size[0] + 4, dm.size[1] + 4), (0, 0, 0, 0))
    dl.paste((20, 14, 20, 200), (2, 2), dm)
    dl.paste((255, 255, 255, 255), (1, 1), dm)
    img.alpha_composite(dl, (W - dm.size[0] - 12, H - dm.size[1] - 12))
    img.resize((W * SCALE, H * SCALE), Image.NEAREST).convert("RGB").save(os.path.join(OUT, "banner.png"), optimize=True)


def icon():
    S = 64
    img = Image.new("RGBA", (S, S), (0, 0, 0, 255))
    px = img.load()
    for y in range(S):  # dusk gradient background
        t = round(y / (S - 1) * 8) / 8
        c = ramp([(0, (20, 34, 92)), (0.6, (88, 78, 150)), (1, (240, 150, 96))], t)
        for x in range(S):
            px[x, y] = (*c, 255)
    cx, cy, r = 32, 33, 19
    rnd = random.Random(11)
    land = [(26, 27, 7), (40, 40, 6), (21, 41, 4), (38, 24, 4), (31, 46, 3)]
    for y in range(S):
        for x in range(S):
            dx, dy = x - cx, y - cy
            dist = math.hypot(dx, dy)
            if dist > r:
                continue
            lit = (-dx * 0.6 - dy * 0.8) / r  # light from upper-left
            on_land = any(math.hypot(x - lx + rnd.uniform(-1, 1), y - ly + rnd.uniform(-1, 1)) < lr for lx, ly, lr in land)
            base = (74, 150, 74) if on_land else (36, 96, 186)
            shade = 0.55 + 0.45 * min(max(lit * 0.5 + 0.5, 0), 1)
            shade = round(shade * 5) / 5
            px[x, y] = (*tuple(int(v * shade) for v in base), 255)
    ov = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    gold, gold_dk = (255, 214, 96, 255), (190, 124, 30, 255)
    d.ellipse((cx - 9, cy - r, cx + 9, cy + r), outline=gold)  # the meridian
    d.line((cx - r, cy, cx + r, cy), fill=gold)
    d.ellipse((cx - r - 5, cy - r - 5, cx + r + 5, cy + r + 5), outline=gold_dk, width=3)
    d.ellipse((cx - r - 5, cy - r - 5, cx + r + 5, cy + r + 5), outline=gold, width=1)
    d.polygon([(cx, 1), (cx - 4, 9), (cx + 4, 9)], fill=gold, outline=(120, 70, 14, 255))  # north mark
    for tx, ty in ((cx - r - 9, cy), (cx + r + 9, cy)):
        d.rectangle((tx - 2, ty - 1, tx + 2, ty + 1), fill=gold)
    img.alpha_composite(ov)
    img.resize((512, 512), Image.NEAREST).convert("RGB").save(os.path.join(OUT, "icon.png"), optimize=True)


if __name__ == "__main__":
    banner()
    icon()
    print("wrote", os.path.abspath(OUT))
