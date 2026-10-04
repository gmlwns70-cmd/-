"""유튜브 영상 자동 제작 도구 - Streamlit 화면.

실행: run.bat 더블클릭 (또는 명령 프롬프트에서 `streamlit run app.py`)
"""
from __future__ import annotations

import traceback

import pandas as pd
import streamlit as st
from PIL import Image

from core import assets, pipeline, render, research, script, subtitles, tts
from core.config import KEY_INFO, UserFacingError, find_ffmpeg, key_status, load_config
from core.project import STAGE_LABELS, STAGES, Project

st.set_page_config(page_title="유튜브 영상 자동 제작", page_icon="🎬", layout="wide")

try:
    CFG = load_config()
except UserFacingError as e:
    st.error(str(e))
    st.stop()


# ---------------- 공통 도우미 ----------------
def run_safely(fn, *args, **kwargs):
    """오류가 나도 프로그램이 멈추지 않고, 한국어로 안내합니다."""
    try:
        return fn(*args, **kwargs)
    except UserFacingError as e:
        st.error(str(e))
    except Exception as e:  # 예상하지 못한 오류
        st.error(f"❌ 예상하지 못한 오류가 생겼어요: {e}\n\n아래 '자세한 내용'을 복사해서 질문하면 해결에 도움이 돼요.")
        with st.expander("자세한 내용 (개발자용)"):
            st.code(traceback.format_exc())
    return None


def progress_bar():
    bar = st.progress(0.0, text="준비 중…")
    return lambda p, msg="": bar.progress(min(max(float(p), 0.0), 1.0), text=msg)


def current_project() -> Project | None:
    name = st.session_state.get("project_name")
    if not name:
        return None
    for p in Project.list_all():
        if p.name == name:
            return p
    return None


def need_project() -> Project | None:
    proj = current_project()
    if proj is None:
        st.info("👈 왼쪽 사이드바에서 프로젝트를 먼저 만들거나 선택해 주세요.")
    return proj


def tts_widgets(prefix: str, proj: Project | None) -> dict:
    """TTS 엔진/목소리/속도 선택 (③ 탭과 ⑦ 탭에서 함께 사용)."""
    saved = proj.get_settings() if proj else {}
    keys = key_status()
    available = ["edge"] + [e for e, k in (("elevenlabs", "ELEVENLABS_API_KEY"), ("typecast", "TYPECAST_API_KEY")) if keys[k]]
    default_engine = saved.get("tts_engine") or CFG["tts"]["engine"]
    engine = st.selectbox("음성 엔진", available, format_func=lambda e: tts.ENGINES[e],
                          index=available.index(default_engine) if default_engine in available else 0,
                          key=f"{prefix}_engine",
                          help="ElevenLabs/타입캐스트는 .env에 키를 넣으면 목록에 나타나요.")
    if engine == "edge":
        voices = list(tts.EDGE_VOICES)
        dv = saved.get("tts_voice") if saved.get("tts_voice") in voices else CFG["tts"]["edge_voice"]
        voice = st.selectbox("목소리", voices, format_func=lambda v: tts.EDGE_VOICES[v],
                             index=voices.index(dv) if dv in voices else 0, key=f"{prefix}_voice")
    else:
        default_id = CFG["tts"]["elevenlabs_voice_id"] if engine == "elevenlabs" else CFG["tts"]["typecast_voice_id"]
        voice = st.text_input("Voice ID", value=saved.get("tts_voice") or default_id, key=f"{prefix}_voice_id")
    rate_default = int(str(saved.get("tts_rate") or CFG["tts"]["edge_rate"]).rstrip("%"))
    rate = st.slider("말 속도 (%)", -30, 30, rate_default, step=5, key=f"{prefix}_rate")
    return {"tts_engine": engine, "tts_voice": voice, "tts_rate": f"{rate:+d}%"}


def render_widgets(prefix: str, proj: Project | None) -> dict:
    saved = proj.get_settings() if proj else {}
    bgm_files = [p.name for p in render.list_bgm()]
    options = ["없음", "랜덤"] + bgm_files
    default_bgm = saved.get("bgm") if saved.get("bgm") in options else ("랜덤" if bgm_files else "없음")
    c1, c2 = st.columns(2)
    with c1:
        bgm = st.selectbox("배경음악 (assets/bgm 폴더)", options, index=options.index(default_bgm), key=f"{prefix}_bgm")
        quality = st.radio("화질", ["1080p", "720p"], horizontal=True, key=f"{prefix}_quality",
                           index=0 if saved.get("quality", "1080p") == "1080p" else 1,
                           help="720p는 빠른 미리보기용이에요. 업로드용은 1080p를 쓰세요.")
    with c2:
        burn = st.checkbox("자막을 영상에 직접 입히기", value=saved.get("burn_subtitles", True), key=f"{prefix}_burn",
                           help="끄면 자막 없는 영상 + SRT 파일이 만들어져요. (유튜브에 SRT를 따로 올릴 수 있어요)")
        shorts = st.checkbox("쇼츠(9:16, 60초 이내)도 만들기", value=saved.get("make_shorts", True), key=f"{prefix}_shorts")
    if not bgm_files:
        st.caption("ℹ️ assets/bgm 폴더에 음원이 없어서 배경음악 없이 만들어요.")
    return {"bgm": bgm, "quality": quality, "burn_subtitles": burn, "make_shorts": shorts}


# ---------------- 사이드바 ----------------
with st.sidebar:
    st.title("🎬 영상 자동 제작")
    projects = Project.list_all()
    names = [p.name for p in projects]
    NEW = "➕ 새 프로젝트 만들기"
    cur = st.session_state.get("project_name")
    choice = st.selectbox("프로젝트", [NEW] + names, index=(names.index(cur) + 1) if cur in names else 0)
    if choice == NEW:
        new_topic = st.text_input("영상 주제", placeholder="예: 집에서 카페 라떼 만들기")
        if st.button("프로젝트 만들기", type="primary", disabled=not new_topic.strip()):
            p = Project.create(new_topic)
            st.session_state["project_name"] = p.name
            st.rerun()
        if cur:
            st.session_state["project_name"] = None
    else:
        st.session_state["project_name"] = choice

    proj = current_project()
    if proj:
        st.caption(f"📁 projects/{proj.name}")
        for s in STAGES:
            st.write(("✅ " if proj.is_done(s) else "⬜ ") + STAGE_LABELS[s])

    st.divider()
    st.subheader("🔑 API 키 상태")
    for k, ok in key_status().items():
        st.write(f"{'✅' if ok else '❌'} {KEY_INFO[k][0]} — {KEY_INFO[k][1]}")
    st.caption("키는 .env 파일에 넣고 프로그램을 다시 켜면 적용돼요.")
    st.divider()
    st.write("✅ ffmpeg" if find_ffmpeg() else "❌ ffmpeg 없음 (README 참고)")
    fw = subtitles.font_warning()
    st.write(fw if fw else f"✅ 폰트: {subtitles.find_font(CFG['subtitles'].get('font_file', '')).name}")

tabs = st.tabs(["① 리서치", "② 대본", "③ 내레이션", "④ 소재", "⑤ 자막", "⑥ 렌더링", "⑦ 전체 자동 실행"])

# ---------------- ① 리서치 ----------------
with tabs[0]:
    st.header("① 트렌드 리서치")
    st.caption("유튜브의 숫자 정보(조회수·구독자·게시일·제목)만 봅니다. 영상 내용은 가져오지 않아요. "
               "'배율'이 높을수록 작은 채널도 조회수가 잘 나온 = 수요가 큰 주제예요.")
    c1, c2, c3, c4 = st.columns(4)
    keyword = c1.text_input("키워드", value=proj.topic if proj else "")
    days = c2.number_input("최근 N일", 1, 365, 90)
    min_min = c3.number_input("최소 길이(분)", 0.0, 60.0, 4.0, step=1.0)
    max_res = c4.number_input("최대 결과 수", 10, 200, 50, step=10, help="많을수록 API 사용량(쿼터)을 많이 써요.")
    if st.button("🔍 검색", type="primary"):
        with st.spinner("유튜브에서 찾는 중…"):
            df = run_safely(research.search_videos, keyword, int(days), float(min_min), int(max_res))
        if df is not None:
            st.session_state["research_df"] = df
            if proj:
                research.save_csv(df, proj.research_csv)
                proj.mark_done("research", keyword=keyword, rows=len(df))
    df = st.session_state.get("research_df")
    if df is None and proj and proj.research_csv.exists():
        df = pd.read_csv(proj.research_csv)
    if df is not None:
        if df.empty:
            st.warning("조건에 맞는 영상이 없어요. 기간을 늘리거나 최소 길이를 줄여 보세요.")
        else:
            st.dataframe(df, width="stretch", hide_index=True,
                         column_config={"URL": st.column_config.LinkColumn("URL", display_text="열기"),
                                        "구독자수": st.column_config.NumberColumn(format="%d")})
            st.download_button("⬇️ CSV 저장", df.to_csv(index=False).encode("utf-8-sig"),
                               file_name="research.csv", mime="text/csv")
            st.subheader("제목에 자주 나오는 단어 TOP 20")
            words = research.top_title_words(df["제목"].tolist(), 20)
            st.dataframe(pd.DataFrame(words, columns=["단어", "등장 횟수"]), hide_index=True)
            st.caption("💡 이 단어들은 '수요 파악'용 참고 자료예요. 다른 영상의 내용을 따라 하지 말고 나만의 관점으로 대본을 만드세요.")

# ---------------- ② 대본 ----------------
with tabs[1]:
    st.header("② 대본 생성")
    proj = need_project()
    if proj:
        saved = proj.get_settings()
        c1, c2, c3 = st.columns([3, 1, 2])
        topic = c1.text_input("주제", value=saved.get("topic") or proj.topic, key="s_topic")
        minutes = c2.number_input("목표 길이(분)", 1.0, 20.0, float(saved.get("minutes", 8)), step=1.0, key="s_min")
        tone = c3.radio("톤", script.TONES, horizontal=True, key="s_tone",
                        index=script.TONES.index(saved.get("tone", "정보형")))
        local = assets.scan_local_assets()
        with st.expander(f"📂 내 소재 목록 ({len(local)}개) — 대본 작성에 참고돼요"):
            if local:
                st.dataframe(pd.DataFrame([{"파일": a.path.name, "종류": "직접 촬영" if a.source == "my" else "허락 소재",
                                             "메모": a.memo} for a in local]), hide_index=True, width="stretch")
            else:
                st.write("assets/my_footage 폴더가 비어 있어요.")
            for p in assets.licensed_without_memo():
                st.warning(f"'{p.name}'은(는) 허락 메모({p.stem}.license.txt)가 없어서 사용하지 않아요.")
        if st.button("✍️ 대본 생성 (1~3분)", type="primary"):
            with st.spinner("Claude가 대본을 쓰는 중이에요…"):
                data = run_safely(pipeline.run_until_review, proj, topic, minutes, tone, log=lambda m: None)
            if data:
                st.session_state["editor_ver"] = st.session_state.get("editor_ver", 0) + 1
                st.success("대본이 만들어졌어요! 아래 표에서 직접 고친 뒤 '저장하고 확정'을 눌러 주세요.")

        data = proj.load_script()
        if data:
            st.divider()
            c1, c2 = st.columns(2)
            title = c1.text_input("제목", data["title"])
            thumb = c2.text_input("썸네일 문구", data["thumbnail_text"])
            desc = st.text_area("설명란", data["description"], height=100)
            tags = st.text_input("태그 (쉼표로 구분)", ", ".join(data["tags"]))
            st.caption("표 안의 칸을 더블클릭하면 고칠 수 있어요. 맨 아래 빈 줄에 장면을 추가하거나, 왼쪽 칸을 선택해 삭제할 수 있어요.")
            edited = st.data_editor(
                pd.DataFrame(script.scenes_to_rows(data["scenes"])), num_rows="dynamic", width="stretch",
                hide_index=True, key=f"editor_{proj.name}_{st.session_state.get('editor_ver', 0)}",
                column_config={
                    "id": st.column_config.NumberColumn("번호", disabled=True, width="small"),
                    "type": st.column_config.SelectboxColumn("구간", options=script.SCENE_TYPES, width="small"),
                    "narration": st.column_config.TextColumn("내레이션", width="large"),
                    "on_screen_text": st.column_config.TextColumn("화면 텍스트"),
                    "visual_keywords_en": st.column_config.TextColumn("영상 검색어(영어)"),
                    "prefer_my_footage": st.column_config.CheckboxColumn("내 소재 우선"),
                    "shorts": st.column_config.CheckboxColumn("쇼츠 포함"),
                })
            est = script.estimate_minutes({"scenes": [{"narration": str(script.clean_cell(n))} for n in edited["narration"]]},
                                          CFG["claude"]["chars_per_minute"])
            st.caption(f"⏱️ 예상 길이: 약 {est:.1f}분 (내레이션 글자 수 기준)")
            if st.button("💾 저장하고 확정", type="primary"):
                new = run_safely(script.normalize_script, {
                    "title": title, "thumbnail_text": thumb, "description": desc, "tags": tags,
                    "scenes": script.rows_to_scenes(edited.to_dict("records"))})
                if new:
                    proj.save_script(new)
                    proj.invalidate_from("script")
                    pipeline.approve_script(proj)
                    st.session_state["editor_ver"] = st.session_state.get("editor_ver", 0) + 1
                    st.toast("저장했어요! ③ 내레이션 탭으로 가거나 ⑦ 탭에서 이어서 자동 실행하세요.", icon="✅")
                    st.rerun()

# ---------------- ③ 내레이션 ----------------
with tabs[2]:
    st.header("③ 내레이션 (AI 음성)")
    proj = need_project()
    if proj:
        opts = tts_widgets("t3", proj)
        c1, c2 = st.columns(2)
        if c1.button("🔊 미리 듣기"):
            out = proj.audio_dir / "preview.mp3"
            eng = run_safely(tts.make_engine, opts["tts_engine"], opts["tts_voice"], opts["tts_rate"])
            ok = eng and run_safely(lambda: eng.synthesize("안녕하세요. 이 목소리로 영상을 만들어 드릴게요.", out) or True)
            if ok:
                st.audio(str(out))
        if c2.button("🎙️ 전체 내레이션 만들기", type="primary"):
            proj.update_settings(**opts)
            eng = run_safely(tts.make_engine, opts["tts_engine"], opts["tts_voice"], opts["tts_rate"])
            if eng:
                res = run_safely(tts.generate_narration, proj, eng, progress_bar())
                if res:
                    st.success(f"완료! 전체 {sum(s['duration'] for s in res['scenes']) / 60:.1f}분")
        data = proj.load_scenes()
        if data:
            st.dataframe(pd.DataFrame([{"번호": s["id"], "길이(초)": s["duration"], "내레이션": s["narration"]}
                                       for s in data["scenes"]]), hide_index=True, width="stretch")
            with st.expander("장면별로 들어보기"):
                for s in data["scenes"]:
                    if s.get("audio"):
                        st.write(f"**장면 {s['id']}** — {s['narration'][:40]}…")
                        st.audio(str(proj.path / s["audio"]))

# ---------------- ④ 소재 ----------------
with tabs[3]:
    st.header("④ 소재 매칭")
    st.caption("① 내 소재(assets/my_footage) → ② 허락 소재(assets/licensed, 허락 메모 필수) → ③ Pexels/Pixabay 무료 스톡 순서로 찾아요.")
    proj = need_project()
    if proj:
        use_stock = st.checkbox("부족한 장면은 Pexels/Pixabay에서 찾기", value=True)
        force = st.checkbox("이미 고른 소재도 처음부터 다시 찾기", value=False)
        if st.button("🎞️ 소재 찾기", type="primary"):
            res = run_safely(assets.match_assets, proj, progress_bar(), force=force, use_stock=use_stock)
            if res:
                proj.update_settings(use_stock=use_stock)
                for w in res["warnings"]:
                    st.warning(w)
                st.success("소재 매칭 완료!")
        data = proj.load_scenes()
        if data and any(s.get("media") for s in data["scenes"]):
            src_name = {"my": "📷 내 소재", "licensed": "🤝 허락 소재", "pexels": "Pexels", "pixabay": "Pixabay", "none": "단색 배경"}
            rows = []
            for s in data["scenes"]:
                for m in s.get("media", []):
                    rows.append({"장면": s["id"], "출처": src_name.get(m["source"], m["source"]),
                                 "종류": {"video": "영상", "image": "사진", "color": "-"}[m["kind"]],
                                 "파일": m["path"].replace("\\", "/").split("/")[-1], "작가": m.get("author", "")})
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            with st.expander("소재 미리보기"):
                for s in data["scenes"]:
                    m = (s.get("media") or [{}])[0]
                    if m.get("kind") in ("video", "image"):
                        p = assets.resolve_path(proj, m["path"])
                        st.write(f"**장면 {s['id']}** — {s['narration'][:40]}…")
                        (st.image if m["kind"] == "image" else st.video)(str(p))
        if proj.credits_path.exists():
            st.subheader("📌 출처 표기 (영상 설명란에 붙여넣기)")
            st.text_area("credits.txt", proj.credits_path.read_text(encoding="utf-8"), height=180)

# ---------------- ⑤ 자막 ----------------
with tabs[4]:
    st.header("⑤ 자막")
    proj = need_project()
    if proj:
        saved = proj.get_settings()
        sty = {**CFG["subtitles"], **(saved.get("sub_style") or {})}
        c1, c2, c3 = st.columns(3)
        font_size = c1.slider("글자 크기", 30, 100, int(sty["font_size"]))
        stroke = c1.slider("테두리 두께", 0, 12, int(sty["stroke_width"]))
        bottom = c2.slider("아래쪽 여백(%)", 3, 30, int(float(sty["bottom_margin_pct"])))
        max_chars = c2.slider("한 줄 최대 글자 수", 10, 24, int(saved.get("sub_max_chars") or CFG["subtitles"]["max_chars_per_line"]))
        color = c3.color_picker("글자 색", sty["color"])
        stroke_color = c3.color_picker("테두리 색", sty["stroke_color"])
        max_lines = c3.radio("최대 줄 수", [1, 2], horizontal=True,
                             index=int(saved.get("sub_max_lines") or CFG["subtitles"]["max_lines"]) - 1)
        style_over = {"font_size": font_size, "stroke_width": stroke, "bottom_margin_pct": bottom,
                      "color": color, "stroke_color": stroke_color}

        # 미리보기 (1080p 화면을 축소해서 보여줌)
        style = subtitles.SubtitleStyle.from_config(CFG, **style_over)
        frame = Image.new("RGBA", (1920, 1080), (70, 90, 110, 255))
        sample = subtitles.chunk_text("집에서도 카페처럼 맛있는 라떼를 만들 수 있어요", max_chars, max_lines)[0]
        txt = subtitles.render_text_image(sample, style)
        frame.alpha_composite(txt, ((1920 - txt.width) // 2, int(1080 * (1 - bottom / 100)) - txt.height))
        st.image(frame.resize((960, 540)), caption="자막 미리보기")

        use_whisper = st.checkbox("faster-whisper로 정밀하게 맞추기 (선택, 설치 필요, 느림)",
                                  value=saved.get("use_whisper", False))
        if st.button("💬 자막 만들기", type="primary"):
            proj.update_settings(sub_style=style_over, use_whisper=use_whisper)
            cues = run_safely(subtitles.build_subtitles, proj, max_chars, max_lines, use_whisper,
                              progress=progress_bar() if use_whisper else None)
            if cues is not None:
                st.success(f"자막 {len(cues)}개를 만들었어요.")
        if proj.srt_path.exists():
            srt = proj.srt_path.read_text(encoding="utf-8")
            st.text_area("subtitles.srt", srt, height=200)
            st.download_button("⬇️ SRT 저장", srt.encode("utf-8"), file_name="subtitles.srt")

# ---------------- ⑥ 렌더링 ----------------
with tabs[5]:
    st.header("⑥ 영상 조립 (렌더링)")
    proj = need_project()
    if proj:
        opts = render_widgets("t6", proj)
        missing = [STAGE_LABELS[s] for s in ("tts", "assets", "subtitles") if not proj.is_done(s)]
        if missing:
            st.warning("먼저 끝내야 하는 단계: " + ", ".join(missing))
        st.caption("⏳ 10분 영상 기준 컴퓨터 성능에 따라 10~40분 정도 걸려요. 그동안 창을 닫지 마세요.")
        if st.button("🎬 영상 만들기", type="primary", disabled=bool(missing)):
            proj.update_settings(**opts)
            outs = run_safely(render.render_all, proj, make_shorts=opts["make_shorts"], bgm=opts["bgm"],
                              burn_subtitles=opts["burn_subtitles"], quality=opts["quality"], progress=progress_bar())
            if outs:
                st.success("🎉 영상이 완성됐어요!")
                st.balloons()
        for label, path in (("가로 영상 (16:9)", proj.final_video), ("쇼츠 (9:16)", proj.shorts_video)):
            if path.exists():
                st.subheader(label)
                st.video(str(path))
                st.caption(f"📁 파일 위치: projects/{proj.name}/output/{path.name}")
        data = proj.load_script()
        if data and proj.final_video.exists():
            st.subheader("📋 업로드할 때 복사해서 쓰세요")
            credits = proj.credits_path.read_text(encoding="utf-8") if proj.credits_path.exists() else ""
            st.text_input("제목", data["title"], key="up_title")
            st.text_area("설명란", f"{data['description']}\n\n{credits}", height=220, key="up_desc")
            st.text_input("태그", ", ".join(data["tags"]), key="up_tags")

# ---------------- ⑦ 전체 자동 실행 ----------------
with tabs[6]:
    st.header("⑦ 전체 자동 실행")
    st.caption("대본 → (확인) → 내레이션 → 소재 → 자막 → 렌더링을 차례로 실행해요. 이미 끝난 단계는 건너뛰어서 중간부터 이어서 할 수 있어요.")
    proj = need_project()
    if proj:
        state = proj.load_state()
        saved = proj.get_settings()
        st.subheader("1단계: 대본 만들기")
        c1, c2, c3 = st.columns([3, 1, 2])
        topic = c1.text_input("주제", value=saved.get("topic") or proj.topic, key="a_topic")
        minutes = c2.number_input("목표 길이(분)", 1.0, 20.0, float(saved.get("minutes", 8)), step=1.0, key="a_min")
        tone = c3.radio("톤", script.TONES, horizontal=True, key="a_tone",
                        index=script.TONES.index(saved.get("tone", "정보형")))
        if st.button("✍️ 대본 만들기", type="primary" if not proj.load_script() else "secondary"):
            with st.spinner("Claude가 대본을 쓰는 중이에요… (1~3분)"):
                if run_safely(pipeline.run_until_review, proj, topic, minutes, tone, log=lambda m: None):
                    st.session_state["editor_ver"] = st.session_state.get("editor_ver", 0) + 1
                    st.rerun()

        data = proj.load_script()
        if data:
            st.subheader("2단계: 대본 확인")
            if state.get("status") == "awaiting_review" and not proj.is_done("script"):
                st.info("⏸️ 대본을 확인해 주세요. 고칠 곳이 있으면 **② 대본 탭**에서 수정 후 '저장하고 확정'을 누르세요. "
                        "그대로 괜찮으면 아래 버튼을 누르면 돼요.")
            with st.expander(f"📜 {data['title']} (장면 {len(data['scenes'])}개)", expanded=not proj.is_done("script")):
                for s in data["scenes"]:
                    st.markdown(f"**{s['id']}. [{s['type']}]** {s['narration']}")

            st.subheader("3단계: 나머지 자동 실행")
            with st.expander("⚙️ 설정", expanded=False):
                tts_opts = tts_widgets("a7", proj)
                use_stock = st.checkbox("Pexels/Pixabay 스톡 사용", value=saved.get("use_stock", True), key="a_stock")
                use_whisper = st.checkbox("faster-whisper 정밀 자막 (설치 필요)", value=saved.get("use_whisper", False), key="a_whisper")
                r_opts = render_widgets("a7", proj)
            nxt = proj.next_stage()
            label = "✅ 확인 완료, 계속 진행" if not proj.is_done("script") else (
                f"▶️ 이어서 실행 ({STAGE_LABELS[nxt]}부터)" if nxt else "🔁 처음부터 다시 만들기 (대본 제외)")
            if st.button(label, type="primary"):
                settings = {**tts_opts, **r_opts, "use_stock": use_stock, "use_whisper": use_whisper}
                proj.update_settings(**settings)
                if nxt is None:
                    proj.invalidate_from("tts")
                bar = progress_bar()
                with st.status("작업 중…", expanded=True) as status:
                    outs = run_safely(pipeline.run_after_review, proj, settings, bar, log=status.write)
                    status.update(label="완료!" if outs else "멈췄어요 (위 메시지를 확인해 주세요)",
                                  state="complete" if outs else "error")
                if outs:
                    st.balloons()
                    for p in outs:
                        st.video(str(p))
                    st.caption("업로드용 제목·설명·출처는 ⑥ 렌더링 탭 아래에 정리돼 있어요.")
