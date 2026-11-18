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
