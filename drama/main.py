"""숏폼 AI 드라마: 아이디어 한 줄 → 대본 → 컷별 영상 프롬프트 생성기

사용법
  python main.py --idea "비 오는 날 우산 하나로 엮인 꽃집 사장과 건축가" --episodes 3 --seconds 60
  python main.py sample                              # API 키 없이 결과물 미리보기
  python main.py export output/2026-11-18_우산은_하나뿐   # series.json 을 고친 뒤 다시 내보내기
  python main.py edit   output/2026-11-18_우산은_하나뿐   # 컷 영상·음성·자막 → 완성 영상 자동 편집
  python main.py subtitle-preview                     # 자막 스타일 3가지 미리보기 이미지
  python main.py thumbnail output/2026-11-18_우산은_하나뿐  # 썸네일만 다시 만들기 (edit 하면 자동으로도 만들어짐)
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

from dramamaker import check, export, settings


def _finish(out: Path, series: dict, cfg: dict) -> None:
    check.fix(series, cfg)
    files = export.export_all(out, series, cfg)
    rep = check.report(series, cfg)
    (out / "검수.txt").write_text(rep, encoding="utf-8")
    print("\n" + rep)
    print(f"\n✅ 완성! 결과 폴더: {out}")
    for f in files[1:]:
        print(f"   - {f.name}")


def cmd_generate(args) -> int:
    cfg = settings.load_config(Path(args.config) if args.config else None, {
        "idea": args.idea, "genre": args.genre, "episodes": args.episodes, "seconds": args.seconds})
    if not cfg["idea"]:
        print("❌ 아이디어가 없어요. --idea \"한 줄 아이디어\" 를 붙이거나 config.yaml 의 idea 를 채워 주세요.")
        return 1
    if not settings.has_key("ANTHROPIC_API_KEY"):
        print("❌ .env 파일에 ANTHROPIC_API_KEY 가 없어요. README의 'API 키 넣기'를 봐 주세요.")
        return 1
    from dramamaker import generate
    print(f"▶ 아이디어: {cfg['idea']}\n  장르: {cfg['genre']} / {cfg['episodes']}회 / 회당 약 {cfg['seconds']}초")
    try:
        series = generate.make_series(cfg)
    except generate.GenerateError as e:
        print(f"❌ {e}")
        return 1
    series["config"] = {k: cfg[k] for k in ("idea", "genre", "episodes", "seconds", "aspect",
                                             "cut_min", "cut_max", "visual_style")}
    _finish(settings.new_output_dir(series["bible"]["title"]), series, cfg)
    return 0


def cmd_sample(args) -> int:
    from dramamaker.sample import SAMPLE
    cfg = settings.load_config(Path(args.config) if args.config else None, {"episodes": 1, "seconds": 60})
    series = copy.deepcopy(SAMPLE)
    _finish(settings.new_output_dir("샘플_" + series["bible"]["title"]), series, cfg)
    return 0


def cmd_export(args) -> int:
    out = Path(args.folder)
    src = out / "series.json"
    if not src.exists():
        print(f"❌ {out} 안에 series.json 이 없어요. 폴더 경로를 확인해 주세요.")
        return 1
    try:
        series = json.loads(src.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"❌ series.json 을 고치다 형식이 깨졌어요 ({e.lineno}번째 줄 근처). 따옴표·쉼표를 확인해 주세요.")
        return 1
    cfg = settings.load_config(Path(args.config) if args.config else None, series.get("config"))
    _finish(out, series, cfg)
    return 0


def cmd_edit(args) -> int:
    from dramamaker import edit
    out = Path(args.folder)
    src = out / "series.json"
    if not src.exists():
        print(f"❌ {out} 안에 series.json 이 없어요. 폴더 경로를 확인해 주세요.")
        return 1
    series = json.loads(src.read_text(encoding="utf-8"))
    cfg = settings.load_config(Path(args.config) if args.config else None, series.get("config"))
    nos = [args.episode] if args.episode else [e["no"] for e in series["episodes"]]
    export.write_clip_guide(out, series)
    for no in nos:
        print(f"▶ EP{no:02d} 자동 편집")
        try:
            final = edit.edit_episode(out, series, no, cfg, tts=not args.no_tts)
        except edit.EditError as e:
            print(f"❌ {e}")
            return 1
        print(f"✅ 완성: {final}")
        from dramamaker import thumbnail
        for f in thumbnail.make_thumbnails(out, series, no, cfg):
            print(f"✅ 썸네일: {f}")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "edit":
        p = argparse.ArgumentParser(prog="main.py edit", description="컷 영상 + 음성 + 자막 → 완성 영상")
        p.add_argument("folder", help="output 안의 결과 폴더")
        p.add_argument("--episode", type=int, help="이 회차만 편집 (안 쓰면 전체)")
        p.add_argument("--no-tts", action="store_true", help="자동 음성(TTS) 끄기 (자막·원래 소리는 유지)")
        p.add_argument("--config", help="다른 설정 파일을 쓸 때")
        return cmd_edit(p.parse_args(argv[1:]))
    if argv and argv[0] == "thumbnail":
        p = argparse.ArgumentParser(prog="main.py thumbnail", description="회차 썸네일만 다시 만들기")
        p.add_argument("folder", help="output 안의 결과 폴더")
        p.add_argument("--episode", type=int, help="이 회차만 (안 쓰면 전체)")
        a = p.parse_args(argv[1:])
        from dramamaker import thumbnail
        out = Path(a.folder)
        if not (out / "series.json").exists():
            print(f"❌ {out} 안에 series.json 이 없어요. 폴더 경로를 확인해 주세요.")
            return 1
        series = json.loads((out / "series.json").read_text(encoding="utf-8"))
        cfg = settings.load_config(None, series.get("config"))
        for no in ([a.episode] if a.episode else [e["no"] for e in series["episodes"]]):
            for f in thumbnail.make_thumbnails(out, series, no, cfg):
                print(f"✅ 썸네일: {f}")
        return 0
    if argv and argv[0] == "subtitle-preview":
        from dramamaker import edit, subtitle_style
        cfg = settings.load_config()
        settings.OUTPUT_DIR.mkdir(exist_ok=True)
        out = subtitle_style.preview(edit.find_font(settings.BASE_DIR / "fonts"),
                                     settings.OUTPUT_DIR / "자막_스타일_미리보기.png",
                                     int(cfg["edit"].get("subtitle_size", 58)))
        print(f"✅ 자막 스타일 미리보기: {out}\n   마음에 드는 스타일 이름을 config.yaml 의 subtitle_style 에 적으세요.")
        return 0
    if argv and argv[0] in ("sample", "export"):
        p = argparse.ArgumentParser(prog=f"main.py {argv[0]}")
        if argv[0] == "export":
            p.add_argument("folder", help="output 안의 결과 폴더")
        p.add_argument("--config", help="다른 설정 파일을 쓸 때")
        args = p.parse_args(argv[1:])
        return cmd_sample(args) if argv[0] == "sample" else cmd_export(args)

    p = argparse.ArgumentParser(description="숏폼 AI 드라마 대본 → 컷 프롬프트 생성기")
    p.add_argument("--idea", help="한 줄 아이디어")
    p.add_argument("--genre", help="장르 (기본: 로맨스)")
    p.add_argument("--episodes", type=int, help="회차 수 (1~20)")
    p.add_argument("--seconds", type=int, help="회당 길이(초, 20~180)")
    p.add_argument("--config", help="다른 설정 파일을 쓸 때")
    return cmd_generate(p.parse_args(argv))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
