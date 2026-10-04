import wave
from pathlib import Path

import numpy as np
import pytest
from PIL import Image


def write_tone(path: Path, seconds: float, freq: float = 440.0, rate: int = 24000):
    t = np.linspace(0, seconds, int(rate * seconds), endpoint=False)
    data = (0.3 * np.sin(2 * np.pi * freq * t) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data.tobytes())


def write_video(path: Path, seconds: float = 2.0, size=(320, 180)):
    from moviepy import VideoClip

    def frame(t):
        img = np.zeros((size[1], size[0], 3), dtype=np.uint8)
        img[:, :, 0] = int(255 * t / seconds)
        img[:, : int(size[0] * t / seconds) + 1, 1] = 200
        return img
    VideoClip(frame, duration=seconds).write_videofile(str(path), fps=15, codec="libx264", logger=None,
                                                         preset="ultrafast")


def write_image(path: Path, size=(400, 300)):
    arr = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    arr[..., 0] = np.linspace(0, 255, size[0], dtype=np.uint8)[None, :]
    arr[..., 2] = np.linspace(255, 0, size[1], dtype=np.uint8)[:, None]
    Image.fromarray(arr).save(path)


@pytest.fixture
def tmp_project(tmp_path, monkeypatch):
    from core.project import Project
    return Project.create("테스트 주제", base_dir=tmp_path / "projects", date="2026-10-04")
