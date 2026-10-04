"""API 키 없이 돌아가는 모듈 테스트 (외부 API는 가짜 응답 사용)."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import assets, pipeline, script, subtitles, tts
from core.config import UserFacingError, load_config

from .conftest import write_image, write_tone, write_video

SAMPLE = {
    "title": "집에서 카페 라떼", "thumbnail_text": "라떼 비법", "description": "설명", "tags": ["홈카페", "라떼"],
    "scenes": [
        {"id": 1, "type": "hook", "narration": "카페 라떼, 집에서도 똑같이 만들 수 있을까요?", "on_screen_text": "집에서 라떼?",
         "visual_keywords_en": ["latte art", "coffee cup"], "prefer_my_footage": True, "shorts": True},
        {"id": 2, "type": "outro", "narration": "구독과 좋아요 부탁드려요. 여러분의 레시피를 댓글로 알려주세요!",
         "on_screen_text": "", "visual_keywords_en": ["coffee beans"], "prefer_my_footage": False, "shorts": False},
    ],
}


# ---------- 대본 ----------
class FakeStream:
    def __init__(self, text, stop="end_turn"):
        self.msg = SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text)])

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.msg


class FakeClient:
    def __init__(self, text, stop="end_turn"):
        self.kwargs = None
        outer = self

        class _Msgs:
            def stream(self, **kw):
                outer.kwargs = kw
                return FakeStream(text, stop)
        self.beta = SimpleNamespace(messages=_Msgs())


def test_build_prompt_fills_placeholders():
    p = script.build_prompt("홈카페", 8, "정보형", [{"file": "cafe.mp4", "memo": "라떼 아트"}])
    assert "홈카페" in p and "2400" in p and "cafe.mp4 — 라떼 아트" in p
    assert "{{" not in p and "<!--" not in p


def test_generate_script_with_fake_client():
    client = FakeClient(json.dumps(SAMPLE, ensure_ascii=False))
    data = script.generate_script("홈카페", 1, "정보형", assets=[], client=client)
    assert data["scenes"][0]["type"] == "hook" and len(data["scenes"]) == 2
    kw = client.kwargs
    assert kw["model"] == load_config()["claude"]["model"]
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["fallbacks"] == "default"


def test_generate_script_refusal():
    with pytest.raises(UserFacingError, match="거절"):
        script.generate_script("x", 1, "정보형", assets=[], client=FakeClient("", stop="refusal"))


def test_missing_anthropic_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(UserFacingError, match="ANTHROPIC_API_KEY"):
        script.generate_script("홈카페", 1, "정보형", assets=[])


def test_editor_roundtrip():
    rows = script.scenes_to_rows(SAMPLE["scenes"])
    assert rows[0]["visual_keywords_en"] == "latte art, coffee cup"
    rows[1]["on_screen_text"] = float("nan")  # 표에서 비운 칸
    back = script.normalize_script({**SAMPLE, "scenes": script.rows_to_scenes(rows)})
    assert back["scenes"][0]["visual_keywords_en"] == ["latte art", "coffee cup"]
    assert back["scenes"][1]["on_screen_text"] == ""


# ---------- 내레이션 ----------
class FakeEngine(tts.TTSEngine):
    name = "fake"

    def __init__(self):
        self.calls = 0

    def synthesize(self, text, out_path):
        self.calls += 1
        write_tone(Path(out_path), 1.2)
        return [{"text": text, "start": 0.0, "end": 1.1}]


def test_generate_narration_and_cache(tmp_project):
    tmp_project.save_script(script.normalize_script(SAMPLE))
    eng = FakeEngine()
    data = tts.generate_narration(tmp_project, eng)
    assert eng.calls == 2
    assert abs(data["scenes"][0]["duration"] - 1.2) < 0.05
    tts.generate_narration(tmp_project, eng)  # 바뀐 게 없으면 다시 만들지 않음
    assert eng.calls == 2
    assert tmp_project.is_done("tts")


# ---------- 소재 ----------
def test_licensed_requires_memo(tmp_path):
    my, lic = tmp_path / "my", tmp_path / "lic"
    my.mkdir(), lic.mkdir()
    write_image(my / "카페_latte_art.png")
    (my / "카페_latte_art.txt").write_text("라떼 아트 우유 거품", encoding="utf-8")
    write_image(lic / "drone_city.png")
    write_image(lic / "no_permission.png")
    (lic / "drone_city.license.txt").write_text("허락: 홍길동 2026-10-01\n키워드: city", encoding="utf-8")
    found = assets.scan_local_assets(my, lic)
    names = {a.path.name for a in found}
    assert names == {"카페_latte_art.png", "drone_city.png"}
    assert [p.name for p in assets.licensed_without_memo(lic)] == ["no_permission.png"]
    cafe = next(a for a in found if a.source == "my")
    assert assets.score_asset(SAMPLE["scenes"][0], cafe) >= 2


class FakeHTTP:
    def __init__(self, video_file: Path):
        self.video_file = video_file

    def get(self, url, params=None, headers=None, timeout=None, stream=False):
        if "pexels.com/videos/search" in url:
            q = params["query"].replace(" ", "")
            return _Resp({"videos": [{"id": abs(hash(q)) % 10000, "url": f"https://pexels.com/video/{q}",
                                      "duration": 3, "user": {"name": "Jane", "url": "https://pexels.com/@jane"},
                                      "video_files": [{"file_type": "video/mp4", "width": 1920, "link": "https://dl/x.mp4"}]}]})
        if url.startswith("https://dl/"):
            return _Resp(None, content=self.video_file.read_bytes())
        raise AssertionError(url)


class _Resp:
    def __init__(self, data, content=b""):
        self.data, self.content, self.status_code, self.text = data, content, 200, ""

    def json(self):
        return self.data

    def raise_for_status(self):
        pass

    def iter_content(self, n):
        yield self.content

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_match_assets_with_fake_pexels(tmp_project, tmp_path, monkeypatch):
    tmp_project.save_script(script.normalize_script(SAMPLE))
    tts.generate_narration(tmp_project, FakeEngine())
    vid = tmp_path / "v.mp4"
    write_video(vid, 1.0)
    monkeypatch.setenv("PEXELS_API_KEY", "fake")
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    monkeypatch.setattr(assets, "scan_local_assets", lambda *a, **k: [])
    res = assets.match_assets(tmp_project, session=FakeHTTP(vid))
    media = res["scenes"][0]["media"]
    assert media and media[0]["source"] == "pexels" and media[0]["author"] == "Jane"
    credits = tmp_project.credits_path.read_text(encoding="utf-8")
    assert "Jane (Pexels)" in credits


def test_no_keys_gives_color_and_warning(tmp_project, monkeypatch):
    tmp_project.save_script(script.normalize_script(SAMPLE))
    tts.generate_narration(tmp_project, FakeEngine())
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    monkeypatch.setattr(assets, "scan_local_assets", lambda *a, **k: [])
    res = assets.match_assets(tmp_project)
    assert res["scenes"][0]["media"][0]["kind"] == "color"
    assert any("키가 없어서" in w for w in res["warnings"])
    assert "직접 촬영" in tmp_project.credits_path.read_text(encoding="utf-8")


# ---------- 자막 ----------
def test_wrap_max_18_chars():
    text = "오늘은 집에서 카페처럼 맛있는 라떼를 만드는 아주 간단한 방법을 알려드릴게요. 끝까지 봐주세요!"
    for chunk in subtitles.chunk_text(text, 18, 2):
        lines = chunk.split("\n")
        assert 1 <= len(lines) <= 2
        assert all(len(l) <= 18 for l in lines)


def test_srt_format_and_timeline():
    scenes = [{"narration": "첫 문장입니다. 두 번째 문장이에요.", "duration": 4.0,
               "sentences": [{"text": "첫 문장입니다.", "start": 0.1, "end": 1.8},
                             {"text": "두 번째 문장이에요.", "start": 2.0, "end": 3.9}]},
              {"narration": "다음 장면", "duration": 2.0}]
    cues = subtitles.all_cues(scenes, padding=0.5)
    assert cues[0]["start"] == 0.1 and cues[1]["start"] == 2.0
    assert cues[2]["start"] == 4.5  # 두 번째 장면 = 4.0 + 0.5
    srt = subtitles.to_srt(cues)
    assert srt.startswith("1\n00:00:00,100 --> 00:00:02,000\n첫 문장입니다.")


def test_whisper_words_alignment():
    scene = {"narration": "하나 둘 셋 넷", "duration": 4.0,
             "words": [{"word": w, "start": i, "end": i + 0.8} for i, w in enumerate(["하나", "둘", "셋", "넷"])]}
    cues = subtitles.scene_cues(scene, max_chars=5, max_lines=1)
    assert [c["text"] for c in cues] == ["하나 둘", "셋 넷"]
    assert cues[1]["start"] == 2


# ---------- 원클릭 ----------
def test_pipeline_stops_for_review(tmp_project, monkeypatch):
    monkeypatch.setattr(script, "generate_script", lambda *a, **k: script.normalize_script(SAMPLE))
    pipeline.run_until_review(tmp_project, "홈카페", 1, "정보형", log=lambda m: None)
    assert tmp_project.load_state()["status"] == "awaiting_review"
    assert not tmp_project.is_done("script")
    pipeline.approve_script(tmp_project)
    assert tmp_project.is_done("script") and tmp_project.next_stage() == "tts"
