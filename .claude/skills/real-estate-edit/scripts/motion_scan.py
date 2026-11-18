#!/usr/bin/env python3
"""Find the usable part of each clip: steady, intentional camera motion only.

Flags wobble (hand-held jitter, gimbal bounce), jerky starts/stops and direction changes, and reports
the clean in/out ranges, plus fps and the speed to use on a 25 fps timeline.

usage: python motion_scan.py <clip or folder> [...] [--json out.json] [--min 1.0]
needs: python3, numpy, opencv-python (pip install numpy opencv-python)
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

EXT = {".mp4", ".mov", ".mxf", ".m4v", ".avi", ".mkv"}


def smooth(x, k):
    k = max(1, min(int(k), len(x)))
    if k < 2:
        return np.asarray(x, float)
    pad = np.pad(np.asarray(x, float), (k // 2, k - 1 - k // 2), mode="edge")
    return np.convolve(pad, np.ones(k) / k, mode="valid")


def speed_for(fps):
    if 47 <= fps <= 61:
        return "50%"
    if 23 <= fps <= 31:
        return "100%"
    if fps > 90:
        return "ASK (100/120 fps: 25% or 20.8% for full slow-mo)"
    return "CHECK"


def scan(path, min_len):
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w0 = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)); h0 = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    prev, vx, vy = None, [], []
    win = None
    while True:
        ok, f = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(cv2.resize(f, (320, int(320 * f.shape[0] / f.shape[1]))), cv2.COLOR_BGR2GRAY).astype(np.float32)
        if win is None:
            win = cv2.createHanningWindow(g.shape[::-1], cv2.CV_32F)
        if prev is not None:
            (dx, dy), _ = cv2.phaseCorrelate(prev, g, win)
            vx.append(dx / 320); vy.append(dy / 320)   # frame widths per frame
        prev = g
    cap.release()
    n = len(vx)
    dur = (n + 1) / fps
    info = {"clip": str(path), "fps": round(fps, 3), "size": f"{w0}x{h0}", "duration": round(dur, 2),
            "speed_on_25p": speed_for(fps), "segments": [], "best": None}
    if n < 5:
        return info
    vx, vy = np.array(vx), np.array(vy)
    k = max(3, int(fps * 0.5))                       # intended motion = 0.5 s moving average
    sx, sy = smooth(vx, k), smooth(vy, k)
    jit = np.sqrt(smooth((vx - sx) ** 2 + (vy - sy) ** 2, max(3, int(fps * 0.25))))
    spd = np.hypot(sx, sy)
    acc = np.abs(np.diff(spd, prepend=spd[0])) * fps  # change of speed per second
    # thresholds scale with fps (motion per frame halves when fps doubles)
    s = 25.0 / fps
    bad = (jit > 0.0022 * s) | (acc > 0.03 * s)  # wobble, or a sudden lurch in speed
    # direction flips while moving = wobble / correction
    ang = np.arctan2(sy, sx)
    flip = np.abs(np.angle(np.exp(1j * (ang - np.roll(ang, int(fps * 0.3)))))) > 1.2
    bad |= flip & (spd > 0.0015 * s)
    bad = smooth(bad.astype(float), max(3, int(fps * 0.2))) > 0.25   # bridge single-frame noise
    segs, i = [], 0
    while i < n:
        if not bad[i]:
            j = i
            while j < n and not bad[j]:
                j += 1
            # trim gimbal start/stop: edges where speed is far below the segment's typical speed
            med = np.median(spd[i:j])
            a, b = i, j
            if med > 0.002 * s:
                while a < b and spd[a] < 0.6 * med:
                    a += 1
                while b > a and spd[b - 1] < 0.6 * med:
                    b -= 1
            if (b - a) / fps >= min_len:
                mx, my = sx[a:b].mean(), sy[a:b].mean()
                move = "locked-off" if np.hypot(mx, my) < 0.0008 * s else \
                    ("pan/truck " + ("right" if mx < 0 else "left")) if abs(mx) > abs(my) else \
                    ("tilt/boom " + ("down" if my < 0 else "up"))
                segs.append({"in": round(a / fps, 2), "out": round(b / fps, 2), "dur": round((b - a) / fps, 2),
                             "move": move, "steadiness": round(float(1 - min(1, jit[a:b].mean() / (0.0022 * s))), 2),
                             "speed_consistency": round(float(1 - min(1, spd[a:b].std() / (spd[a:b].mean() + 1e-6))), 2)})
            i = j
        i += 1
    info["segments"] = segs
    if segs:
        info["best"] = max(segs, key=lambda g: g["dur"] * (0.5 + g["steadiness"]) * (0.5 + g["speed_consistency"]))
    info["unstable_pct"] = round(float(bad.mean() * 100), 1)
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--json")
    ap.add_argument("--min", type=float, default=1.0, help="shortest usable segment in source seconds")
    a = ap.parse_args()
    files = []
    for p in map(Path, a.paths):
        files += sorted(q for q in p.rglob("*") if q.suffix.lower() in EXT) if p.is_dir() else [p]
    out = []
    for f in files:
        r = scan(f, a.min)
        out.append(r)
        print(f"\n{Path(r['clip']).name}  {r['size']} @ {r['fps']} fps  {r['duration']}s  -> speed {r['speed_on_25p']}  "
              f"unstable {r.get('unstable_pct', '?')}%")
        for g in r["segments"]:
            star = " *best" if g == r["best"] else ""
            print(f"   keep {g['in']:6.2f}-{g['out']:6.2f}s ({g['dur']:.2f}s) {g['move']:18} steady {g['steadiness']:.2f} "
                  f"consistent {g['speed_consistency']:.2f}{star}")
        if not r["segments"]:
            print("   no clean segment: stabilize hard or drop this clip")
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    sys.exit(main())
