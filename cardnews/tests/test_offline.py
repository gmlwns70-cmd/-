"""API 키 없이 돌아가는 기본 점검. 실행: python -m pytest tests  (또는 python tests/test_offline.py)"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cardmaker import caption, check, factcheck, render, script_gen, settings  # noqa: E402

FACTS = [{"id": "S1", "claim": "2023년 신생 기업 5년 생존율은 34.7%", "figure": "34.7%",
          "publisher": "테스트기관", "title": "가상 테스트 자료", "date": "2024",
          "url": "https://example.com/board/123"}]


def _script():
    cards = [{"no": i, "role": "", "type": "text", "image_prompt": "", "emotion": "",
              "lines": [{"text": "평범한 카드 문장이에요", "highlight": False}],
              "source": {"name": "", "url": ""}, "verify_needed": False} for i in range(1, 16)]
    cards[6]["lines"] = [{"text": "테스트기관에 따르면", "highlight": False},
                         {"text": "5년 생존율은 34.7%", "highlight": True}]
    cards[6]["source"] = {"name": "테스트기관", "url": "https://www.example.com/board/123/"}
    cards[7]["lines"] = [{"text": "손님 82%가", "highlight": False}, {"text": "다시 안 와요", "highlight": False}]
    return {"topic": "테스트", "brand": "@t", "cards": cards,
            "caption": {"body": "가" * 900, "cta": "저장해 두세요", "hashtags": [f"태그{i}" for i in range(17)]}}


def test_factcheck_flags_and_strips():
    s = _script()
    problems = factcheck.verify_cards(s, FACTS)
    assert [p["no"] for p in problems] == [8]          # 7번은 출처와 숫자가 맞음, 8번은 출처 없음
    factcheck.strip_unverified(s, {8})
    assert s["cards"][7]["verify_needed"] and not factcheck.has_figure(factcheck.card_text(s["cards"][7]))


def test_assign_types_ratio():
    s = _script()
    script_gen.assign_types(s["cards"], 0.4)
    types = [c["type"] for c in s["cards"]]
    assert types[0] == "cover" and types.count("illustrated") + 1 == 6
    assert all(not (a == b == "illustrated") for a, b in zip(types, types[1:]))


def test_render_caption_check(tmp_path=None):
    out = Path(tmp_path or (settings.OUTPUT_DIR / "_test"))
    out.mkdir(parents=True, exist_ok=True)
    s = _script()
    script_gen.assign_types(s["cards"])
    s["cards"][2]["lines"] = [{"text": "이건 아주아주아주 길어서 넘치는 줄이에요 정말로요", "highlight": True}]
    (out / "script.json").write_text(json.dumps(s, ensure_ascii=False), encoding="utf-8")
    caption.write_caption(out / "caption.txt", s)
    assert len(s["caption"]["hashtags"]) == 15
    factcheck.write_sources_md(out / "sources.md", s, FACTS)
    meta = render.render_dir(out, settings.load_config(), only=[1, 3, 7])
    assert (out / "card_03.png").exists() and len(meta) == 3
    report = check.run_check(out, settings.load_config())
    assert "8번 카드: 82" in report and "3번" in report


if __name__ == "__main__":
    test_factcheck_flags_and_strips()
    test_assign_types_ratio()
    test_render_caption_check()
    print("모든 점검 통과")
