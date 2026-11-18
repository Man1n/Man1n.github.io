"""First-frame / last-frame prompt sheets for AI video generation, one per reference shot.

The generator fills in everything that can be measured (duration, camera move, ramp, how much footage the
ramp eats) and leaves [DESCRIBE ...] slots. Claude fills those after looking at the shot's frames
(frames/shotNN_first.jpg and _last.jpg) and the property the user is selling.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

MOVE_PHRASE = {
    "push-in": "slow, steady dolly push-in",
    "pull-out": "smooth dolly pull-back that reveals more of the space",
    "truck right": "smooth lateral tracking move to the right, gentle parallax",
    "truck left": "smooth lateral tracking move to the left, gentle parallax",
    "tilt/boom up": "camera cranes up, rising reveal",
    "tilt/boom down": "camera cranes down, descending reveal",
    "static / locked-off": "locked-off tripod frame with subtle natural motion in the scene",
    "roll cw": "slow clockwise orbit / roll",
    "roll ccw": "slow counter-clockwise orbit / roll",
}

LOOKS = {
    "luxury_golden": "golden hour, warm low sun, long soft shadows, glowing windows, luxury real-estate cinematography, "
                     "35mm lens, shallow depth of field, rich contrast, clean architectural lines",
    "twilight": "blue-hour twilight, deep blue sky, every interior light on, warm tungsten glow through glass, "
                "reflections on wet surfaces, high-end real-estate photography look",
    "bright_interior": "bright airy interior, soft daylight through large windows, neutral whites, true-to-life colors, "
                       "vertical lines kept straight, wide 16mm architectural lens",
    "lifestyle": "candid lifestyle moment, natural light, warm tones, people blurred in motion, aspirational but real",
    "aerial": "aerial drone shot, high vantage, clear sky, crisp detail, slow cinematic drone movement",
}


def _phrase(move):
    for k, v in MOVE_PHRASE.items():
        if move.startswith(k):
            extra = " combined with a slight push" if "+ push" in move else " combined with a slight pull-back" if "+ pull" in move else ""
            return v + extra
    return move


def _gen_seconds(shot, peak=5.0):
    """How long the generated clip should be: ramps eat footage, plus handles for trimming."""
    need = shot["dur"]
    if shot.get("ramp"):
        r = shot["ramp"]
        fast = max(0.0, r["to"] - r["from"])
        need = shot["dur"] - fast + fast * min(r["peak_ratio"], peak) * 0.6
    return int(math.ceil(need + 1.0))


def build(report_path, outdir, look="luxury_golden", aspect=None):
    rep = json.loads(Path(report_path).read_text())
    v = rep["video"]
    ar = aspect or ("9:16" if rep["info"].get("height", 0) > rep["info"].get("width", 1) else "16:9")
    style = LOOKS.get(look, look)
    shots = []
    for s in v["shots"]:
        cam = _phrase(s["move"])
        sec = _gen_seconds(s)
        speed_note = ""
        if s.get("ramp"):
            speed_note = ("Generate at real-time speed with CONTINUOUS camera motion (no pauses) - the speed ramp is "
                          f"done in the edit (ref ramps x{s['ramp']['peak_ratio']} at its {s['ramp']['where']}).")
        shots.append({
            "shot": s["index"], "ref_time": s["start"], "ref_dur": s["dur"], "section": s.get("section"),
            "camera": s["move"], "generate_seconds": sec, "aspect": ar,
            "ref_frames": {k: str(Path(rep_dir(report_path)) / p) for k, p in s["frames"].items()},
            "first_frame": f"[DESCRIBE the opening composition: subject, room/exterior, framing], {style}, {ar}, photorealistic",
            "last_frame": f"[DESCRIBE the same scene where the camera ends after a {cam}: what is now revealed / closer], "
                          f"{style}, {ar}, photorealistic, identical lighting and materials to the first frame",
            "motion": f"{cam}, {sec}s, steady stabilized camera, no cuts, no morphing of architecture, keep straight lines straight. {speed_note}".strip(),
        })
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "prompts.json").write_text(json.dumps({"look": look, "shots": shots}, indent=1))
    L = [f"# Shot prompts: {Path(rep['source']).name}", "",
         f"Look: {style}", "",
         "For each shot: generate the FIRST and LAST frame images, then the video between them with the motion prompt.",
         "Name the results `shotNN_<role>.mp4` (role = hero / lifestyle / detail / interior / establishing) and drop them in clips/.", ""]
    for s in shots:
        L += [f"## Shot {s['shot']:02d}  ({s['ref_time']:.2f}s, {s['ref_dur']:.2f}s, {s['section']}, {s['camera']})", "",
              f"Reference frames: `{s['ref_frames']['first']}` -> `{s['ref_frames']['last']}`", "",
              f"**First frame:** {s['first_frame']}", "",
              f"**Last frame:** {s['last_frame']}", "",
              f"**Motion ({s['generate_seconds']}s, {s['aspect']}):** {s['motion']}", ""]
    (out / "prompts.md").write_text("\n".join(L))
    return str(out / "prompts.md")


def rep_dir(report_path):
    return Path(report_path).parent
