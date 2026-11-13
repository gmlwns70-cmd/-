"""인스타그램 스토리텔링형 카드뉴스 자동 제작 프로그램

사용법
  python main.py --topic "주제" --target "자영업 사장님" --cards 15   # 새로 만들기
  python main.py render output/2026-11-12_주제                        # 원고만 고쳐서 다시 합성
  python main.py check  output/2026-11-12_주제                        # 검수 리포트
  python main.py images output/2026-11-12_주제                        # 빠진 일러스트만 새로 만들기
  python main.py sample                                               # API 키 없이 디자인 미리보기
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from cardmaker import settings

for _stream in (sys.stdout, sys.stderr):  # 윈도우에서 이모지 출력 때문에 멈추지 않도록
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass


def cmd_generate(args) -> int:
    cfg = settings.load_config(Path(args.config) if args.config else None, {
        "topic": args.topic, "target": args.target, "brand": args.brand,
        "cards": args.cards, "character": args.character,
    })
    if not cfg["topic"]:
        print("❌ 주제가 없어요. --topic \"주제\" 를 붙이거나 config.yaml 의 topic 을 채워 주세요.")
        return 1
    if not settings.has_key("ANTHROPIC_API_KEY"):
        print("❌ .env 파일에 ANTHROPIC_API_KEY 가 없어요. README의 'API 키 넣는 법'을 봐 주세요.")
        return 1

    from cardmaker import caption, factcheck, render, script_gen

    print(f"▶ 주제: {cfg['topic']}  /  타깃: {cfg['target']}  /  {cfg['cards']}장")
    try:
        print("[1/5] 자료 조사 (웹 검색으로 실제 수치 찾기)")
        facts = script_gen.research(cfg)
        print("[2/5] 원고 작성")
        script = script_gen.write_script(cfg, facts)
        print("[3/5] 수치 검증")
        script_gen.repair_numbers(cfg, script, facts)
    except script_gen.ScriptError as e:
        print(f"❌ {e}")
        return 1

    script_gen.assign_types(script["cards"], float(cfg["style"]["illustration_ratio"]))
    script.update({"topic": cfg["topic"], "target": cfg["target"], "brand": cfg["brand"],
                   "character": cfg["character"], "total_cards": len(script["cards"]), "facts": facts})
    out = settings.new_output_dir(cfg["topic"])
    caption.write_caption(out / "caption.txt", script)
    (out / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    factcheck.write_sources_md(out / "sources.md", script, facts)

    print("[4/5] 일러스트")
    provider = settings.image_provider()
    if args.text_only or provider == "none":
        print("  · 텍스트 카드 전용 모드 (일러스트 없이 만듭니다)")
    else:
        try:
            from cardmaker import images
            res = images.generate_all(out, script, cfg, provider)
            if res["failed"]:
                print("  ⚠ 그림을 못 만든 카드는 글자 카드로 대신 만들어요. 이유를 해결하고 '일러스트 다시 만들기'를 누르면 돼요.")
        except Exception as e:  # 일러스트가 실패해도 카드는 만들어지도록
            print(f"  ⚠ 일러스트 생성 실패: {e}\n  → 텍스트 카드로 대신 만들어요. 나중에 다시 시도할 수 있어요.")

    print("[5/5] 카드 합성")
    render.render_dir(out, cfg)
    from cardmaker import check
    report = check.run_check(out, cfg)
    print("\n" + report)
    print(f"\n✅ 완성! 결과 폴더: {out}")
    return 0


def cmd_render(args) -> int:
    from cardmaker import caption, render
    out = Path(args.folder)
    if not (out / "script.json").exists():
        print(f"❌ {out} 안에 script.json 이 없어요. 폴더 경로를 확인해 주세요.")
        return 1
    cfg = settings.load_config(Path(args.config) if args.config else None)
    script = json.loads((out / "script.json").read_text(encoding="utf-8"))
    if script.get("caption"):
        caption.write_caption(out / "caption.txt", script)
    print(f"▶ 다시 합성: {out}  (일러스트는 새로 만들지 않아요)")
    render.render_dir(out, cfg)
    print("✅ 완료")
    return 0


def cmd_check(args) -> int:
    from cardmaker import check
    out = Path(args.folder)
    if not (out / "script.json").exists():
        print(f"❌ {out} 안에 script.json 이 없어요.")
        return 1
    cfg = settings.load_config(Path(args.config) if args.config else None)
    print(check.run_check(out, cfg))
    print(f"\n(리포트 파일: {out / 'check_report.md'})")
    return 0


def cmd_images(args) -> int:
    """비어 있는 일러스트만 새로 만들고 다시 합성합니다."""
    from cardmaker import images, render
    out = Path(args.folder)
    if not (out / "script.json").exists():
        print(f"❌ {out} 안에 script.json 이 없어요.")
        return 1
    cfg = settings.load_config(Path(args.config) if args.config else None)
    provider = settings.image_provider()
    if provider == "none":
        print("❌ .env 의 IMAGE_PROVIDER 가 none 이에요. openai 또는 gemini 로 바꿔 주세요.")
        return 1
    script = json.loads((out / "script.json").read_text(encoding="utf-8"))
    try:
        images.generate_all(out, script, cfg, provider)
    except RuntimeError as e:
        print(f"❌ {e}")
        return 1
    render.render_dir(out, cfg)
    print("✅ 완료")
    return 0


def cmd_sample(args) -> int:
    from cardmaker import render
    from cardmaker.sample import SAMPLE_SCRIPT
    cfg = settings.load_config(Path(args.config) if args.config else None)
    out = settings.OUTPUT_DIR / "sample"
    out.mkdir(parents=True, exist_ok=True)
    (out / "script.json").write_text(json.dumps(SAMPLE_SCRIPT, ensure_ascii=False, indent=2), encoding="utf-8")
    print("▶ 샘플 카드 만들기 (API 키 필요 없음)")
    render.render_dir(out, cfg)
    print(f"✅ 완료: {out}")
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("render", "check", "images", "sample"):
        p = argparse.ArgumentParser(prog=f"main.py {argv[0]}")
        if argv[0] != "sample":
            p.add_argument("folder", help="output 안의 결과 폴더")
        p.add_argument("--config", help="설정 파일 경로 (기본: config.yaml)")
        args = p.parse_args(argv[1:])
        return {"render": cmd_render, "check": cmd_check, "images": cmd_images, "sample": cmd_sample}[argv[0]](args)

    p = argparse.ArgumentParser(description="인스타그램 카드뉴스 자동 제작")
    p.add_argument("--topic", help="주제 한 줄")
    p.add_argument("--target", help="핵심 타깃")
    p.add_argument("--brand", help="브랜드명/계정명")
    p.add_argument("--cards", type=int, help="장수 (10~15, 기본 15)")
    p.add_argument("--character", help="고정 캐릭터 설명")
    p.add_argument("--text-only", action="store_true", help="일러스트 없이 텍스트 카드만")
    p.add_argument("--config", help="설정 파일 경로 (기본: config.yaml)")
    return cmd_generate(p.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
