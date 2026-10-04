"""projects/{날짜_주제}/ 폴더와 단계별 진행 상태 관리.

각 단계 결과물을 파일로 남기므로, 프로그램을 껐다 켜도 중간부터 다시 진행할 수 있습니다.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from .config import PROJECTS_DIR

STAGES = ["research", "script", "tts", "assets", "subtitles", "render"]
STAGE_LABELS = {
    "research": "1. 리서치", "script": "2. 대본", "tts": "3. 내레이션",
    "assets": "4. 소재", "subtitles": "5. 자막", "render": "6. 렌더링",
}


def slugify(text: str, max_len: int = 30) -> str:
    text = re.sub(r'[\\/:*?"<>|\s]+', "_", text.strip())
    text = re.sub(r"_+", "_", text).strip("_.")
    return text[:max_len] or "untitled"


def _read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


class Project:
    def __init__(self, path: Path):
        self.path = Path(path)
        for sub in ("audio", "media", "output"):
            (self.path / sub).mkdir(parents=True, exist_ok=True)

    # ---------- 생성 / 목록 ----------
    @classmethod
    def create(cls, topic: str, base_dir: Path = PROJECTS_DIR, date: str | None = None) -> "Project":
        date = date or datetime.now().strftime("%Y-%m-%d")
        name = f"{date}_{slugify(topic)}"
        path = base_dir / name
        n = 2
        while path.exists():
            path = base_dir / f"{name}_{n}"
            n += 1
        proj = cls(path)
        proj.save_state({"topic": topic, "created": datetime.now().isoformat(timespec="seconds"),
                         "stages": {}, "status": "new", "settings": {}})
        return proj

    @classmethod
    def list_all(cls, base_dir: Path = PROJECTS_DIR) -> list["Project"]:
        if not base_dir.exists():
            return []
        dirs = [p for p in base_dir.iterdir() if p.is_dir() and (p / "state.json").exists()]
        return [cls(p) for p in sorted(dirs, reverse=True)]

    @property
    def name(self) -> str:
        return self.path.name

    # ---------- 경로 ----------
    research_csv = property(lambda self: self.path / "research.csv")
    script_path = property(lambda self: self.path / "script.json")
    scenes_path = property(lambda self: self.path / "scenes.json")
    credits_path = property(lambda self: self.path / "credits.txt")
    srt_path = property(lambda self: self.path / "subtitles.srt")
    audio_dir = property(lambda self: self.path / "audio")
    media_dir = property(lambda self: self.path / "media")
    output_dir = property(lambda self: self.path / "output")
    final_video = property(lambda self: self.path / "output" / "final_16x9.mp4")
    shorts_video = property(lambda self: self.path / "output" / "shorts_9x16.mp4")

    # ---------- 상태 ----------
    def load_state(self) -> dict:
        return _read_json(self.path / "state.json", {"stages": {}, "settings": {}})

    def save_state(self, state: dict) -> None:
        _write_json(self.path / "state.json", state)

    @property
    def topic(self) -> str:
        return self.load_state().get("topic", self.name)

    def is_done(self, stage: str) -> bool:
        return bool(self.load_state().get("stages", {}).get(stage, {}).get("done"))

    def mark_done(self, stage: str, **info) -> None:
        state = self.load_state()
        state.setdefault("stages", {})[stage] = {
            "done": True, "at": datetime.now().isoformat(timespec="seconds"), **info}
        self.save_state(state)

    def invalidate_from(self, stage: str) -> None:
        """앞 단계를 다시 하면 그 뒤 단계들은 '다시 해야 함'으로 표시합니다."""
        state = self.load_state()
        idx = STAGES.index(stage)
        for s in STAGES[idx:]:
            state.get("stages", {}).pop(s, None)
        self.save_state(state)

    def set_status(self, status: str) -> None:
        state = self.load_state()
        state["status"] = status
        self.save_state(state)

    def get_settings(self) -> dict:
        return self.load_state().get("settings", {})

    def update_settings(self, **values) -> None:
        state = self.load_state()
        state.setdefault("settings", {}).update(values)
        self.save_state(state)

    def next_stage(self) -> str | None:
        for s in STAGES[1:]:
            if not self.is_done(s):
                return s
        return None

    # ---------- 데이터 ----------
    def load_script(self) -> dict | None:
        return _read_json(self.script_path, None)

    def save_script(self, script: dict) -> None:
        _write_json(self.script_path, script)

    def load_scenes(self) -> dict | None:
        """scenes.json: 대본 + 단계별로 추가된 정보(음성 길이, 소재, 자막 타이밍)."""
        return _read_json(self.scenes_path, None)

    def save_scenes(self, data: dict) -> None:
        _write_json(self.scenes_path, data)
