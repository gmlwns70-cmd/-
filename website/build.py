"""청남대 대추 정원 홈페이지 빌드 스크립트.

_pages/ 안의 본문 조각에 공통 헤더·푸터·SEO 태그를 입혀
website/ 폴더에 완성된 HTML 파일을 만듭니다.

사용법:  python3 build.py
사업 정보가 확정되면 아래 SITE 값만 채우고 다시 실행하세요.
빈 값("")은 홈페이지에 '등록 예정'으로 표시되며, 지어낸 값을 넣지 않습니다.
"""

from __future__ import annotations

import html
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAGES = ROOT / "_pages"

# ---------------------------------------------------------------------------
# 사업 정보 — 확인된 값만 입력하세요.
# ---------------------------------------------------------------------------
SITE = {
    "name": "청남대 대추 정원",
    "name_en": "CHEONGNAMDAE JUJUBE GARDEN",
    "region": "충청북도 청주시 상당구 문의면",
    "base_url": "",            # 예: "https://www.example.kr" (도메인 연결 후 입력 → canonical·sitemap 생성)
    "phone": "",               # 예: "010-0000-0000"
    "email": "",               # 문의 받을 이메일
    "kakao_url": "",           # 카카오톡 채널 주소
    "store_url": "",           # 스마트스토어 등 외부 결제 채널 주소 (있을 경우)
    "form_endpoint": "",       # 폼 접수 주소 (Formspree 등). 비어 있으면 '접수 미연결' 안내를 표시
    # 전자상거래법상 사업자 정보 표시 항목
    "biz_owner": "",           # 대표자
    "biz_number": "",          # 사업자등록번호
    "biz_mail_order": "",      # 통신판매업 신고번호
    "biz_address": "",         # 사업장 주소 (상세)
    "privacy_officer": "",     # 개인정보 보호책임자
    "policy_date": "",         # 개인정보 처리방침·이용약관 시행일 (예: "2026년 11월 1일")
}

PENDING = '<span class="pending">등록 예정</span>'

NAV = [
    ("brand", "brand.html", "브랜드 소개"),
    ("product", "product.html", "상품 안내"),
    ("grade", "grade.html", "상품 등급"),
    ("gift", "gift.html", "선물 세트"),
    ("reserve", "reserve.html", "예약 구매"),
    ("news", "news.html", "농장 소식"),
]

FOOTER_LINKS = [
    ("quality.html", "품질 정보 공개"),
    ("storage.html", "보관 및 이용 안내"),
    ("faq.html", "자주 묻는 질문"),
    ("contact.html", "고객 문의"),
]

LOGO_SVG = (
    '<svg viewBox="0 0 40 40" aria-hidden="true"><circle cx="20" cy="20" r="19" fill="currentColor" opacity=".1"/>'
    '<ellipse cx="20" cy="23" rx="10" ry="12" fill="#8f3422"/>'
    '<ellipse cx="17" cy="19" rx="2.6" ry="4" fill="#fff" opacity=".35"/>'
    '<path d="M20 11 C21 7 24.5 5 29 6 C27 10 24 11.5 20 11Z" fill="#5d8a5f"/></svg>'
)

ICONS = {
    "phone": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2"/></svg>',
    "chat": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 4c5 0 9 3.1 9 7s-4 7-9 7c-.9 0-1.8-.1-2.6-.3L5 20l1-3.7C4.2 15 3 13.1 3 11c0-3.9 4-7 9-7z"/></svg>',
    "mail": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/></svg>',
    "form": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h3"/></svg>',
    "store": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 9h16l-1 11H5L4 9z"/><path d="M9 9V7a3 3 0 0 1 6 0v2"/></svg>',
    "scale": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 4v16M5 20h14M4 9l3-5 3 5a3 3 0 0 1-6 0zM14 9l3-5 3 5a3 3 0 0 1-6 0zM7 4h10"/></svg>',
    "calendar": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>',
    "eye": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>',
    "gift": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="8" width="18" height="13" rx="1"/><path d="M12 8v13M3 12h18M12 8c-2-4-6-4-6-1.5S10 8 12 8zm0 0c2-4 6-4 6-1.5S14 8 12 8z"/></svg>',
    "leaf": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M5 19C5 10 10 5 20 4c0 10-5 15-14 15zM5 19l8-8"/></svg>',
    "box": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M3 7l9-4 9 4v10l-9 4-9-4V7z"/><path d="M3 7l9 4 9-4M12 11v10"/></svg>',
    "fridge": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="5" y="2" width="14" height="20" rx="2"/><path d="M5 9h14M8 5v2M8 12v3"/></svg>',
    "repeat": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M17 2l3 3-3 3"/><path d="M4 11V9a4 4 0 0 1 4-4h12M7 22l-3-3 3-3"/><path d="M20 13v2a4 4 0 0 1-4 4H4"/></svg>',
    "menu": '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h16"/></svg>',
}


def val(key: str) -> str:
    v = SITE.get(key, "")
    return html.escape(v) if v else PENDING


def contact_channels() -> str:
    """확인된 연락 채널만 노출하고, 없으면 '등록 예정'으로 표시."""
    items = []
    if SITE["phone"]:
        tel = re.sub(r"[^0-9+]", "", SITE["phone"])
        items.append(f'<a class="channel" href="tel:{tel}"><span class="card-icon">{ICONS["phone"]}</span><span><strong>전화 문의</strong><small>{html.escape(SITE["phone"])}</small></span></a>')
    if SITE["kakao_url"]:
        items.append(f'<a class="channel" href="{html.escape(SITE["kakao_url"])}" target="_blank" rel="noopener"><span class="card-icon">{ICONS["chat"]}</span><span><strong>카카오톡 채널</strong><small>채팅으로 편하게 문의하세요</small></span></a>')
    if SITE["email"]:
        items.append(f'<a class="channel" href="mailto:{html.escape(SITE["email"])}"><span class="card-icon">{ICONS["mail"]}</span><span><strong>이메일</strong><small>{html.escape(SITE["email"])}</small></span></a>')
    if SITE["store_url"]:
        items.append(f'<a class="channel" href="{html.escape(SITE["store_url"])}" target="_blank" rel="noopener"><span class="card-icon">{ICONS["store"]}</span><span><strong>온라인 스토어</strong><small>결제 가능한 판매 채널로 이동</small></span></a>')
    if not items:
        items.append(
            f'<div class="channel"><span class="card-icon">{ICONS["phone"]}</span><span><strong>전화 · 카카오톡 · 이메일</strong>'
            f'<small>공식 연락처는 확정 후 이곳에 안내합니다. {PENDING}</small></span></div>'
        )
    return '<div class="channels">' + "".join(items) + "</div>"


def mobile_bar() -> str:
    if SITE["phone"]:
        tel = re.sub(r"[^0-9+]", "", SITE["phone"])
        second = f'<a class="btn btn-line" href="tel:{tel}">전화 문의</a>'
    elif SITE["kakao_url"]:
        second = f'<a class="btn btn-line" href="{html.escape(SITE["kakao_url"])}" target="_blank" rel="noopener">카톡 문의</a>'
    else:
        second = '<a class="btn btn-line" href="contact.html">구매 문의</a>'
    return f'<nav class="mobile-bar" aria-label="빠른 메뉴"><a class="btn btn-primary" href="reserve.html">예약 신청</a>{second}</nav>'


def privacy_consent(purpose: str, items: str) -> str:
    return f"""
<div class="consent field">
  <p class="mb-0"><strong>개인정보 수집·이용 동의 (필수)</strong></p>
  <div class="table-wrap"><table>
    <tbody>
      <tr><th scope="row">수집 항목</th><td>{items}</td></tr>
      <tr><th scope="row">수집 목적</th><td>{purpose}</td></tr>
      <tr><th scope="row">보유 기간</th><td>목적 달성 후 지체 없이 파기 (관계 법령에 따라 보존이 필요한 경우 해당 기간까지)</td></tr>
    </tbody>
  </table></div>
  <p class="small text-muted">동의를 거부할 수 있으며, 거부 시 신청 및 상담이 제한됩니다. 자세한 내용은 <a href="privacy.html">개인정보 처리방침</a>을 확인해 주세요.</p>
  <label class="check"><input type="checkbox" name="agree_privacy" value="동의" data-label="개인정보 수집·이용 동의(필수)" required> <span>위 내용을 확인했으며 개인정보 수집·이용에 동의합니다. <span class="req">(필수)</span></span></label>
  <p class="error" role="alert"></p>
</div>
<div class="consent">
  <label class="check"><input type="checkbox" name="agree_marketing" value="동의" data-label="수확·예약 소식 수신 동의(선택)"> <span>수확 시작, 예약 오픈 등 농장 소식을 문자·카카오톡으로 받겠습니다. <span class="text-muted">(선택 · 동의하지 않아도 신청 가능 · 언제든 철회 가능)</span></span></label>
</div>
<input type="text" name="_hp" tabindex="-1" autocomplete="off" aria-hidden="true" style="position:absolute;left:-9999px">
"""


TOKENS = {
    "{{CONTACT_CHANNELS}}": contact_channels,
    "{{PRIVACY_OFFICER}}": lambda: val("privacy_officer"),
    "{{POLICY_DATE}}": lambda: val("policy_date"),
    "{{BIZ_NAME}}": lambda: html.escape(SITE["name"]),
    "{{CONSENT_RESERVE}}": lambda: privacy_consent(
        "예약 접수, 수확·발송 일정 안내, 주문 확인 연락", "이름, 연락처, 받는 분 주소(선물 시 받는 분 정보 포함), 요청사항"),
    "{{CONSENT_CONTACT}}": lambda: privacy_consent(
        "문의 확인 및 답변", "이름, 연락처, 이메일(선택), 문의 내용"),
    "{{CONSENT_NOTIFY}}": lambda: privacy_consent(
        "수확 시작·예약 오픈 알림 발송", "이름, 연락처"),
}
for k, svg in ICONS.items():
    TOKENS["{{ICON_" + k.upper() + "}}"] = (lambda s=svg: s)


def parse_page(path: Path) -> tuple[dict, str]:
    raw = path.read_text(encoding="utf-8")
    m = re.match(r"\s*<!--(.*?)-->\s*", raw, re.S)
    meta = {}
    if m:
        for line in m.group(1).strip().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        raw = raw[m.end():]
    return meta, raw


def render(slug: str, meta: dict, body: str) -> str:
    for token, fn in TOKENS.items():
        if token in body:
            body = body.replace(token, fn())
    leftover = re.findall(r"\{\{[A-Z_]+\}\}", body)
    if leftover:
        raise SystemExit(f"{slug}: 처리되지 않은 토큰 {leftover}")

    name = SITE["name"]
    title = meta.get("title", name)
    full_title = title if slug == "index" else f"{title} | {name}"
    desc = meta.get("description", "")
    active = meta.get("nav", "")
    filename = "index.html" if slug == "index" else f"{slug}.html"
    base = SITE["base_url"].rstrip("/")
    url = f"{base}/{'' if slug == 'index' else filename}" if base else ""

    nav_items = []
    for key, href, label in NAV:
        cur = ' aria-current="page"' if key == active else ""
        nav_items.append(f'<li><a href="{href}"{cur}>{label}</a></li>')
    cur = ' aria-current="page"' if active == "contact" else ""
    nav_items.append(f'<li class="gnb-cta"><a href="contact.html"{cur}>고객 문의</a></li>')

    head_extra = []
    if url:
        head_extra.append(f'<link rel="canonical" href="{url}">')
        head_extra.append(f'<meta property="og:url" content="{url}">')
    if meta.get("noindex"):
        head_extra.append('<meta name="robots" content="noindex">')
    if slug == "index":
        ld = {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": name,
            "description": desc,
            "address": {"@type": "PostalAddress", "addressCountry": "KR",
                        "addressRegion": "충청북도", "addressLocality": "청주시 상당구 문의면"},
        }
        if url:
            ld["url"] = url
        if SITE["phone"]:
            ld["telephone"] = SITE["phone"]
        head_extra.append('<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + "</script>")
    if meta.get("faq_ld"):
        qa = re.findall(r"<summary>(.*?)</summary>\s*<div class=\"answer\">(.*?)</div>", body, re.S)
        ld = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": re.sub(r"<.*?>", "", q).strip(),
             "acceptedAnswer": {"@type": "Answer", "text": re.sub(r"\s+", " ", re.sub(r"<.*?>", "", a)).strip()}}
            for q, a in qa]}
        head_extra.append('<script type="application/ld+json">' + json.dumps(ld, ensure_ascii=False) + "</script>")

    footer_links = "".join(f'<li><a href="{h}">{t}</a></li>' for h, t in FOOTER_LINKS)
    nav_footer = "".join(f'<li><a href="{h}">{t}</a></li>' for _, h, t in NAV)
    year = date.today().year

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{html.escape(full_title)}</title>
<meta name="description" content="{html.escape(desc)}">
<meta name="theme-color" content="#1c3527">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{name}">
<meta property="og:title" content="{html.escape(full_title)}">
<meta property="og:description" content="{html.escape(desc)}">
<meta property="og:locale" content="ko_KR">
{chr(10).join(head_extra)}
<link rel="icon" href="assets/img/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@500;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css">
<link rel="stylesheet" href="assets/css/style.css">
</head>
<body data-form-endpoint="{html.escape(SITE['form_endpoint'])}" data-email="{html.escape(SITE['email'])}">
<a class="skip-link" href="#main">본문 바로가기</a>
<header class="site-header">
  <div class="wrap">
    <a class="logo" href="index.html" aria-label="{name} 홈">{LOGO_SVG}<span><span class="logo-text">{name}</span><span class="logo-sub">{SITE['name_en']}</span></span></a>
    <button class="menu-btn" type="button" aria-expanded="false" aria-controls="gnb" aria-label="메뉴 열기">{ICONS['menu']}</button>
    <nav class="gnb" id="gnb" aria-label="주 메뉴"><ul>{''.join(nav_items)}</ul></nav>
  </div>
</header>
<main id="main">
{body.strip()}
</main>
<footer class="site-footer">
  <div class="wrap">
    <div class="footer-top">
      <div class="footer-brand">
        <a class="logo" href="index.html">{LOGO_SVG}<span><span class="logo-text">{name}</span><span class="logo-sub">{SITE['name_en']}</span></span></a>
        <p>문의의 햇살과 정성을 담아,<br>한 알 한 알 제대로 키웁니다.</p>
      </div>
      <div><h2>둘러보기</h2><ul>{nav_footer}</ul></div>
      <div><h2>고객 안내</h2><ul>{footer_links}</ul></div>
    </div>
    <div class="footer-legal">
      <div class="policy-links"><a href="privacy.html">개인정보 처리방침</a><a href="terms.html">이용약관</a></div>
      <dl>
        <div><dt>상호</dt><dd>{name}</dd></div>
        <div><dt>대표자</dt><dd>{val('biz_owner')}</dd></div>
        <div><dt>사업자등록번호</dt><dd>{val('biz_number')}</dd></div>
        <div><dt>통신판매업 신고번호</dt><dd>{val('biz_mail_order')}</dd></div>
      </dl>
      <dl>
        <div><dt>주소</dt><dd>{html.escape(SITE['biz_address']) if SITE['biz_address'] else html.escape(SITE['region'])}</dd></div>
        <div><dt>전화</dt><dd>{val('phone')}</dd></div>
        <div><dt>이메일</dt><dd>{val('email')}</dd></div>
      </dl>
      <p class="copyright">© {year} {name}. All rights reserved.</p>
    </div>
  </div>
</footer>
{mobile_bar()}
<script src="assets/js/main.js" defer></script>
</body>
</html>
"""


def main() -> None:
    built = []
    for path in sorted(PAGES.glob("*.html")):
        slug = path.stem
        meta, body = parse_page(path)
        out = ROOT / ("index.html" if slug == "index" else f"{slug}.html")
        out.write_text(render(slug, meta, body), encoding="utf-8")
        built.append((slug, meta))
        print(f"생성: {out.name}")

    base = SITE["base_url"].rstrip("/")
    robots = "User-agent: *\nAllow: /\n"
    if base:
        urls = "".join(
            f"  <url><loc>{base}/{'' if s == 'index' else s + '.html'}</loc></url>\n"
            for s, m in built if not m.get("noindex")
        )
        (ROOT / "sitemap.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + urls + "</urlset>\n",
            encoding="utf-8")
        robots += f"Sitemap: {base}/sitemap.xml\n"
        print("생성: sitemap.xml")
    else:
        print("안내: SITE['base_url']이 비어 있어 sitemap.xml·canonical은 생성하지 않았습니다.")
    (ROOT / "robots.txt").write_text(robots, encoding="utf-8")


if __name__ == "__main__":
    main()
