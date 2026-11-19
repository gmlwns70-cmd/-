"""숏폼 AI 드라마: 아이디어 한 줄 → 대본 → 컷별 영상 프롬프트 생성기

사용법
  python main.py --idea "비 오는 날 우산 하나로 엮인 꽃집 사장과 건축가" --episodes 3 --seconds 60
  python main.py chat-prompt                         # Claude 대화창용 요청문 복사 (API 키 불필요)
  python main.py import                              # 대화창 답변(복사한 것) 가져오기
  python main.py sample                              # API 키 없이 결과물 미리보기
  python main.py export output/2026-11-18_우산은_하나뿐   # series.json 을 고친 뒤 다시 내보내기
  python main.py edit   output/2026-11-18_우산은_하나뿐   # 컷 영상·음성·자막 → 완성 영상 자동 편집
  python main.py subtitle-preview                     # 자막 스타일 3가지 미리보기 이미지
  python main.py thumbnail output/2026-11-18_우산은_하나뿐  # 썸네일만 다시 만들기 (edit 하면 자동으로도 만들어짐)
  python main.py upload-text output/2026-11-18_우산은_하나뿐 [--regen]  # 업로드 제목·설명·해시태그
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


def latest_folder() -> Path | None:
    """샘플을 뺀 가장 최근 결과 폴더."""
    if not settings.OUTPUT_DIR.exists():
        return None
    dirs = [d for d in settings.OUTPUT_DIR.iterdir()
            if d.is_dir() and "샘플" not in d.name and (d / "series.json").exists()]
    return max(dirs, key=lambda d: d.stat().st_mtime) if dirs else None


def cmd_chat_prompt(args) -> int:
    from dramamaker import chat_bridge
    cfg = settings.load_config(Path(args.config) if args.config else None, {
        "idea": args.idea, "genre": args.genre, "episodes": args.episodes, "seconds": args.seconds})
    text = chat_bridge.build_prompt(cfg, cfg["idea"])
    settings.OUTPUT_DIR.mkdir(exist_ok=True)
    f = settings.OUTPUT_DIR / "대화창_요청문.txt"
    f.write_text(text, encoding="utf-8")
    copied = chat_bridge.write_clipboard(text)
    print("✅ 요청문이 " + ("복사됐어요! (Ctrl+V 로 붙여넣기)" if copied else f"만들어졌어요: {f}"))
    print("  1) claude.ai 대화창을 열고 붙여넣기 하세요.")
    if not cfg["idea"]:
        print("  2) 맨 위 '■ 아이디어:' 줄에 아이디어를 적고 보내세요.")
    else:
        print("  2) 그대로 보내세요.")
    print("  3) 답변의 코드블록 오른쪽 위 '복사' 버튼을 누른 뒤, 2_대본_가져오기.bat 을 실행하세요.")
    return 0


def cmd_import(args) -> int:
    from dramamaker import chat_bridge
    try:
        text = Path(args.file).read_text(encoding="utf-8-sig") if args.file else chat_bridge.read_clipboard()
        data = chat_bridge.extract_json(text)
        cfg = settings.load_config(Path(args.config) if args.config else None)
        new = chat_bridge.normalize(data, cfg)
    except FileNotFoundError:
        print(f"❌ 파일을 찾지 못했어요: {args.file}")
        return 1
    except chat_bridge.ImportError_ as e:
        print(f"❌ {e}")
        return 1
    if "bible" in new:                                   # 새 시리즈
        series = {"bible": new["bible"], "episodes": new["episodes"]}
        series["config"] = {k: cfg[k] for k in ("idea", "genre", "episodes", "seconds", "aspect",
                                                 "cut_min", "cut_max", "visual_style")}
        out = settings.new_output_dir(series["bible"]["title"])
        print(f"▶ 새 시리즈: {series['bible']['title']}  ({len(series['episodes'])}회)")
    else:                                                # '다음 화' 답변 → 최근 시리즈에 붙이기
        out = Path(args.folder) if args.folder else latest_folder()
        if not out or not (out / "series.json").exists():
            print("❌ 이 답변은 '다음 화'만 들어 있는데, 붙일 시리즈 폴더가 없어요. 1화부터 가져와 주세요.")
            return 1
        series = json.loads((out / "series.json").read_text(encoding="utf-8"))
        cfg = settings.load_config(Path(args.config) if args.config else None, series.get("config"))
        added = chat_bridge.merge_episodes(series, new["episodes"])
        print(f"▶ '{series['bible']['title']}' 에 EP{', EP'.join(f'{n:02d}' for n in added)} 추가")
    _finish(out, series, cfg)
    return 0


def cmd_edit(args) -> int:
    from dramamaker import edit
    out = Path(args.folder) if args.folder else latest_folder()
    if out is None:
        print("❌ 편집할 결과 폴더가 없어요. 먼저 대본을 만들거나 가져와 주세요.")
        return 1
    if not args.folder:
        print(f"▶ 가장 최근 결과 폴더를 편집해요: {out.name}")
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
        p.add_argument("folder", nargs="?", help="output 안의 결과 폴더 (안 쓰면 가장 최근 폴더)")
        p.add_argument("--episode", type=int, help="이 회차만 편집 (안 쓰면 전체)")
        p.add_argument("--no-tts", action="store_true", help="자동 음성(TTS) 끄기 (자막·원래 소리는 유지)")
        p.add_argument("--config", help="다른 설정 파일을 쓸 때")
        return cmd_edit(p.parse_args(argv[1:]))
    if argv and argv[0] == "chat-prompt":
        p = argparse.ArgumentParser(prog="main.py chat-prompt", description="Claude 대화창용 요청문 만들기(복사)")
        p.add_argument("--idea", help="한 줄 아이디어 (안 쓰면 대화창에서 직접 적기)")
        p.add_argument("--genre", help="장르")
        p.add_argument("--episodes", type=int, help="회차 수")
        p.add_argument("--seconds", type=int, help="회당 길이(초)")
        p.add_argument("--config", help="다른 설정 파일을 쓸 때")
        return cmd_chat_prompt(p.parse_args(argv[1:]))
    if argv and argv[0] == "import":
        p = argparse.ArgumentParser(prog="main.py import", description="Claude 대화창 답변 가져오기")
        p.add_argument("--file", help="답변을 저장한 텍스트 파일 (안 쓰면 클립보드에서 읽음)")
        p.add_argument("--folder", help="'다음 화'를 붙일 결과 폴더 (안 쓰면 가장 최근 폴더)")
        p.add_argument("--config", help="다른 설정 파일을 쓸 때")
        return cmd_import(p.parse_args(argv[1:]))
    if argv and argv[0] == "upload-text":
        p = argparse.ArgumentParser(prog="main.py upload-text", description="업로드 제목·설명·해시태그 만들기")
        p.add_argument("folder", help="output 안의 결과 폴더")
        p.add_argument("--regen", action="store_true", help="Claude로 문구를 새로 쓰기 (API 비용 조금 듦)")
        a = p.parse_args(argv[1:])
        from dramamaker import upload
        out = Path(a.folder)
        if not (out / "series.json").exists():
            print(f"❌ {out} 안에 series.json 이 없어요. 폴더 경로를 확인해 주세요.")
            return 1
        series = json.loads((out / "series.json").read_text(encoding="utf-8"))
        cfg = settings.load_config(None, series.get("config"))
        if a.regen:
            if not settings.has_key("ANTHROPIC_API_KEY"):
                print("❌ .env 파일에 ANTHROPIC_API_KEY 가 없어요.")
                return 1
            from dramamaker import generate
            for ep in series["episodes"]:
                print(f"  · EP{ep['no']:02d} 업로드 문구 작성 중...")
                try:
                    ep["upload"] = generate.make_upload(cfg, series, ep)
                except generate.GenerateError as e:
                    print(f"❌ {e}")
                    return 1
            (out / "series.json").write_text(json.dumps(series, ensure_ascii=False, indent=2), encoding="utf-8")
        for ep in series["episodes"]:
            f = out / f"07_업로드문구_EP{ep['no']:02d}.txt"
            upload.write(f, series, ep)
            print(f"✅ {f}" + ("" if ep.get("upload") else "  (기본 문구. Claude로 쓰려면 --regen)"))
        return 0
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
