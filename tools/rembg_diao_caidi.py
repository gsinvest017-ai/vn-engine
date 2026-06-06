"""
diao_caidi.jpg rembg + grayscale + 3 expression variants
Output: assets/characters/diao_caidi/*.png (400x800 RGBA)
"""
import io, sys
from pathlib import Path
import numpy as np
from rembg import remove
from PIL import Image, ImageEnhance, ImageOps, ImageFilter

SRC = Path(r'C:\Users\User\vn-engine\tools\vrm\diao_caidi.jpg')
OUT = Path(r'C:\Users\User\vn-engine\assets\characters\diao_caidi')
OUT.mkdir(parents=True, exist_ok=True)
W, H = 400, 800

# Step 1: Remove background
print("Step 1: rembg ...")
result_bytes = remove(SRC.read_bytes())
img_rgba = Image.open(io.BytesIO(result_bytes)).convert('RGBA')
print(f"  done: {img_rgba.size}")

# Step 2: Crop to subject + fit 400x800
print("Step 2: crop + scale 400x800...")
alpha = np.array(img_rgba.split()[3])
rows_mask = np.any(alpha > 15, axis=1)
cols_mask = np.any(alpha > 15, axis=0)
r_idx = np.where(rows_mask)[0]
c_idx = np.where(cols_mask)[0]

if len(r_idx) == 0 or len(c_idx) == 0:
    print("  ERROR: no subject found after rembg")
    sys.exit(1)

pad = 30
rmin = max(0, int(r_idx[0])  - pad)
rmax = min(img_rgba.height, int(r_idx[-1]) + pad)
cmin = max(0, int(c_idx[0])  - pad)
cmax = min(img_rgba.width,  int(c_idx[-1]) + pad)

cropped = img_rgba.crop((cmin, rmin, cmax, rmax))
sw, sh = cropped.size

scale  = min(W / sw, H / sh)
nw, nh = int(sw * scale), int(sh * scale)
scaled = cropped.resize((nw, nh), Image.LANCZOS)

base = Image.new('RGBA', (W, H), (0, 0, 0, 0))
base.paste(scaled, ((W - nw) // 2, H - nh), scaled)
print(f"  scaled {sw}x{sh} -> {nw}x{nh}, bottom-centered")

# Step 3: Grayscale (match narrator B&W style)
print("Step 3: grayscale conversion...")
r, g, b, a = base.split()
rgb = Image.merge('RGB', (r, g, b))
gray_rgb = ImageOps.grayscale(rgb).convert('RGB')
base = Image.merge('RGBA', (*gray_rgb.split(), a))
print("  done: converted to B&W")

# Step 3b: Feather edges
def feather_edges(img_rgba, feather=5):
    r, g, b, a = img_rgba.split()
    a_np   = np.array(a, dtype=np.float32)
    a_blur = np.array(a.filter(ImageFilter.GaussianBlur(radius=feather)),
                      dtype=np.float32)
    boundary = (a_np > 8) & (a_np < 248)
    result   = np.where(boundary, a_blur * 0.75 + a_np * 0.25, a_np)
    result   = np.clip(result, 0, 255).astype(np.uint8)
    return Image.merge('RGBA', (r, g, b, Image.fromarray(result)))

base = feather_edges(base, feather=5)
print("  edge feathering done (5px)")

# Step 4: Expression colour grades
def grade(img, bright=1.0, contrast=1.0, tint=None, crush=0.0):
    r, g, b, a = img.split()
    rgb = Image.merge('RGB', (r, g, b))
    if bright != 1.0:
        rgb = ImageEnhance.Brightness(rgb).enhance(bright)
    if contrast != 1.0:
        rgb = ImageEnhance.Contrast(rgb).enhance(contrast)
    if tint:
        overlay = Image.new('RGB', rgb.size, tint)
        rgb = Image.blend(rgb, overlay, 0.09)
    if crush > 0:
        arr = np.array(rgb).astype(np.float32)
        arr = np.clip(arr * (1 - crush * 0.28), 0, 255).astype(np.uint8)
        rgb = Image.fromarray(arr)
    ro, go, bo = rgb.split()
    return Image.merge('RGBA', (ro, go, bo, a))

# 3 expressions for diao_caidi (young man, student/civilian)
EXPRS = {
    'normal':      dict(bright=1.00, contrast=1.00, tint=None,          crush=0.00),
    'questioning': dict(bright=0.92, contrast=1.20, tint=(140,140,170), crush=0.15),
    'shocked':     dict(bright=1.10, contrast=1.35, tint=None,          crush=0.00),
}

print("Step 4: rendering 3 expressions...")
for name, params in EXPRS.items():
    out = grade(base, **params)
    out.save(OUT / f'{name}.png', 'PNG')
    print(f"  OK {name}.png")

print(f"\nDone! Output: {OUT}")
