"""API 키 없이 돌아가는 점검. 실행: python -m pytest tests"""
import copy
import csv
import json
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402
from dramamaker import check, export, generate, settings  # noqa: E402
from dramamaker.sample import SAMPLE  # noqa: E402


def _cfg(**kw):
    return settings.load_config(Path("/nonexistent.yaml"), kw)


def test_full_prompt_injects_fixed_look_only_for_visible_characters():
    s = SAMPLE["bible"]
    cut = SAMPLE["episodes"][0]["cuts"][1]          # 하은만 나오는 컷
    p = export.full_prompt(cut, s, _cfg(), "video")
    assert "yellow raincoat" in p and "navy trench" not in p
    assert "Vertical 9:16" in p and cut["video_prompt_en"] in p


def test_fix_clamps_seconds_and_maps_names_to_ids():
    series = copy.deepcopy(SAMPLE)
    c = series["episodes"][0]["cuts"][0]
    c["seconds"], c["characters"] = 30, ["한하은", "ghost", "dojun", "dojun"]
    c["dialogue"] = [{"speaker": "강도준", "line": "안녕"}]
    check.fix(series, _cfg())
    assert c["seconds"] == 8 and c["characters"] == ["haeun", "dojun"]
    assert c["dialogue"][0]["speaker"] == "dojun"


def test_report_flags_long_dialogue_and_length():
    series = copy.deepcopy(SAMPLE)
    series["episodes"][0]["cuts"][2]["dialogue"] = [{"speaker": "dojun", "line": "가" * 60}]
    rep = check.report(series, _cfg(seconds=120))
    assert "컷 3" in rep and "목표 120초" in rep


def test_sample_export_writes_all_files(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)
    assert main.main(["sample"]) == 0
    out = next(tmp_path.iterdir())
    names = {p.name for p in out.iterdir()}
    assert {"series.json", "01_인물설정표.md", "02_대본_EP01.md", "03_컷목록_EP01.csv",
            "04_뉴테이크_프롬프트_EP01.txt", "검수.txt"} <= names
    rows = list(csv.reader(open(out / "03_컷목록_EP01.csv", encoding="utf-8-sig")))
    assert rows[0][0] == "컷" and len(rows) == 1 + len(SAMPLE["episodes"][0]["cuts"])
    assert sum(int(r[1]) for r in rows[1:]) == 60
    # series.json 을 고친 뒤 다시 내보내기
    data = json.loads((out / "series.json").read_text(encoding="utf-8"))
    data["episodes"][0]["title"] = "고친 제목"
    (out / "series.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert main.main(["export", str(out)]) == 0
    assert "고친 제목" in (out / "02_대본_EP01.md").read_text(encoding="utf-8")


class FakeClient:
    """Claude API 대신 SAMPLE 을 돌려주는 가짜 클라이언트."""

    def __init__(self):
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    @contextmanager
    def _stream(self, **params):
        self.calls.append(params)
        schema = params["output_config"]["format"]["schema"]
        data = SAMPLE["bible"] if schema is generate.BIBLE_SCHEMA else SAMPLE["episodes"][0]
        msg = SimpleNamespace(stop_reason="end_turn",
                              content=[SimpleNamespace(type="text", text=json.dumps(data, ensure_ascii=False))])
        yield SimpleNamespace(get_final_message=lambda: msg)


def test_make_series_with_fake_client():
    fake = FakeClient()
    series = generate.make_series(_cfg(idea="테스트", episodes=1), client=fake, log=lambda *_: None)
    assert series["bible"]["title"] == "우산은 하나뿐" and len(series["episodes"]) == 1
    assert fake.calls[0]["model"] == "claude-opus-5-5" and fake.calls[0]["fallbacks"] == "default"
    assert "rainy" not in fake.calls[0]["messages"][0]["content"]       # 설정집 단계엔 회차 정보 없음
    assert "haeun" in fake.calls[1]["messages"][0]["content"]          # 회차 단계엔 설정집 인물 전달


def test_schemas_are_strict():
    def walk(s):
        if s.get("type") == "object":
            assert s["additionalProperties"] is False and set(s["required"]) == set(s["properties"])
            for v in s["properties"].values():
                walk(v)
        if s.get("type") == "array":
            walk(s["items"])
    walk(generate.BIBLE_SCHEMA)
    walk(generate.EPISODE_SCHEMA)


# ── 자동 편집 ───────────────────────────────────────────
from dramamaker import edit  # noqa: E402


def test_assign_voices_by_gender_and_override():
    v = edit.assign_voices(SAMPLE["bible"])
    assert v["haeun"]["voice"] == edit.FEMALE and v["dojun"]["voice"] == edit.MALE
    v = edit.assign_voices(SAMPLE["bible"], {"dojun": "ko-KR-HyunsuNeural"})
    assert v["dojun"]["voice"] == "ko-KR-HyunsuNeural"


def test_plan_cut_extends_for_long_voice_and_spreads_subtitles():
    cut = {"seconds": 4, "dialogue": [{"speaker": "a", "line": "하나"}, {"speaker": "b", "line": "둘"}]}
    length, ev = edit.plan_cut(cut, [(Path("1.mp3"), 2.0), (Path("2.mp3"), 3.0)], False)
    assert abs(length - 6.05) < 1e-9 and abs(ev[1]["start"] - 2.55) < 1e-9
    length, ev = edit.plan_cut(cut, [], False)               # 음성 없음 → 자막만 고르게
    assert length == 4 and ev[0]["end"] == ev[1]["start"] and abs(ev[1]["end"] - 3.7) < 1e-9


def _tone(text, voice, out):
    edit._run(["-f", "lavfi", "-i", "sine=f=440", "-t", f"{0.2 * len(text):.2f}", str(out)])


def test_edit_episode_end_to_end(tmp_path):
    series = copy.deepcopy(SAMPLE)
    series["episodes"][0]["cuts"] = series["episodes"][0]["cuts"][:3]
    clip = tmp_path / "clips" / "EP01"
    clip.mkdir(parents=True)
    edit._run(["-f", "lavfi", "-i", "testsrc=size=1280x720:rate=24", "-t", "2", str(clip / "cut01.mp4")])
    final = edit.edit_episode(tmp_path, series, 1, _cfg(), tts=True, synth=_tone, log=lambda *_: None)
    total = sum(max(c["seconds"], 0) for c in series["episodes"][0]["cuts"])
    assert abs(edit.media_duration(final) - total) < 0.3       # 5+5+5초, 짧은 클립은 마지막 장면 유지
    srt = (tmp_path / "05_자막_EP01.srt").read_text(encoding="utf-8")
    assert "그 우산, 제 건데요." in srt and "확실해요?" in srt


def _mean_db(path, start, dur):
    p = edit.subprocess.run([edit.ffmpeg_exe(), "-hide_banner", "-ss", str(start), "-t", str(dur), "-i", str(path),
                             "-af", "volumedetect", "-vn", "-f", "null", "-"], capture_output=True, text=True)
    return float(edit.re.search(r"mean_volume: (-?[\d.]+) dB", p.stderr).group(1))


def test_clip_original_sound_kept_and_ducked_under_dialogue(tmp_path):
    src = tmp_path / "clip.mp4"
    edit._run(["-f", "lavfi", "-i", "testsrc=size=720x1280:rate=24", "-f", "lavfi", "-i", "sine=f=300",
               "-t", "4", "-shortest", str(src)])
    assert edit.has_audio(src)
    silent = tmp_path / "silent.wav"
    edit._run(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "1", str(silent)])
    ev = [{"text": "", "start": 2.0, "end": 3.0, "audio": silent}]
    out = tmp_path / "seg.mp4"
    edit.render_cut(src, "video", 4.0, ev, [], out, clip_volume=0.7, clip_duck=0.2)
    before, during = _mean_db(out, 0.5, 1.0), _mean_db(out, 2.3, 0.5)
    assert before > -30                       # 원래 소리가 들어감
    assert before - during > 10               # 대사 동안 크게 줄어듦 (0.2배 ≈ -14dB)
    muted = tmp_path / "muted.mp4"
    edit.render_cut(src, "video", 4.0, ev, [], muted, clip_volume=0.0)
    assert _mean_db(muted, 0.5, 1.0) < -80    # clip_volume 0 이면 끔
