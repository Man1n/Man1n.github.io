"""Picture rendering.

bake    one file per shot, exact shot length, speed ramp + motion blur baked in, framed to the sequence.
        Scale punches and shakes stay OFF so they arrive in Premiere as editable Motion keyframes.
        (--burn-motion bakes those too.)
previz  the whole edit in one file: ramps, scale, shakes, overlays, mixed audio. For reviewing fast.
"""
from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

import numpy as np

from . import curves, media


def _sample(reader, src_fps, t_src, speed, out_fps, blur, shutter_deg):
    """Frame at source time t_src. Fast -> average sub-frames across the shutter. Slow -> blend neighbours."""
    if blur and speed > 1.6:
        span = speed / out_fps * shutter_deg / 360.0  # seconds of source the shutter is open
        nsub = int(min(10, max(2, math.ceil(span * src_fps))))
        acc = None
        for j in range(nsub):
            f = reader.get(int(round((t_src + span * j / nsub) * src_fps))).astype(np.float32)
            acc = f if acc is None else acc + f
        return (acc / nsub).astype(np.uint8)
    x = t_src * src_fps
    i0 = int(math.floor(x))
    w = x - i0
    if speed < 0.9 and 0.15 < w < 0.85:
        a = reader.get(i0).astype(np.float32)
        b = reader.get(i0 + 1).astype(np.float32)
        return (a * (1 - w) + b * w).astype(np.uint8)
    return reader.get(int(round(x)))


def _frame_xform(frame, W, H, scale_pct, dx, dy, rot):
    import cv2
    sh, sw = frame.shape[:2]
    s = max(W / sw, H / sh) * scale_pct / 100.0
    M = cv2.getRotationMatrix2D((sw / 2, sh / 2), -rot, s)
    M[0, 2] += W / 2 - sw / 2 + dx
    M[1, 2] += H / 2 - sh / 2 + dy
    return cv2.warpAffine(frame, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def render_shot_frames(shot, plan, style, W, H, motion=True):
    fps = plan["meta"]["fps"]
    rp = style["speed_ramp"]
    reader = media.FrameReader(shot["src"])
    keys = curves.speed_keys_for_shot(shot, rp)
    src_t, speeds = curves.time_map(keys, shot["dur"], fps, shot["in"])
    try:
        for k, (ts, sp) in enumerate(zip(src_t, speeds)):
            f = _sample(reader, reader.fps, ts, sp, fps, rp.get("motion_blur", True), rp.get("shutter_deg", 270))
            t = shot["start"] + k / fps
            if motion:
                scale = curves.interp_keys(shot.get("scale") or [], t, 100.0)
                dx, dy, rot = curves.shake_offset(t, shot.get("shakes") or [], W)
            else:
                scale, dx, dy, rot = 100.0, 0.0, 0.0, 0.0
            yield _frame_xform(f, W, H, scale, dx, dy, rot)
    finally:
        reader.close()


def bake(plan, style, outdir, codec="prores", burn_motion=False):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    W, H, fps = plan["meta"]["width"], plan["meta"]["height"], plan["meta"]["fps"]
    ext = ".mov" if codec.startswith("prores") else ".mp4"
    for s in plan["shots"]:
        out = outdir / f"{s['id']}{ext}"
        w = media.FrameWriter(out, W, H, fps, codec=codec, crf=14)
        for fr in render_shot_frames(s, plan, style, W, H, motion=burn_motion):
            w.write(fr)
        w.close()
        s["baked"] = str(out)
        s["baked_motion"] = burn_motion
    return plan


def previz(plan, style, outdir, scale=0.5, overlays_dir=None, audio=None):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    W = int(plan["meta"]["width"] * scale) // 2 * 2
    H = int(plan["meta"]["height"] * scale) // 2 * 2
    fps = plan["meta"]["fps"]
    pic = outdir / "previz_picture.mp4"
    w = media.FrameWriter(pic, W, H, fps, codec="h264", crf=20)
    for s in plan["shots"]:
        # shake amplitudes are defined at full res; scale them down with the frame
        sc = {**s, "shakes": [{**x, "amp": x["amp"]} for x in s.get("shakes", [])]}
        for fr in render_shot_frames(sc, plan, style, W, H, motion=True):
            w.write(fr)
    w.close()
    cur = pic
    # overlays
    ovs = [o for o in plan["overlays"] if o.get("file") and Path(o["file"]).exists()]
    if ovs:
        comp = outdir / "previz_comp.mp4"
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(cur)]
        for o in ovs:
            cmd += ["-i", o["file"]]
        fg, last = [], "0:v"
        for k, o in enumerate(ovs, start=1):
            fg.append(f"[{k}:v]scale={W}:{H},format=rgba,setpts=PTS-STARTPTS+{o['start']}/TB[o{k}]")
            fg.append(f"[{last}][o{k}]overlay=0:0:eof_action=pass:enable='between(t,{o['start']},{o['start'] + o['dur']})'[v{k}]")
            last = f"v{k}"
        cmd += ["-filter_complex", ";".join(fg), "-map", f"[{last}]", "-c:v", "libx264", "-crf", "20",
                "-pix_fmt", "yuv420p", str(comp)]
        subprocess.run(cmd, check=True)
        cur = comp
    final = outdir / "previz.mp4"
    if audio:
        media.mux(cur, audio, final)
    else:
        cur.replace(final)
    return str(final)
