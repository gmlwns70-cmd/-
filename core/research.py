"""1단계: 트렌드 리서치 (YouTube Data API v3, 읽기 전용).

영상의 '숫자 정보'(조회수·구독자·게시일·제목)만 가져옵니다.
영상 파일이나 자막·스크립트는 가져오지 않습니다. 목적은 '어떤 주제에 수요가 있는가' 파악입니다.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

from .config import UserFacingError, get_key, load_config

API = "https://www.googleapis.com/youtube/v3"

STOPWORDS = {
    # 한국어 흔한 단어
    "그리고", "하는", "있는", "없는", "이런", "저런", "그런", "진짜", "정말", "너무", "이거", "그냥", "하기",
    "합니다", "했다", "하면", "해서", "에서", "으로", "까지", "부터", "대한", "위한", "모든", "가지",
    "영상", "오늘", "이제", "제가", "우리", "여러분", "ep", "편",
    # 영어 흔한 단어
    "the", "and", "for", "with", "you", "your", "this", "that", "how", "what", "from", "are",
    "shorts", "short", "vlog", "official", "video",
}
PARTICLES = ("으로", "에서", "까지", "부터", "은", "는", "이", "가", "을", "를", "의", "에", "로", "와", "과", "도", "만")


def _api_get(endpoint: str, params: dict, session=None) -> dict:
    http = session or requests
    try:
        resp = http.get(f"{API}/{endpoint}", params=params, timeout=30)
    except requests.RequestException as e:
        raise UserFacingError(f"❌ 인터넷 연결을 확인해 주세요. (YouTube 접속 실패: {e})") from e
    if resp.status_code == 200:
        return resp.json()
    try:
        err = resp.json().get("error", {})
        reason = (err.get("errors") or [{}])[0].get("reason", "")
        message = err.get("message", "")
    except ValueError:
        reason, message = "", resp.text[:200]
    if reason in ("quotaExceeded", "dailyLimitExceeded"):
        raise UserFacingError("❌ 오늘 YouTube API 사용량(쿼터)을 다 썼어요. 한국 시간 오후 4~5시쯤 초기화되니 내일 다시 해 주세요.\n"
                              "팁: '최대 결과 수'를 줄이면 쿼터를 덜 씁니다. (검색 1회 = 100 유닛, 하루 기본 10,000 유닛)")
    if reason in ("keyInvalid", "badRequest") and "key" in message.lower():
        raise UserFacingError("❌ YouTube API 키가 올바르지 않아요. .env 파일의 YOUTUBE_API_KEY 값을 다시 확인해 주세요.")
    if resp.status_code == 403 and reason in ("accessNotConfigured", "forbidden"):
        raise UserFacingError("❌ Google Cloud 콘솔에서 'YouTube Data API v3'를 '사용 설정'해야 해요. README의 API 키 받기 부분을 확인해 주세요.")
    raise UserFacingError(f"❌ YouTube API 오류 ({resp.status_code} {reason}): {message}")


def parse_iso_duration(value: str) -> float:
    """'PT1H2M30S' → 초 단위."""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value or "")
    if not m:
        return 0.0
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return float(d * 86400 + h * 3600 + mi * 60 + s)


def _chunks(items: list, n: int = 50):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def search_videos(keyword: str, days: int = 90, min_minutes: float = 0, max_results: int = 50,
                  api_key: str | None = None, session=None, now: datetime | None = None) -> pd.DataFrame:
    """키워드로 최근 N일 영상을 찾아 배율·일평균 조회수 순으로 정렬한 표를 돌려줍니다."""
    if not keyword.strip():
        raise UserFacingError("❌ 검색할 키워드를 입력해 주세요.")
    api_key = api_key or get_key("YOUTUBE_API_KEY")
    cfg = load_config()["research"]
    now = now or datetime.now(timezone.utc)
    published_after = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {
        "key": api_key, "part": "id", "type": "video", "q": keyword, "order": "viewCount",
        "publishedAfter": published_after, "maxResults": 50,
        "regionCode": cfg.get("region_code", "KR"), "relevanceLanguage": cfg.get("relevance_language", "ko"),
    }
    # 4~20분은 API의 medium 필터를 쓰면 20분 넘는 영상이 빠지므로, 길이 필터는 아래에서 직접 합니다.
    if min_minutes >= 20:
        params["videoDuration"] = "long"

    video_ids: list[str] = []
    page_token = None
    while len(video_ids) < max_results:
        if page_token:
            params["pageToken"] = page_token
        data = _api_get("search", params, session)
        for item in data.get("items", []):
            vid = item.get("id", {}).get("videoId")
            if vid and vid not in video_ids:
                video_ids.append(vid)
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    video_ids = video_ids[:max_results]
    if not video_ids:
        return pd.DataFrame(columns=COLUMNS)

    videos = []
    for chunk in _chunks(video_ids):
        data = _api_get("videos", {"key": api_key, "part": "snippet,statistics,contentDetails",
                                   "id": ",".join(chunk), "maxResults": 50}, session)
        videos.extend(data.get("items", []))

    channel_ids = sorted({v["snippet"]["channelId"] for v in videos})
    subs: dict[str, float] = {}
    for chunk in _chunks(channel_ids):
        data = _api_get("channels", {"key": api_key, "part": "statistics",
                                     "id": ",".join(chunk), "maxResults": 50}, session)
        for ch in data.get("items", []):
            st = ch.get("statistics", {})
            subs[ch["id"]] = float("nan") if st.get("hiddenSubscriberCount") else float(st.get("subscriberCount", 0))

    rows = []
    for v in videos:
        sn, st = v["snippet"], v.get("statistics", {})
        minutes = parse_iso_duration(v.get("contentDetails", {}).get("duration", "")) / 60
        if minutes < min_minutes:
            continue
        published = datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00"))
        age_days = max((now - published).total_seconds() / 86400, 1.0)
        views = float(st.get("viewCount", 0))
        sub = subs.get(sn["channelId"], float("nan"))
        ratio = views / sub if sub and sub == sub else float("nan")  # sub==sub: NaN 확인
        rows.append({
            "제목": sn.get("title", ""), "채널": sn.get("channelTitle", ""),
            "조회수": int(views), "구독자수": sub, "배율(조회/구독)": ratio,
            "일평균조회수": views / age_days, "길이(분)": round(minutes, 1),
            "게시일": published.strftime("%Y-%m-%d"), "URL": f"https://www.youtube.com/watch?v={v['id']}",
        })
    df = pd.DataFrame(rows, columns=COLUMNS)
    if df.empty:
        return df
    df = df.sort_values(["배율(조회/구독)", "일평균조회수"], ascending=False, na_position="last").reset_index(drop=True)
    df["배율(조회/구독)"] = df["배율(조회/구독)"].round(2)
    df["일평균조회수"] = df["일평균조회수"].round(0).astype(int)
    return df


COLUMNS = ["제목", "채널", "조회수", "구독자수", "배율(조회/구독)", "일평균조회수", "길이(분)", "게시일", "URL"]


def _strip_particle(word: str) -> str:
    if re.fullmatch(r"[가-힣]+", word) and len(word) >= 3:
        for p in PARTICLES:
            if word.endswith(p) and len(word) - len(p) >= 2:
                return word[: -len(p)]
    return word


def top_title_words(titles: list[str], n: int = 20) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for title in titles:
        words = {_strip_particle(w.lower()) for w in re.findall(r"[가-힣A-Za-z0-9]+", title or "")}
        for w in words:  # 한 제목에서 같은 단어는 1번만 셈
            if len(w) >= 2 and w not in STOPWORDS and not w.isdigit():
                counter[w] += 1
    return counter.most_common(n)


def save_csv(df: pd.DataFrame, path: Path) -> Path:
    # utf-8-sig: 엑셀에서 열어도 한글이 깨지지 않게
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path
