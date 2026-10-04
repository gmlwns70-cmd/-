"""7단계: 원클릭 실행.

1부: 대본 생성 → 여기서 멈추고 사용자 확인을 기다림 (status = awaiting_review)
2부: 내레이션 → 소재 → 자막 → 렌더링 (이미 끝난 단계는 건너뜀 = 중간부터 다시 실행)
"""
from __future__ import annotations

from typing import Callable

from . import assets, render, script, subtitles, tts
from .project import Project

Progress = Callable[[float, str], None]


def run_until_review(project: Project, topic: str, minutes: float, tone: str,
                     log: Callable[[str], None] = print) -> dict:
    log("✍️ 대본을 만드는 중이에요… (1~3분 걸려요)")
    data = script.generate_script(topic, minutes, tone)
    project.invalidate_from("script")
    project.save_script(data)
    project.update_settings(topic=topic, minutes=minutes, tone=tone)
    project.set_status("awaiting_review")
    log("✅ 대본 완성! 내용을 확인·수정한 뒤 '확인 완료, 계속 진행'을 눌러 주세요.")
    return data


def approve_script(project: Project) -> None:
    project.mark_done("script")
    project.set_status("approved")


def run_after_review(project: Project, settings: dict, progress: Progress | None = None,
                     log: Callable[[str], None] = print, force: bool = False) -> list:
    """settings: tts_engine, tts_voice, tts_rate, use_stock, use_whisper, bgm, burn_subtitles, make_shorts, quality"""
    if not project.is_done("script"):
        approve_script(project)

    steps = [("tts", 0.0, 0.15), ("assets", 0.15, 0.3), ("subtitles", 0.3, 0.35), ("render", 0.35, 1.0)]

    def sub(lo, hi):
        return (lambda p, m: progress(lo + (hi - lo) * p, m)) if progress else None

    outputs = []
    for stage, lo, hi in steps:
        if project.is_done(stage) and not force:
            log(f"⏭️ {stage} 단계는 이미 끝나서 건너뛰어요.")
            continue
        if stage == "tts":
            log("🎙️ 내레이션 음성을 만드는 중…")
            engine = tts.make_engine(settings.get("tts_engine"), settings.get("tts_voice"), settings.get("tts_rate"))
            tts.generate_narration(project, engine, sub(lo, hi))
        elif stage == "assets":
            log("🎞️ 장면별 소재를 찾는 중…")
            res = assets.match_assets(project, sub(lo, hi), use_stock=settings.get("use_stock", True))
            for w in res["warnings"]:
                log(f"⚠️ {w}")
        elif stage == "subtitles":
            log("💬 자막을 만드는 중…")
            subtitles.build_subtitles(project, use_whisper=settings.get("use_whisper", False), progress=sub(lo, hi))
        elif stage == "render":
            log("🎬 영상을 조립하는 중… (영상 길이에 따라 10~40분 걸릴 수 있어요)")
            outputs = render.render_all(project, make_shorts=settings.get("make_shorts", True),
                                        bgm=settings.get("bgm"), burn_subtitles=settings.get("burn_subtitles", True),
                                        quality=settings.get("quality", "1080p"), progress=sub(lo, hi))
    project.set_status("done")
    log("🎉 모든 작업이 끝났어요!")
    return outputs
