/* 산마루랩 – 화면 그리기와 동작. 내용 수정은 content.js 에서 하세요. */
(function () {
  'use strict';

  var S = window.SITE;
  if (!S) return;

  /* ── 도움 함수 ─────────────────────────────── */
  function esc(str) {
    return String(str == null ? '' : str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
  // 줄바꿈(\n)을 화면 줄바꿈으로
  function text(str) {
    return esc(str).replace(/\n/g, ' <br>');
  }
  // [가격] 처럼 대괄호로 된 빈 자리인지
  function isPlaceholder(str) {
    return !str || /^\s*\[[^\]]*\]\s*$/.test(str);
  }
  // [빈 자리] 글자는 눈에 띄게 표시
  function value(str) {
    return text(str).replace(/\[[^\]]*\]/g, function (m) {
      return '<span class="ph">' + m + '</span>';
    });
  }
  function get(path) {
    return path.split('.').reduce(function (o, k) { return o ? o[k] : undefined; }, S);
  }
  function $(sel) { return document.querySelector(sel); }

  /* ── 사진 (없으면 회색 자리표시 상자) ──────────── */
  function photoHtml(src, alt, placeholder, eager) {
    return (
      '<div class="photo-frame">' +
        '<img src="' + esc(src) + '" alt="' + esc(alt) + '" width="800" height="1000" decoding="async"' +
        (eager ? ' fetchpriority="high"' : ' loading="lazy"') + '>' +
        '<div class="photo-placeholder" role="img" aria-label="' + esc(alt) + ' (사진 준비 중)">' +
          '<span>' + esc(placeholder) + '</span>' +
        '</div>' +
      '</div>'
    );
  }
  function wirePhotos() {
    document.querySelectorAll('.photo-frame').forEach(function (frame) {
      var img = frame.querySelector('img');
      function ok() { frame.classList.add('has-photo'); }
      function fail() { frame.classList.remove('has-photo'); img.remove(); }
      if (!img.getAttribute('src')) return fail();
      if (img.complete) { img.naturalWidth > 0 ? ok() : fail(); }
      else {
        img.addEventListener('load', ok);
        img.addEventListener('error', fail);
      }
    });
  }

  /* ── 단순 글자 채우기 (data-text="경로") ────────── */
  document.querySelectorAll('[data-text]').forEach(function (el) {
    var v = get(el.getAttribute('data-text'));
    if (v != null) el.innerHTML = value(v);
  });

  /* ── 사진 자리 ─────────────────────────────── */
  var heroPhoto = $('[data-photo="hero"]');
  if (heroPhoto) heroPhoto.innerHTML = photoHtml(S.hero.photo, S.hero.photoAlt, S.hero.photoPlaceholder, true);
  var aboutPhoto = $('[data-photo="about"]');
  if (aboutPhoto) aboutPhoto.innerHTML = photoHtml(S.about.photo, S.about.photoAlt, S.about.photoPlaceholder, false);

  /* ── 신뢰 띠 ───────────────────────────────── */
  $('#trust-list').innerHTML = S.trust.map(function (t, i) {
    return (
      '<li class="trust-item reveal">' +
        '<span class="trust-num" aria-hidden="true">0' + (i + 1) + '</span>' +
        '<strong class="trust-title">' + text(t.title) + '</strong>' +
        '<span class="trust-text">' + text(t.text) + '</span>' +
      '</li>'
    );
  }).join('');

  /* ── 작업 사례 (누르면 펼쳐짐) ──────────────── */
  $('#case-grid').innerHTML = S.cases.map(function (c) {
    var body = '';
    if (c.problem) {
      body += '<h4>문제</h4><p>' + text(c.problem) + '</p>';
    }
    if (c.did && c.did.length) {
      body += '<h4>' + (c.problem ? '해결' : '한 일') + '</h4><ul>' +
        c.did.map(function (d) { return '<li>' + value(d) + '</li>'; }).join('') +
        '</ul>';
    }
    if (c.result) {
      body += '<h4>결과</h4><p>' + value(c.result) + '</p>';
    }
    if (c.link && !isPlaceholder(c.link)) {
      body += '<a class="text-link" href="' + esc(c.link) + '" target="_blank" rel="noopener">' +
        esc(c.linkLabel || '자세히 보기') + '<span class="sr-only"> (새 창에서 열림)</span> <span aria-hidden="true">↗</span></a>';
    }
    return (
      '<details class="case reveal' + (c.isDraft ? ' case-draft' : '') + '">' +
        '<summary>' +
          '<span class="case-tags">' +
            '<span class="tag">' + esc(c.label) + '</span>' +
            (c.isDraft ? '<span class="tag tag-draft">시안</span>' : '') +
          '</span>' +
          '<h3 class="case-title">' + text(c.title) + '</h3>' +
          '<span class="case-summary">' + text(c.summary) + '</span>' +
          '<span class="case-more"><span class="more-open">자세히 보기</span><span class="more-close">접기</span>' +
          '<span class="case-icon" aria-hidden="true"></span></span>' +
        '</summary>' +
        '<div class="case-body">' + body + '</div>' +
      '</details>'
    );
  }).join('');

  /* ── 마케팅 제작 상품 ───────────────────────── */
  $('#plan-grid').innerHTML = S.plans.map(function (p, i) {
    return (
      '<article class="plan reveal' + (p.featured ? ' plan-featured' : '') + '">' +
        (p.featured ? '<p class="plan-badge">' + esc(p.featuredLabel || '추천') + '</p>' : '') +
        '<p class="plan-step">' + (i + 1) + '단계</p>' +
        '<h3 class="plan-name">' + text(p.step) + '</h3>' +
        '<p class="plan-for">' + text(p.for) + '</p>' +
        '<ul class="check-list">' + p.items.map(function (it) { return '<li>' + text(it) + '</li>'; }).join('') + '</ul>' +
        '<p class="plan-price">' + value(p.price) + '</p>' +
        '<a class="btn ' + (p.featured ? 'btn-green' : 'btn-outline') + ' btn-block" href="#contact">' + esc(p.step) + ' 상담하기</a>' +
      '</article>'
    );
  }).join('');

  /* ── 지원사업 코칭 ──────────────────────────── */
  $('#coach-grid').innerHTML = S.coaching.map(function (c, i) {
    return (
      '<article class="coach reveal">' +
        '<span class="coach-num" aria-hidden="true">0' + (i + 1) + '</span>' +
        '<h3>' + text(c.title) + '</h3>' +
        '<p>' + text(c.text) + '</p>' +
        '<p class="coach-price">' + value(c.price) + '</p>' +
      '</article>'
    );
  }).join('');

  /* ── 진행 순서 ─────────────────────────────── */
  $('#steps').innerHTML = S.process.map(function (s, i) {
    return (
      '<li class="step reveal">' +
        '<span class="step-num" aria-hidden="true">' + (i + 1) + '</span>' +
        '<h3><span class="sr-only">' + (i + 1) + '단계. </span>' + text(s.title) + '</h3>' +
        '<p>' + text(s.text) + '</p>' +
      '</li>'
    );
  }).join('');

  /* ── 대표 소개 ─────────────────────────────── */
  $('#about-body').innerHTML = S.about.paragraphs.map(function (p) {
    return '<p>' + text(p) + '</p>';
  }).join('');

  /* ── 상담 버튼 ─────────────────────────────── */
  var c = S.contact, cs = S.contactSection;
  var kakaoReady = !isPlaceholder(c.kakaoUrl);
  var phoneReady = !isPlaceholder(c.phone);
  var telHref = phoneReady ? 'tel:' + c.phone.replace(/[^0-9+]/g, '') : '#contact';
  $('#contact-actions').innerHTML =
    '<a class="btn btn-gold btn-lg" href="' + (kakaoReady ? esc(c.kakaoUrl) : '#contact') + '"' +
      (kakaoReady ? ' target="_blank" rel="noopener"' : '') + '>' +
      '<svg class="btn-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M12 3C6.5 3 2 6.6 2 11c0 2.8 1.8 5.3 4.6 6.7L5.7 21l3.8-2.5c.8.1 1.6.2 2.5.2 5.5 0 10-3.6 10-8S17.5 3 12 3Z"/></svg>' +
      '<span>' + esc(cs.kakaoButton) + (kakaoReady ? '<span class="sr-only"> (새 창에서 열림)</span>' : '') + '</span>' +
    '</a>' +
    '<a class="btn btn-outline-light btn-lg" href="' + esc(telHref) + '">' +
      '<svg class="btn-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M6.6 10.8a15.1 15.1 0 0 0 6.6 6.6l2.2-2.2a1 1 0 0 1 1-.25 11.4 11.4 0 0 0 3.6.57 1 1 0 0 1 1 1V20a1 1 0 0 1-1 1A17 17 0 0 1 3 4a1 1 0 0 1 1-1h3.5a1 1 0 0 1 1 1c0 1.25.2 2.45.57 3.6a1 1 0 0 1-.25 1Z"/></svg>' +
      '<span>' + esc(cs.phoneButton) + ' <span class="btn-sub">' + value(c.phone) + '</span></span>' +
    '</a>';
  $('#contact-hours').innerHTML = '상담 시간 ' + value(c.hours);

  /* ── 푸터 ─────────────────────────────────── */
  var f = S.footer;
  $('#footer-info').innerHTML = [
    ['상호', f.company], ['대표', f.owner], ['사업자등록번호', f.bizNumber],
    ['주소', f.address], ['전화', c.phone], ['이메일', f.email]
  ].map(function (row) {
    return '<div><dt>' + row[0] + '</dt><dd>' + value(row[1]) + '</dd></div>';
  }).join('');
  $('#year').textContent = new Date().getFullYear();

  wirePhotos();

  /* ── 휴대폰 메뉴 ───────────────────────────── */
  var toggle = $('.menu-toggle');
  var nav = $('#site-nav');
  function setMenu(open) {
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    toggle.querySelector('.menu-toggle-label').textContent = open ? '닫기' : '메뉴';
    document.body.classList.toggle('menu-open', open);
  }
  toggle.addEventListener('click', function () {
    setMenu(toggle.getAttribute('aria-expanded') !== 'true');
  });
  nav.addEventListener('click', function (e) {
    if (e.target.closest('a')) setMenu(false);
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') {
      setMenu(false);
      toggle.focus();
    }
  });
  window.matchMedia('(min-width: 900px)').addEventListener('change', function (m) {
    if (m.matches) setMenu(false);
  });

  /* ── 스크롤하면 부드럽게 나타나기 ─────────────── */
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var items = document.querySelectorAll('.reveal');
  if (reduce || !('IntersectionObserver' in window)) {
    items.forEach(function (el) { el.classList.add('is-visible'); });
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) {
          en.target.classList.add('is-visible');
          io.unobserve(en.target);
        }
      });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    items.forEach(function (el) { io.observe(el); });
  }
  // 키보드로 이동해 온 요소는 바로 보이게
  document.addEventListener('focusin', function (e) {
    var r = e.target.closest('.reveal');
    if (r) r.classList.add('is-visible');
  });
})();
