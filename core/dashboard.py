"""홈 대시보드용 요약: 프로젝트마다 어디까지 했는지, 완성 영상·썸네일이 있는지."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .project import STAGE_LABELS, Project

PRODUCTION_STAGES = ["script", "tts", "assets", "subtitles", "render"]  # 리서치는 선택 단계라 진행률에서 제외


@dataclass
class ProjectSummary:
    name: str
    topic: str
    title: str
    created: datetime | None
    updated: datetime | None
    done_steps: int
    total_steps: int
    status: str          # 화면에 그대로 보여줄 상태 (아이콘 + 글자)
    next_label: str
    video_seconds: float
    final_video: Path | None
    shorts_video: Path | None
    thumbnail: Path | None

    @property
    def is_done(self) -> bool:
        return self.final_video is not None


def _parse(ts: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(ts) if ts else None
    except ValueError:
        return None


def summarize(project: Project) -> ProjectSummary:
    state = project.load_state()
    stages = state.get("stages", {})
    done = sum(1 for s in PRODUCTION_STAGES if stages.get(s, {}).get("done"))
    times = [_parse(v.get("at")) for v in stages.values() if isinstance(v, dict)]
    created = _parse(state.get("created"))
    updated = max([t for t in times if t] + ([created] if created else []), default=None)

    script = project.load_script() or {}
    scenes = (project.load_scenes() or {}).get("scenes", [])
    video_seconds = sum(float(s.get("duration") or 0) for s in scenes)

    final = project.final_video if project.final_video.exists() else None
    shorts = project.shorts_video if project.shorts_video.exists() else None
    thumbs = [project.output_dir / f"thumbnail_{k}.jpg" for k in ("left", "center", "bottom")]
    thumb = next((t for t in thumbs if t.exists()), None)

    nxt = next((s for s in PRODUCTION_STAGES if not stages.get(s, {}).get("done")), None)
    if final and nxt is None:
        status, next_label = "✅ 완성", "-"
    elif state.get("status") == "awaiting_review" and not stages.get("script", {}).get("done"):
        status, next_label = "⏸️ 대본 확인 대기", STAGE_LABELS["script"]
    elif done == 0 and not script:
        status, next_label = "🆕 시작 전", STAGE_LABELS["script"]
    else:
        status, next_label = "🔄 진행 중", STAGE_LABELS[nxt] if nxt else "-"
    return ProjectSummary(
        name=project.name, topic=state.get("topic", project.name), title=script.get("title", ""),
        created=created, updated=updated, done_steps=done, total_steps=len(PRODUCTION_STAGES),
        status=status, next_label=next_label, video_seconds=video_seconds,
        final_video=final, shorts_video=shorts, thumbnail=thumb,
    )


def overview(summaries: list[ProjectSummary], now: datetime | None = None) -> dict:
    now = now or datetime.now()
    done = [s for s in summaries if s.is_done]
    this_month = [s for s in done if s.updated and (s.updated.year, s.updated.month) == (now.year, now.month)]
    return {
        "total": len(summaries),
        "done": len(done),
        "in_progress": len(summaries) - len(done),
        "this_month": len(this_month),
        "total_minutes": sum(s.video_seconds for s in done) / 60,
        "shorts": sum(1 for s in done if s.shorts_video),
    }


def fmt_duration(seconds: float) -> str:
    if seconds <= 0:
        return "-"
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}분 {s:02d}초"
