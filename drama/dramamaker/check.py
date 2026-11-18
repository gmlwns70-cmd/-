"""만들어진 대본이 숏폼 규칙에 맞는지 검사하고, 고칠 수 있는 건 자동으로 고칩니다."""
from __future__ import annotations


def fix(series: dict, cfg: dict) -> None:
    """컷 길이를 허용 범위로 맞추고, 설정집에 없는 인물 id 는 이름으로 찾아 바꾸거나 뺍니다."""
    chars = series["bible"]["characters"]
    ids = {c["id"] for c in chars}
    by_name = {c["name"]: c["id"] for c in chars}
    for ep in series["episodes"]:
        for c in ep["cuts"]:
            c["seconds"] = max(cfg["cut_min"], min(cfg["cut_max"], int(c["seconds"])))
            c["characters"] = [cid if cid in ids else by_name.get(cid, "") for cid in c["characters"]]
            c["characters"] = [cid for cid in dict.fromkeys(c["characters"]) if cid]
            for d in c["dialogue"]:
                if d["speaker"] not in ids and d["speaker"] in by_name:
                    d["speaker"] = by_name[d["speaker"]]


def report(series: dict, cfg: dict) -> str:
    target = cfg["seconds"]
    lines = ["── 검수 리포트 ──"]
    ok = True
    for ep in series["episodes"]:
        total = sum(c["seconds"] for c in ep["cuts"])
        warn = []
        if abs(total - target) > target * 0.15:
            warn.append(f"총 길이 {total}초 (목표 {target}초와 차이 큼)")
        if not ep["cuts"]:
            warn.append("컷이 없음")
        else:
            if not ep["cuts"][0]["characters"]:
                warn.append("1번 컷(hook)에 인물이 없음 — 첫 3초에 얼굴이 나오는 게 좋아요")
            for c in ep["cuts"]:
                talk = sum(len(d["line"].replace(" ", "")) for d in c["dialogue"])
                if talk > c["seconds"] * 6:  # 한국어 대략 초당 6글자
                    warn.append(f"컷 {c['no']}: 대사({talk}자)가 {c['seconds']}초 안에 말하기엔 길어요")
        mark = "✅" if not warn else "⚠"
        ok &= not warn
        lines.append(f"{mark} EP{ep['no']:02d} {ep['title']} — {len(ep['cuts'])}컷, {total}초")
        lines += [f"    - {w}" for w in warn]
    lines.append("모든 회차가 기준을 통과했어요." if ok else "⚠ 표시는 series.json 을 고친 뒤 'python main.py export 폴더' 로 다시 내보낼 수 있어요.")
    return "\n".join(lines)
