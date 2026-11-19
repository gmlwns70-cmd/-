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


def test_plan_transitions_modes():
    cuts = [{"location": "bus stop", "time_of_day": "evening"},
            {"location": "bus stop", "time_of_day": "evening"},
            {"location": "shop", "time_of_day": "evening"},
            {"location": "shop", "time_of_day": "next morning"},
            {"location": "shop", "time_of_day": "next morning", "transition": "flash_white"},
            {"location": "park", "time_of_day": "noon"}]
    assert edit.plan_transitions(cuts, "auto") == ["cut", "dissolve", "fade_black", "cut", "flash_white"]
    assert edit.plan_transitions(cuts, "none") == ["cut"] * 5
    assert edit.plan_transitions(cuts, "slide") == ["slide"] * 5


def test_transitions_keep_total_length_and_subtitle_timing(tmp_path):
    series = copy.deepcopy(SAMPLE)
    series["episodes"][0]["cuts"] = series["episodes"][0]["cuts"][3:7]   # dissolve, fade_black, flash_white 포함
    cfg = _cfg()
    final = edit.edit_episode(tmp_path, series, 1, cfg, tts=False, log=lambda *_: None)
    total = sum(c["seconds"] for c in series["episodes"][0]["cuts"])
    assert abs(edit.media_duration(final) - total) < 0.15
    srt = (tmp_path / "05_자막_EP01.srt").read_text(encoding="utf-8")
    assert "00:00:00,300 --> " in srt and "00:00:12,900 --> " in srt   # 컷6 대사는 fade_black(0.8초)이 끝난 뒤


def test_join_mixed_cut_then_transitions(tmp_path):
    """바로 넘어가기(cut) 뒤에 전환 효과가 오는 순서 (실제 샘플에서 나왔던 오류 재현)."""
    lengths, trans = [1.0, 1.0, 1.0, 1.0], ["cut", "dissolve", "cut"]
    pads = [edit.TRANSITIONS[t][1] for t in trans] + [0.0]
    segs = []
    for i, (L, pad) in enumerate(zip(lengths, pads)):
        seg = tmp_path / f"s{i}.mp4"
        edit._run(["-f", "lavfi", "-i", f"color=c=red:s={edit.W}x{edit.H}:r={edit.FPS}", "-f", "lavfi",
                   "-i", "anullsrc=r=44100:cl=stereo", "-t", f"{L + pad}", "-c:v", "libx264", "-pix_fmt",
                   "yuv420p", "-c:a", "aac", str(seg)])
        segs.append(seg)
    out = tmp_path / "joined.mp4"
    edit.join_segments(segs, lengths, trans, out, end_fade=0.5)
    assert abs(edit.media_duration(out) - 4.0) < 0.15


def test_failed_tts_leaves_no_broken_cache(tmp_path):
    series = copy.deepcopy(SAMPLE)
    series["episodes"][0]["cuts"] = series["episodes"][0]["cuts"][1:2]   # 대사 있는 컷 하나

    def broken(text, voice, out):
        out.write_bytes(b"")                     # edge-tts 가 실패할 때처럼 빈 파일을 남김
        raise OSError("network down")

    edit.edit_episode(tmp_path, series, 1, _cfg(), tts=True, synth=broken, log=lambda *_: None)
    assert not [f for f in (tmp_path / "_편집작업" / "EP01").glob("*.mp3")]
    final = edit.edit_episode(tmp_path, series, 1, _cfg(), tts=True, synth=_tone, log=lambda *_: None)
    assert edit.media_duration(final) > 1


def test_duck_expr_merges_close_spans():
    assert edit.duck_volume_expr([], 0.4) == "" and edit.duck_volume_expr([(1, 2)], 1.0) == ""
    e = edit.duck_volume_expr([(1.0, 2.0), (3.0, 4.0), (6.0, 7.0)], 0.4)
    assert e.count("clip((t-") == 2 and "1-0.600*" in e      # 1~4초는 하나로 합쳐짐 (간격 1초)


def test_bgm_ducked_under_dialogue(tmp_path):
    series = copy.deepcopy(SAMPLE)
    series["episodes"][0]["cuts"] = series["episodes"][0]["cuts"][:2]   # 컷1 대사 없음, 컷2 대사 5.3~9.7초
    (tmp_path / "clips").mkdir()
    edit._run(["-f", "lavfi", "-i", "sine=f=330", "-t", "15", str(tmp_path / "clips" / "bgm.mp3")])
    cfg = _cfg()
    cfg["edit"]["end_fade"] = 0
    final = edit.edit_episode(tmp_path, series, 1, cfg, tts=False, log=lambda *_: None)
    quiet_part, talk_part = _mean_db(final, 1.5, 2.0), _mean_db(final, 6.5, 2.0)
    assert quiet_part - talk_part > 6        # 0.4배 ≈ -8dB


# ── 자막 디자인 ─────────────────────────────────────────
from dramamaker import subtitle_style  # noqa: E402


def _font():
    return edit.find_font(settings.BASE_DIR / "fonts")


def test_char_colors_warm_for_women_cool_for_men():
    c = subtitle_style.char_colors(SAMPLE["bible"])
    assert c["haeun"] in subtitle_style.FEMALE_COLORS and c["dojun"] in subtitle_style.MALE_COLORS
    assert subtitle_style.char_colors(SAMPLE["bible"], {"dojun": "#123456"})["dojun"] == "#123456"


def test_balanced_wrap_keeps_lines_even():
    from PIL import ImageFont
    font = ImageFont.truetype(str(_font()), 58)
    text = "내일도 비 온다던데. 그럼 우산 하나 더 챙겨 와요, 같이 쓰게."
    lines = subtitle_style.balanced_wrap(text, font)
    assert len(lines) == 2 and "".join(lines).replace(" ", "") == text.replace(" ", "")
    w = [font.getlength(l) for l in lines]
    assert max(w) - min(w) < 200
    assert all(font.getlength(l) <= subtitle_style.MAX_W for l in subtitle_style.wrap_px("가" * 80, font))


def test_all_styles_render_inside_safe_area(tmp_path):
    from PIL import Image
    for style in subtitle_style.STYLES:
        p = tmp_path / f"{style}.png"
        subtitle_style.render("그 우산, 제 건데요.", _font(), p, style, 58, "한하은", "#FF8FB1")
        box = Image.open(p).getchannel("A").point(lambda a: 255 if a > 100 else 0).getbbox()  # 옅은 그림자 제외
        assert box and box[1] > 1100 and box[3] <= subtitle_style.BOTTOM + 40, (style, box)


# ── 썸네일 ─────────────────────────────────────────────
from dramamaker import thumbnail  # noqa: E402


def test_thumb_lines():
    assert thumbnail.thumb_lines({"thumbnail_text": "우산 하나에\n심장이 철렁", "title": "x"}) == ["우산 하나에", "심장이 철렁"]
    assert thumbnail.thumb_lines({"title": "비 오는 날 우산을 둘러싼 오해"}) == ["비 오는 날", "우산을 둘러싼 오해"]
    assert thumbnail.thumb_lines({"title": "짧은 제목"}) == ["짧은 제목"]


def test_make_thumbnails_sizes_and_background_priority(tmp_path):
    from PIL import Image
    series = copy.deepcopy(SAMPLE)
    clip = tmp_path / "clips" / "EP01"
    clip.mkdir(parents=True)
    logs = []
    files = thumbnail.make_thumbnails(tmp_path, series, 1, _cfg(), log=logs.append)   # 아무것도 없음 → 기본 배경
    assert [Image.open(f).size for f in files] == [(1080, 1920), (1280, 720)] and "기본 배경" in logs[-1]
    Image.new("RGB", (640, 360), "red").save(clip / "cut03.png")
    thumbnail.make_thumbnails(tmp_path, series, 1, _cfg(), log=logs.append)          # 인물 많은 컷이 없어 cut03
    assert "컷 3 이미지" in logs[-1]
    edit._run(["-f", "lavfi", "-i", "color=c=blue:s=720x1280:r=24", "-t", "2", str(clip / "cut01.mp4")])
    thumbnail.make_thumbnails(tmp_path, series, 1, _cfg(), log=logs.append)          # thumbnail_cut=1 영상 우선
    assert "컷 1 영상" in logs[-1]
    Image.new("RGB", (1080, 1920), "green").save(clip / "thumb.png")
    files = thumbnail.make_thumbnails(tmp_path, series, 1, _cfg(), log=logs.append)  # 직접 고른 장면이 최우선
    assert "직접 고른 장면" in logs[-1]
    assert Image.open(files[0]).getpixel((540, 700))[1] > 100                         # 초록 배경이 실제로 쓰임


# ── 업로드 문구 ─────────────────────────────────────────
from dramamaker import upload  # noqa: E402


def test_upload_tags_clean_dedup_and_limits():
    series = copy.deepcopy(SAMPLE)
    ep = series["episodes"][0]
    ep["upload"]["hashtags"] = ["#로맨스", "로맨스", "설렘 주의", "숏드라마"] + [f"태그{i}" for i in range(30)]
    b = upload.build(series, ep)
    yt = [w for w in b["youtube"]["description"].split() if w.startswith("#")]
    assert yt[:2] == ["#Shorts", "#우산은하나뿐"] and "#설렘주의" in yt and len(yt) == upload.YT_TAG_MAX
    assert len(yt) == len(set(yt))
    ig = [w for w in b["instagram"].split() if w.startswith("#")]
    assert len(ig) == upload.IG_TAG_MAX and "#숏드라마" in ig
    tt = [w for w in b["tiktok"].split() if w.startswith("#")]
    assert "#숏드라마" in tt and "#웹드라마" in tt


def test_upload_fallback_without_claude_text():
    series = copy.deepcopy(SAMPLE)
    ep = series["episodes"][0]
    del ep["upload"]
    b = upload.build(series, ep)
    assert "우산은 하나뿐 EP.01" in b["titles"][0] and b["youtube"]["description"]


def test_upload_text_command_and_fake_regen(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path)
    assert main.main(["sample"]) == 0
    out = next(tmp_path.iterdir())
    text = (out / "07_업로드문구_EP01.txt").read_text(encoding="utf-8")
    assert "변경되거나 합성된 콘텐츠" in text and "#Shorts" in text

    class Fake(FakeClient):
        @contextmanager
        def _stream(self, **params):
            self.calls.append(params)
            data = {"titles": ["새 제목"], "description": "새 설명", "hashtags": ["새태그"]}
            msg = SimpleNamespace(stop_reason="end_turn",
                                  content=[SimpleNamespace(type="text", text=json.dumps(data, ensure_ascii=False))])
            yield SimpleNamespace(get_final_message=lambda: msg)
    fake = Fake()
    series = json.loads((out / "series.json").read_text(encoding="utf-8"))
    up = generate.make_upload(_cfg(), series, series["episodes"][0], client=fake)
    assert up["titles"] == ["새 제목"] and fake.calls[0]["output_config"]["format"]["schema"] is generate.UPLOAD
    assert "그 우산, 제 건데요." in fake.calls[0]["messages"][0]["content"]


def test_requirements_files_readable_on_korean_windows():
    """한국어 윈도우의 pip 는 requirements.txt 를 cp949 로 읽습니다. 한글이 있으면 설치가 깨집니다."""
    root = Path(__file__).resolve().parents[2]
    for f in (root / "requirements.txt", root / "cardnews" / "requirements.txt",
              root / "drama" / "requirements.txt"):
        f.read_bytes().decode("ascii")


# ── 목소리 자동 대체 ───────────────────────────────────
def test_voice_engine_falls_back_to_windows_and_keeps_it(tmp_path, monkeypatch):
    calls = []

    def edge_blocked(text, voice, out):
        calls.append("edge")
        out.write_bytes(b"")
        raise OSError("[WinError 64] 지정된 네트워크 이름을 더 이상 사용할 수 없습니다")

    def windows_ok(text, voice, out):
        calls.append("windows")
        _tone(text, voice, out)

    monkeypatch.setattr(edit, "edge_tts_synth", edge_blocked)
    monkeypatch.setattr(edit, "windows_tts_synth", windows_ok)
    monkeypatch.setattr(edit.VoiceEngine, "ENGINES", {"edge": edge_blocked, "windows": windows_ok})
    monkeypatch.setattr(edit.VoiceEngine, "WAIT", 0)
    series = copy.deepcopy(SAMPLE)
    series["episodes"][0]["cuts"] = series["episodes"][0]["cuts"][1:4]   # 대사 있는 컷 3개
    logs = []
    edit.edit_episode(tmp_path, series, 1, _cfg(), tts=True, log=logs.append)
    assert calls == ["edge"] * edit.VoiceEngine.RETRIES + ["windows"] * 3   # 몇 번 재시도 후 윈도우로, 이후엔 바로 윈도우
    assert any("윈도우 기본 한국어 목소리로 만들어요" in l for l in logs)
    assert "음성 3/3컷 (윈도우 기본 목소리)" in logs[-1]
    mp3s = sorted((tmp_path / "_편집작업" / "EP01").glob("*.mp3"))
    assert len(mp3s) == 3 and all(m.stat().st_size > 0 for m in mp3s)
    srt = (tmp_path / "05_자막_EP01.srt").read_text(encoding="utf-8")
    assert "확실해요?" in srt


def test_voice_engine_modes_and_windows_guard(tmp_path):
    assert edit.VoiceEngine("windows").name == "windows" and edit.VoiceEngine("edge").name == "edge"
    assert [n for n, _ in edit.VoiceEngine("auto").order] == ["edge", "windows"]
    assert edit.is_male_voice({"voice": edit.MALE}) and not edit.is_male_voice({"voice": edit.FEMALE})
    import sys
    if sys.platform != "win32":
        try:
            edit.windows_tts_synth("안녕", {"voice": edit.FEMALE}, tmp_path / "a.mp3")
            assert False, "윈도우가 아니면 안내 오류가 나야 함"
        except edit.EditError as e:
            assert "윈도우" in str(e)


def test_flaky_internet_voice_recovers_with_retry(tmp_path, monkeypatch):
    """사용자 PC 처럼 연결이 가끔 끊길 때: 재시도로 살아나면 윈도우 목소리로 바꾸지 않음."""
    state = {"n": 0}

    def edge_flaky(text, voice, out):
        state["n"] += 1
        if state["n"] % 2 == 0:                     # 두 번에 한 번 끊김
            raise OSError("connection reset")
        _tone(text, voice, out)

    def windows_never(text, voice, out):
        raise AssertionError("윈도우 목소리로 바뀌면 안 됨")

    monkeypatch.setattr(edit.VoiceEngine, "ENGINES", {"edge": edge_flaky, "windows": windows_never})
    monkeypatch.setattr(edit.VoiceEngine, "WAIT", 0)
    series = copy.deepcopy(SAMPLE)
    series["episodes"][0]["cuts"] = series["episodes"][0]["cuts"][1:4]
    logs = []
    edit.edit_episode(tmp_path, series, 1, _cfg(), tts=True, log=logs.append)
    assert "음성 3/3컷" in logs[-1] and "윈도우" not in logs[-1]


def test_voice_summary_is_honest():
    assert edit._voice_summary(2, 5, {"edge"}) == " / 음성 2/5컷"
    assert edit._voice_summary(0, 5, set()) == " / 음성 없음(자막만)"
    assert "섞임" in edit._voice_summary(5, 5, {"edge", "windows"})
    assert edit._voice_summary(0, 0, set()) == " / 대사 없음"


# ── Claude 대화창 연결 ─────────────────────────────────
from dramamaker import chat_bridge  # noqa: E402


def test_chat_prompt_contains_rules_and_example():
    text = chat_bridge.build_prompt(_cfg(episodes=2, seconds=60), "꽃집 사장과 건축가")
    assert "꽃집 사장과 건축가" in text and "2회" in text and "```json" in text
    assert "look_en" in text and "thumbnail_text" in text and "다음 화" in text


def test_extract_json_handles_messy_answers():
    body = json.dumps({"bible": {"title": "t"}, "episodes": []}, ensure_ascii=False)
    assert chat_bridge.extract_json(f"네, 써 드릴게요!\n```json\n{body}\n```\n즐거운 제작 되세요")["bible"]["title"] == "t"
    assert chat_bridge.extract_json('{"a": [1, 2,], "b": 1,}') == {"a": [1, 2], "b": 1}   # 끝 쉼표
    for bad, word in (('{"bible": {"title": "끊김"', "끊긴"), ("그냥 글", "찾지 못했어요")):
        try:
            chat_bridge.extract_json(bad)
            assert False
        except chat_bridge.ImportError_ as e:
            assert word in str(e)


def test_normalize_fills_missing_fields():
    raw = {"bible": {"title": "제목", "characters": [{"name": "소담", "age": "29세"}]},
           "episodes": [{"title": "1화", "thumbnail_text": "첫 줄\\n둘째 줄",
                         "cuts": [{"seconds": "5초", "dialogue": [{"speaker": "소담", "line": " 안녕 "}, "잘못된 값"]}]}]}
    s = chat_bridge.normalize(raw, _cfg())
    c = s["bible"]["characters"][0]
    assert c["id"] == "char1" and c["age"] == 29 and c["look_en"] == ""
    cut = s["episodes"][0]["cuts"][0]
    assert cut["seconds"] == 5 and cut["dialogue"] == [{"speaker": "소담", "line": "안녕"}] and cut["subtitle"] == "안녕"
    assert cut["transition"] == "cut" and s["episodes"][0]["thumbnail_text"] == "첫 줄\n둘째 줄"


def test_import_new_series_then_next_episode_from_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path / "output")
    first = copy.deepcopy(chat_bridge.EXAMPLE)
    f1 = tmp_path / "answer1.txt"
    f1.write_text("답변입니다\n```json\n" + json.dumps(first, ensure_ascii=False) + "\n```", encoding="utf-8")
    assert main.main(["import", "--file", str(f1)]) == 0
    out = next((tmp_path / "output").iterdir())
    assert (out / "04_뉴테이크_프롬프트_EP01.txt").exists() and (out / "07_업로드문구_EP01.txt").exists()
    nxt = {"episodes": [dict(copy.deepcopy(first["episodes"][0]), no=2, title="둘째 날")]}
    f2 = tmp_path / "answer2.txt"
    f2.write_text(json.dumps(nxt, ensure_ascii=False), encoding="utf-8")
    assert main.main(["import", "--file", str(f2)]) == 0           # 최근 시리즈에 2화 붙이기
    series = json.loads((out / "series.json").read_text(encoding="utf-8"))
    assert [e["no"] for e in series["episodes"]] == [1, 2] and (out / "02_대본_EP02.md").exists()
    assert main.main(["edit", "--no-tts", "--episode", "2"]) == 0    # 폴더를 안 써도 최근 폴더 편집
    assert (out / "05_완성_EP02.mp4").exists()


def test_bat_files_call_existing_commands():
    root = Path(__file__).resolve().parent.parent
    text = "".join(f.read_text(encoding="utf-8") for f in root.glob("[123]_*.bat"))
    for cmd in ("main.py chat-prompt", "main.py import", "main.py edit"):
        assert cmd in text


def test_character_portrait_prompt_forbids_text(tmp_path):
    """실제 뉴테이크(Seedream)에서 인물 사진 구석에 한글 소개 글이 찍혀 나온 문제 재발 방지."""
    p = tmp_path / "chars.md"
    export.write_characters(p, SAMPLE["bible"], _cfg())
    text = p.read_text(encoding="utf-8")
    assert text.count("No text, no letters, no captions, no logo, no watermark.") == len(SAMPLE["bible"]["characters"])


def test_full_prompt_drops_korean_fields_and_double_periods():
    """실제 대본: 장소·카메라·감정을 한국어로 써서 영어 프롬프트에 한글이 섞였던 문제."""
    bible = copy.deepcopy(SAMPLE["bible"])
    bible["characters"][0]["look_en"] += "."                       # 끝에 마침표가 있어도 '..' 가 되지 않게
    cut = dict(SAMPLE["episodes"][0]["cuts"][1], location="골목 끝 소담화원 가게 앞", camera_move="핸드헬드",
               time_of_day="늦은 오후, 폭우", emotion="당황")
    p = export.full_prompt(cut, bible, _cfg(), "image")
    assert not export.HANGUL.search(p) and ".." not in p
    assert "Shot: medium close-up." in p and "Setting" not in p and "Mood" not in p
    p2 = export.full_prompt(SAMPLE["episodes"][0]["cuts"][1], SAMPLE["bible"], _cfg(), "video")
    assert "Setting: bus stop, rainy evening." in p2 and "camera: static" in p2   # 영어로 쓴 항목은 그대로


def test_image_prompt_starts_with_scene_not_portrait():
    """실제 뉴테이크: 외모 설명이 앞에 오면 참조 사진을 베낀 증명사진이 나왔다 → 장면이 먼저."""
    cut = SAMPLE["episodes"][0]["cuts"][1]
    img = export.full_prompt(cut, SAMPLE["bible"], _cfg(), "image")
    assert img.startswith("Same person as in the reference image") and "Not a studio portrait" in img
    assert img.index("New scene:") < img.index(cut["image_prompt_en"][:20]) < img.index("Appearance —")
    vid = export.full_prompt(cut, SAMPLE["bible"], _cfg(), "video")
    assert vid.startswith("Characters —") and "studio portrait" not in vid
    no_char = dict(cut, characters=[])
    assert not export.full_prompt(no_char, SAMPLE["bible"], _cfg(), "image").startswith("Same person")
