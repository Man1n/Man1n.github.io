"""Turn a rendered plan into ONE Filmit `pr_applyEditPlan` call that builds the edit in Premiere Pro.

Layout it builds:
  V1  baked shots end to end (speed ramps already inside the files)
  V2+ overlays (ProRes 4444, alpha)
  A1  music   (stems mode: lowpass + ducking already printed into the file)
  A2  SFX     (stems mode: one SFX stem | cues mode: every cue as its own clip on A2-A4)
  A3  ambience
Motion: scale punches / drifts and shakes arrive as Motion keyframes on the V1 clips, so they stay editable.

Paths: Premiere needs paths on the machine it runs on. --map /local/prefix=/premiere/prefix rewrites them
(e.g. into a Google Drive for desktop folder when the render happened in a cloud session).
"""
from __future__ import annotations

import json
from pathlib import Path

from . import curves

INTERP = {"linear": "linear", "easeOut": "easeOut", "easeIn": "easeIn", "smooth": "ease", "ease": "ease",
          "expoOut": "easeOut", "backOut": "easeOut", "hold": "hold"}


def _mapper(maps):
    pairs = []
    for m in maps or []:
        a, b = m.split("=", 1)
        pairs.append((a.rstrip("/"), b.rstrip("/")))

    def f(p):
        p = str(Path(p).resolve())
        for a, b in pairs:
            if p.startswith(a):
                return b + p[len(a):]
        return p
    return f


def _motion_keys(shot, W, H, fps):
    keys = {}
    for k in shot.get("scale") or []:
        e = INTERP.get(k[2] if len(k) > 2 else "linear", "linear")
        keys.setdefault(round(k[0], 4), {})["scale"] = round(k[1], 2)
        keys[round(k[0], 4)]["interpolation"] = e
    for sh in shot.get("shakes") or []:
        n = max(2, int(round(sh["dur"] * fps)))  # one key per frame so Premiere matches the previz
        for j in range(n + 1):
            t = sh["start"] + j * sh["dur"] / n
            dx, dy, rot = curves.shake_offset(t, [sh], W)
            kk = keys.setdefault(round(t, 4), {})
            kk["position"] = [round(W / 2 + dx, 1), round(H / 2 + dy, 1)]
            kk["rotation"] = round(rot, 2)
            kk.setdefault("interpolation", "linear")
        # settle exactly back to centre
        t_end = round(sh["start"] + sh["dur"] + 1 / fps, 4)
        keys.setdefault(t_end, {}).update(position=[W / 2, H / 2], rotation=0, interpolation="linear")
    out = []
    for t in sorted(keys):
        if shot["start"] - 1e-3 <= t <= shot["start"] + shot["dur"] + 1e-3:
            out.append({"time": t, **keys[t]})
    return out


def build_steps(plan, audio_paths=None, maps=None, audio_mode="stems"):
    P = _mapper(maps)
    m = plan["meta"]
    name = m["name"]
    W, H, fps = m["width"], m["height"], m["fps"]
    shots = plan["shots"]
    missing = [s["id"] for s in shots if not s.get("baked")]
    if missing:
        raise SystemExit(f"bake the shots first (missing: {missing[:5]}...)")
    steps, files = [], []

    def imp(paths, bin_):
        files.extend(paths)
        steps.append({"tool": "pr_importFiles", "input": {"paths": [P(p) for p in paths], "bin": bin_}})

    root = f"EditKit/{name}"
    imp([s["baked"] for s in shots], f"{root}/Shots")
    ovs = [o for o in plan["overlays"] if o.get("file")]
    if ovs:
        imp(sorted({o["file"] for o in ovs}), f"{root}/Graphics")
    if audio_mode == "stems":
        if not audio_paths:
            raise SystemExit("run `mix` first (stems mode needs audio/music.wav, sfx.wav, ambience.wav)")
        stems = [audio_paths[k] for k in ("music", "sfx", "ambience") if audio_paths.get(k)]
        imp(stems, f"{root}/Audio")
    else:
        aud = sorted({c["file"] for c in plan["sfx"]} | {a["file"] for a in plan["ambience"]})
        if plan["music"].get("file"):
            aud = [plan["music"]["file"]] + aud
        imp(aud, f"{root}/Audio")

    item = lambda p, b: f"{root}/{b}/{Path(p).name}"
    steps.append({"tool": "pr_createSequence", "input": {"name": name, "bin": root,
                                                         "fromItems": [item(s["baked"], "Shots") for s in shots]}})
    # overlays: stack on V2, V3... so overlapping graphics never overwrite each other
    lanes = []
    for o in sorted(ovs, key=lambda o: o["start"]):
        lane = next((i for i, end in enumerate(lanes) if end <= o["start"] + 1e-3), None)
        if lane is None:
            lanes.append(0)
            lane = len(lanes) - 1
        lanes[lane] = o["start"] + o["dur"]
        steps.append({"tool": "pr_placeClip", "input": {"item": item(o["file"], "Graphics"), "track": f"V{lane + 2}",
                                                        "time": round(o["start"], 4)}})
    # audio
    if audio_mode == "stems":
        for k, tr in (("music", "A1"), ("sfx", "A2"), ("ambience", "A3")):
            if audio_paths.get(k):
                steps.append({"tool": "pr_placeClip", "input": {"item": item(audio_paths[k], "Audio"), "track": tr, "time": 0}})
    else:
        if plan["music"].get("file"):
            steps.append({"tool": "pr_placeClip", "input": {"item": item(plan["music"]["file"], "Audio"), "track": "A1",
                                                            "time": 0, "sourceIn": plan["music"].get("offset", 0)}})
        lanes = [0.0, 0.0, 0.0]
        for c in plan["sfx"]:
            st = max(0.0, c["start"])
            lane = next((i for i, e in enumerate(lanes) if e <= st), 0)
            lanes[lane] = st + c["dur"]
            tr = f"A{lane + 2}"
            inp = {"item": item(c["file"], "Audio"), "track": tr, "time": round(st, 4)}
            if c.get("file_in", 0) > 0 or c["start"] < 0:
                inp["sourceIn"] = round(c.get("file_in", 0) + max(0.0, -c["start"]), 4)
            steps.append({"tool": "pr_placeClip", "input": inp})
            if abs(c["gain_db"]) > 0.05:
                steps.append({"tool": "pr_setClipProperties", "input": {"clips": [{"track": tr, "time": round(st + 0.01, 4)}],
                                                                        "volume": c["gain_db"]}})
        for a in plan["ambience"]:
            steps.append({"tool": "pr_placeClip", "input": {"item": item(a["file"], "Audio"), "track": "A5",
                                                            "time": round(a["start"], 4)}})
            steps.append({"tool": "pr_trimClip", "input": {"clip": {"track": "A5", "time": round(a["start"] + 0.01, 4)},
                                                           "end": round(a["end"], 4)}})
            steps.append({"tool": "pr_setClipProperties", "input": {"clips": [{"track": "A5", "time": round(a["start"] + 0.01, 4)}],
                                                                    "volume": a["gain_db"]}})
        lp = [f for f in plan["fx"] if f["type"] == "lowpass"]
        if lp and plan["music"].get("file"):
            steps.append({"tool": "pr_applyEffect", "input": {"name": "Lowpass", "clips": [{"track": "A1", "clip": 1}]}})
            steps.append({"tool": "pr_setEffectProperties", "input": {
                "clips": [{"track": "A1", "clip": 1}], "effect": "Lowpass",
                "keyframes": [{"time": k[0], "properties": {"Cutoff": k[1]},
                               "interpolation": INTERP.get(k[2] if len(k) > 2 else "linear", "linear")} for k in lp[0]["keys"]]}})
    # motion keyframes on V1
    for idx, s in enumerate(shots, start=1):
        if s.get("baked_motion"):
            continue
        keys = _motion_keys(s, W, H, fps)
        if keys:
            steps.append({"tool": "pr_setClipProperties", "input": {"clips": [{"track": "V1", "clip": idx}], "keyframes": keys}})
    return {"tool": "pr_applyEditPlan", "input": {"steps": steps, "stopOnError": False}}, sorted(set(files))


def write(plan, outdir, audio_paths=None, maps=None, audio_mode="stems"):
    call, files = build_steps(plan, audio_paths, maps, audio_mode)
    out = Path(outdir) / "premiere_steps.json"
    out.write_text(json.dumps(call, indent=1))
    (Path(outdir) / "premiere_files.txt").write_text("\n".join(files) + "\n")
    return str(out), len(call["input"]["steps"]), files
