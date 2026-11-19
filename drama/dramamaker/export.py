"""series.json → 사람이 보는 파일(대본·컷 표·뉴테이크 붙여넣기용 프롬프트)로 내보냅니다."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from . import upload


def char_map(bible: dict) -> dict:
    return {c["id"]: c for c in bible["characters"]}


def full_prompt(cut: dict, bible: dict, cfg: dict, kind: str = "video") -> str:
    """컷 프롬프트 앞에 등장인물 고정 외모를 붙여, 어느 컷에서도 같은 얼굴이 나오게 합니다."""
    chars = char_map(bible)
    looks = [f"{cid}: {chars[cid]['look_en']}" for cid in cut["characters"] if cid in chars]
    body = cut["video_prompt_en"] if kind == "video" else cut["image_prompt_en"]
    parts = []
    if looks:
        parts.append("Characters — " + " | ".join(looks) + ".")
    body = body.strip()
    parts.append(body if body.endswith((".", "!", "?")) else body + ".")
    parts.append(f"Shot: {cut['shot']}, camera: {cut['camera_move']}.")
    parts.append(f"Setting: {cut['location']}, {cut['time_of_day']}. Mood: {cut['emotion']}.")
    parts.append(f"Style: {cfg['visual_style']}. Vertical {cfg['aspect']} frame. No text, no subtitles, no watermark.")
    return " ".join(parts)


def _dialogue_text(cut: dict, bible: dict) -> str:
    chars = char_map(bible)
    return " / ".join(f"{chars.get(d['speaker'], {}).get('name', d['speaker'])}: {d['line']}"
                      for d in cut["dialogue"])


def write_characters(path: Path, bible: dict, cfg: dict) -> None:
    lines = [f"# {bible['title']} — 인물 설정표", "", f"> {bible['logline']}", "",
             "뉴테이크에서 **각 인물의 기준 이미지를 먼저 한 장씩** 만들어 두고, 모든 컷에 그 이미지를 참조로 넣으세요.",
             "그래야 회차가 바뀌어도 같은 얼굴이 나옵니다.", ""]
    for c in bible["characters"]:
        portrait = (f"Character reference portrait of {c['look_en']} Front-facing, neutral expression, "
                    f"plain light grey background, upper body. Style: {cfg['visual_style']}. "
                    "No text, no letters, no captions, no logo, no watermark.")
        lines += [f"## {c['name']} (`{c['id']}`) — {c['role']}, {c['age']}세",
                  f"- 성격: {c['personality']}",
                  f"- 외모: {c['look_ko']}",
                  f"- 목소리(TTS 고를 때 참고): {c['voice']}",
                  "", "기준 이미지 프롬프트 (복사해서 뉴테이크 이미지 생성에 붙여넣기):", "```", portrait, "```", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_script(path: Path, ep: dict, bible: dict) -> None:
    chars = char_map(bible)
    total = sum(c["seconds"] for c in ep["cuts"])
    lines = [f"# EP{ep['no']:02d}. {ep['title']}", "", f"총 {len(ep['cuts'])}컷 · 약 {total}초", ""]
    if ep.get("thumbnail_text"):
        lines += [f"> 썸네일 문구: {ep['thumbnail_text'].replace(chr(10), ' / ')}  (배경: 컷 {ep.get('thumbnail_cut', 1)})", ""]
    t = 0
    for c in ep["cuts"]:
        names = ", ".join(chars.get(i, {}).get("name", i) for i in c["characters"]) or "인물 없음"
        lines += [f"### 컷 {c['no']}  ({t}~{t + c['seconds']}초)  {c['location']} / {c['time_of_day']}",
                  f"- 화면: {c['shot']}, {c['camera_move']} — {names}",
                  f"- 행동: {c['action_ko']}",
                  f"- 감정: {c['emotion']}   · 소리: {c['sound']}"]
        for d in c["dialogue"]:
            lines.append(f"- **{chars.get(d['speaker'], {}).get('name', d['speaker'])}**: \"{d['line']}\"")
        if c.get("transition", "cut") != "cut":
            lines.append(f"- ↪ 다음 컷으로: {c['transition']}")
        lines.append("")
        t += c["seconds"]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_csv(path: Path, ep: dict, bible: dict, cfg: dict) -> None:
    # utf-8-sig: 엑셀에서 열어도 한글이 깨지지 않게
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["컷", "초", "장소", "시간대", "등장인물", "샷", "카메라", "행동", "대사", "자막",
                    "감정", "소리", "전환", "영상 프롬프트(뉴테이크)", "시작 이미지 프롬프트", "상태"])
        for c in ep["cuts"]:
            w.writerow([c["no"], c["seconds"], c["location"], c["time_of_day"], ", ".join(c["characters"]),
                        c["shot"], c["camera_move"], c["action_ko"], _dialogue_text(c, bible), c["subtitle"],
                        c["emotion"], c["sound"], c.get("transition", ""), full_prompt(c, bible, cfg, "video"),
                        full_prompt(c, bible, cfg, "image"), "대기"])


def write_paste(path: Path, ep: dict, bible: dict, cfg: dict) -> None:
    out = [f"EP{ep['no']:02d}. {ep['title']} — 뉴테이크 붙여넣기용",
           "각 컷의 [영상 프롬프트] 를 복사해 뉴테이크에 붙여넣고, 길이를 '초'에 맞추세요.",
           "등장인물 기준 이미지(01_인물설정표.md)를 참조 이미지로 함께 넣으세요.", ""]
    for c in ep["cuts"]:
        out += ["=" * 60,
                f"컷 {c['no']}  |  {c['seconds']}초  |  인물: {', '.join(c['characters']) or '-'}",
                f"대사: {_dialogue_text(c, bible) or '(없음)'}",
                "", "[시작 이미지 프롬프트]", full_prompt(c, bible, cfg, "image"),
                "", "[영상 프롬프트]", full_prompt(c, bible, cfg, "video"), ""]
    path.write_text("\n".join(out), encoding="utf-8")


def write_clip_guide(out: Path, series: dict) -> None:
    """뉴테이크에서 받은 파일을 어디에 어떤 이름으로 넣는지 알려주는 폴더와 안내문을 만듭니다."""
    clips = out / "clips"
    clips.mkdir(exist_ok=True)
    lines = ["뉴테이크에서 받은 파일을 아래 이름으로 넣고  python main.py edit 결과폴더  를 실행하세요.", "",
             "  EP01/cut01.mp4        컷 영상 (mp4, mov, webm)",
             "  EP01/cut01.png        영상이 아직 없을 때 시작 이미지 (천천히 확대 효과로 대신 사용)",
             "  EP01/cut01_voice.mp3  직접 녹음한 음성을 쓰고 싶을 때만 (없으면 자동 TTS)",
             "  bgm.mp3               배경음악 (clips 폴더 바로 아래, 선택)", "",
             "아무 파일도 없는 컷은 '영상 대기 중' 화면으로 채워지니, 먼저 편집을 돌려 콘티 영상으로 미리 볼 수 있어요.",
             "⚠ 배경음악은 저작권 걱정 없는 무료 음원(유튜브 오디오 보관함 등)만 쓰세요.", ""]
    for ep in series["episodes"]:
        tag = f"EP{ep['no']:02d}"
        (clips / tag).mkdir(exist_ok=True)
        lines.append(f"[{tag}] {ep['title']}")
        lines += [f"  cut{c['no']:02d}.mp4  ({c['seconds']}초) {c['action_ko']}" for c in ep["cuts"]]
        lines.append("")
    (clips / "넣는법.txt").write_text("\n".join(lines), encoding="utf-8")


def export_all(out: Path, series: dict, cfg: dict) -> list[Path]:
    write_clip_guide(out, series)
    bible = series["bible"]
    (out / "series.json").write_text(json.dumps(series, ensure_ascii=False, indent=2), encoding="utf-8")
    files = [out / "series.json", out / "01_인물설정표.md"]
    write_characters(files[-1], bible, cfg)
    for ep in series["episodes"]:
        tag = f"EP{ep['no']:02d}"
        for name, fn in ((f"02_대본_{tag}.md", lambda p: write_script(p, ep, bible)),
                         (f"03_컷목록_{tag}.csv", lambda p: write_csv(p, ep, bible, cfg)),
                         (f"04_뉴테이크_프롬프트_{tag}.txt", lambda p: write_paste(p, ep, bible, cfg))):
            fn(out / name)
            files.append(out / name)
        name = f"07_업로드문구_{tag}.txt"
        upload.write(out / name, series, ep)
        files.append(out / name)
    return files
