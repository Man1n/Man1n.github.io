"""Thin wrappers over ffmpeg / ffprobe / OpenCV used by every other module."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import numpy as np

SR = 48000  # internal audio sample rate

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm", ".mxf"}
AUDIO_EXT = {".wav", ".mp3", ".aif", ".aiff", ".flac", ".m4a", ".ogg"}


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(map(str, cmd))}\n{r.stderr[-2000:]}")
    return r


def probe(path) -> dict:
    r = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)])
    data = json.loads(r.stdout)
    info = {"path": str(path), "duration": float(data["format"].get("duration", 0) or 0),
            "has_video": False, "has_audio": False}
    for s in data["streams"]:
        if s["codec_type"] == "video" and not info["has_video"]:
            num, den = (s.get("avg_frame_rate") or s.get("r_frame_rate") or "30/1").split("/")
            fps = float(num) / float(den) if float(den) else 30.0
            rot = 0
            for sd in s.get("side_data_list", []) or []:
                if "rotation" in sd:
                    rot = int(sd["rotation"])
            w, h = int(s["width"]), int(s["height"])
            if abs(rot) in (90, 270):
                w, h = h, w
            info.update(has_video=True, width=w, height=h, fps=fps,
                        nb_frames=int(s.get("nb_frames", 0) or 0), vcodec=s.get("codec_name"))
        elif s["codec_type"] == "audio" and not info["has_audio"]:
            info.update(has_audio=True, sample_rate=int(s.get("sample_rate", SR)),
                        channels=int(s.get("channels", 2)))
    return info


def load_audio(path, sr=SR, mono=False, start=None, duration=None) -> np.ndarray:
    """Decode any audio/video file to float32. Returns (n,) if mono else (n, 2)."""
    ch = 1 if mono else 2
    cmd = ["ffmpeg", "-v", "error"]
    if start is not None:
        cmd += ["-ss", f"{start:.4f}"]
    if duration is not None:
        cmd += ["-t", f"{duration:.4f}"]
    cmd += ["-i", str(path), "-vn", "-ac", str(ch), "-ar", str(sr), "-f", "f32le", "-"]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode()[-1500:])
    a = np.frombuffer(r.stdout, dtype=np.float32).copy()
    return a if mono else a.reshape(-1, 2)


def write_wav(path, audio: np.ndarray, sr=SR):
    import soundfile as sf
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.asarray(audio, dtype=np.float32), sr, subtype="PCM_24")


class FrameWriter:
    """Pipe raw BGR frames into ffmpeg. codec: 'h264' (previz), 'prores' (Premiere master), 'prores4444' (alpha)."""

    def __init__(self, path, width, height, fps, codec="h264", crf=18, pix_in="bgr24"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.w, self.h = width, height
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", pix_in,
               "-s", f"{width}x{height}", "-r", f"{fps}", "-i", "-"]
        if codec == "h264":
            cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p"]
        elif codec == "prores":
            cmd += ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le"]
        elif codec == "prores4444":
            cmd += ["-c:v", "prores_ks", "-profile:v", "4444", "-pix_fmt", "yuva444p10le", "-alpha_bits", "16"]
        else:
            raise ValueError(codec)
        cmd += [str(path)]
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    def write(self, frame: np.ndarray):
        self.p.stdin.write(np.ascontiguousarray(frame).tobytes())

    def close(self):
        self.p.stdin.close()
        err = self.p.stderr.read().decode()
        if self.p.wait() != 0:
            raise RuntimeError(err[-1500:])


class FrameReader:
    """Sequential frame access by index with a small cache (for speed ramps that read forward)."""

    def __init__(self, path, cache=48):
        import cv2
        self.cv2 = cv2
        self.cap = cv2.VideoCapture(str(path))
        if not self.cap.isOpened():
            raise RuntimeError(f"cannot open {path}")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.n = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.pos = 0
        self.cache: dict[int, np.ndarray] = {}
        self.cache_size = cache
        self.last = None

    def get(self, idx: int) -> np.ndarray:
        idx = max(0, idx if self.n <= 0 else min(idx, self.n - 1))
        if idx in self.cache:
            return self.cache[idx]
        if idx < self.pos or idx > self.pos + 240:
            self.cap.set(self.cv2.CAP_PROP_POS_FRAMES, idx)
            self.pos = idx
        frame = self.last
        while self.pos <= idx:
            ok, f = self.cap.read()
            if not ok:
                break
            frame = f
            self.cache[self.pos] = f
            self.pos += 1
            if len(self.cache) > self.cache_size:
                del self.cache[min(self.cache)]
        if frame is None:
            raise RuntimeError("no frames decoded")
        self.last = frame
        return self.cache.get(idx, frame)

    def close(self):
        self.cap.release()


def list_media(folder, exts):
    folder = Path(folder)
    if not folder.exists():
        return []
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() in exts and not p.name.startswith("."))


def mux(video, audio, out):
    run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", str(audio), "-map", "0:v", "-map", "1:a",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-shortest", str(out)])


def db(x):
    return 10 ** (x / 20.0)


def rel(path, root):
    try:
        return os.path.relpath(path, root)
    except ValueError:
        return str(path)
