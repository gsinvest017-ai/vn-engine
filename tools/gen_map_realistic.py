"""
gen_map_realistic.py  —  v2: hand-drawn Qing-dynasty survey map
Output: assets/backgrounds/city_historical.png (1920x1080 grayscale)

Techniques:
  - Wobbly line drawing (small-step jitter → no ruler-straight lines)
  - Ink-bleed text (Gaussian blur + slight displacement on text layer)
  - Heavy paper grain + water damage + foxing spots
  - River drawn as brush-stroke with multi-pass width variation
  - Building blocks with cross-hatch at varied angles
  - Turbulence displacement on final image for organic overall warp
"""
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageChops

W, H = 1920, 1080
OUT = Path(r'C:\Users\User\vn-engine\assets\backgrounds\city_historical.png')
rng = np.random.default_rng(42)

# ────────────────────────────────────────────────────────────────────────────
# Utility: wobbly line (hand-drawn segments with pressure jitter)
# ────────────────────────────────────────────────────────────────────────────
def wobbly_line(draw, x0, y0, x1, y1, fill, base_width=2, jitter=2.5, steps=None):
    dist = ((x1-x0)**2 + (y1-y0)**2) ** 0.5
    steps = steps or max(6, int(dist / 12))
    prev = (x0, y0)
    for i in range(1, steps + 1):
        t = i / steps
        cx = x0 + t * (x1 - x0)
        cy = y0 + t * (y1 - y0)
        if 0 < i < steps:
            cx += rng.normal(0, jitter * 0.6)
            cy += rng.normal(0, jitter * 0.6)
        # Ink pressure: width varies slightly per segment
        w = max(1, base_width + int(rng.integers(-1, 2)))
        draw.line([prev, (int(cx), int(cy))], fill=fill, width=w)
        prev = (int(cx), int(cy))

def wobbly_path(pts, draw, fill, base_width=2, jitter=1.5):
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i+1]
        wobbly_line(draw, x0, y0, x1, y1, fill, base_width, jitter)

# ────────────────────────────────────────────────────────────────────────────
# Paper base — heavy grain + age stains
# ────────────────────────────────────────────────────────────────────────────
base_tone = (208, 198, 178)
img = Image.new('RGB', (W, H), base_tone)

# Multi-octave noise for paper texture
for oct_scale, oct_amp in [(0.5, 28), (0.25, 14), (0.1, 8)]:
    nh, nw = max(4, int(H * oct_scale)), max(4, int(W * oct_scale))
    n = rng.integers(0, 255, (nh, nw, 3), dtype=np.uint8)
    n_img = Image.fromarray(n).resize((W, H), Image.BILINEAR)
    arr = np.array(img).astype(np.int16)
    narr = np.array(n_img).astype(np.int16)
    arr = np.clip(arr + (narr - 127) * oct_amp // 127, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)

# Fiber direction lines
fiber = Image.new('RGB', (W, H), (0, 0, 0))
fd = ImageDraw.Draw(fiber)
for y in range(0, H, 2):
    tone = int(rng.integers(185, 218))
    fd.line([(0, y), (W, y)], fill=(tone, tone, tone), width=1)
img = Image.blend(img, fiber, 0.08)
draw = ImageDraw.Draw(img)

# Water damage patches
water_layer = Image.new('RGBA', (W, H), (0,0,0,0))
wd = ImageDraw.Draw(water_layer)
water_patches = [
    (380, 740, 200, 130, 22),
    (1560, 860, 240, 150, 18),
    (920, 440, 110, 75, 14),
    (1710, 330, 160, 110, 20),
    (130, 300, 100, 70, 12),
    (660, 90, 135, 55, 14),
    (1850, 620, 90, 60, 10),
    (420, 480, 80, 55, 10),
]
for cx, cy, rx, ry, a in water_patches:
    wd.ellipse([(cx-rx, cy-ry), (cx+rx, cy+ry)], fill=(145,125,90,a))

# Foxing (age spots)
for _ in range(65):
    x = int(rng.integers(50, W-50))
    y = int(rng.integers(50, H-50))
    r = int(rng.integers(4, 18))
    a = int(rng.integers(15, 45))
    wd.ellipse([(x-r, y-r), (x+r, y+r)], fill=(105,85,48,a))

wl_blur = water_layer.filter(ImageFilter.GaussianBlur(22))
img = Image.alpha_composite(img.convert('RGBA'), wl_blur).convert('RGB')
draw = ImageDraw.Draw(img)

# ────────────────────────────────────────────────────────────────────────────
# Map border — double frame, uneven wobbly lines
# ────────────────────────────────────────────────────────────────────────────
ink     = (45, 38, 28)
ink_mid = (75, 65, 50)
margin  = 55
# Outer double frame (4 sides, each drawn as wobbly segments)
for x0, y0, x1, y1, c, w in [
    (margin, margin, W-margin, margin, ink, 3),
    (W-margin, margin, W-margin, H-margin, ink, 3),
    (W-margin, H-margin, margin, H-margin, ink, 3),
    (margin, H-margin, margin, margin, ink, 3),
    (margin+10, margin+10, W-margin-10, margin+10, ink_mid, 1),
    (W-margin-10, margin+10, W-margin-10, H-margin-10, ink_mid, 1),
    (W-margin-10, H-margin-10, margin+10, H-margin-10, ink_mid, 1),
    (margin+10, H-margin-10, margin+10, margin+10, ink_mid, 1),
]:
    wobbly_line(draw, x0, y0, x1, y1, c, base_width=w, jitter=2.0)

# Corner ornaments (hand-drawn cross marks)
for cx, cy in [(margin+5,margin+5),(W-margin-5,margin+5),(margin+5,H-margin-5),(W-margin-5,H-margin-5)]:
    wobbly_line(draw, cx-18, cy, cx+18, cy, ink, 2, 1)
    wobbly_line(draw, cx, cy-18, cx, cy+18, ink, 2, 1)
    draw.ellipse([(cx-3,cy-3),(cx+3,cy+3)], fill=ink)

# ────────────────────────────────────────────────────────────────────────────
# River system — brush-stroke style
# ────────────────────────────────────────────────────────────────────────────
def make_river_pts(x0, y0, x1, y1, n=180, amp=22, seed=1):
    local = np.random.default_rng(seed)
    pts = []
    for i in range(n+1):
        t = i / n
        x = x0 + t*(x1-x0)
        y = y0 + t*(y1-y0)
        # Sinusoidal meandering + individual noise
        y += np.sin(t * 4.8 * np.pi + seed) * amp * 0.6
        x += local.normal(0, amp * 0.25) * np.sin(t*np.pi)
        y += local.normal(0, amp * 0.18)
        pts.append((int(x), int(y)))
    return pts

river_pts = make_river_pts(145, 348, W-145, 392, n=220, amp=22, seed=7)

# Multi-pass brush-stroke river (different widths + opacities)
for pass_w, pass_a in [(28, 60), (20, 85), (12, 105), (6, 120), (3, 70)]:
    riv_layer = Image.new('RGBA', (W, H), (0,0,0,0))
    rd = ImageDraw.Draw(riv_layer)
    riv_col = (52, 72, 95, pass_a)
    for i in range(len(river_pts)-1):
        # Slight width variation per segment (brush pressure)
        w_var = max(1, pass_w + int(rng.integers(-2, 3)))
        rd.line([river_pts[i], river_pts[i+1]], fill=riv_col, width=w_var)
    riv_blur = riv_layer.filter(ImageFilter.GaussianBlur(max(1, pass_w//4)))
    img = Image.alpha_composite(img.convert('RGBA'), riv_blur).convert('RGB')

draw = ImageDraw.Draw(img)
# Thin highlight on river
for i in range(len(river_pts)-1):
    draw.line([river_pts[i], river_pts[i+1]], fill=(145,165,175), width=1)

# Secondary channels
channel_defs = [
    (make_river_pts(618, 348, 575, 75, n=60, amp=9, seed=2), 7, 72),
    (make_river_pts(815, 368, 828, 665, n=75, amp=10, seed=3), 7, 72),
    (make_river_pts(1015, 382, 1078, 728, n=85, amp=9, seed=4), 6, 68),
    (make_river_pts(1405, 388, 1452, 685, n=68, amp=8, seed=5), 6, 68),
    (make_river_pts(490, 358, 462, 605, n=58, amp=7, seed=6), 5, 62),
    (make_river_pts(1205, 370, 1245, 195, n=48, amp=7, seed=8), 5, 62),
]
for ch_pts, ch_w, ch_a in channel_defs:
    for i in range(len(ch_pts)-1):
        ch_lay = Image.new('RGBA', (W, H), (0,0,0,0))
        cd = ImageDraw.Draw(ch_lay)
        cd.line([ch_pts[i], ch_pts[i+1]], fill=(55,78,100,ch_a), width=ch_w)
        img = Image.alpha_composite(img.convert('RGBA'),
              ch_lay.filter(ImageFilter.GaussianBlur(1))).convert('RGB')
draw = ImageDraw.Draw(img)
for ch_pts, _, _ in channel_defs:
    for i in range(len(ch_pts)-1):
        draw.line([ch_pts[i], ch_pts[i+1]], fill=(145,160,170), width=1)

# ────────────────────────────────────────────────────────────────────────────
# Street grid — wobbly, uneven, varying width
# ────────────────────────────────────────────────────────────────────────────
ink_st  = (65, 55, 42)
ink_mn  = (100, 88, 70)
ink_al  = (138, 125, 108)

# N-S arteries (spaced ~110px, each slightly off-vertical)
for xi, x in enumerate(range(200, 1750, 112)):
    jx = int(rng.integers(-8, 8))
    jx2 = int(rng.integers(-8, 8))
    wobbly_line(draw, x+jx, margin+12, x+jx2, H-margin-12, ink_st, base_width=2, jitter=2)

# E-W streets above river (~42px spacing)
for y in range(margin+14, 340, 44):
    jy = int(rng.integers(-4, 4))
    wobbly_line(draw, margin+12, y+jy, W-margin-12, y+jy, ink_st, base_width=2, jitter=1.5)

# E-W streets below river
for y in range(415, H-margin-14, 46):
    jy = int(rng.integers(-4, 4))
    wobbly_line(draw, margin+12, y+jy, W-margin-12, y+jy, ink_st, base_width=2, jitter=1.5)

# Minor alleys N-S (lighter, narrower)
for x in enumerate(range(256, 1710, 112)):
    _, x = x
    jx = int(rng.integers(-5, 5))
    wobbly_line(draw, x+jx, margin+14, x+jx, H-margin-14, ink_mn, base_width=1, jitter=1.5)

# Minor alleys E-W above
for y in range(margin+36, 340, 44):
    jy = int(rng.integers(-3, 3))
    wobbly_line(draw, margin+14, y+jy, W-margin-14, y+jy, ink_al, base_width=1, jitter=1)

# Minor alleys E-W below
for y in range(460, H-margin-14, 46):
    jy = int(rng.integers(-3, 3))
    wobbly_line(draw, margin+14, y+jy, W-margin-14, y+jy, ink_al, base_width=1, jitter=1)

# ────────────────────────────────────────────────────────────────────────────
# Building hatching — irregular cross-hatch inside blocks
# ────────────────────────────────────────────────────────────────────────────
hatch_layer = Image.new('RGBA', (W, H), (0,0,0,0))
hd = ImageDraw.Draw(hatch_layer)

def hatch_block(x0, y0, x1, y1, density=10, opacity=28, angle_deg=45):
    ang = np.radians(angle_deg)
    ca, sa = np.cos(ang), np.sin(ang)
    diag = int(((x1-x0)**2 + (y1-y0)**2)**0.5)
    for d in range(-diag, diag*2, density):
        # Line in rotated coords clipped to block
        ax = x0 + d * ca - diag * sa
        ay = y0 + d * sa + diag * ca
        bx = ax + diag * 2 * sa
        by = ay - diag * 2 * ca
        hd.line([(int(ax), int(ay)), (int(bx), int(by))],
                fill=(38,30,22,opacity), width=1)

blocks = [
    (202,147,310,212), (312,147,422,212), (424,147,532,212),
    (644,147,752,212), (754,147,862,212), (974,147,1082,212),
    (1194,147,1302,212), (1414,147,1522,212), (1524,147,1634,212),
    (202,252,310,308), (534,252,642,308), (864,252,972,308),
    (1084,252,1192,308), (1304,252,1412,308), (1636,252,1744,308),
    (202,432,310,490), (424,432,532,490), (644,432,752,490),
    (864,432,972,490), (1084,432,1192,490), (1304,432,1412,490),
    (202,548,310,604), (314,548,422,604), (754,548,862,604),
    (1194,548,1302,604), (1524,548,1634,604), (1636,548,1744,604),
    (202,660,310,716), (534,660,642,716), (974,660,1082,716),
    (1414,660,1522,716), (202,774,310,830), (754,774,862,830),
    (1084,774,1192,830), (1304,774,1412,830), (1636,774,1744,830),
    (202,886,310,942), (424,886,532,942), (864,886,972,942),
    (1194,886,1302,942), (1524,886,1634,942),
]
for bi, b in enumerate(blocks):
    # Alternate hatch angle per block for variety
    angle = 42 + (bi % 3) * 15 + rng.integers(-5, 5)
    hatch_block(*b, density=10 + int(rng.integers(0, 4)), opacity=25, angle_deg=int(angle))

img = Image.alpha_composite(img.convert('RGBA'), hatch_layer).convert('RGB')
draw = ImageDraw.Draw(img)

# ────────────────────────────────────────────────────────────────────────────
# Landmark symbols — wobbly hand-drawn
# ────────────────────────────────────────────────────────────────────────────
def temple_symbol(draw, cx, cy, r=14):
    pts_t = [(cx, cy-r), (cx-r, cy), (cx+r, cy)]
    wobbly_path(pts_t + [pts_t[0]], draw, ink, base_width=2, jitter=1.5)
    wobbly_line(draw, cx-r+4, cy, cx+r-4, cy+r, ink, 2, 1.5)
    wobbly_line(draw, cx+r-4, cy, cx-r+4, cy+r, ink, 2, 1.5)
    wobbly_line(draw, cx-r+4, cy, cx+r-4, cy+r, ink, 2, 1.5)

def settle_symbol(draw, cx, cy, r=11):
    corners = [(cx-r,cy-r),(cx+r,cy-r),(cx+r,cy+r),(cx-r,cy+r),(cx-r,cy-r)]
    wobbly_path(corners, draw, ink, base_width=2, jitter=1.5)
    # Cross inside
    wobbly_line(draw, cx-r, cy-r, cx+r, cy+r, ink, 1, 1.2)
    wobbly_line(draw, cx+r, cy-r, cx-r, cy+r, ink, 1, 1.2)

temple_symbol(draw, 968, 508)
temple_symbol(draw, 1198, 255)
temple_symbol(draw, 452, 695)
temple_symbol(draw, 1652, 762)
settle_symbol(draw, 730, 605)
settle_symbol(draw, 462, 205)
settle_symbol(draw, 1362, 558)
settle_symbol(draw, 892, 828)

# ────────────────────────────────────────────────────────────────────────────
# Text labels — ink-bleed effect (draw on separate layer, blur, composite)
# ────────────────────────────────────────────────────────────────────────────
try:
    # Use KaiTi or SimSun — traditional Chinese serif feels more like brush
    for fname in ['kaiu.ttf', 'KAIU.TTF', 'mingliu.ttc', 'simsun.ttc']:
        try:
            font_ti = ImageFont.truetype(f'C:/Windows/Fonts/{fname}', 34)
            font_lg = ImageFont.truetype(f'C:/Windows/Fonts/{fname}', 25)
            font_md = ImageFont.truetype(f'C:/Windows/Fonts/{fname}', 19)
            font_sm = ImageFont.truetype(f'C:/Windows/Fonts/{fname}', 15)
            font_xs = ImageFont.truetype(f'C:/Windows/Fonts/{fname}', 13)
            break
        except Exception:
            continue
except Exception:
    font_ti = font_lg = font_md = font_sm = font_xs = ImageFont.load_default()

def ink_text(img, x, y, text, font, color=(32,25,15), bleed=1.4, jitter_px=1):
    """Draw text with ink-bleed: render on separate layer, blur, then composite."""
    txt_layer = Image.new('RGBA', (W, H), (0,0,0,0))
    td = ImageDraw.Draw(txt_layer)
    # Slight position jitter
    jx = rng.integers(-jitter_px, jitter_px+1)
    jy = rng.integers(-jitter_px, jitter_px+1)
    td.text((x + jx, y + jy), text, font=font,
            fill=(color[0], color[1], color[2], 240))
    # Ink bleed: blur the text slightly
    blurred = txt_layer.filter(ImageFilter.GaussianBlur(radius=bleed))
    # Composite: blend slightly lighter version (halo) + sharp original
    img_rgba = img.convert('RGBA')
    img_rgba = Image.alpha_composite(img_rgba, blurred)
    # Sharp overprint
    sharp = txt_layer.filter(ImageFilter.GaussianBlur(radius=0.3))
    img_rgba = Image.alpha_composite(img_rgba, sharp)
    return img_rgba.convert('RGB')

ink_col  = (25, 18, 10)
dim_col  = (68, 55, 38)

img = ink_text(img, 740, 74,  '翰溪庄水路圖', font_ti, ink_col, bleed=1.8)
img = ink_text(img, 905, 118, '乾隆十八年　繪', font_sm, dim_col, bleed=1.2)
img = ink_text(img, 898, 356, '翰溪', font_md, ink_col, bleed=1.5)
img = ink_text(img, 685, 628, '翰溪庄', font_lg, ink_col, bleed=1.6)
img = ink_text(img, 928, 535, '福德祠', font_md, dim_col, bleed=1.4)
img = ink_text(img, 1155, 278, '水仙宮', font_md, dim_col, bleed=1.4)
img = ink_text(img, 418, 718, '三角庄', font_md, dim_col, bleed=1.4)
img = ink_text(img, 548, 228, '頂庄', font_sm, dim_col, bleed=1.2)
img = ink_text(img, 1318, 580, '東庄', font_sm, dim_col, bleed=1.2)
img = ink_text(img, 1608, 788, '下庄', font_sm, dim_col, bleed=1.2)
img = ink_text(img, 848, 855, '舊市場', font_sm, dim_col, bleed=1.2)
# Scattered annotations — slightly slanted
annots = [
    (200, 175, '水深三尺'), (1108, 722, '舊渡口'),
    (302, 478, '農田水利'), (1512, 668, '廢渠跡'),
    (640, 248, '此段已淤'), (872, 668, '支渠引灌'),
    (1615, 310, '地勢低窪'), (158, 472, '水圳'),
    (1762, 458, '旱田'), (492, 845, '舊址'),
    (1102, 162, '大道'),
]
for ax, ay, atext in annots:
    img = ink_text(img, ax, ay, atext, font_xs, (80,65,45), bleed=0.9, jitter_px=2)

draw = ImageDraw.Draw(img)

# Legend box (wobbly border)
lx0, ly0, lx1, ly1 = 1478, 182, 1710, 278
for bpts in [
    [(lx0,ly0),(lx1,ly0),(lx1,ly1),(lx0,ly1),(lx0,ly0)],
]:
    wobbly_path(bpts, draw, dim_col, base_width=1, jitter=1.5)
img = ink_text(img, 1490, 192, '□ 庄社', font_sm, dim_col, bleed=1.0)
img = ink_text(img, 1490, 218, '▲ 廟祠', font_sm, dim_col, bleed=1.0)
img = ink_text(img, 1490, 244, '～ 水路', font_sm, dim_col, bleed=1.0)

# Compass — hand-drawn
draw = ImageDraw.Draw(img)
wobbly_line(draw, 1722, 140, 1722, 228, ink_col, 2, 1)
wobbly_line(draw, 1682, 184, 1762, 184, ink_col, 2, 1)
# Arrow head (wobbly polygon)
wobbly_path([(1722,140),(1714,164),(1730,164),(1722,140)], draw, ink_col, 2, 1)
img = ink_text(img, 1716, 118, '北', font_sm, ink_col, bleed=1.2)
img = ink_text(img, 1716, 230, '南', font_xs, dim_col, bleed=1.0)
img = ink_text(img, 1764, 179, '東', font_xs, dim_col, bleed=1.0)
img = ink_text(img, 1670, 179, '西', font_xs, dim_col, bleed=1.0)

# Scale bar
draw = ImageDraw.Draw(img)
wobbly_line(draw, 1480, 292, 1706, 292, dim_col, 2, 1)
wobbly_line(draw, 1480, 286, 1480, 300, dim_col, 2, 1)
wobbly_line(draw, 1706, 286, 1706, 300, dim_col, 2, 1)
img = ink_text(img, 1570, 296, '一里', font_xs, dim_col, bleed=0.9)

# ────────────────────────────────────────────────────────────────────────────
# Global turbulence displacement — makes everything feel hand-drawn
# ────────────────────────────────────────────────────────────────────────────
arr = np.array(img).astype(np.float32)
# Generate smooth displacement field via low-res noise upscaled
dfield_h, dfield_w = H // 20, W // 20
dx_field = rng.normal(0, 2.2, (dfield_h, dfield_w))
dy_field = rng.normal(0, 2.2, (dfield_h, dfield_w))
dx_img = np.array(Image.fromarray(dx_field.astype(np.float32)).resize((W, H), Image.BICUBIC))
dy_img = np.array(Image.fromarray(dy_field.astype(np.float32)).resize((W, H), Image.BICUBIC))

# Remap pixels
ys, xs = np.indices((H, W))
xs_d = np.clip(xs + dx_img, 0, W-1).astype(np.int32)
ys_d = np.clip(ys + dy_img, 0, H-1).astype(np.int32)
arr_d = arr[ys_d, xs_d]
img = Image.fromarray(arr_d.astype(np.uint8))

# ────────────────────────────────────────────────────────────────────────────
# Vignette + final adjustments
# ────────────────────────────────────────────────────────────────────────────
vig = Image.new('RGBA', (W, H), (0,0,0,0))
vd = ImageDraw.Draw(vig)
for ring in range(0, 130, 4):
    a = int((ring / 130) * 100)
    vd.rectangle([ring, ring, W-ring, H-ring], outline=(0,0,0,a), width=4)
img = Image.alpha_composite(img.convert('RGBA'),
      vig.filter(ImageFilter.GaussianBlur(32))).convert('RGB')

# Final grayscale + contrast
from PIL import ImageOps
img = ImageOps.grayscale(img).convert('RGB')
img = ImageEnhance.Contrast(img).enhance(1.15)
img = ImageEnhance.Brightness(img).enhance(1.02)
# Very slight final blur to unify everything (real paper absorbs ink)
img = img.filter(ImageFilter.GaussianBlur(0.4))

OUT.parent.mkdir(parents=True, exist_ok=True)
img.save(OUT, 'PNG', optimize=True)
print(f'Done: {OUT}  ({W}x{H} hand-drawn grayscale map)')
