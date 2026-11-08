"""자막 디자인 · 썸네일 · 장면 전환 테스트."""
import pytest
from moviepy import VideoFileClip
from PIL import Image

from core import render, subtitles, thumbnail
from core.config import load_config

from .test_render import make_scenes


# ---------- 자막 디자인 ----------
def test_presets_render_and_differ():
    imgs = {name: subtitles.render_text_image("자막 디자인\n테스트", subtitles.SubtitleStyle.from_config(preset=name))
            for name in subtitles.SUBTITLE_PRESETS}
    assert len({im.tobytes() for im in imgs.values()}) == len(imgs)  # 프리셋마다 모양이 다름
    box = imgs["반투명 검은 상자"]
    assert box.getpixel((5, box.height // 2))[3] > 100  # 상자 안쪽은 불투명


def test_user_override_beats_preset():
    st = subtitles.SubtitleStyle.from_config(preset="예능 (노란 글씨 + 두꺼운 테두리)", color="#00FF00")
    assert st.color == "#00FF00" and st.stroke_width == 7 and st.shadow_offset == 5


def test_shadow_enlarges_canvas():
    plain = subtitles.SubtitleStyle.from_config()
    shadow = subtitles.SubtitleStyle.from_config(shadow_color="#000000C0", shadow_offset=6)
    a, b = subtitles.render_text_image("그림자", plain), subtitles.render_text_image("그림자", shadow)
    assert b.width == a.width + 6 and b.height == a.height + 6


# ---------- 썸네일 ----------
def test_make_thumbnail_all_layouts():
    bg = Image.new("RGB", (800, 600), (40, 120, 200))
    for layout in thumbnail.LAYOUTS:
        img = thumbnail.make_thumbnail(bg, "비싼 머신 없이 카페라떼", layout)
        assert img.size == (1280, 720)
        assert img.getpixel((640, 360)) != (40, 120, 200) or layout == "bottom"


def test_generate_thumbnails_from_project(tmp_project):
    make_scenes(tmp_project)
    tmp_project.save_script({"title": "제목", "thumbnail_text": "라떼 비법", "scenes": []})
    outs = thumbnail.generate_thumbnails(tmp_project)
    assert [p.name for p in outs] == ["thumbnail_left.jpg", "thumbnail_center.jpg", "thumbnail_bottom.jpg"]
    for p in outs:
        assert p.stat().st_size < 2 * 1024 * 1024  # 유튜브 2MB 제한
        assert Image.open(p).size == (1280, 720)


# ---------- 장면 전환 ----------
@pytest.mark.parametrize("transition", ["none", "crossfade", "black", "slide"])
def test_transitions_keep_total_length(tmp_project, transition):
    make_scenes(tmp_project)
    tmp_project.update_settings(transition=transition, transition_seconds=0.5)
    cfg = load_config()
    cfg["render"]["preset"] = "ultrafast"
    cfg["render"]["fps"] = 10
    out = render.render_video(tmp_project, cfg=cfg, size=(320, 180))
    expected = 2.0 + 1.5 + 2 * cfg["render"]["scene_padding"]
    with VideoFileClip(str(out)) as v:
        assert abs(v.duration - expected) < 0.3  # 전환을 넣어도 길이(=음성·자막 타이밍)는 그대로
        if transition == "black":
            # 두 장면 경계(2.35초) 근처는 검게 페이드
            assert v.get_frame(2.34).mean() < v.get_frame(1.0).mean()
