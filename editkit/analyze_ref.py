"""Break a reference edit down into its 'edit DNA'.

Video: cuts, flashes, per-shot camera move, speed ramps, scale punches, shakes.
Audio: tempo + beat grid, drop, and likely SFX events (whooshes, risers, impacts, clicks, lowpass sweeps).

Every number here is a measurement, not a judgement. The classifications of sound events are educated
guesses from the spectrum; confirm them by looking at timeline.png and listening.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from . import media

AW = 256  # analysis width in px


# ============================================================== video

def _features(path):
    import cv2
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    hists, luma, sharp, flows, thumbs = [], [], [], [], []
    prev = None
    ys = xs = None
    while True:
        ok, f = cap.read()
        if not ok:
            break
        h, w = f.shape[:2]
        ah = int(round(AW * h / w / 2) * 2)
        small = cv2.resize(f, (AW, ah), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1, 2], None, [16, 4, 4], [0, 180, 0, 256, 0, 256]).flatten()
        hists.append(hist / (hist.sum() + 1e-9))
        luma.append(float(gray.mean()))
        th = cv2.resize(gray, (48, 48), interpolation=cv2.INTER_AREA).astype(np.float32)
        th = (th - cv2.GaussianBlur(th, (0, 0), 3)).ravel()  # high-pass: drop the low-frequency glow of a leak
        thumbs.append((th - th.mean()) / (th.std() + 1e-6))  # structure only: immune to flashes / leaks / grades
        sharp.append(float(cv2.Laplacian(gray, cv2.CV_32F).var()))
        if prev is None:
            flows.append(None)
            yy, xx = np.mgrid[0:ah:4, 0:AW:4]
            xs = (xx - AW / 2) / AW
            ys = (yy - ah / 2) / AW
        else:
            fl = cv2.calcOpticalFlowFarneback(prev, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
            u = fl[::4, ::4, 0] / AW
            v = fl[::4, ::4, 1] / AW
            flows.append(_fit_similarity(u, v, xs, ys))
        prev = gray
    cap.release()
    return fps, np.array(hists), np.array(luma), np.array(sharp), flows, np.array(thumbs)


def _fit_similarity(u, v, x, y):
    """Least squares u = a + s*x - r*y ; v = b + r*x + s*y. Units: frame widths per frame."""
    x, y, u, v = x.ravel(), y.ravel(), u.ravel(), v.ravel()
    n = len(x)
    A = np.zeros((2 * n, 4))
    A[:n, 0] = 1
    A[:n, 2] = x
    A[:n, 3] = -y
    A[n:, 1] = 1
    A[n:, 2] = y
    A[n:, 3] = x
    rhs = np.concatenate([u, v])
    sol, *_ = np.linalg.lstsq(A, rhs, rcond=None)
    a, b, s, r = sol
    mag = float(np.median(np.hypot(u, v)))
    return {"tx": float(a), "ty": float(b), "zoom": float(s), "rot": float(r), "mag": mag}


def _bhatt(h1, h2):
    return float(np.sqrt(max(0.0, 1.0 - np.sum(np.sqrt(h1 * h2)))))


def detect_cuts(hists, luma, fps, thumbs=None):
    n = len(hists)
    d = np.zeros(n)
    for i in range(1, n):
        d[i] = _bhatt(hists[i - 1], hists[i])
    med = np.median(d[1:]) if n > 1 else 0
    mad = np.median(np.abs(d[1:] - med)) + 1e-6 if n > 1 else 1
    thr = max(0.30, med + 8 * mad)
    min_len = max(3, int(fps * 0.1))
    cuts, flashes = [0], []
    for i in range(1, n):
        # flash: big luma spike that returns within ~4 frames
        if i + 4 < n and luma[i] - luma[i - 1] > 45 and abs(luma[min(i + 4, n - 1)] - luma[i - 1]) < 30:
            flashes.append(i)
        if d[i] > thr and i - cuts[-1] >= min_len:
            cuts.append(i)
    # light leaks / flashes produce a burst of "cuts" within a fraction of a second over bright frames:
    # keep only the strongest one of each burst and record it as a flash transition
    win_f = int(0.45 * fps)
    out, k = [0], 1
    while k < len(cuts):
        grp = [cuts[k]]
        while k + 1 < len(cuts) and cuts[k + 1] - grp[-1] <= win_f:
            k += 1
            grp.append(cuts[k])
        if len(grp) >= 2:
            inside = luma[grp[0]:grp[-1] + 1].mean()
            outside = np.r_[luma[max(0, grp[0] - win_f):grp[0]], luma[grp[-1] + 1:grp[-1] + 1 + win_f]].mean()
            if inside > outside + 12:
                # the real cut is where the picture's STRUCTURE changes (a leak only changes light and colour)
                if thumbs is not None:
                    span = range(max(1, grp[0] - 2), min(len(thumbs), grp[-1] + 3))
                    best = min(span, key=lambda g: float(np.dot(thumbs[g - 1], thumbs[g]) / len(thumbs[g])))
                else:
                    best = max(grp, key=lambda g: d[g])
                out.append(best)
                flashes.append(best)
                k += 1
                continue
        out.extend(grp)
        k += 1
    return out, d, sorted(set(flashes))


def _smooth(x, k):
    if k <= 1 or len(x) < 3:
        return np.asarray(x, float)
    k = min(k, len(x))
    ker = np.ones(k) / k
    pad = np.pad(np.asarray(x, float), (k // 2, k - 1 - k // 2), mode="edge")
    return np.convolve(pad, ker, mode="valid")


def describe_move(tx, ty, zoom, rot, fps):
    """Mean per-frame similarity params -> human camera-move label (pixels move opposite to camera)."""
    zx = zoom * fps  # fractional scale change per second
    vx, vy = -tx * fps, -ty * fps  # camera direction, frame widths per second
    rr = math.degrees(rot * fps)
    cands = {"push-in": zx, "pull-out": -zx, "truck right": vx, "truck left": -vx,
             "tilt/boom down": vy, "tilt/boom up": -vy}
    best = max(cands, key=cands.get)
    val = cands[best]
    if abs(rr) > 6 and abs(rr) > val * 57:
        return f"roll {'cw' if rr > 0 else 'ccw'}", abs(rr)
    if val < 0.015:
        return "static / locked-off", val
    if best.startswith("truck") and abs(zx) > 0.02:
        best += " + " + ("push" if zx > 0 else "pull")
    return best, val


def analyze_video(path, outdir):
    fps, hists, luma, sharp, flows, thumbs = _features(path)
    n = len(hists)
    cuts, cutscore, flashes = detect_cuts(hists, luma, fps, thumbs)
    bounds = cuts + [n]
    cutset = set(cuts)

    def series(key):
        out = np.full(n, np.nan)
        for i, f in enumerate(flows):
            if f is not None and i not in cutset:
                out[i] = f[key]
        return out

    mag, tx, ty, zm, rt = (series(k) for k in ("mag", "tx", "ty", "zoom", "rot"))
    speed = mag * fps  # frame widths per second
    sharp_n = sharp / (np.median(sharp) + 1e-9)

    shots, shakes, punches, ramps = [], [], [], []
    for si, (a, b) in enumerate(zip(bounds, bounds[1:])):
        seg = slice(a, b)
        sp = speed[seg]
        valid = ~np.isnan(sp)
        sps = _smooth(np.where(valid, sp, np.nanmedian(sp) if valid.any() else 0), 3)
        base = float(np.median(sps)) if len(sps) else 0.0
        label, strength = describe_move(np.nanmean(tx[seg]) if valid.any() else 0,
                                        np.nanmean(ty[seg]) if valid.any() else 0,
                                        np.nanmean(zm[seg]) if valid.any() else 0,
                                        np.nanmean(rt[seg]) if valid.any() else 0, fps)
        shot = {"index": si + 1, "start_frame": int(a), "end_frame": int(b), "start": round(a / fps, 3),
                "end": round(b / fps, 3), "dur": round((b - a) / fps, 3), "move": label,
                "move_speed": round(float(strength), 3), "avg_speed": round(float(np.mean(sps)) if len(sps) else 0, 3),
                "ramp": None, "punch": None, "shake": False}

        # ---- speed ramp: a section much faster than the shot's own baseline
        thr = max(2.0 * base, 0.08)
        fast = sps > thr
        if fast.any() and len(sps) >= 4:
            idx = np.where(fast)[0]
            r0, r1 = int(idx[0]), int(idx[-1])
            peak_i = int(np.argmax(sps))
            ratio = float(sps[peak_i] / max(base, 0.05))
            where = "end" if r1 >= len(sps) - 2 else "start" if r0 <= 1 else "middle"
            shot["ramp"] = {"where": where, "from": round((a + r0) / fps, 3), "to": round((a + r1 + 1) / fps, 3),
                            "peak_at": round((a + peak_i) / fps, 3), "peak_ratio": round(min(ratio, 20), 2),
                            "blur_dip": round(float(np.min(sharp_n[a + r0:a + r1 + 1])), 2)}
            ramps.append({"shot": si + 1, **shot["ramp"]})

        # ---- scale punch: fast zoom right after the cut, or a short zoom spike
        z = zm[seg] * fps
        zv = np.where(np.isnan(z), 0, z)
        if len(zv) > 2:
            k = int(np.argmax(np.abs(zv)))
            if abs(zv[k]) > 0.6 and k < max(3, int(0.4 * fps)):
                shot["punch"] = {"dir": "in" if zv[k] > 0 else "out", "at": round((a + k) / fps, 3),
                                 "rate": round(float(zv[k]), 2)}
                punches.append({"shot": si + 1, **shot["punch"]})

        # ---- shake: high-frequency jitter in translation
        if b - a > 6:
            jx = np.nan_to_num(tx[seg])
            jy = np.nan_to_num(ty[seg])
            rx, ry = jx - _smooth(jx, 7), jy - _smooth(jy, 7)
            jit = np.sqrt(_smooth(rx ** 2 + ry ** 2, 5))
            hot = jit > 0.0025
            if hot.sum() >= 3:
                idx = np.where(hot)[0]
                groups = np.split(idx, np.where(np.diff(idx) > 3)[0] + 1)
                for g in groups:
                    if len(g) >= 3:
                        shakes.append({"shot": si + 1, "start": round((a + g[0]) / fps, 3),
                                       "dur": round(len(g) / fps, 3),
                                       "intensity": round(float(jit[g].max() * 1080), 1)})
                        shot["shake"] = True
        # a punch right after the cut is not a speed ramp
        if shot["punch"] and shot["ramp"] and shot["ramp"]["where"] == "start" and shot["ramp"]["to"] - shot["start"] < 0.35:
            ramps.pop()
            shot["ramp"] = None
        shots.append(shot)

    curves = {"fps": fps, "speed": np.nan_to_num(speed).round(4).tolist(),
              "zoom": np.nan_to_num(zm * fps).round(4).tolist(), "cutscore": cutscore.round(4).tolist(),
              "luma": np.round(luma, 2).tolist(), "sharp": np.round(sharp_n, 3).tolist()}
    return {"fps": fps, "frames": n, "duration": n / fps, "shots": shots, "ramps": ramps,
            "punches": punches, "shakes": shakes,
            "flashes": [round(i / fps, 3) for i in flashes]}, curves


def export_frames(path, shots, outdir):
    """First / middle / last frame of every shot at full resolution."""
    import cv2
    fdir = Path(outdir) / "frames"
    fdir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(path))
    want = {}
    for s in shots:
        a, b = s["start_frame"], s["end_frame"] - 1
        for tag, fr in (("first", a + min(1, b - a)), ("mid", (a + b) // 2), ("last", max(a, b - 1))):
            want.setdefault(fr, []).append((s["index"], tag))
    i, got = 0, {}
    while want and i <= max(want):
        ok, f = cap.read()
        if not ok:
            break
        if i in want:
            for idx, tag in want[i]:
                p = fdir / f"shot{idx:02d}_{tag}.jpg"
                cv2.imwrite(str(p), f, [cv2.IMWRITE_JPEG_QUALITY, 90])
                got[(idx, tag)] = str(p)
        i += 1
    cap.release()
    for s in shots:
        s["frames"] = {t: media.rel(got.get((s["index"], t), ""), outdir) for t in ("first", "mid", "last")}


def contact_sheet(shots, outdir, cols=6):
    from PIL import Image, ImageDraw
    tiles = []
    for s in shots:
        p = Path(outdir) / s["frames"]["mid"]
        if not p.exists():
            continue
        im = Image.open(p).convert("RGB")
        im.thumbnail((240, 240))
        canvas = Image.new("RGB", (240, im.height + 46), (18, 18, 18))
        canvas.paste(im, ((240 - im.width) // 2, 0))
        d = ImageDraw.Draw(canvas)
        tag = f"#{s['index']} {s['start']:.2f}s  {s['dur']:.2f}s"
        extra = s["move"][:24]
        if s["ramp"]:
            extra += f" | RAMP x{s['ramp']['peak_ratio']}"
        if s["punch"]:
            extra += f" | punch {s['punch']['dir']}"
        d.text((6, im.height + 4), tag, fill=(255, 255, 255))
        d.text((6, im.height + 22), extra[:38], fill=(255, 200, 80))
        tiles.append(canvas)
    if not tiles:
        return None
    th = max(t.height for t in tiles)
    rows = math.ceil(len(tiles) / cols)
    sheet = Image.new("RGB", (cols * 244, rows * (th + 4)), (0, 0, 0))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * 244, (i // cols) * (th + 4)))
    out = Path(outdir) / "contact_sheet.jpg"
    sheet.save(out, quality=88)
    return str(out)


# ============================================================== audio

ASR = 22050
NFFT = 1024
HOP = 256
T0 = NFFT / 2 / ASR  # frame i is centred at i*HOP/ASR + T0


def _stft_mag(y):
    win = np.hanning(NFFT).astype(np.float32)
    nfr = 1 + max(0, (len(y) - NFFT) // HOP)
    idx = np.arange(NFFT)[None, :] + HOP * np.arange(nfr)[:, None]
    frames = y[idx] * win
    return np.abs(np.fft.rfft(frames, axis=1)).astype(np.float32)  # (frames, bins)


def _peaks(x, min_dist, thr):
    out = []
    last = -10 ** 9
    for i in range(1, len(x) - 1):
        if x[i] >= thr[i] if np.ndim(thr) else x[i] >= thr:
            if x[i] >= x[i - 1] and x[i] >= x[i + 1]:
                if i - last >= min_dist:
                    out.append(i)
                    last = i
                elif x[i] > x[last]:
                    out[-1] = i
                    last = i
    return out


def tempo_and_beats(onset, fr_rate):
    o = onset - onset.mean()
    ac = np.correlate(o, o, mode="full")[len(o) - 1:]
    lags = np.arange(len(ac))
    bpm = 60.0 * fr_rate / np.maximum(lags, 1)
    ok = (bpm >= 70) & (bpm <= 180)
    w = np.exp(-0.5 * (np.log2(np.maximum(bpm, 1) / 120.0) / 0.9) ** 2)
    score = np.where(ok, ac * w, -np.inf)
    lag = int(np.argmax(score))
    tempo = float(60.0 * fr_rate / lag)
    # dynamic-programming beat tracker (Ellis 2007)
    period = lag
    n = len(onset)
    cum = onset.astype(float).copy()
    back = np.full(n, -1)
    for i in range(n):
        lo, hi = i - 2 * period, i - period // 2
        if hi <= 0:
            continue
        lo = max(lo, 0)
        cand = np.arange(lo, hi)
        pen = -100 * (np.log((i - cand) / period)) ** 2
        sc = cum[cand] + pen
        j = int(np.argmax(sc))
        cum[i] = onset[i] + sc[j]
        back[i] = cand[j]
    # end on the best beat in the last period
    i = int(np.argmax(cum[max(0, n - period):])) + max(0, n - period)
    beats = []
    while i >= 0:
        beats.append(i)
        i = back[i]
    beats = beats[::-1]
    return tempo, [b / fr_rate for b in beats]


def analyze_audio(path):
    y = media.load_audio(path, sr=ASR, mono=True)
    if len(y) < NFFT * 2:
        return None, None
    S = _stft_mag(y)
    fr_rate = ASR / HOP
    freqs = np.fft.rfftfreq(NFFT, 1 / ASR)
    P = S ** 2 + 1e-12

    def band(lo, hi):
        m = (freqs >= lo) & (freqs < hi)
        return 10 * np.log10(P[:, m].sum(axis=1) + 1e-12)

    sub, low, mid, high = band(20, 120), band(120, 500), band(500, 4000), band(4000, 11000)
    total = 10 * np.log10(P.sum(axis=1))
    rms_db = total - total.max()
    centroid = (P * freqs).sum(axis=1) / P.sum(axis=1)
    cum = np.cumsum(P, axis=1)
    rolloff = freqs[np.argmax(cum >= 0.85 * cum[:, -1:], axis=1)]
    flat = np.exp(np.mean(np.log(P[:, 5:]), axis=1)) / np.mean(P[:, 5:], axis=1)
    logS = np.log1p(10 * S)
    flux = np.maximum(0, np.diff(logS, axis=0, prepend=logS[:1])).sum(axis=1)
    onset = _smooth(flux, 3)
    onset = onset / (onset.max() + 1e-9)
    # beat tracking leans on the low end (kick / bass) so hats don't pull the grid onto the off-beats
    lowm = freqs < 300
    lflux = np.maximum(0, np.diff(logS[:, lowm], axis=0, prepend=logS[:1, lowm])).sum(axis=1)
    lflux = _smooth(lflux, 3)
    beat_onset = lflux / (lflux.max() + 1e-9) + 0.4 * onset

    tempo, beats = tempo_and_beats(beat_onset, fr_rate)
    beats = [b + T0 for b in beats]
    t = np.arange(len(onset)) / fr_rate + T0
    events = []

    # transients -> impact / kick / click / hit
    loc = _smooth(onset, int(fr_rate * 0.5))
    thr = np.maximum(0.25, loc * 2.2)
    lowsum = _smooth((sub + low) / 2, int(0.03 * fr_rate))
    f = lambda sec: int(sec * fr_rate)
    for i in _peaks(onset, f(0.08), thr):
        pre = slice(max(0, i - f(0.15)), max(1, i - 2))
        post = slice(i, min(len(sub), i + f(0.25)))
        low_jump = lowsum[post].mean() - lowsum[pre].mean()
        lpk = lowsum[i:i + f(0.06)].max() if i + f(0.06) < len(lowsum) else lowsum[i]
        tail = lowsum[i + f(0.3):i + f(0.5)].mean() if i + f(0.5) < len(lowsum) else lpk - 20
        sustain = tail - lpk  # SFX impacts ring out (sub boom); music kicks die within ~0.3 s
        k40 = min(len(total) - 1, i + f(0.04))
        decay = total[i] - total[k40]
        hi_ratio = high[i] - low[i]
        if low_jump > 8 and np.mean(rms_db[post]) > -30:
            kind = "impact" if sustain > -10 else "kick"
        elif decay > 12 and hi_ratio > -6:
            kind = "click"
        else:
            kind = "hit"
        events.append({"type": kind, "time": round(float(t[i]), 3), "strength": round(float(onset[i]), 2)})

    # whooshes: noisy high-band swells 0.2-2.2 s wide. Smoothing hides short hats; the baseline is the music bed.
    hb = _smooth(band(1500, 8000), f(0.08))
    base = _smooth(hb, f(2.0))
    prom = hb - base
    for i in _peaks(prom, f(0.3), 6.0):
        half = prom[i] - min(10.0, prom[i] / 2)
        l = i
        while l > 0 and prom[l] > half:
            l -= 1
        r = i
        while r < len(prom) - 1 and prom[r] > half:
            r += 1
        width = (r - l) / fr_rate
        if 0.15 <= width <= 2.2 and np.mean(flat[l:r + 1]) > 0.02:
            events.append({"type": "whoosh", "time": round(float(t[i]), 3), "start": round(float(t[l]), 3),
                           "end": round(float(t[r]), 3), "dur": round(width, 3),
                           "rise": round(float((i - l) / fr_rate), 3), "prominence_db": round(float(prom[i]), 1)})

    # drop: biggest low-end jump comparing 1 s after vs 1 s before
    w = f(1.0)
    lows = _smooth((sub + low) / 2, f(0.1))
    best, drop = -1e9, None
    for i in range(w, len(lows) - w, max(1, f(0.05))):
        d = lows[i:i + w].mean() - lows[i - w:i].mean()
        if d > best:
            best, drop = d, i
    drop_t = float(t[drop]) if drop is not None and best > 4 else None
    if drop_t is not None and beats:  # a drop lives on a beat: snap to it when close
        nb = min(beats, key=lambda b: abs(b - drop_t))
        if abs(nb - drop_t) < 0.12:
            drop_t = float(nb)

    # risers: steady build (centroid + energy) for 1-10 s that ends on a strong moment
    cs = _smooth(centroid, f(0.2))
    es = _smooth(total, f(0.2))
    ends = [e["time"] for e in events if e["type"] in ("impact", "kick", "hit") and e["strength"] > 0.45]
    if drop_t:
        ends.append(drop_t)
    used_end = -1
    for et in sorted(set(round(x, 3) for x in ends)):
        i = int((et - T0) * fr_rate)
        best_r = None
        for L in (1, 1.5, 2, 3, 4, 6, 8, 10):
            a0 = i - f(L)
            if a0 < 0:
                break
            seg_t = np.arange(i - a0)
            c1 = np.corrcoef(seg_t, cs[a0:i])[0, 1]
            c2 = np.corrcoef(seg_t, es[a0:i])[0, 1]
            rise = es[i - 1] - es[a0]
            if (c1 > 0.75 or c2 > 0.8) and rise > 5:
                best_r = (L, a0)
        if best_r and i > used_end + f(1.0):
            used_end = i
            events.append({"type": "riser", "start": round(float(t[best_r[1]]), 3), "time": et, "dur": best_r[0]})

    # lowpass: the top end is missing for a while, then opens up at a strong moment (usually the drop)
    hr = _smooth(high - mid, f(0.3))
    alive = rms_db > -40
    cands = sorted(set([drop_t] if drop_t else []) | {e["time"] for e in events if e["type"] == "impact"})
    done = -1.0
    for c in cands:
        if c <= done:
            continue
        i = int((c - T0) * fr_rate)
        if i - f(1.5) < 0 or i + f(1.5) >= len(hr):
            continue
        before = hr[i - f(1.5):i - f(0.15)][alive[i - f(1.5):i - f(0.15)]]
        after = hr[i + f(0.05):i + f(1.5)]
        if len(before) < f(0.5):
            continue
        gain = float(after.mean() - before.mean())
        if gain > 8:
            j = i - f(0.15)
            while j > 0 and hr[j] < after.mean() - 4 and alive[j]:
                j -= 1
            events.append({"type": "lowpass", "start": round(float(t[j]), 3), "end": round(c, 3), "time": round(c, 3),
                           "top_end_gain_db": round(gain, 1)})
            done = c
    ro = _smooth(rolloff, f(0.25))

    events.sort(key=lambda e: e.get("start", e["time"]) if e["type"] in ("riser", "lowpass") else e["time"])
    curves = {"rate": fr_rate, "t0": T0, "rms_db": rms_db[::2].round(2).tolist(), "onset": onset[::2].round(3).tolist(),
              "rolloff": ro[::2].round(0).tolist()}
    return {"duration": len(y) / ASR, "tempo_bpm": round(tempo, 1), "beats": [round(b, 3) for b in beats],
            "drop": round(drop_t, 3) if drop_t else None, "events": events,
            "_spec": (S, freqs)}, curves


# ============================================================== combine

def relate(video, audio):
    """Cut timing vs beats, and which sound events sit on cuts / ramps / punches."""
    cuts = [s["start"] for s in video["shots"][1:]]
    out = {"cuts": len(cuts), "avg_shot": round(np.mean([s["dur"] for s in video["shots"]]), 3)}
    if audio and audio["beats"]:
        beats = np.array(audio["beats"])
        period = 60.0 / audio["tempo_bpm"]
        offs = [float(c - beats[np.argmin(np.abs(beats - c))]) for c in cuts]
        out["cuts_on_beat_pct"] = round(100 * np.mean([abs(o) < 0.07 for o in offs]), 1) if offs else 0
        out["shot_len_beats"] = [round(s["dur"] / period, 2) for s in video["shots"]]
        for s in video["shots"]:
            s["beats"] = round(s["dur"] / period, 2)
    if audio:
        for s in video["shots"]:
            near = [e for e in audio["events"] if abs(e["time"] - s["start"]) < 0.12 and e["type"] != "lowpass"]
            s["sound_on_cut"] = sorted({e["type"] for e in near})
        for r in video["ramps"]:
            r["whoosh"] = any(e["type"] == "whoosh" and e.get("start", 0) - 0.1 <= r["peak_at"] <= e.get("end", 0) + 0.1
                              for e in audio["events"])
    # sections: hook = up to the drop (if early) else up to where shots get longer
    durs = np.array([s["dur"] for s in video["shots"]])
    hook_end = None
    if audio and audio.get("drop") and audio["drop"] < 0.5 * video["duration"]:
        hook_end = audio["drop"]
    elif len(durs) > 4:
        med = np.median(durs)
        for s in video["shots"]:
            if s["start"] > 1.5 and s["dur"] > 1.6 * med:
                hook_end = s["start"]
                break
    out["sections"] = [{"name": "hook", "start": 0, "end": round(hook_end, 3)},
                       {"name": "body", "start": round(hook_end, 3), "end": round(video["duration"], 3)}] if hook_end else \
        [{"name": "body", "start": 0, "end": round(video["duration"], 3)}]
    for s in video["shots"]:
        s["section"] = "hook" if hook_end and s["start"] < hook_end - 0.05 else "body"
    return out


def plot_timeline(video, vcurves, audio, acurves, outdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    dur = video["duration"]
    rows = 4 if audio else 2
    fig, axes = plt.subplots(rows, 1, figsize=(18, 2.3 * rows + 1), sharex=True,
                             gridspec_kw={"height_ratios": [1, 1.3, 1.2, 2.2][:rows]})
    fig.patch.set_facecolor("#111")
    for ax in axes:
        ax.set_facecolor("#161616")
        ax.tick_params(colors="#bbb")
        for sp in ax.spines.values():
            sp.set_color("#333")
    ax = axes[0]
    for s in video["shots"]:
        c = "#e0a030" if s["ramp"] else ("#40a0e0" if s.get("section") == "hook" else "#5a5a5a")
        ax.barh(0, s["dur"], left=s["start"], color=c, edgecolor="#000")
        ax.text(s["start"] + s["dur"] / 2, 0, str(s["index"]), ha="center", va="center", color="w", fontsize=7)
    for f in video["flashes"]:
        ax.axvline(f, color="w", lw=1)
    ax.set_yticks([])
    ax.set_title("shots (blue=hook, orange=has speed ramp, white line=flash)", color="#ddd", fontsize=9, loc="left")
    fps = vcurves["fps"]
    tt = np.arange(len(vcurves["speed"])) / fps
    ax = axes[1]
    ax.plot(tt, vcurves["speed"], color="#e0a030", lw=1, label="motion speed (frame widths/s)")
    ax.plot(tt, np.clip(vcurves["zoom"], -3, 3), color="#50d0a0", lw=1, label="zoom rate (+in / -out)")
    for sh in video["shakes"]:
        ax.axvspan(sh["start"], sh["start"] + sh["dur"], color="#ff4060", alpha=0.25)
    for p in video["punches"]:
        ax.axvline(p["at"], color="#50d0a0", ls=":", lw=1)
    ax.legend(loc="upper right", fontsize=7, facecolor="#222", labelcolor="#ddd")
    ax.set_title("camera motion (red band = shake, dotted = scale punch)", color="#ddd", fontsize=9, loc="left")
    if audio:
        ar = acurves["rate"] / 2
        ta = np.arange(len(acurves["rms_db"])) / ar + acurves.get("t0", 0)
        ax = axes[2]
        ax.plot(ta, acurves["rms_db"], color="#9090ff", lw=0.8)
        for b in audio["beats"]:
            ax.axvline(b, color="#444", lw=0.5)
        if audio["drop"]:
            ax.axvline(audio["drop"], color="#ff4060", lw=2)
        ax.set_title(f"loudness dB, beat grid ({audio['tempo_bpm']} BPM), red = drop", color="#ddd", fontsize=9, loc="left")
        ax = axes[3]
        S, freqs = audio["_spec"]
        m = freqs <= 11000
        spec = 20 * np.log10(S[:, m].T + 1e-6)
        ax.imshow(spec, aspect="auto", origin="lower", cmap="magma", extent=[T0, S.shape[0] * HOP / ASR + T0, 0, 11],
                  vmin=spec.max() - 80, vmax=spec.max())
        colors = {"whoosh": "#40e0ff", "impact": "#ff4060", "click": "#ffffff", "hit": "#aaaaaa", "kick": "#666666",
                  "riser": "#ffd040", "lowpass": "#80ff80"}
        for e in audio["events"]:
            c = colors[e["type"]]
            if e["type"] in ("riser", "lowpass"):
                a0, a1 = e["start"], e.get("end", e["time"]) if e["type"] == "lowpass" else e["time"]
                ax.axvspan(a0, a1, ymin=0.9 if e["type"] == "riser" else 0.0, ymax=1.0 if e["type"] == "riser" else 0.08,
                           color=c, alpha=0.7)
            else:
                quiet = e["type"] in ("hit", "kick")
                ax.axvline(e["time"], color=c, lw=0.5 if quiet else 1.2, alpha=0.35 if quiet else 0.9)
                if not quiet:
                    ax.text(e["time"], 10.2, e["type"][0].upper(), color=c, fontsize=8, ha="center", weight="bold")
        ax.set_ylabel("kHz", color="#bbb")
        ax.set_title("spectrogram  W=whoosh I=impact C=click (faint lines = drum hits / kicks), yellow top band=riser, green bottom band=lowpass",
                     color="#ddd", fontsize=9, loc="left")
    axes[-1].set_xlim(0, dur)
    axes[-1].set_xlabel("seconds", color="#bbb")
    for s in video["shots"][1:]:
        for ax in axes[1:]:
            ax.axvline(s["start"], color="#666", lw=0.6, ls="--")
    plt.tight_layout()
    out = Path(outdir) / "timeline.png"
    plt.savefig(out, dpi=90, facecolor=fig.get_facecolor())
    plt.close(fig)
    return str(out)


def write_markdown(rep, outdir):
    v, a, rel = rep["video"], rep.get("audio"), rep["relations"]
    L = [f"# Reference breakdown: {Path(rep['source']).name}", "",
         f"- Length **{v['duration']:.2f}s**, {len(v['shots'])} shots, average shot **{rel['avg_shot']:.2f}s**, {v['fps']:.2f} fps",
         f"- Size {rep['info'].get('width')}x{rep['info'].get('height')}"]
    if a:
        L.append(f"- Tempo **{a['tempo_bpm']} BPM**, drop at **{a['drop']}s**, cuts on the beat: **{rel.get('cuts_on_beat_pct', 0)}%**")
    for s in rel["sections"]:
        L.append(f"- Section **{s['name']}**: {s['start']}s to {s['end']}s")
    L += ["", "## Shots", "",
          "| # | start | dur | beats | section | camera move | speed ramp | punch | shake | sound on cut |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for s in v["shots"]:
        ramp = f"{s['ramp']['where']} x{s['ramp']['peak_ratio']} @ {s['ramp']['peak_at']}s" if s["ramp"] else ""
        punch = f"{s['punch']['dir']} ({s['punch']['rate']}/s)" if s["punch"] else ""
        L.append(f"| {s['index']} | {s['start']:.2f} | {s['dur']:.2f} | {s.get('beats', '')} | {s.get('section', '')} | "
                 f"{s['move']} | {ramp} | {punch} | {'yes' if s['shake'] else ''} | {', '.join(s.get('sound_on_cut', []))} |")
    if a:
        L += ["", "## Sound events (estimated from the spectrum, confirm by ear)", "", "| type | time | details |", "|---|---|---|"]
        for e in a["events"]:
            det = {k: e[k] for k in e if k not in ("type", "time")}
            L.append(f"| {e['type']} | {e['time']:.2f} | {det} |")
    L += ["", "## Files", "", "- `timeline.png`: shots, motion, loudness and spectrogram on one time axis",
          "- `contact_sheet.jpg`: middle frame of every shot", "- `frames/`: first / mid / last frame of every shot"]
    Path(outdir, "report.md").write_text("\n".join(L))


def analyze(path, outdir):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    info = media.probe(path)
    video, vcurves = analyze_video(path, outdir)
    export_frames(path, video["shots"], outdir)
    audio, acurves = analyze_audio(path) if info["has_audio"] else (None, None)
    rel = relate(video, audio)
    contact_sheet(video["shots"], outdir)
    plot_timeline(video, vcurves, audio, acurves, outdir)
    if audio:
        audio.pop("_spec", None)
    rep = {"source": str(path), "info": info, "video": video, "audio": audio, "relations": rel}
    (outdir / "report.json").write_text(json.dumps(rep, indent=1))
    (outdir / "curves.json").write_text(json.dumps({"video": vcurves, "audio": acurves}))
    write_markdown(rep, outdir)
    return rep
