"""Auto sound design: turns the plan's picture events into SFX cues, ambience beds and music FX.

Rules (all tunable in style/profile.yaml):
  speed ramp      whoosh whose loudest point lands on the fastest frame; its length matches the fast stretch
  hook cuts       click on each cut; a quick whoosh under each scale-in
  hook -> drop    riser that ends exactly on the drop; music lowpassed under the hook, swept open into the drop
  hero shots      impact (with a sub boom) on the reveal, plus a camera shake on the same frame
  lifestyle       ambience bed under the shot (pool / birds / city / room tone picked from the clip name)
  overlays        click as each graphic pops in
  body            SFX sit lower once the music takes the lead
Manual cues (no "auto": true) are never touched when this re-runs.
"""
from __future__ import annotations

import math
from pathlib import Path

from . import curves
from .plan import _shake


def _cue(cat, pick, start, gain, align, reason, file_in=0.0):
    return {"id": None, "category": cat, "file": pick["path"], "start": round(start, 3), "file_in": round(file_in, 3),
            "gain_db": round(gain, 1), "align_time": round(align, 3), "dur": pick["dur"], "reason": reason, "auto": True}


def _amb_tags(src):
    n = Path(src).stem.lower()
    for key, tag in (("pool", "pool"), ("water", "pool"), ("beach", "pool"), ("ocean", "pool"), ("garden", "birds"),
                     ("yard", "birds"), ("outdoor", "birds"), ("patio", "birds"), ("terrace", "birds"),
                     ("balcony", "city"), ("city", "city"), ("street", "city"), ("rooftop", "city")):
        if key in n:
            return [tag]
    return ["room"]


def auto_sfx(plan, style, picker):
    fps = plan["meta"]["fps"]
    rp = style["speed_ramp"]
    body_gain = style["body"]["sfx_gain_db"]
    plan["sfx"] = [c for c in plan["sfx"] if not c.get("auto")]
    plan["ambience"] = [a for a in plan["ambience"] if not a.get("auto")]
    plan["fx"] = [f for f in plan["fx"] if not f.get("auto")]
    shots = plan["shots"]
    hook_end = next((s["end"] for s in plan["sections"] if s["name"] == "hook"), 0.0)
    bpm = plan["music"].get("bpm") or 120
    period = 60.0 / bpm
    cues = []

    def sec_gain(t):
        return body_gain if t >= hook_end - 0.02 else 0.0

    # ---- speed ramps -> whooshes matched to the fast stretch
    if rp.get("whoosh", True):
        handled = set()
        for i, s in enumerate(shots):
            sp = s["speed"]
            if not isinstance(sp, dict) or s["id"] in handled:
                continue
            nxt = shots[i + 1] if i + 1 < len(shots) else None
            if sp.get("ramp_out") and nxt is not None:
                cut = nxt["start"]
                fast_from = s["start"] + s["dur"] * (1 - float(sp.get("out_portion", rp["out_portion"])))
                nsp = nxt["speed"] if isinstance(nxt["speed"], dict) else {}
                fast_to = cut + nxt["dur"] * float(nsp.get("in_portion", rp["in_portion"])) if nsp.get("ramp_in") else cut
                peak_t, peak_speed = cut, float(sp.get("peak", rp["peak_speed"]))
                handled.add(nxt["id"])
            elif sp.get("ramp_in") and not sp.get("ramp_out"):
                peak_t, peak_speed = s["start"], float(sp.get("peak", rp["peak_speed"]))
                fast_from, fast_to = s["start"] - 0.1, s["start"] + s["dur"] * float(sp.get("in_portion", rp["in_portion"]))
            else:
                peak_t, peak_speed = curves.peak_time(s, rp, fps)
                fast_from, fast_to = peak_t - 0.25, peak_t + 0.25
            window = max(0.25, fast_to - fast_from)
            pick = picker.pick("whoosh", target_dur=window)
            if not pick:
                continue
            gain = -4 + 3 * math.log2(max(1.0, peak_speed) / 4) + sec_gain(peak_t) * 0.5
            cues.append(_cue("whoosh", pick, peak_t - pick["sync_time"], gain, peak_t,
                             f"speed ramp x{peak_speed:g}, fast for {window:.2f}s, peak on {peak_t:.2f}s"))

    # ---- hook: clicks on cuts, whoosh under scale-ins
    hk = style["hook"]
    for s in shots:
        if s["section"] != "hook":
            continue
        if hk.get("click_on_cuts") and s["start"] > 0.01:
            p = picker.pick("click", tags=["tick"])
            if p:
                cues.append(_cue("click", p, s["start"] - p["sync_time"], style["clicks"]["gain_db"], s["start"], "hook cut"))
        if len(s["scale"]) >= 2 and s["scale"][-1][1] > s["scale"][0][1] + 3:
            p = picker.pick("whoosh", target_dur=0.4)
            if p:
                t = s["scale"][-1][0]
                cues.append(_cue("whoosh", p, t - p["sync_time"], -12, t, "scale-in on hook shot"))

    # ---- riser into the drop + lowpassed music under the hook
    if hook_end > 0.5:
        if hk.get("riser_into_drop"):
            pool = [i for i in picker.items if i["category"] == "riser"]
            fits = [i for i in pool if i["dur"] <= hook_end + 1.0] or pool  # trimming a riser's quiet first second is fine
            target = min(hook_end, 8 * period)
            best = min(fits, key=lambda i: abs(i["dur"] - target)) if fits else None
            pick = {**best, "path": str(picker.root / best["file"])} if best else None
            if pick:
                start = hook_end - pick["dur"]
                cues.append(_cue("riser", pick, max(0.0, start), -5, hook_end, "build into the drop",
                                 file_in=max(0.0, -start)))
        lp = hk.get("music_lowpass", {})
        if lp.get("enabled"):
            open_at = max(0.0, hook_end - lp.get("open_beats", 1) * period)
            plan["fx"].append({"type": "lowpass", "target": "music", "auto": True,
                               "keys": [[0.0, lp["cutoff_hz"]], [open_at, lp["cutoff_hz"]], [hook_end, 20000, "easeIn"]],
                               "reason": "muffled hook, opens on the drop"})

    # ---- impacts on meaningful shots (+ shake on the same frame)
    imp = style["impacts"]
    last_imp = -10.0
    for i, s in enumerate(shots):
        is_drop = abs(s["start"] - hook_end) < 0.05 and hook_end > 0
        if not (is_drop or (s["role"] in imp["on_roles"] and s["section"] == "body")):
            continue
        t = s["start"] if imp.get("at", "start") == "start" or is_drop else s["start"] + s["dur"]
        if t - last_imp < 1.5:
            continue
        p = picker.pick("impact")
        if not p:
            continue
        last_imp = t
        cues.append(_cue("impact", p, t - p["sync_time"], -2 if is_drop else -4 + sec_gain(t) * 0.5, t,
                         "drop" if is_drop else f"hero shot {s['id']}"))
        if imp.get("shake"):
            target = s if imp.get("at", "start") == "start" or is_drop else (shots[i + 1] if i + 1 < len(shots) else s)
            if not any(abs(sh["start"] - t) < 0.1 for sh in target["shakes"]):
                target["shakes"].append({**_shake(style, t, 1.2), "auto": True})

    # ---- ambience under lifestyle shots (consecutive shots share one bed)
    amb = style["ambience"]
    run = []
    for s in shots + [None]:
        if s is not None and s["role"] in amb["on_roles"]:
            run.append(s)
            continue
        if run:
            tags = _amb_tags(run[0]["src"])
            p = picker.pick("ambience", tags=tags)
            if p:
                a, b = run[0]["start"], run[-1]["start"] + run[-1]["dur"]
                plan["ambience"].append({"file": p["path"], "start": round(max(0, a - amb["fade"]), 3),
                                         "end": round(b + amb["fade"], 3), "gain_db": amb["gain_db"], "fade": amb["fade"],
                                         "reason": f"lifestyle {run[0]['id']}..{run[-1]['id']} ({tags[0]})", "auto": True})
            run = []

    # ---- clicks on overlay pop-ins
    if style["clicks"].get("on_overlays"):
        for o in plan["overlays"]:
            if o["template"] in ("light_leak",):
                continue
            p = picker.pick("click", tags=["pop"])
            if p:
                t = o["start"] + o.get("pop_at", 0.0)
                cues.append(_cue("click", p, t - p["sync_time"], style["clicks"]["gain_db"] + sec_gain(t) * 0.5, t,
                                 f"overlay {o['template']} pops in"))

    plan["sfx"].extend(cues)
    plan["sfx"].sort(key=lambda c: c["start"])
    for k, c in enumerate(plan["sfx"]):
        c["id"] = f"fx{k + 1:02d}"
    return plan
