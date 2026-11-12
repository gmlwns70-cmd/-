"""연회색 수채화 종이 질감을 노이즈로 직접 만들어 assets/paper.png 로 저장합니다."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from .settings import ASSETS_DIR

W, H = 1080, 1350
BASE_GRAY = 217  # #D9D9D9


def _blur_noise(rng, scale: int, radius: float) -> np.ndarray:
    """작은 노이즈를 키우고 흐려서 부드러운 얼룩을 만듭니다. 결과 범위 약 -1~1."""
    small = rng.random((H // scale + 2, W // scale + 2)).astype(np.float32)
    img = Image.fromarray((small * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC)
    img = img.filter(ImageFilter.GaussianBlur(radius))
    a = np.asarray(img, dtype=np.float32) / 255.0
    return (a - a.mean()) / (a.std() + 1e-6)


def make_paper(seed: int = 7) -> Image.Image:
    rng = np.random.default_rng(seed)
    blotch = _blur_noise(rng, 90, 40) * 3.2      # 큰 수채 얼룩
    mid = _blur_noise(rng, 18, 6) * 1.6          # 중간 결
    grain = rng.normal(0, 1, (H, W)).astype(np.float32)
    grain_img = Image.fromarray(np.clip(grain * 40 + 128, 0, 255).astype(np.uint8))
    grain = (np.asarray(grain_img.filter(ImageFilter.GaussianBlur(0.6)), np.float32) - 128) / 40 * 2.2

    # 가는 종이 섬유(가로로 길쭉한 흐림)
    fiber = rng.normal(0, 1, (H, W)).astype(np.float32)
    fiber_img = Image.fromarray(np.clip(fiber * 40 + 128, 0, 255).astype(np.uint8))
    fiber_img = fiber_img.filter(ImageFilter.BoxBlur(1)).resize((W // 6, H), Image.BILINEAR).resize((W, H), Image.BILINEAR)
    fiber = (np.asarray(fiber_img, np.float32) - 128) / 40 * 1.3

    # 가장자리를 아주 살짝 어둡게 (비네팅)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    vignette = -np.clip(d - 0.6, 0, None) * 9

    gray = BASE_GRAY + blotch + mid + grain + fiber + vignette
    rgb = np.stack([gray - 0.6, gray, gray + 0.8], axis=-1)  # 아주 약간 차가운 회색
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")


def get_paper(path: Path = ASSETS_DIR / "paper.png") -> Image.Image:
    if path.exists():
        img = Image.open(path).convert("RGB")
        if img.size == (W, H):
            return img
    path.parent.mkdir(parents=True, exist_ok=True)
    img = make_paper()
    img.save(path, optimize=True)
    return img
