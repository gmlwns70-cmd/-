import numpy as np
from moviepy import VideoFileClip

from core import render
from core.config import load_config
from core.tts import audio_duration

from .conftest import write_image, write_tone, write_video


def make_scenes(project):
    write_video(project.media_dir / "clip.mp4", seconds=1.5)
    write_image(project.media_dir / "photo.png")
    write_tone(project.audio_dir / "scene_01.wav", 2.0)
    write_tone(project.audio_dir / "scene_02.wav", 1.5, freq=660)
    scenes = [
        {"id": 1, "type": "hook", "narration": "첫 번째 장면입니다. 집에서 라떼를 만들어 볼까요?",
         "on_screen_text": "홈카페", "visual_keywords_en": ["latte"], "prefer_my_footage": False, "shorts": True,
         "audio": "audio/scene_01.wav", "duration": audio_duration(project.audio_dir / "scene_01.wav"),
         "sentences": [], "media": [{"path": "media/clip.mp4", "kind": "video", "source": "pexels", "duration": 1.5}]},
        {"id": 2, "type": "body", "narration": "두 번째 장면은 사진입니다.",
         "on_screen_text": "", "visual_keywords_en": ["coffee"], "prefer_my_footage": False, "shorts": False,
         "audio": "audio/scene_02.wav", "duration": 1.5, "sentences": [],
         "media": [{"path": "media/photo.png", "kind": "image", "source": "pixabay", "duration": 0}]},
    ]
    project.save_scenes({"title": "테스트", "thumbnail_text": "라떼 비법", "scenes": scenes})
    return scenes


def test_render_landscape_and_shorts(tmp_project, tmp_path, monkeypatch):
    make_scenes(tmp_project)
    bgm = tmp_path / "bgm.wav"
    write_tone(bgm, 1.0, freq=220, rate=44100)
    cfg = load_config()
    cfg["render"]["preset"] = "ultrafast"
    cfg["render"]["fps"] = 10
    seen = []
    out = render.render_video(tmp_project, bgm=str(bgm), cfg=cfg, size=(320, 180),
                              progress=lambda p, m: seen.append(p))
    with VideoFileClip(str(out)) as v:
        expected = 2.0 + 1.5 + 2 * cfg["render"]["scene_padding"]
        assert abs(v.duration - expected) < 0.3
        assert v.size == [320, 180]
        assert v.audio is not None
    assert seen and seen[-1] == 1.0

    out2 = render.render_video(tmp_project, shorts=True, cfg=cfg, size=(180, 320))
    with VideoFileClip(str(out2)) as v:
        assert v.size == [180, 320]
        assert v.duration < 3.0   # shorts=True 인 1번 장면만


def test_select_shorts_limits_length():
    scenes = [{"id": i, "type": "body", "duration": 20, "shorts": True} for i in range(5)]
    picked = render.select_shorts_scenes(scenes, 58, 0.35)
    assert len(picked) == 2
    long_one = render.select_shorts_scenes([{"id": 1, "type": "hook", "duration": 90, "shorts": True}], 58, 0.35)
    assert long_one[0]["trimmed"] and long_one[0]["duration"] < 58


def test_duck_envelope():
    env = render.duck_envelope([(2.0, 5.0)], total=10, base=0.3, duck=0.1)
    v = env(np.array([0.0, 1.0, 3.0, 8.0, 10.0]))
    assert v[0] == 0  # 페이드 인 시작
    assert abs(v[2] - 0.1) < 1e-6 and abs(v[3] - 0.3) < 1e-6
    assert v[4] == 0  # 페이드 아웃 끝
