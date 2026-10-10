/* 문의대추정원 — 공통 스크립트 (외부 라이브러리 없음) */
(function () {
  "use strict";

  var body = document.body;
  var cfg = {
    endpoint: body.getAttribute("data-form-endpoint") || "",
    email: body.getAttribute("data-email") || ""
  };

  /* ---------- 모바일 메뉴 ---------- */
  var menuBtn = document.querySelector(".menu-btn");
  var gnb = document.getElementById("gnb");
  if (menuBtn && gnb) {
    var setMenu = function (open) {
      gnb.classList.toggle("is-open", open);
      body.classList.toggle("menu-open", open);
      menuBtn.setAttribute("aria-expanded", String(open));
      menuBtn.setAttribute("aria-label", open ? "메뉴 닫기" : "메뉴 열기");
    };
    menuBtn.addEventListener("click", function () {
      setMenu(menuBtn.getAttribute("aria-expanded") !== "true");
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && gnb.classList.contains("is-open")) { setMenu(false); menuBtn.focus(); }
    });
    gnb.addEventListener("click", function (e) { if (e.target.closest("a")) setMenu(false); });
    window.addEventListener("resize", function () { if (window.innerWidth > 1040) setMenu(false); });
  }

  /* ---------- 폼 ---------- */
  var phoneRe = /^0\d{1,2}-?\d{3,4}-?\d{4}$/;

  function fieldError(input, msg) {
    var field = input.closest(".field") || input.closest(".consent");
    if (!field) return;
    var err = field.querySelector(".error");
    if (msg) {
      field.classList.add("has-error");
      input.setAttribute("aria-invalid", "true");
      if (err) err.textContent = msg;
    } else {
      field.classList.remove("has-error");
      input.removeAttribute("aria-invalid");
    }
  }

  function validate(form) {
    var firstBad = null;
    form.querySelectorAll("[required]").forEach(function (input) {
      var msg = "";
      if (input.type === "checkbox") {
        if (!input.checked) msg = "필수 동의 항목입니다.";
      } else if (input.type === "radio") {
        if (!form.querySelector('[name="' + input.name + '"]:checked')) msg = "항목을 선택해 주세요.";
      } else if (!input.value.trim()) {
        msg = "필수 입력 항목입니다.";
      } else if (input.type === "tel" && !phoneRe.test(input.value.replace(/\s/g, ""))) {
        msg = "연락처 형식을 확인해 주세요. (예: 010-1234-5678)";
      } else if (input.type === "email" && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(input.value)) {
        msg = "이메일 형식을 확인해 주세요.";
      }
      fieldError(input, msg);
      if (msg && !firstBad) firstBad = input;
    });
    if (firstBad) firstBad.focus();
    return !firstBad;
  }

  function summarize(form) {
    var lines = ["[" + (form.getAttribute("data-form-title") || "문의") + "]"];
    var seen = {};
    form.querySelectorAll("input, select, textarea").forEach(function (el) {
      if (!el.name || el.name.charAt(0) === "_" || el.type === "hidden" || seen[el.name]) return;
      if (el.type === "radio" || el.type === "checkbox") {
        var checked = form.querySelectorAll('[name="' + el.name + '"]:checked');
        seen[el.name] = true;
        if (el.type === "checkbox" && form.querySelectorAll('[name="' + el.name + '"]').length === 1) {
          lines.push((el.getAttribute("data-label") || el.name) + ": " + (el.checked ? "동의" : "미동의"));
          return;
        }
        var vals = Array.prototype.map.call(checked, function (c) {
          var span = c.parentNode.querySelector("span");
          return span ? span.textContent.trim() : c.value;
        });
        lines.push((el.getAttribute("data-label") || el.name) + ": " + (vals.join(", ") || "-"));
        return;
      }
      var label = form.querySelector('label[for="' + el.id + '"]');
      var name = el.getAttribute("data-label") || (label ? label.textContent.replace("*", "").trim() : el.name);
      var shown = el.tagName === "SELECT" && el.selectedIndex >= 0 ? el.options[el.selectedIndex].text : el.value.trim();
      lines.push(name + ": " + (el.value.trim() ? shown : "-"));
    });
    return lines.join("\n");
  }

  function showResult(form, html, text) {
    var panel = document.getElementById(form.getAttribute("data-result"));
    if (!panel) return;
    panel.innerHTML = html;
    panel.classList.add("is-visible");
    if (text) {
      var pre = document.createElement("pre");
      pre.textContent = text;
      panel.appendChild(pre);
      var row = document.createElement("div");
      row.className = "btn-row";
      var copy = document.createElement("button");
      copy.type = "button";
      copy.className = "btn btn-green";
      copy.textContent = "내용 복사하기";
      copy.addEventListener("click", function () {
        var done = function () { copy.textContent = "복사되었습니다"; };
        if (navigator.clipboard) navigator.clipboard.writeText(text).then(done, function () { selectPre(pre); });
        else selectPre(pre);
      });
      row.appendChild(copy);
      if (cfg.email) {
        var mail = document.createElement("a");
        mail.className = "btn btn-line";
        mail.textContent = "이메일로 보내기";
        mail.href = "mailto:" + cfg.email + "?subject=" + encodeURIComponent(form.getAttribute("data-form-title") || "문의") + "&body=" + encodeURIComponent(text);
        row.appendChild(mail);
      }
      panel.appendChild(row);
    }
    panel.setAttribute("tabindex", "-1");
    panel.focus();
    panel.scrollIntoView({ block: "start" });
  }

  function selectPre(pre) {
    var r = document.createRange();
    r.selectNodeContents(pre);
    var s = window.getSelection();
    s.removeAllRanges();
    s.addRange(r);
  }

  document.querySelectorAll("form[data-result]").forEach(function (form) {
    form.setAttribute("novalidate", "");
    form.addEventListener("input", function (e) {
      if (e.target.getAttribute("aria-invalid")) fieldError(e.target, "");
    });
    form.addEventListener("change", function (e) {
      if (e.target.type === "checkbox" || e.target.type === "radio") {
        form.querySelectorAll('[name="' + e.target.name + '"]').forEach(function (i) { fieldError(i, ""); });
      }
    });
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      if (form.querySelector('[name="_hp"]') && form.querySelector('[name="_hp"]').value) return; // 스팸 방지
      if (!validate(form)) return;
      var text = summarize(form);
      var btn = form.querySelector('[type="submit"]');

      if (!cfg.endpoint) {
        // 접수 서버가 연결되지 않은 상태: 접수 완료로 표시하지 않는다.
        showResult(form,
          "<h3>아직 온라인 접수가 연결되지 않았습니다</h3>" +
          "<p>현재 홈페이지에서는 문의 내용이 자동으로 전송되지 않습니다. 아래 내용을 복사하여 " +
          (cfg.email ? "이메일로 보내 주시거나 " : "") +
          "안내된 연락처로 전달해 주세요.</p>", text);
        return;
      }

      btn.disabled = true;
      var original = btn.textContent;
      btn.textContent = "전송 중…";
      var data = new FormData(form);
      data.append("_summary", text);
      fetch(cfg.endpoint, { method: "POST", body: data, headers: { Accept: "application/json" } })
        .then(function (res) {
          if (!res.ok) throw new Error(String(res.status));
          form.reset();
          showResult(form,
            "<h3>신청이 접수되었습니다</h3>" +
            "<p>남겨 주신 연락처로 확인 연락을 드리겠습니다. 접수 내용은 아래와 같습니다.</p>", text);
        })
        .catch(function () {
          showResult(form,
            "<h3>전송에 실패했습니다</h3>" +
            "<p>일시적인 오류로 접수되지 않았습니다. 잠시 후 다시 시도하시거나, 아래 내용을 복사해 연락처로 전달해 주세요.</p>", text);
        })
        .then(function () { btn.disabled = false; btn.textContent = original; });
    });
  });

  /* ---------- 다른 페이지에서 넘어온 상품 선택값 (?item=gift) ---------- */
  var params = new URLSearchParams(location.search);
  var item = params.get("item");
  if (item) {
    var target = document.querySelector('[name="item"][value="' + item + '"]');
    if (target) target.checked = true;
    var sel = document.querySelector('select[name="type"] option[value="' + item + '"]');
    if (sel) sel.selected = true;
  }
})();
