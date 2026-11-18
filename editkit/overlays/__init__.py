"""Render the plan's motion-graphics overlays (HTML templates -> ProRes 4444 with alpha)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
TEMPLATES = HERE / "templates"


def templates():
    return sorted(p.stem for p in TEMPLATES.glob("*.html"))


def render_one(template, out, w, h, fps, dur, params=None, still=None):
    tpl = TEMPLATES / f"{template}.html"
    if not tpl.exists():
        raise SystemExit(f"unknown template {template}; have {templates()}")
    cmd = ["node", str(HERE / "render_overlay.js"), "--template", str(tpl), "--out", str(out), "--w", str(w),
           "--h", str(h), "--fps", str(fps), "--dur", str(dur), "--params", json.dumps(params or {})]
    if still is not None:
        cmd += ["--still", str(still)]
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(cmd, check=True)
    return str(out)


def render_plan(plan, outdir, only=None):
    m = plan["meta"]
    for k, o in enumerate(plan["overlays"]):
        oid = o.setdefault("id", f"ov{k + 1:02d}")
        if only and oid not in only:
            continue
        out = Path(outdir) / f"{oid}_{o['template']}.mov"
        render_one(o["template"], out, m["width"], m["height"], m["fps"], o["dur"], o.get("params"))
        o["file"] = str(out)
    return plan
