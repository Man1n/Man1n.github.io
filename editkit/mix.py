"""Audio mixer: music (with lowpass automation and impact ducking), SFX cues, ambience beds -> stems + master."""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from scipy import signal

from . import curves, media

SR = media.SR


def automate_lowpass(x, keys, block=512, order=4):
    out = np.empty_like(x)
    zi = None
    n = len(x)
    for i in range(0, n, block):
        t = i / SR
        fc = float(curves.interp_keys(keys, t, 20000))
        fc = min(max(fc, 40.0), SR * 0.45)
        sos = signal.butter(order, fc, "low", fs=SR, output="sos")
        if zi is None:
            zi = np.zeros((sos.shape[0], 2, x.shape[1]))
        seg = x[i:i + block]
        y = np.empty_like(seg)
        for ch in range(x.shape[1]):
            y[:, ch], zi[:, :, ch] = signal.sosfilt(sos, seg[:, ch], zi=zi[:, :, ch])
        out[i:i + block] = y
    return out


class _Cache:
    def __init__(self):
        self.d = {}

    def get(self, path):
        if path not in self.d:
            self.d[path] = media.load_audio(path)
        return self.d[path]


def _place(bus, clip, start, gain=1.0, fade_in=0.0, fade_out=0.004):
    s = int(round(start * SR))
    if s < 0:
        clip = clip[-s:]
        s = 0
    e = min(len(bus), s + len(clip))
    if e <= s:
        return
    c = clip[: e - s].copy() * gain
    fi, fo = int(fade_in * SR), int(fade_out * SR)
    if fi > 0:
        c[: min(fi, len(c))] *= np.linspace(0, 1, min(fi, len(c)))[:, None]
    if fo > 0:
        c[-min(fo, len(c)):] *= np.linspace(1, 0, min(fo, len(c)))[:, None]
    bus[s:e] += c


def mix(plan, style, outdir):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    T = plan["shots"][-1]["start"] + plan["shots"][-1]["dur"]
    n = int(T * SR) + 1
    cache = _Cache()
    music = np.zeros((n, 2), np.float32)
    sfx = np.zeros((n, 2), np.float32)
    amb = np.zeros((n, 2), np.float32)

    m = plan.get("music") or {}
    if m.get("file"):
        a = media.load_audio(m["file"], start=m.get("offset", 0.0), duration=T + 0.5)
        a = a[:n] * media.db(m.get("gain_db", 0) + style["mix"]["music_gain_db"])
        music[: len(a)] = a
        for fx in plan["fx"]:
            if fx["type"] == "lowpass" and fx.get("target", "music") == "music":
                music = automate_lowpass(music, fx["keys"])
        # duck under impacts
        dd = style["mix"].get("duck_music_under_impacts_db", 0)
        if dd:
            g = np.ones(n, np.float32)
            for c in plan["sfx"]:
                if c["category"] == "impact":
                    t0 = int(c["align_time"] * SR)
                    att, rel = int(0.03 * SR), int(0.7 * SR)
                    env = np.concatenate([np.linspace(0, 1, att), np.linspace(1, 0, rel)])
                    seg = slice(max(0, t0 - att), min(n, t0 - att + len(env)))
                    k = seg.stop - seg.start
                    g[seg] = np.minimum(g[seg], 1 - (1 - media.db(dd)) * env[:k])
            music *= g[:, None]
        fo = int(min(1.0, T * 0.1) * SR)
        music[-fo:] *= np.linspace(1, 0, fo)[:, None]

    for c in plan["sfx"]:
        clip = cache.get(c["file"])
        fi = int(c.get("file_in", 0) * SR)
        _place(sfx, clip[fi:], c["start"], media.db(c["gain_db"]))

    for b in plan["ambience"]:
        clip = cache.get(b["file"])
        length = int((b["end"] - b["start"]) * SR)
        reps = int(np.ceil(length / len(clip))) + 1
        loop = np.tile(clip, (reps, 1))[:length]
        _place(amb, loop, b["start"], media.db(b["gain_db"]), b.get("fade", 0.25), b.get("fade", 0.25))

    master = music + sfx + amb
    peak = np.abs(master).max()
    if peak > 0.98:  # soft limit only the peaks
        master = np.tanh(master * 1.2) / np.tanh(1.2)
    paths = {}
    for name, bus in (("music", music), ("sfx", sfx), ("ambience", amb), ("mix_raw", master)):
        p = outdir / f"{name}.wav"
        media.write_wav(p, bus)
        paths[name] = str(p)
    final = outdir / "mix.wav"
    lufs = style["mix"].get("target_lufs", -14)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", paths["mix_raw"], "-af",
                    f"loudnorm=I={lufs}:TP=-1.0:LRA=11", "-ar", str(SR), "-c:a", "pcm_s24le", str(final)], check=True)
    paths["mix"] = str(final)
    return paths
