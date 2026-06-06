"""
pack_demo.py — 打包 VN 遊戲成可部署的 dist/ 目錄

用法:
  python pack_demo.py         # 產生 dist/
  python pack_demo.py --zip   # 額外產生 vn-demo.zip（itch.io 用）

部署選項:
  Netlify Drop  → 拖 dist/ 到 https://app.netlify.com/drop
  itch.io       → 上傳 vn-demo.zip（Kind: HTML, check "play in browser"）
  GitHub Pages  → 用 .github/workflows/pages.yml（git push 後自動觸發）
"""
import shutil, sys, zipfile
from pathlib import Path

# Force UTF-8 output on Windows terminals
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).parent
DIST = ROOT / 'dist'

# Only these directories/files go into the deployable package
GAME_FILES = ['index.html', 'engine', 'assets', 'scripts']

# Skip these anywhere in the tree
SKIP_DIRS  = {'__pycache__', '.git', 'node_modules', '.venv'}
SKIP_FILES = {'.DS_Store', 'Thumbs.db'}


def copy_item(src: Path, dst: Path) -> int:
    """Recursively copy src → dst, returning count of files copied."""
    if src.name in SKIP_FILES:
        return 0
    if src.is_dir():
        if src.name in SKIP_DIRS:
            return 0
        count = 0
        for child in sorted(src.iterdir()):
            count += copy_item(child, dst / child.name)
        return count
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return 1


def main():
    make_zip = '--zip' in sys.argv

    # Clean and recreate dist/
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()

    total_files = 0
    for name in GAME_FILES:
        src = ROOT / name
        if not src.exists():
            print(f'  !!  {name} not found -- skipping')
            continue
        n = copy_item(src, DIST / name)
        total_files += n
        print(f'  OK  {name}  ({n} files)')

    total_size = sum(f.stat().st_size for f in DIST.rglob('*') if f.is_file())
    print(f'\ndist/ → {total_files} files, {total_size / 1024 / 1024:.1f} MB')

    if make_zip:
        zip_path = ROOT / 'vn-demo.zip'
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for f in sorted(DIST.rglob('*')):
                if f.is_file():
                    zf.write(f, f.relative_to(DIST))
        zip_size = zip_path.stat().st_size / 1024 / 1024
        print(f'vn-demo.zip → {zip_size:.1f} MB  ({zip_path})')

    print()
    print('─' * 48)
    print('部署選項:')
    print()
    print('  A. Netlify Drop（60 秒，不需帳號）')
    print('     拖 dist/ 到 https://app.netlify.com/drop')
    print()
    print('  B. itch.io（需帳號，最適合遊戲分享）')
    if make_zip:
        print('     上傳 vn-demo.zip → Kind: HTML → "play in browser"')
    else:
        print('     先執行 python pack_demo.py --zip 產生 vn-demo.zip')
    print()
    print('  C. GitHub Pages（需 GitHub 帳號，push 後自動部署）')
    print('     git remote add origin https://github.com/<user>/vn-engine.git')
    print('     git push -u origin main')
    print('     → repo Settings → Pages → Source: GitHub Actions')
    print('─' * 48)


if __name__ == '__main__':
    main()
