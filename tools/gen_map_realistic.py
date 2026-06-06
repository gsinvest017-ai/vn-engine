"""
gen_map_realistic.py
Generate a photorealistic grayscale historical map PNG for city_historical.
Output: assets/backgrounds/city_historical.png (1920x1080)

Style: Qing-dynasty hand-survey map, ink on fibrous paper
  - Aged paper base with stains and water damage
  - Dense street/block grid with building hatching
  - Waterway system with shaded riverbanks
  - Temple and landmark symbols
  - Calligraphic labels
  - Full grayscale — matches character B&W style
"""
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

W, H = 1920, 1080
OUT = Path(r'C:\Users\User\vn-engine\assets\backgrounds\city_historical.png')

rng = np.random.default_rng(42)

# ── Canvas ────────────────────────────────────────────────────────────────────
img = Image.new('RGB', (W, H), (210, 202, 185))
draw = ImageDraw.Draw(img)

# ── Paper base texture (layered noise) ────────────────────────────────────────
noise = rng.integers(0, 22, (H, W, 3), dtype=np.uint8)
base_arr = np.array(img).astype(np.int16)
base_arr = np.clip(base_arr + noise - 11, 0, 255).astype(np.uint8)
img = Image.fromarray(base_arr)
draw = ImageDraw.Draw(img)

# Paper fiber lines (horizontal, low opacity)
fiber_overlay = Image.new('RGB', (W, H), (0, 0, 0))
fd = ImageDraw.Draw(fiber_overlay)
for y in range(0, H, 3):
    tone = rng.integers(190, 215)
    offset = int(rng.normal(0, 1.2))
    fd.line([(0, y + offset), (W, y + offset)], fill=(tone, tone, tone), width=1)
img = Image.blend(img, fiber_overlay, 0.06)
draw = ImageDraw.Draw(img)

# ── Water damage + age stains ─────────────────────────────────────────────────
stain_img = Image.new('RGBA', (W, H), (0, 0, 0, 0))
sd = ImageDraw.Draw(stain_img)
stains = [
    # (cx, cy, rx, ry, intensity)
    (340, 720, 180, 120, 18),
    (1540, 840, 220, 140, 14),
    (890, 420, 100, 70, 12),
    (1680, 320, 140, 100, 16),
    (120, 280, 90, 65, 10),
    (1820, 600, 80, 55, 8),
    (620, 90, 120, 50, 12),
]
for cx, cy, rx, ry, alpha in stains:
    sd.ellipse([(cx - rx, cy - ry), (cx + rx, cy + ry)],
               fill=(148, 128, 95, alpha))
# Foxing spots
for _ in range(45):
    x = int(rng.integers(60, W - 60))
    y = int(rng.integers(60, H - 60))
    r = int(rng.integers(3, 14))
    a = int(rng.integers(12, 35))
    sd.ellipse([(x - r, y - r), (x + r, y + r)], fill=(110, 90, 55, a))

stain_blur = stain_img.filter(ImageFilter.GaussianBlur(radius=18))
img = Image.alpha_composite(img.convert('RGBA'), stain_blur).convert('RGB')
draw = ImageDraw.Draw(img)

# ── Map border (double frame) ─────────────────────────────────────────────────
ink = (55, 48, 38)
mid = (90, 80, 60)
draw.rectangle([52, 52, W - 52, H - 52], outline=ink, width=4)
draw.rectangle([60, 60, W - 60, H - 60], outline=mid, width=2)
draw.rectangle([44, 44, W - 44, H - 44], outline=(110, 100, 75), width=1)
# Corner ornaments
for cx, cy in [(60, 60), (W - 60, 60), (60, H - 60), (W - 60, H - 60)]:
    draw.line([(cx - 20, cy), (cx + 20, cy)], fill=ink, width=2)
    draw.line([(cx, cy - 20), (cx, cy + 20)], fill=ink, width=2)

# ── Main waterway: 翰溪 (horizontal river) ────────────────────────────────────
def wavy_path(x0, y0, x1, y1, steps=160, amplitude=12, seed=0):
    local = np.random.default_rng(seed)
    pts = []
    for i in range(steps + 1):
        t = i / steps
        x = x0 + t * (x1 - x0)
        y = y0 + t * (y1 - y0) + local.normal(0, amplitude) * np.sin(t * np.pi)
        pts.append((int(x), int(y)))
    return pts

river_pts = wavy_path(140, 345, W - 140, 385, steps=200, amplitude=18, seed=1)
# River body fill (multi-pass for realistic width)
for width, alpha_val in [(24, 80), (18, 110), (10, 140), (5, 90)]:
    riv_layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    rd = ImageDraw.Draw(riv_layer)
    rd.line(river_pts, fill=(68, 90, 110, alpha_val), width=width)
    img = Image.alpha_composite(img.convert('RGBA'), riv_layer.filter(ImageFilter.GaussianBlur(2))).convert('RGB')
draw = ImageDraw.Draw(img)
draw.line(river_pts, fill=(105, 128, 148), width=2)

# ── Secondary channels ────────────────────────────────────────────────────────
def draw_channel(pts, w=6, a=70):
    ch = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    cd = ImageDraw.Draw(ch)
    cd.line(pts, fill=(68, 90, 110, a), width=w)
    return Image.alpha_composite(img.convert('RGBA'), ch.filter(ImageFilter.GaussianBlur(1))).convert('RGB')

channels = [
    wavy_path(620, 345, 580, 80,  steps=60, amplitude=8, seed=2),
    wavy_path(820, 370, 830, 660, steps=80, amplitude=9, seed=3),
    wavy_path(1010, 380, 1080, 720, steps=90, amplitude=8, seed=4),
    wavy_path(1400, 390, 1450, 680, steps=70, amplitude=7, seed=5),
    wavy_path(480, 355, 450, 600, steps=60, amplitude=6, seed=6),
    wavy_path(1200, 368, 1240, 200, steps=50, amplitude=6, seed=7),
]
for ch_pts in channels:
    img = draw_channel(ch_pts, w=7, a=75)
draw = ImageDraw.Draw(img)
# Thin labels on main river
for pts in channels:
    # Draw thin highlight line
    draw.line(pts, fill=(145, 165, 175), width=1)

# ── City grid — street blocks ─────────────────────────────────────────────────
# Main grid zone: 200-1720 x: 140-700 y (above river) + 420-960 y (below)
street_c = (60, 52, 42)
minor_c  = (100, 88, 72)
alley_c  = (140, 128, 108)

# Major N-S arteries (lighter, hand-drawn feel)
for x in range(200, 1750, 110):
    jitter = int(rng.integers(-6, 6))
    draw.line([(x + jitter, 140), (x + jitter, H - 140)], fill=(88, 78, 62), width=2)
# Major E-W streets (above river)
for y in range(145, 345, 42):
    jitter = int(rng.integers(-3, 3))
    draw.line([(145, y + jitter), (W - 145, y + jitter)], fill=(88, 78, 62), width=2)
# Major E-W streets (below river)
for y in range(415, H - 145, 45):
    jitter = int(rng.integers(-3, 3))
    draw.line([(145, y + jitter), (W - 145, y + jitter)], fill=(88, 78, 62), width=2)

# Minor alleys (subdivide blocks — very light)
for x in range(255, 1700, 110):
    jitter = int(rng.integers(-4, 4))
    draw.line([(x + jitter, 145), (x + jitter, H - 145)], fill=(130, 118, 100), width=1)
for y in range(162, 345, 42):
    jitter = int(rng.integers(-2, 2))
    draw.line([(145, y + jitter), (W - 145, y + jitter)], fill=(148, 135, 115), width=1)
for y in range(460, H - 145, 45):
    jitter = int(rng.integers(-2, 2))
    draw.line([(145, y + jitter), (W - 145, y + jitter)], fill=(148, 135, 115), width=1)

# ── Building hatching in blocks ───────────────────────────────────────────────
hatch_layer = Image.new('RGBA', (W, H), (0, 0, 0, 0))
hd = ImageDraw.Draw(hatch_layer)

def hatch_block(x0, y0, x1, y1, density=8, opacity=35):
    for ox in range(0, (x1 - x0) + (y1 - y0), density):
        hd.line([(max(x0, x0 + ox - (y1 - y0)), min(y1, y0 + ox)),
                 (min(x1, x0 + ox), max(y0, y1 - ((x1 - x0) - (ox - (y1 - y0))))  )],
                fill=(42, 35, 28, opacity), width=1)

# Sample building blocks in a few cells
block_cells = [
    (200, 145, 310, 210), (310, 145, 420, 210), (420, 145, 530, 210),
    (640, 145, 750, 210), (750, 145, 860, 210), (970, 145, 1080, 210),
    (1190, 145, 1300, 210), (1410, 145, 1520, 210), (1520, 145, 1630, 210),
    (200, 250, 310, 305), (530, 250, 640, 305), (860, 250, 970, 305),
    (1080, 250, 1190, 305), (1300, 250, 1410, 305), (1630, 250, 1740, 305),
    (200, 430, 310, 488), (420, 430, 530, 488), (640, 430, 750, 488),
    (860, 430, 970, 488), (1080, 430, 1190, 488), (1300, 430, 1410, 488),
    (200, 545, 310, 600), (310, 545, 420, 600), (750, 545, 860, 600),
    (1190, 545, 1300, 600), (1520, 545, 1630, 600), (1630, 545, 1740, 600),
    (200, 658, 310, 713), (530, 658, 640, 713), (970, 658, 1080, 713),
    (1410, 658, 1520, 713), (200, 770, 310, 825), (750, 770, 860, 825),
    (1080, 770, 1190, 825), (1300, 770, 1410, 825), (1630, 770, 1740, 825),
    (200, 883, 310, 938), (420, 883, 530, 938), (860, 883, 970, 938),
    (1190, 883, 1300, 938), (1520, 883, 1630, 938),
]
for cell in block_cells:
    hatch_block(*cell, density=9, opacity=30)

img = Image.alpha_composite(img.convert('RGBA'), hatch_layer).convert('RGB')
draw = ImageDraw.Draw(img)

# ── Landmark symbols ──────────────────────────────────────────────────────────
def temple_symbol(draw, cx, cy, r=14):
    # Triangle roof + rectangle body
    draw.polygon([(cx, cy - r), (cx - r, cy), (cx + r, cy)], fill=(50, 42, 30), outline=None)
    draw.rectangle([(cx - r + 3, cy), (cx + r - 3, cy + r)], fill=(50, 42, 30), outline=None)

def settle_symbol(draw, cx, cy, r=12):
    draw.rectangle([(cx - r, cy - r), (cx + r, cy + r)], outline=(50, 42, 30), width=2)
    draw.line([(cx - r, cy - r), (cx + r, cy + r)], fill=(50, 42, 30), width=1)
    draw.line([(cx + r, cy - r), (cx - r, cy + r)], fill=(50, 42, 30), width=1)

# Temples
temple_symbol(draw, 968, 500)
temple_symbol(draw, 1198, 248)
temple_symbol(draw, 448, 688)
temple_symbol(draw, 1648, 758)
# Settlements
settle_symbol(draw, 728, 600)
settle_symbol(draw, 458, 200)
settle_symbol(draw, 1358, 550)
settle_symbol(draw, 888, 820)

# ── Text labels (Chinese serif) ───────────────────────────────────────────────
try:
    font_lg  = ImageFont.truetype("C:/Windows/Fonts/simsun.ttc",  28)
    font_md  = ImageFont.truetype("C:/Windows/Fonts/simsun.ttc",  20)
    font_sm  = ImageFont.truetype("C:/Windows/Fonts/simsun.ttc",  16)
    font_xs  = ImageFont.truetype("C:/Windows/Fonts/simsun.ttc",  14)
    font_ti  = ImageFont.truetype("C:/Windows/Fonts/simsun.ttc",  32)
except Exception:
    font_lg = font_md = font_sm = font_xs = font_ti = ImageFont.load_default()

ink_text = (32, 26, 18)
dim_text = (75, 65, 50)

# Map title
draw.text((760, 78),  '翰溪庄水路圖', font=font_ti, fill=ink_text)
draw.text((920, 118), '乾隆十八年　繪', font=font_sm, fill=dim_text)

# River label
draw.text((900, 360), '翰溪', font=font_md, fill=ink_text)

# Settlements + temples
draw.text((688, 625), '翰溪庄', font=font_lg, fill=ink_text)
draw.text((928, 530), '福德祠', font=font_md, fill=dim_text)
draw.text((1158, 275), '水仙宮', font=font_md, fill=dim_text)
draw.text((420, 715), '三角庄', font=font_md, fill=dim_text)
draw.text((548, 225), '頂庄',   font=font_sm, fill=dim_text)
draw.text((1318, 578), '東庄',  font=font_sm, fill=dim_text)
draw.text((1608, 785), '下庄',  font=font_sm, fill=dim_text)
draw.text((848, 850),  '舊市場', font=font_sm, fill=dim_text)

# Annotations (scattered handwriting)
annotations = [
    (198, 175, '水深三尺'),
    (1108, 720, '舊渡口'),
    (300, 475, '農田水利'),
    (1510, 665, '廢渠跡'),
    (638, 245, '此段已淤'),
    (870, 665, '支渠引灌'),
    (1612, 308, '地勢低窪'),
    (155, 468, '水圳'),
    (1760, 455, '旱田'),
    (490, 840, '舊址'),
    (1100, 160, '大道'),
]
for ax, ay, atext in annotations:
    draw.text((ax, ay), atext, font=font_xs, fill=(88, 75, 55))

# Legend box
draw.rectangle([1478, 185, 1700, 275], outline=dim_text, width=1)
draw.text((1488, 195), '□ 庄社', font=font_sm, fill=dim_text)
draw.text((1488, 220), '▲ 廟祠', font=font_sm, fill=dim_text)
draw.text((1488, 245), '～ 水路', font=font_sm, fill=dim_text)

# Compass
draw.line([(1720, 145), (1720, 225)], fill=ink_text, width=2)
draw.line([(1680, 185), (1760, 185)], fill=ink_text, width=2)
draw.polygon([(1720, 145), (1713, 165), (1727, 165)], fill=ink_text)
draw.text((1715, 122), '北', font=font_sm, fill=ink_text)
draw.text((1715, 228), '南', font=font_xs, fill=dim_text)
draw.text((1762, 180), '東', font=font_xs, fill=dim_text)
draw.text((1668, 180), '西', font=font_xs, fill=dim_text)

# Scale bar
draw.line([(1478, 295), (1698, 295)], fill=dim_text, width=2)
draw.line([(1478, 288), (1478, 302)], fill=dim_text, width=2)
draw.line([(1698, 288), (1698, 302)], fill=dim_text, width=2)
draw.text((1568, 300), '一里', font=font_xs, fill=dim_text)

# ── Vignette edge darkening ───────────────────────────────────────────────────
vig = Image.new('RGBA', (W, H), (0, 0, 0, 0))
vd = ImageDraw.Draw(vig)
for ring in range(0, 120, 4):
    a = int((ring / 120) * 90)
    vd.rectangle([ring, ring, W - ring, H - ring], outline=(0, 0, 0, a), width=4)
vig_blur = vig.filter(ImageFilter.GaussianBlur(radius=28))
img = Image.alpha_composite(img.convert('RGBA'), vig_blur).convert('RGB')

# ── Final grayscale conversion ────────────────────────────────────────────────
from PIL import ImageOps
img = ImageOps.grayscale(img).convert('RGB')
# Boost contrast slightly for map legibility
img = ImageEnhance.Contrast(img).enhance(1.18)
img = ImageEnhance.Brightness(img).enhance(0.96)

# ── Save ──────────────────────────────────────────────────────────────────────
OUT.parent.mkdir(parents=True, exist_ok=True)
img.save(OUT, 'PNG', optimize=True)
print(f'Done: {OUT}  ({W}x{H} grayscale)')
