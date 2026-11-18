"""SFX library: a procedural starter pack, a catalog that measures each file, and a picker.

The starter pack is placeholder quality so the pipeline works on day one. Drop real libraries into
sfx/<category>/ (whooshes, risers, impacts, clicks, ambience) and re-run `sfx-catalog`.
File names matter: words like whoosh / riser / impact / click / ambience / pool / city are read as tags.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
from scipy import signal

from . import media

SR = media.SR
CATEGORIES = {
    "whoosh": ["whoosh", "swoosh", "swish", "woosh", "swipe", "whip", "pass", "transition"],
    "riser": ["riser", "uplifter", "rise", "build", "tension", "sweep_up"],
    "impact": ["impact", "hit", "boom", "slam", "thud", "drop", "sub", "punch", "bass_hit"],
    "click": ["click", "tick", "pop", "snap", "shutter", "ui", "blip", "tap"],
    "ambience": ["ambience", "ambient", "amb", "roomtone", "room_tone", "atmos", "atmosphere", "birds", "city", "pool", "ocean", "wind"],
    "downer": ["downer", "down", "reverse", "fall"],
}


# ------------------------------------------------------------------ synth helpers

def _noise(n, rng, color="white"):
    w = rng.standard_normal(n)
    if color == "pink":
        b, a = [0.049922035, -0.095993537, 0.050612699, -0.004408786], [1, -2.494956002, 2.017265875, -0.522189400]
        w = signal.lfilter(b, a, w)
    elif color == "brown":
        w = np.cumsum(w)
        w = signal.lfilter([1, -1], [1, -0.995], w)
    return w / (np.abs(w).max() + 1e-9)


def _sweep_bandpass(x, f0, f1, q=1.2, block=256):
    """Band-pass with a centre frequency that glides f0 -> f1 (log), processed in blocks."""
    out = np.zeros_like(x)
    n = len(x)
    zi = None
    fs = np.geomspace(max(f0, 20), max(f1, 20), max(1, n // block + 1))
    for k, i in enumerate(range(0, n, block)):
        fc = min(fs[k], SR * 0.45)
        bw = fc / q
        lo, hi = max(20, fc - bw / 2), min(SR * 0.49, fc + bw / 2)
        sos = signal.butter(2, [lo, hi], btype="band", fs=SR, output="sos")
        if zi is None or zi.shape != (sos.shape[0], 2):
            zi = np.zeros((sos.shape[0], 2))
        out[i:i + block], zi = signal.sosfilt(sos, x[i:i + block], zi=zi)
    return out


def _env_peak(n, peak_frac, attack_pow=2.2, release_pow=1.6):
    t = np.linspace(0, 1, n)
    p = max(1e-3, min(0.999, peak_frac))
    up = (t / p) ** attack_pow
    down = ((1 - t) / (1 - p)) ** release_pow
    return np.where(t <= p, up, down)


def _stereo_pan(x, pan_from=-0.6, pan_to=0.6):
    pan = np.linspace(pan_from, pan_to, len(x))
    l = x * np.sqrt((1 - pan) / 2)
    r = x * np.sqrt((1 + pan) / 2)
    return np.stack([l, r], axis=1)


def _reverb(x, seconds=0.8, mix=0.25, rng=None):
    rng = rng or np.random.default_rng(1)
    n = int(seconds * SR)
    ir = rng.standard_normal(n) * np.exp(-np.linspace(0, 7, n))
    wet = signal.fftconvolve(x, ir)[: len(x) + n]
    dry = np.pad(x, (0, len(wet) - len(x)))
    wet = wet / (np.abs(wet).max() + 1e-9) * np.abs(x).max()
    return dry * (1 - mix) + wet * mix


def _norm(x, peak_db=-1.0):
    return x / (np.abs(x).max() + 1e-9) * media.db(peak_db)


def whoosh(dur, peak=0.6, f0=300, f1=4000, seed=0, airy=0.5):
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    nz = _noise(n, rng, "pink")
    body = _sweep_bandpass(nz, f0, f1, q=1.0)
    air = signal.sosfilt(signal.butter(2, 3500, "high", fs=SR, output="sos"), _noise(n, rng))
    tone = np.sin(2 * np.pi * np.cumsum(np.geomspace(90, 240, n)) / SR) * 0.15
    x = (body + airy * 0.35 * air + tone) * _env_peak(n, peak)
    return _norm(_stereo_pan(x, -0.7, 0.7))


def riser(dur, seed=0):
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    t = np.arange(n) / SR
    env = (t / dur) ** 2.5
    nz = _sweep_bandpass(_noise(n, rng), 200, 9000, q=1.5)
    f = np.geomspace(110, 880, n)
    saw = signal.sawtooth(2 * np.pi * np.cumsum(f) / SR) * 0.25
    trem_rate = np.geomspace(3, 22, n)
    trem = 0.6 + 0.4 * np.sin(2 * np.pi * np.cumsum(trem_rate) / SR)
    x = (nz + saw * signal.sosfilt(signal.butter(2, 3000, "low", fs=SR, output="sos"), np.ones(n))) * env * trem
    x[-int(0.01 * SR):] *= np.linspace(1, 0, int(0.01 * SR))  # hard stop exactly at the end
    st = np.stack([x, np.roll(x, 37)], axis=1)
    return _norm(st)


def impact(dur=2.0, seed=0, sub_hz=55):
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = sub_hz * (1 + 1.5 * np.exp(-t * 18))
    sub = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 2.2)
    crack = signal.sosfilt(signal.butter(2, [800, 7000], "band", fs=SR, output="sos"), _noise(n, rng)) * np.exp(-t * 35)
    body = signal.sosfilt(signal.butter(2, 400, "low", fs=SR, output="sos"), _noise(n, rng)) * np.exp(-t * 6)
    x = sub * 1.0 + crack * 0.6 + body * 0.5
    x = np.tanh(x * 1.8)
    x = _reverb(x, 1.2, 0.2, rng)[:n]
    return _norm(np.stack([x, x], axis=1))


def click(kind="tick", seed=0):
    rng = np.random.default_rng(seed)
    n = int(0.08 * SR)
    t = np.arange(n) / SR
    if kind == "tick":
        x = np.sin(2 * np.pi * 3200 * t) * np.exp(-t * 400) + _noise(n, rng) * np.exp(-t * 900) * 0.5
    elif kind == "pop":
        x = np.sin(2 * np.pi * np.cumsum(np.geomspace(900, 300, n)) / SR) * np.exp(-t * 90)
    else:  # shutter
        x = (_noise(n, rng) * (np.exp(-t * 300) + 0.6 * np.exp(-np.maximum(0, t - 0.035) * 300) * (t > 0.035)))
    return _norm(np.stack([x, x], axis=1), -3)


def ambience(kind, dur=12.0, seed=0):
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    if kind == "room_tone":
        x = signal.sosfilt(signal.butter(2, 300, "low", fs=SR, output="sos"), _noise(n, rng, "brown")) * 0.6
    elif kind == "outdoor_birds":
        x = signal.sosfilt(signal.butter(2, [200, 4000], "band", fs=SR, output="sos"), _noise(n, rng, "pink")) * 0.25
        for _ in range(int(dur * 1.5)):
            st = rng.integers(0, n - SR // 2)
            ln = int(rng.uniform(0.05, 0.18) * SR)
            tt = np.arange(ln) / SR
            f = rng.uniform(2500, 5500) + 900 * np.sin(2 * np.pi * rng.uniform(8, 25) * tt)
            x[st:st + ln] += np.sin(2 * np.pi * np.cumsum(f) / SR) * np.hanning(ln) * rng.uniform(0.1, 0.35)
    elif kind == "pool_water":
        nz = _noise(n, rng)
        x = signal.sosfilt(signal.butter(2, [400, 3000], "band", fs=SR, output="sos"), nz)
        mod = 0.5 + 0.5 * np.abs(signal.sosfilt(signal.butter(1, 3, "low", fs=SR, output="sos"), _noise(n, rng)))
        x = x * mod * 0.5
    elif kind == "city_distant":
        x = signal.sosfilt(signal.butter(2, 500, "low", fs=SR, output="sos"), _noise(n, rng, "brown")) * 0.7
        x += signal.sosfilt(signal.butter(2, [800, 2500], "band", fs=SR, output="sos"), _noise(n, rng)) * 0.05
    else:
        raise ValueError(kind)
    fade = int(0.5 * SR)
    x[:fade] *= np.linspace(0, 1, fade)
    x[-fade:] *= np.linspace(1, 0, fade)
    st = np.stack([x, np.roll(x, 911)], axis=1)
    return _norm(st, -6)


def build_starter_pack(root):
    root = Path(root)
    made = []

    def save(sub, name, x):
        p = root / sub / f"{name}.wav"
        media.write_wav(p, x)
        made.append(str(p))

    for i, (d, pk, f0, f1) in enumerate([(0.35, 0.55, 500, 6000), (0.5, 0.6, 400, 5000), (0.7, 0.6, 300, 4500),
                                         (1.0, 0.65, 250, 4000), (1.4, 0.7, 200, 3500), (2.0, 0.7, 150, 3000)]):
        speed = "fast" if d < 0.6 else "medium" if d < 1.2 else "slow"
        save("whooshes", f"whoosh_{speed}_{d:.2f}s_{i + 1:02d}", whoosh(d, pk, f0, f1, seed=i))
    for i, d in enumerate([1.0, 2.0, 4.0, 8.0]):
        save("risers", f"riser_{d:.0f}s_{i + 1:02d}", riser(d, seed=i))
    for i, hz in enumerate([45, 55, 70]):
        save("impacts", f"impact_sub_boom_{i + 1:02d}", impact(2.2, seed=i, sub_hz=hz))
    save("clicks", "click_tick_01", click("tick"))
    save("clicks", "click_pop_01", click("pop"))
    save("clicks", "click_camera_shutter_01", click("shutter"))
    for k in ("room_tone", "outdoor_birds", "pool_water", "city_distant"):
        save("ambience", f"ambience_{k}_01", ambience(k))
    return made


# ------------------------------------------------------------------ catalog

def _category_from_name(name):
    low = name.lower()
    for cat, words in CATEGORIES.items():
        if any(w in low for w in words):
            return cat
    return None


def measure(path):
    a = media.load_audio(path, mono=True)
    if len(a) == 0:
        return None
    dur = len(a) / SR
    hop = 256
    env = np.sqrt(np.convolve(a ** 2, np.ones(hop) / hop, mode="same")[::hop])
    peak_i = int(np.argmax(env))
    peak_t = peak_i * hop / SR
    thr = env[peak_i] * 0.1
    above = np.where(env > thr)[0]
    attack = (peak_i - above[0]) * hop / SR if len(above) else 0
    spec = np.abs(np.fft.rfft(a[: min(len(a), SR * 4)] * np.hanning(min(len(a), SR * 4))))
    fr = np.fft.rfftfreq(min(len(a), SR * 4), 1 / SR)
    p = spec ** 2 + 1e-12
    centroid = float((p * fr).sum() / p.sum())
    low_ratio = float(p[fr < 150].sum() / p.sum())
    onset_t = float(np.argmax(np.abs(a) > 0.5 * np.abs(a).max())) / SR  # first loud sample: where a hit "lands"
    return {"dur": round(dur, 3), "peak_time": round(peak_t, 3), "onset_time": round(onset_t, 4), "attack": round(attack, 3),
            "centroid_hz": int(centroid), "low_ratio": round(low_ratio, 3),
            "peak_db": round(float(20 * np.log10(np.abs(a).max() + 1e-9)), 1)}


def guess_category(m):
    if m["dur"] < 0.25:
        return "click"
    if m["attack"] < 0.03 and m["low_ratio"] > 0.25:
        return "impact"
    if m["dur"] > 6 and m["attack"] > 1.0 and m["peak_time"] < m["dur"] * 0.8:
        return "ambience"
    if m["peak_time"] > 0.85 * m["dur"] and m["dur"] > 0.9:
        return "riser"
    if 0.2 < m["dur"] < 3 and 0.2 < m["peak_time"] / m["dur"] < 0.85:
        return "whoosh"
    return "unknown"


def catalog(root):
    root = Path(root)
    items = []
    for p in media.list_media(root, media.AUDIO_EXT):
        m = measure(p)
        if not m:
            continue
        cat = _category_from_name(p.stem) or _category_from_name(p.parent.name) or guess_category(m)
        tags = sorted(set(re.split(r"[^a-z0-9]+", (p.parent.name + "_" + p.stem).lower())) - {""})
        # sync point: transients sync on their first loud sample, swells (whoosh / riser) on their loudest moment
        m["sync_time"] = m["onset_time"] if cat in ("impact", "click") else m["peak_time"]
        items.append({"file": media.rel(p, root), "category": cat, "tags": tags, **m})
    out = {"root": str(root), "items": items}
    (root / "sfx_catalog.json").write_text(json.dumps(out, indent=1))
    return out


class Picker:
    """Chooses SFX for a cue, preferring a duration match and avoiding back-to-back repeats."""

    def __init__(self, catalog_path):
        data = json.loads(Path(catalog_path).read_text())
        self.root = Path(data["root"])
        if not self.root.exists():
            self.root = Path(catalog_path).parent
        self.items = data["items"]
        self.recent: dict[str, list] = {}

    def pick(self, category, target_dur=None, tags=None, align="peak"):
        pool = [i for i in self.items if i["category"] == category]
        if not pool:
            return None
        def score(i):
            s = 0.0
            if target_dur:
                ref = i["peak_time"] * 2 if category == "whoosh" else i["dur"]
                s += abs(np.log((ref + 1e-3) / (target_dur + 1e-3)))
            if tags:
                s -= 1.5 * len(set(tags) & set(i["tags"]))
            if i["file"] in self.recent.get(category, []):
                s += 0.8
            return s
        best = min(pool, key=score)
        self.recent.setdefault(category, []).append(best["file"])
        self.recent[category] = self.recent[category][-2:]
        return {**best, "path": str(self.root / best["file"])}
