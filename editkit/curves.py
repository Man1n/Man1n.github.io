"""Easing, keyframe interpolation, speed-ramp time maps and shake curves."""
from __future__ import annotations

import math

import numpy as np

EASES = {
    "linear": lambda t: t,
    "easeIn": lambda t: t ** 3,
    "easeOut": lambda t: 1 - (1 - t) ** 3,
    "smooth": lambda t: t * t * (3 - 2 * t),
    "ease": lambda t: t * t * (3 - 2 * t),
    "expoOut": lambda t: 1 - 2 ** (-10 * t) if t < 1 else 1.0,
    "backOut": lambda t: 1 + 2.70158 * (t - 1) ** 3 + 1.70158 * (t - 1) ** 2,
    "hold": lambda t: 0.0,
}


def ease(name, t):
    t = min(1.0, max(0.0, t))
    return EASES.get(name or "linear", EASES["linear"])(t)


def interp_keys(keys, t, default=None):
    """keys: [[time, value, ease?], ...] sorted by time. Ease on a key shapes the segment that ENDS at it."""
    if not keys:
        return default
    if t <= keys[0][0]:
        return keys[0][1]
    for a, b in zip(keys, keys[1:]):
        if a[0] <= t <= b[0]:
            span = b[0] - a[0]
            u = 0.0 if span <= 0 else (t - a[0]) / span
            e = ease(b[2] if len(b) > 2 else "linear", u)
            va, vb = a[1], b[1]
            if isinstance(va, (list, tuple)):
                return [x + (y - x) * e for x, y in zip(va, vb)]
            return va + (vb - va) * e
    return keys[-1][1]


# ---------------------------------------------------------------- speed ramps

def speed_keys_for_shot(shot, ramp_cfg):
    """Return speed keyframes [[t_norm, speed, ease]] for a shot from its 'speed' field.

    shot["speed"] may be:
      a number                         constant speed
      {"keys": [[t_norm, speed, ease], ...]}   explicit curve over the shot's OUTPUT time (0..1)
      {"ramp_in": true, "ramp_out": true, "peak": 5}  standard speed-ramp transition halves
    """
    sp = shot.get("speed", 1.0)
    if isinstance(sp, (int, float)):
        return [[0.0, float(sp), "linear"], [1.0, float(sp), "linear"]]
    if "keys" in sp:
        return sp["keys"]
    base = float(sp.get("base", ramp_cfg.get("base_speed", 1.0)))
    peak = float(sp.get("peak", ramp_cfg.get("peak_speed", 5.0)))
    e = sp.get("ease", ramp_cfg.get("ease", "smooth"))
    keys = []
    if sp.get("ramp_in"):
        p = float(sp.get("in_portion", ramp_cfg.get("in_portion", 0.3)))
        keys += [[0.0, peak, "linear"], [p, base, e]]
    else:
        keys += [[0.0, base, "linear"]]
    if sp.get("ramp_out"):
        p = float(sp.get("out_portion", ramp_cfg.get("out_portion", 0.35)))
        keys += [[1.0 - p, base, "linear"], [1.0, peak, e]]
    else:
        keys += [[1.0, base, "linear"]]
    keys.sort(key=lambda k: k[0])
    return keys


def time_map(speed_keys, out_dur, fps, src_in):
    """Integrate speed over output frames -> source time for each output frame (and per-frame speed)."""
    n = max(1, int(round(out_dur * fps)))
    speeds = np.array([interp_keys(speed_keys, (i + 0.5) / n) for i in range(n)], dtype=np.float64)
    dt = 1.0 / fps
    src = src_in + np.concatenate([[0.0], np.cumsum(speeds[:-1] * dt)])
    return src, speeds


def source_needed(shot, ramp_cfg, fps):
    keys = speed_keys_for_shot(shot, ramp_cfg)
    src, speeds = time_map(keys, shot["dur"], fps, 0.0)
    return float(src[-1] + speeds[-1] / fps)


def peak_time(shot, ramp_cfg, fps):
    """Timeline time (absolute) of the fastest frame in a shot."""
    keys = speed_keys_for_shot(shot, ramp_cfg)
    _, speeds = time_map(keys, shot["dur"], fps, 0.0)
    i = int(np.argmax(speeds))
    return shot["start"] + (i + 0.5) / fps, float(speeds[i])


# ---------------------------------------------------------------- shake

def _noise1d(t, seed):
    # smooth value-noise built from a few incommensurate sines; deterministic per seed
    r = np.random.default_rng(seed)
    ph = r.uniform(0.6, 2.5, 4)  # phases chosen so the first frame already has a solid kick
    fr = np.array([1.0, 1.73, 2.41, 3.17])
    amp = np.array([1.0, 0.6, 0.35, 0.2])
    return float(sum(a * math.sin(2 * math.pi * f * t + p) for a, f, p in zip(amp, fr, ph)) / (amp.sum() * 0.55))


def shake_offset(t, shakes, width):
    """Sum of decaying shakes at timeline time t -> (dx, dy, rot_deg). shakes: [{start,dur,amp,freq,rot,decay,seed}]"""
    dx = dy = rot = 0.0
    scale = width / 1080.0
    for i, s in enumerate(shakes):
        u = t - s["start"]
        if u < 0 or u > s["dur"]:
            continue
        env = math.exp(-s.get("decay", 2.5) * u / s["dur"]) * (1 - u / s["dur"]) * min(1.0, u * 60 + 0.35)
        f = s.get("freq", 18.0)
        seed = s.get("seed", i)
        dx += s.get("amp", 14) * scale * env * _noise1d(u * f, seed)
        dy += s.get("amp", 14) * scale * env * _noise1d(u * f, seed + 101)
        rot += s.get("rot", 0.6) * env * _noise1d(u * f * 0.7, seed + 202)
    return dx, dy, rot
