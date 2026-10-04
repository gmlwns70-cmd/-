from datetime import datetime, timezone

import pytest

from core import research
from core.config import UserFacingError


class FakeResp:
    def __init__(self, data, status=200):
        self._data, self.status_code, self.text = data, status, ""

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, params=None, timeout=None):
        endpoint = url.rsplit("/", 1)[-1]
        self.calls.append((endpoint, params))
        return self.routes[endpoint](params)


NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def make_session():
    return FakeSession({
        "search": lambda p: FakeResp({"items": [{"id": {"videoId": v}} for v in ("a", "b", "c")]}),
        "videos": lambda p: FakeResp({"items": [
            {"id": "a", "snippet": {"title": "홈카페 라떼 만들기", "channelTitle": "큰채널", "channelId": "C1",
                                    "publishedAt": "2026-09-21T00:00:00Z"},
             "statistics": {"viewCount": "100000"}, "contentDetails": {"duration": "PT10M"}},
            {"id": "b", "snippet": {"title": "홈카페 원두 추천", "channelTitle": "작은채널", "channelId": "C2",
                                    "publishedAt": "2026-09-30T00:00:00Z"},
             "statistics": {"viewCount": "50000"}, "contentDetails": {"duration": "PT8M30S"}},
            {"id": "c", "snippet": {"title": "짧은 영상", "channelTitle": "작은채널", "channelId": "C2",
                                    "publishedAt": "2026-09-30T00:00:00Z"},
             "statistics": {"viewCount": "999999"}, "contentDetails": {"duration": "PT50S"}},
        ]}),
        "channels": lambda p: FakeResp({"items": [
            {"id": "C1", "statistics": {"subscriberCount": "1000000"}},
            {"id": "C2", "statistics": {"subscriberCount": "1000"}},
        ]}),
    })


def test_search_sorts_by_ratio_and_filters_length():
    df = research.search_videos("홈카페", days=90, min_minutes=5, max_results=10,
                                api_key="x", session=make_session(), now=NOW)
    assert list(df["제목"]) == ["홈카페 원두 추천", "홈카페 라떼 만들기"]  # 짧은 영상 제외, 배율 50 > 0.1
    assert df.iloc[0]["배율(조회/구독)"] == 50.0
    assert df.iloc[0]["일평균조회수"] == 50000
    assert df.iloc[1]["일평균조회수"] == 10000  # 10일 경과


def test_quota_error_is_korean():
    s = FakeSession({"search": lambda p: FakeResp(
        {"error": {"errors": [{"reason": "quotaExceeded"}], "message": "quota"}}, status=403)})
    with pytest.raises(UserFacingError, match="쿼터"):
        research.search_videos("x", api_key="k", session=s)


def test_missing_key(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    with pytest.raises(UserFacingError, match="YOUTUBE_API_KEY"):
        research.search_videos("홈카페")


def test_parse_duration():
    assert research.parse_iso_duration("PT1H2M3S") == 3723
    assert research.parse_iso_duration("PT45S") == 45


def test_top_words():
    words = dict(research.top_title_words(["홈카페 라떼 만들기", "홈카페에서 라떼를", "The best latte"]))
    assert words["홈카페"] == 2 and words["라떼"] == 2
    assert "the" not in words
