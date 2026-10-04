"""4단계: 장면별 영상 소재 매칭.

사용하는 소재는 딱 세 종류뿐입니다.
  1) assets/my_footage  : 직접 촬영한 영상·사진
  2) Pexels / Pixabay   : 공식 API로 받은 무료 라이선스 스톡 (credits.txt에 출처 자동 기록)
  3) assets/licensed    : 허락받은 소재 (같은 이름의 .license.txt 허락 메모가 있어야만 사용)
유튜브 등 다른 플랫폼의 영상을 내려받는 기능은 없습니다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import requests

from .config import LICENSED_DIR, MY_FOOTAGE_DIR, UserFacingError, get_key, load_config
from .project import Project

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
LICENSE_SUFFIX = ".license.txt"


@dataclass
class LocalAsset:
    path: Path
    kind: str                 # video / image
    source: str               # my / licensed
    memo: str = ""
    license_note: str = ""
    keywords: set[str] = field(default_factory=set)


def tokenize(text: str) -> set[str]:
    words = re.findall(r"[가-힣]+|[a-zA-Z]+|\d+", (text or "").lower())
    return {w for w in words if len(w) >= 2}


def _kind(path: Path) -> str | None:
    ext = path.suffix.lower()
    return "video" if ext in VIDEO_EXT else "image" if ext in IMAGE_EXT else None


def scan_local_assets(my_dir: Path = MY_FOOTAGE_DIR, licensed_dir: Path = LICENSED_DIR) -> list[LocalAsset]:
    found: list[LocalAsset] = []
    for source, folder in (("my", my_dir), ("licensed", licensed_dir)):
        if not folder.exists():
            continue
        for p in sorted(folder.rglob("*")):
            kind = _kind(p)
            if not kind:
                continue
            memo_file = p.with_suffix(".txt")
            memo = memo_file.read_text(encoding="utf-8", errors="ignore").strip() if memo_file.exists() else ""
            note = ""
            if source == "licensed":
                lic = p.with_name(p.stem + LICENSE_SUFFIX)
                if not lic.exists():
                    continue  # 허락 메모가 없으면 절대 사용하지 않음
                note = lic.read_text(encoding="utf-8", errors="ignore").strip()
                memo = (memo + " " + note).strip()
            found.append(LocalAsset(p, kind, source, memo=memo[:300], license_note=note,
                                    keywords=tokenize(p.stem.replace("_", " ").replace("-", " ") + " " + memo)))
    return found


def licensed_without_memo(licensed_dir: Path = LICENSED_DIR) -> list[Path]:
    if not licensed_dir.exists():
        return []
    return [p for p in sorted(licensed_dir.rglob("*"))
            if _kind(p) and not p.with_name(p.stem + LICENSE_SUFFIX).exists()]


def score_asset(scene: dict, asset: LocalAsset) -> float:
    kw_en = tokenize(" ".join(scene.get("visual_keywords_en", [])))
    ko = tokenize(scene.get("on_screen_text", "") + " " + scene.get("narration", ""))
    return 2.0 * len(kw_en & asset.keywords) + 1.0 * len(ko & asset.keywords)


# ---------------- 스톡 API ----------------
@dataclass
class StockItem:
    provider: str
    id: str
    kind: str          # video / image
    url: str           # 다운로드 주소
    page_url: str
    author: str
    author_url: str
    duration: float = 0.0


class PexelsClient:
    name = "pexels"

    def __init__(self, api_key: str, session=None):
        self.key, self.http = api_key, session or requests

    def _get(self, url, params):
        r = self.http.get(url, params=params, headers={"Authorization": self.key}, timeout=30)
        if r.status_code in (401, 403):
            raise UserFacingError("❌ Pexels API 키가 올바르지 않아요. .env의 PEXELS_API_KEY를 확인해 주세요.")
        if r.status_code == 429:
            raise UserFacingError("❌ Pexels 사용 한도(시간당 200회)를 넘었어요. 잠시 후 다시 시도해 주세요.")
        r.raise_for_status()
        return r.json()

    def search_videos(self, query: str, n: int = 6) -> list[StockItem]:
        data = self._get("https://api.pexels.com/videos/search",
                         {"query": query, "per_page": n, "orientation": "landscape", "size": "medium"})
        items = []
        for v in data.get("videos", []):
            files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("width")]
            if not files:
                continue
            # 1920 이하 중 가장 큰 것 (너무 큰 4K는 느림)
            files.sort(key=lambda f: (f["width"] <= 1920, f["width"]), reverse=True)
            user = v.get("user", {})
            items.append(StockItem("pexels", str(v["id"]), "video", files[0]["link"], v.get("url", ""),
                                   user.get("name", "Unknown"), user.get("url", ""), float(v.get("duration", 0))))
        return items

    def search_images(self, query: str, n: int = 4) -> list[StockItem]:
        data = self._get("https://api.pexels.com/v1/search", {"query": query, "per_page": n, "orientation": "landscape"})
        return [StockItem("pexels", str(p["id"]), "image", p["src"].get("large2x") or p["src"]["original"],
                          p.get("url", ""), p.get("photographer", "Unknown"), p.get("photographer_url", ""))
                for p in data.get("photos", [])]


class PixabayClient:
    name = "pixabay"

    def __init__(self, api_key: str, session=None):
        self.key, self.http = api_key, session or requests

    def _get(self, url, params):
        r = self.http.get(url, params={"key": self.key, "safesearch": "true", **params}, timeout=30)
        if r.status_code in (400, 401, 403) and "key" in r.text.lower():
            raise UserFacingError("❌ Pixabay API 키가 올바르지 않아요. .env의 PIXABAY_API_KEY를 확인해 주세요.")
        if r.status_code == 429:
            raise UserFacingError("❌ Pixabay 사용 한도를 넘었어요. 잠시 후 다시 시도해 주세요.")
        r.raise_for_status()
        return r.json()

    def search_videos(self, query: str, n: int = 6) -> list[StockItem]:
        data = self._get("https://pixabay.com/api/videos/", {"q": query[:100], "per_page": max(3, n)})
        items = []
        for h in data.get("hits", []):
            vids = h.get("videos", {})
            pick = vids.get("large") if vids.get("large", {}).get("url") else vids.get("medium", {})
            if not pick or not pick.get("url"):
                continue
            items.append(StockItem("pixabay", str(h["id"]), "video", pick["url"], h.get("pageURL", ""),
                                   h.get("user", "Unknown"), f"https://pixabay.com/users/{h.get('user', '')}-{h.get('user_id', '')}/",
                                   float(h.get("duration", 0))))
        return items

    def search_images(self, query: str, n: int = 4) -> list[StockItem]:
        data = self._get("https://pixabay.com/api/", {"q": query[:100], "per_page": max(3, n),
                                                     "image_type": "photo", "orientation": "horizontal"})
        return [StockItem("pixabay", str(h["id"]), "image", h.get("largeImageURL") or h["webformatURL"],
                          h.get("pageURL", ""), h.get("user", "Unknown"),
                          f"https://pixabay.com/users/{h.get('user', '')}-{h.get('user_id', '')}/")
                for h in data.get("hits", [])]


def stock_clients(cfg: dict | None = None, session=None) -> list:
    order = (cfg or load_config())["assets"]["stock_order"]
    clients = []
    for name in order:
        if name == "pexels" and get_key("PEXELS_API_KEY", required=False):
            clients.append(PexelsClient(get_key("PEXELS_API_KEY"), session))
        if name == "pixabay" and get_key("PIXABAY_API_KEY", required=False):
            clients.append(PixabayClient(get_key("PIXABAY_API_KEY"), session))
    return clients


def download(item: StockItem, media_dir: Path, session=None) -> Path:
    ext = ".mp4" if item.kind == "video" else (Path(item.url.split("?")[0]).suffix.lower() or ".jpg")
    if ext not in VIDEO_EXT | IMAGE_EXT:
        ext = ".jpg"
    out = media_dir / f"{item.provider}_{item.kind}_{item.id}{ext}"
    if out.exists() and out.stat().st_size > 0:
        return out
    http = session or requests
    tmp = out.with_suffix(out.suffix + ".part")
    with http.get(item.url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
    tmp.replace(out)
    return out


def probe_duration(path: Path) -> float:
    try:
        from moviepy import VideoFileClip
        with VideoFileClip(str(path), audio=False) as c:
            return float(c.duration or 0)
    except Exception:
        return 0.0


# ---------------- credits.txt ----------------
def credit_line(m: dict) -> str:
    if m["source"] in ("pexels", "pixabay"):
        site = "Pexels" if m["source"] == "pexels" else "Pixabay"
        what = "영상" if m["kind"] == "video" else "사진"
        return f"- {what}: {m.get('author') or 'Unknown'} ({site}) {m.get('page_url', '')}".rstrip()
    if m["source"] == "licensed":
        first = (m.get("license_note") or "").splitlines()[0] if m.get("license_note") else "허락 메모 참고"
        return f"- 사용 허락 소재: {Path(m['path']).name} / {first}"
    return ""


def write_credits(scenes: list[dict], path: Path) -> str:
    lines, seen = [], set()
    for sc in scenes:
        for m in sc.get("media", []):
            line = credit_line(m)
            if line and line not in seen:
                seen.add(line)
                lines.append(line)
    stock = [l for l in lines if "(Pexels)" in l or "(Pixabay)" in l]
    licensed = [l for l in lines if l.startswith("- 사용 허락")]
    parts = ["📌 영상 소재 출처 (Credits)"]
    if stock:
        parts += ["", "[무료 스톡 소재]", *stock, "Videos & photos provided by Pexels / Pixabay (free license)."]
    if licensed:
        parts += ["", "[사용 허락 받은 소재]", *licensed]
    if not stock and not licensed:
        parts += ["", "이 영상의 모든 소재는 직접 촬영했습니다."]
    text = "\n".join(parts) + "\n"
    path.write_text(text, encoding="utf-8")
    return text


# ---------------- 매칭 ----------------
def _local_media(asset: LocalAsset) -> dict:
    return {"path": str(asset.path), "kind": asset.kind, "source": asset.source,
            "duration": probe_duration(asset.path) if asset.kind == "video" else 0.0,
            "license_note": asset.license_note}


def _stock_media(item: StockItem, path: Path, project: Project) -> dict:
    dur = item.duration or (probe_duration(path) if item.kind == "video" else 0.0)
    return {"path": str(path.relative_to(project.path)), "kind": item.kind, "source": item.provider,
            "duration": dur, "author": item.author, "author_url": item.author_url,
            "page_url": item.page_url, "stock_id": f"{item.provider}:{item.id}"}


def media_seconds(media: list[dict], image_seconds: float) -> float:
    return sum(m["duration"] if m["kind"] == "video" else image_seconds for m in media)


def match_assets(project: Project, progress: Callable[[float, str], None] | None = None,
                 force: bool = False, use_stock: bool = True, session=None, cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    acfg = cfg["assets"]
    data = project.load_scenes()
    if not data:
        raise UserFacingError("❌ 내레이션 정보가 없어요. ③ 내레이션 단계를 먼저 실행해 주세요.")
    project.invalidate_from("assets")
    local = scan_local_assets()
    clients = stock_clients(cfg, session) if use_stock else []
    warnings: list[str] = []
    if use_stock and not clients:
        warnings.append("Pexels/Pixabay 키가 없어서 스톡 소재 검색을 건너뛰었어요. 내 소재가 없는 장면은 단색 배경으로 나옵니다.")

    used_local: dict[str, int] = {}
    used_stock: set[str] = set()
    for sc in data["scenes"]:
        for m in sc.get("media", []):
            used_stock.add(m.get("stock_id", ""))

    scenes = data["scenes"]
    for i, sc in enumerate(scenes):
        if progress:
            progress(i / len(scenes), f"장면 {sc['id']} 소재 찾는 중…")
        if sc.get("media") and not force and all(m["kind"] != "color" and resolve_path(project, m["path"]).exists()
                                                  for m in sc["media"]):
            continue
        need = float(sc.get("duration", 5)) + float(cfg["render"]["scene_padding"])
        media: list[dict] = []

        # ① 내 소재 / 허락 소재
        scored = sorted(((score_asset(sc, a) - 0.5 * used_local.get(str(a.path), 0), a) for a in local),
                        key=lambda x: x[0], reverse=True)
        threshold = 1.0 if sc.get("prefer_my_footage") else 2.0
        for score, a in scored:
            if score < threshold or len(media) >= acfg["max_clips_per_scene"]:
                break
            media.append(_local_media(a))
            used_local[str(a.path)] = used_local.get(str(a.path), 0) + 1
            if media_seconds(media, acfg["image_seconds"]) >= need:
                break

        # ② 스톡 (부족할 때만)
        queries = sc.get("visual_keywords_en") or []
        for kind in ("video", "image"):
            for client in clients:
                for q in queries:
                    if media_seconds(media, acfg["image_seconds"]) >= need or len(media) >= acfg["max_clips_per_scene"]:
                        break
                    try:
                        items = client.search_videos(q) if kind == "video" else client.search_images(q)
                    except UserFacingError:
                        raise
                    except requests.RequestException as e:
                        warnings.append(f"장면 {sc['id']}: {client.name} 검색 실패 ({e})")
                        continue
                    for item in items:
                        sid = f"{item.provider}:{item.id}"
                        if sid in used_stock:
                            continue
                        try:
                            path = download(item, project.media_dir, session)
                        except requests.RequestException as e:
                            warnings.append(f"장면 {sc['id']}: 다운로드 실패 ({e})")
                            continue
                        used_stock.add(sid)
                        media.append(_stock_media(item, path, project))
                        break  # 키워드마다 1개씩 고르게
        if not media:
            media = [{"path": "", "kind": "color", "source": "none", "duration": 0.0}]
            warnings.append(f"장면 {sc['id']}: 맞는 소재가 없어 단색 배경을 사용합니다.")
        sc["media"] = media

    project.save_scenes(data)
    write_credits(scenes, project.credits_path)
    project.mark_done("assets", warnings=warnings)
    if progress:
        progress(1.0, "소재 매칭 완료")
    return {"scenes": scenes, "warnings": warnings}


def resolve_path(project: Project, media_path: str) -> Path:
    p = Path(media_path)
    return p if p.is_absolute() else project.path / p
