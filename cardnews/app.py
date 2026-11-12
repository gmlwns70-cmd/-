"""카드뉴스 대시보드 — 브라우저에서 주제 입력 → 만들기 → 보기·다운로드.

실행: run_dashboard.bat 더블클릭 (Mac: run_dashboard.command)
     또는  python -m streamlit run app.py
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import streamlit as st

from cardmaker import settings

BASE = Path(__file__).resolve().parent
st.set_page_config(page_title="카드뉴스 만들기", page_icon="📱", layout="wide")


# ── 공통 도구 ─────────────────────────────────────────────
def result_folders() -> list[Path]:
    if not settings.OUTPUT_DIR.exists():
        return []
    dirs = [d for d in settings.OUTPUT_DIR.iterdir() if (d / "script.json").exists()]
    return sorted(dirs, key=lambda d: d.stat().st_mtime, reverse=True)


def make_zip(folder: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(folder.glob("card_*.png")):
            z.write(f, f.name)
        for name in ("caption.txt", "sources.md", "check_report.md"):
            if (folder / name).exists():
                z.write(folder / name, name)
    return buf.getvalue()


def run_main(args: list[str], log_box) -> int:
    """main.py 를 실행하면서 진행 상황을 화면에 실시간으로 보여줍니다."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    proc = subprocess.Popen([sys.executable, "-u", "main.py", *args], cwd=BASE, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    lines: list[str] = []
    for raw in proc.stdout:
        lines.append(raw.decode("utf-8", errors="replace").rstrip())
        log_box.code("\n".join(lines[-40:]), language=None, wrap_lines=True)
    return proc.wait()


def lines_to_text(lines: list[dict]) -> str:
    return "\n".join(("*" if l.get("highlight") else "") + l.get("text", "") for l in lines)


def text_to_lines(text: str) -> list[dict]:
    out = []
    for raw in text.splitlines():
        t = raw.rstrip()
        hl = t.startswith("*")
        out.append({"text": t[1:].strip() if hl else t.strip(), "highlight": hl})
    return out


# ── 사이드바: 준비 상태 ───────────────────────────────────
settings.load_config()
with st.sidebar:
    st.header("⚙️ 준비 상태")
    if settings.has_key("ANTHROPIC_API_KEY"):
        st.success("Claude API 키 ✅ 준비됨")
    else:
        st.error("Claude API 키가 없어요")
        st.caption("cardnews 폴더의 `.env` 파일을 메모장으로 열고 `ANTHROPIC_API_KEY=` 뒤에 키를 붙여넣은 뒤 저장하세요. 저장 후 이 화면을 새로고침(F5)하면 돼요.")
    provider = settings.image_provider()
    if provider == "none":
        st.info("일러스트: 끔 (글자 카드만)")
        st.caption("그림을 넣으려면 `.env` 에서 `IMAGE_PROVIDER` 를 openai 또는 gemini 로 바꾸고 해당 키를 넣으세요.")
    else:
        key = {"openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}.get(provider, "")
        if key and settings.has_key(key):
            st.success(f"일러스트: {provider} ✅")
        else:
            st.warning(f"일러스트: {provider} 키가 없어요")
    st.divider()
    st.caption("결과 폴더: `cardnews/output`")

st.title("📱 스토리텔링 카드뉴스 만들기")
tab_make, tab_view, tab_edit = st.tabs(["① 만들기", "② 결과 보기·다운로드", "③ 문구 고치기"])

# ── ① 만들기 ─────────────────────────────────────────────
with tab_make:
    cfg = settings.load_config()
    with st.form("make"):
        topic = st.text_input("주제 *", placeholder="예: 줄 서던 가게가 금방 조용해지는 이유")
        c1, c2, c3 = st.columns([2, 2, 1])
        target = c1.text_input("누구에게 하는 이야기인가요?", value=cfg["target"],
                               help="비워 두면 주제를 보고 알아서 정해요")
        brand = c2.text_input("계정명", value=cfg["brand"])
        cards = c3.slider("장수", 10, 15, int(cfg["cards"]))
        with st.expander("🎨 그림 캐릭터 바꾸기 (주제가 가게 이야기가 아닐 때)"):
            character = st.text_input("고정 캐릭터 설명", value=cfg["character"],
                                      help="모든 그림에 똑같이 나오는 인물이에요. 예: 20대 한국인 남성 e스포츠 팬, 검은 후드티, 짧은 머리")
        text_only = st.checkbox("일러스트 없이 글자 카드만 만들기", value=(provider == "none"))
        go = st.form_submit_button("🚀 카드뉴스 만들기", type="primary", use_container_width=True)

    if go:
        if not topic.strip():
            st.warning("주제를 입력해 주세요.")
        elif not settings.has_key("ANTHROPIC_API_KEY"):
            st.error("Claude API 키가 없어요. 왼쪽 '준비 상태' 안내를 따라 주세요.")
        else:
            args = ["--topic", topic.strip(),
                    "--target", target.strip() or "주제를 보고 가장 관심 있을 독자 (알아서 판단)",
                    "--brand", brand, "--cards", str(cards), "--character", character.strip() or cfg["character"]]
            if text_only:
                args.append("--text-only")
            with st.status("만드는 중이에요… 3~10분 걸려요. 이 창을 닫지 마세요.", expanded=True) as status:
                code = run_main(args, st.empty())
                if code == 0:
                    status.update(label="✅ 완성! '② 결과 보기·다운로드' 탭을 눌러 보세요.", state="complete")
                    st.balloons()
                else:
                    status.update(label="❌ 만들다 멈췄어요. 아래 빨간 상자의 안내를 확인해 주세요.", state="error")
            if code != 0:
                st.error("기록 상자 맨 아래 ❌ 줄이 멈춘 이유예요. 해결이 어려우면 이 화면을 캡처해서 보내 주세요.")

# ── ② 결과 보기·다운로드 ─────────────────────────────────
with tab_view:
    folders = result_folders()
    if not folders:
        st.info("아직 만든 카드뉴스가 없어요. '① 만들기' 탭에서 시작하세요.")
    else:
        folder = st.selectbox("어떤 카드뉴스를 볼까요? (최신순)", folders, format_func=lambda p: p.name, key="view_folder")
        cards_png = sorted(folder.glob("card_*.png"))
        st.download_button("⬇️ 카드 전체 + 캡션 한 번에 받기 (ZIP)", make_zip(folder),
                           file_name=f"{folder.name}.zip", mime="application/zip",
                           type="primary", use_container_width=True)
        if not cards_png:
            st.warning("카드 이미지가 없어요.")
        cols = st.columns(3)
        for i, f in enumerate(cards_png):
            with cols[i % 3]:
                st.image(str(f), caption=f.name, use_container_width=True)
                st.download_button("이 카드만 받기", f.read_bytes(), file_name=f.name, mime="image/png",
                                   key=f"dl_{folder.name}_{f.name}", use_container_width=True)

        st.subheader("📝 인스타 캡션")
        cap = folder / "caption.txt"
        if cap.exists():
            st.caption("오른쪽 위 복사 버튼을 눌러 인스타 본문에 붙여넣으세요.")
            st.code(cap.read_text(encoding="utf-8"), language=None, wrap_lines=True)
        with st.expander("🔍 출처 목록 (올리기 전에 링크를 꼭 확인하세요)"):
            src = folder / "sources.md"
            st.markdown(src.read_text(encoding="utf-8") if src.exists() else "출처 파일이 없어요.")
        with st.expander("✅ 자동 검수 결과"):
            rep = folder / "check_report.md"
            st.markdown(rep.read_text(encoding="utf-8") if rep.exists() else "검수 결과가 없어요.")

# ── ③ 문구 고치기 ────────────────────────────────────────
with tab_edit:
    folders = result_folders()
    if not folders:
        st.info("먼저 카드뉴스를 만들어 주세요.")
    else:
        folder = st.selectbox("어떤 카드뉴스를 고칠까요?", folders, format_func=lambda p: p.name, key="edit_folder")
        script_path = folder / "script.json"
        script = json.loads(script_path.read_text(encoding="utf-8"))
        cards = script["cards"]
        no = st.selectbox("몇 번 카드?", [c["no"] for c in cards],
                          format_func=lambda n: f"{n}번 — {next((c.get('role', '') for c in cards if c['no'] == n), '')}")
        card = next(c for c in cards if c["no"] == no)
        left, right = st.columns([1, 1])
        with left:
            st.caption("한 줄에 한 줄씩 써요. 줄 맨 앞에 `*` 를 붙이면 노란 형광펜, 빈 줄은 간격이에요. 한 줄 13자 안팎이 좋아요.")
            new_text = st.text_area("카드 문구", lines_to_text(card.get("lines", [])), height=260,
                                    key=f"txt_{folder.name}_{no}")
            if card.get("verify_needed"):
                st.warning("이 카드는 '검증 필요' 표시가 있어요. 출처가 확인된 숫자만 넣어 주세요.")
            if st.button("💾 저장하고 다시 만들기", type="primary", use_container_width=True):
                card["lines"] = text_to_lines(new_text)
                script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
                from cardmaker import check, render
                log = io.StringIO()
                with st.spinner("다시 합성 중… (그림은 새로 만들지 않아요)"), contextlib.redirect_stdout(log):
                    cfg = settings.load_config()
                    render.render_dir(folder, cfg, only=[no])
                    check.run_check(folder, cfg)
                warns = [l for l in log.getvalue().splitlines() if "⚠" in l]
                st.success("저장했어요! 오른쪽 미리보기가 바뀌었어요.")
                for w in warns:
                    st.warning(w.strip())
        with right:
            img = folder / f"card_{no:02d}.png"
            if img.exists():
                st.image(str(img), caption=img.name, use_container_width=True)
