"""The edit plan: one JSON file that describes the whole edit.

Everything renders from it (previz, baked ramp clips, Premiere steps), and Claude edits it directly.

plan.json
  meta      {name, width, height, fps}
  music     {file, offset, gain_db, bpm, beats[], drop}
  sections  [{name, start, end}]
  shots     [{id, src, in, start, dur, role, section, speed, scale[], shakes[], transition, note}]
  overlays  [{template, start, dur, params, track}]
  sfx       [{id, category, file, start, gain_db, align_time, reason, auto}]
  ambience  [{file, start, end, gain_db, fade}]
  fx        [{type: lowpass, target: music, keys: [[t, cutoff_hz, ease]]}]
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import yaml

from . import curves, media

HERE = Path(__file__).parent


def load_style(path=None):
    return yaml.safe_load(Path(path or HERE / "style" / "profile.yaml").read_text())


def load(path):
    return json.loads(Path(path).read_text())


def save(plan, path):
    Path(path).write_text(json.dumps(plan, indent=1))


def role_for(name, style):
    low = Path(name).stem.lower()
    first = re.split(r"[^a-z]+", low)[0] if low else ""
    for role in style["roles"]:          # an explicit role as the first word wins: lifestyle_pool.mp4 -> lifestyle
        if first == role:
            return role
    for role, words in style["roles"].items():
        if first in words:
            return role
    for role, words in style["roles"].items():
        if any(re.search(rf"(^|[^a-z]){re.escape(w)}", low) for w in words):
            return role
    return "interior"


def probe_clips(folder):
    out = []
    for p in media.list_media(folder, media.VIDEO_EXT):
        info = media.probe(p)
        if info["has_video"]:
            out.append({"src": str(p), "duration": info["duration"], "fps": info["fps"],
                        "width": info["width"], "height": info["height"]})
    return out


def music_info(path):
    """Tempo, beats and drop for the music track (reuses the ref analyzer's audio pass)."""
    from . import analyze_ref
    a, _ = analyze_ref.analyze_audio(path)
    a.pop("_spec", None)
    return {"file": str(path), "offset": 0.0, "gain_db": 0.0, "bpm": a["tempo_bpm"], "beats": a["beats"],
            "drop": a["drop"], "duration": a["duration"],
            "events": [e for e in a["events"] if e["type"] in ("impact", "riser", "lowpass")]}


# ------------------------------------------------------------------ clip assignment

class ClipPool:
    """Hands out clips by role, cycling, and tracks how much source each clip still has."""

    def __init__(self, clips, style):
        self.clips = clips
        for c in clips:
            c.setdefault("role", role_for(c["src"], style))
            c["cursor"] = min(0.3, c["duration"] * 0.05)
        self.last = None

    def take(self, role=None, need=1.0):
        cands = [c for c in self.clips if role is None or c["role"] == role] or self.clips
        if len(cands) > 1:  # never the same clip twice in a row
            cands = [c for c in cands if c is not self.last] or cands
        elif self.last is cands[0] and len(self.clips) > 1:
            cands = [c for c in self.clips if c is not self.last]
        cands = sorted(cands, key=lambda c: (c.get("uses", 0), -(c["duration"] - c["cursor"])))
        c = cands[0]
        self.last = c
        c["uses"] = c.get("uses", 0) + 1
        start = c["cursor"]
        if start + need > c["duration"] - 0.05:
            start = max(0.0, c["duration"] - need - 0.05)
        c["cursor"] = start + need
        if c["cursor"] > c["duration"] - 0.5:
            c["cursor"] = 0.2
        return c, max(0.0, start)


def _grid_times(beats, bpm, start, end, every):
    period = 60.0 / bpm
    if beats:
        b = np.array(beats)
        # extend the grid before/after the detected beats
        pre = np.arange(b[0] - period, -period, -period)[::-1]
        post = np.arange(b[-1] + period, end + 4 * period, period)
        b = np.concatenate([pre[pre >= 0], b, post])
    else:
        b = np.arange(0, end + period, period)
    if every < 1:
        sub = int(round(1 / every))
        b = np.sort(np.concatenate([b + k * period / sub for k in range(sub)]))
        stride = 1
    else:
        stride = int(round(every))
    first = int(np.argmin(np.abs(b - start)))
    return [float(t) for t in b[first::stride] if start - 1e-3 <= t <= end + 1e-3]


# ------------------------------------------------------------------ builders

def _base_plan(name, style, music):
    f = style["format"]
    return {"meta": {"name": name, "width": f["width"], "height": f["height"], "fps": f["fps"]},
            "music": music, "sections": [], "shots": [], "overlays": [], "sfx": [], "ambience": [], "fx": []}


def _fit_need(shot, style, fps):
    return curves.source_needed(shot, style["speed_ramp"], fps)


def build_auto(name, clips_dir, music_path, style, length=None):
    """No reference: build a beat-synced edit from the house style."""
    music = music_info(music_path)
    plan = _base_plan(name, style, music)
    fps = plan["meta"]["fps"]
    bpm = music["bpm"]
    period = 60.0 / bpm
    total = min(length or music["duration"], music["duration"])
    hook_len = style["hook"]["length_beats"] * period
    drop = music["drop"] if music["drop"] and music["drop"] < total * 0.5 else None
    hook_end = drop if drop and abs(drop - hook_len) < 4 * period else _grid_times(music["beats"], bpm, hook_len, hook_len + period, 1)[0]
    plan["sections"] = [{"name": "hook", "start": 0.0, "end": round(hook_end, 3)},
                        {"name": "body", "start": round(hook_end, 3), "end": round(total, 3)}]
    cuts = [0.0] + _grid_times(music["beats"], bpm, period * 0.999, hook_end, style["hook"]["cut_every_beats"])
    cuts = [c for c in cuts if c < hook_end - 0.1] + [hook_end]
    body = _grid_times(music["beats"], bpm, hook_end, total, style["body"]["cut_every_beats"])
    cuts += [c for c in body if c > hook_end + 0.2 and c < total - 0.2] + [total]
    cuts = sorted(set(round(c, 3) for c in cuts))
    _fill_shots(plan, cuts, clips_dir, style, hook_end)
    return plan


def build_from_ref(name, report_path, clips_dir, music_path, style):
    """Recreate a reference: same shot durations, sections, ramps, punches and shakes; your clips and music."""
    rep = json.loads(Path(report_path).read_text())
    v = rep["video"]
    music = music_info(music_path) if music_path else {"file": None, "offset": 0, "gain_db": 0,
                                                       "bpm": (rep.get("audio") or {}).get("tempo_bpm", 120),
                                                       "beats": (rep.get("audio") or {}).get("beats", []),
                                                       "drop": (rep.get("audio") or {}).get("drop")}
    plan = _base_plan(name, style, music)
    plan["meta"]["reference"] = rep["source"]
    cuts = [s["start"] for s in v["shots"]] + [v["duration"]]
    secs = rep["relations"]["sections"]
    plan["sections"] = secs
    hook_end = next((s["end"] for s in secs if s["name"] == "hook"), 0.0)
    ref_shots = {s["index"]: s for s in v["shots"]}
    _fill_shots(plan, cuts, clips_dir, style, hook_end, ref_shots=ref_shots)
    plan["meta"]["reference_shots"] = [{"index": s["index"], "move": s["move"], "frames": s["frames"]} for s in v["shots"]]
    return plan


def _fill_shots(plan, cuts, clips_dir, style, hook_end, ref_shots=None):
    fps = plan["meta"]["fps"]
    pool = ClipPool(probe_clips(clips_dir), style)
    if not pool.clips:
        raise SystemExit(f"no video clips found in {clips_dir}")
    hs = style["hook"]
    rp = style["speed_ramp"]
    n = len(cuts) - 1
    body_idx = 0
    shots = []
    # decide ramp transitions (cut i is between shot i-1 and shot i)
    ramp_cuts = set()
    for i in range(1, n):
        if ref_shots:
            a, b = ref_shots.get(i), ref_shots.get(i + 1)
            if (a and a["ramp"] and a["ramp"]["where"] == "end") or (b and b["ramp"] and b["ramp"]["where"] == "start"):
                ramp_cuts.add(i)
        elif cuts[i] > hook_end + 0.05:
            body_idx += 1
            if body_idx % style["body"]["ramp_every_n_cuts"] == 0:
                ramp_cuts.add(i)
        elif abs(cuts[i] - hook_end) < 0.05:
            ramp_cuts.add(i)  # hook -> body is a ramp transition
    hero_every = 4
    for i in range(n):
        start, end = cuts[i], cuts[i + 1]
        dur = round(end - start, 3)
        section = "hook" if start < hook_end - 0.05 else "body"
        ref = ref_shots.get(i + 1) if ref_shots else None
        # role: the shot right after the drop and every few body shots are hero moments
        if ref and ref.get("role"):
            want = ref["role"]
        elif section == "body" and (abs(start - hook_end) < 0.05 or (i % hero_every == 0)):
            want = "hero"
        elif section == "body" and i % 3 == 1:
            want = "lifestyle"
        else:
            want = None
        shot = {"id": f"s{i + 1:02d}", "start": round(start, 3), "dur": dur, "section": section,
                "transition": "ramp" if i in ramp_cuts else "cut", "speed": 1.0, "scale": [], "shakes": [], "note": ""}
        ramp_in = i in ramp_cuts
        ramp_out = (i + 1) in ramp_cuts
        if ramp_in or ramp_out:
            shot["speed"] = {"ramp_in": ramp_in, "ramp_out": ramp_out}
        need = _fit_need(shot, style, fps)
        clip, src_in = pool.take(want, need)
        shot.update(src=clip["src"], role=clip["role"] if want is None else want, **{"in": round(src_in, 3)})
        if clip["duration"] < need + src_in:
            shot["note"] = f"source short: needs {need:.2f}s, clip has {clip['duration']:.2f}s; ramp peak lowered"
            if isinstance(shot["speed"], dict):
                shot["speed"]["peak"] = max(1.5, rp["peak_speed"] * clip["duration"] / max(need, 1e-3) * 0.9)
        # motion
        if section == "hook":
            k = i % 2 if hs.get("alt_scale_out") else 0
            sp = hs["scale_punch"]
            t1 = min(dur, sp["frames"] / fps)
            if k == 0:   # punch: lands zoomed, snaps back out (reads as a hit)
                shot["scale"] = [[start, sp["from"]], [start + t1, sp["to"], sp["ease"]]]
            else:        # scale in: lands wide, pushes in fast
                shot["scale"] = [[start, sp["to"]], [start + t1 * 1.5, sp["to"] + (sp["from"] - sp["to"]) * 0.6, sp["ease"]]]
            if hs.get("shake_on_cuts") and i > 0:
                shot["shakes"].append(_shake(style, start, 0.7))
        else:
            drift = style["body"]["slow_scale_drift"]
            if shot["transition"] == "cut" and not ramp_out:
                shot["scale"] = [[start, 100], [end, 100 + drift, "linear"]]
            elif ramp_in:
                # land the ramp with a small push that settles
                shot["scale"] = [[start, 112], [start + min(dur * 0.4, 0.5), 100, "easeOut"]]
        if ref:
            shot["note"] = (shot["note"] + f" ref #{ref['index']}: {ref['move']}").strip()
            if ref.get("punch"):
                t1 = min(dur, 6 / fps)
                if ref["punch"]["dir"] == "in":
                    shot["scale"] = [[start, 100], [start + t1, 114, "easeOut"]]
                else:
                    shot["scale"] = [[start, 116], [start + t1, 100, "easeOut"]]
            if ref.get("shake"):
                shot["shakes"] = [_shake(style, start, 1.0)]
        shots.append(shot)
    plan["shots"] = shots


def _shake(style, t, strength=1.0):
    s = style["shake"]
    return {"start": round(t, 3), "dur": s["duration"], "amp": s["amplitude_px"] * strength,
            "freq": s["frequency_hz"], "rot": s["rotation_deg"] * strength, "decay": s["decay"],
            "seed": int(t * 1000) % 997}


def summary(plan):
    L = [f"{plan['meta']['name']}: {len(plan['shots'])} shots, {plan['shots'][-1]['start'] + plan['shots'][-1]['dur']:.2f}s"]
    for s in plan["shots"]:
        sp = s["speed"]
        spd = "" if sp == 1.0 else ("ramp " + ("in " if sp.get("ramp_in") else "") + ("out" if sp.get("ramp_out") else "")) if isinstance(sp, dict) else f"x{sp}"
        L.append(f"  {s['id']} {s['start']:6.2f}s {s['dur']:5.2f}s {s['section']:4} {s['role']:12} {Path(s['src']).name:28} {spd} "
                 f"{'shake ' if s['shakes'] else ''}{s['note']}")
    L.append(f"  sfx cues: {len(plan['sfx'])}, overlays: {len(plan['overlays'])}, ambience beds: {len(plan['ambience'])}")
    return "\n".join(L)
