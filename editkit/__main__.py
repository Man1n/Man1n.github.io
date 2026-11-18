"""EditKit command line.  Run from the repo root:  python -m editkit <command> ...

Typical flow (see CLAUDE.md):
  analyze-ref  ref.mp4 --out projects/P/ref            break the reference down
  prompts      projects/P/ref/report.json              first/last-frame prompt sheet
  plan-ref     P --ref projects/P/ref/report.json      recreate the ref with your clips + music
  plan-auto    P                                       or: house-style edit from clips + music
  add-overlay  projects/P/plan.json --template property_title --start 0.5 --dur 2.5 --params '{...}'
  auto-sfx     projects/P/plan.json                    sound design pass
  build        projects/P/plan.json                    overlays + mix + previz
  bake         projects/P/plan.json                    per-shot ramp files for Premiere
  premiere     projects/P/plan.json --map /local=/mac  one Filmit call that builds the timeline
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import plan as planmod

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = ROOT / "projects"
SFX_DIR = ROOT / "sfx"


def proj_dir(plan_path):
    return Path(plan_path).resolve().parent


def cmd_analyze_ref(a):
    from . import analyze_ref
    out = a.out or PROJECTS / "_refs" / Path(a.video).stem
    rep = analyze_ref.analyze(a.video, out)
    v, au = rep["video"], rep["audio"]
    print(f"{len(v['shots'])} shots, {v['duration']:.2f}s, ramps {len(v['ramps'])}, punches {len(v['punches'])}, "
          f"shakes {len(v['shakes'])}" + (f", {au['tempo_bpm']} BPM, drop {au['drop']}, {len(au['events'])} sound events" if au else ""))
    print(f"report: {Path(out) / 'report.md'}\ntimeline: {Path(out) / 'timeline.png'}\ncontact sheet: {Path(out) / 'contact_sheet.jpg'}")


def cmd_prompts(a):
    from . import prompts
    print(prompts.build(a.report, a.out or Path(a.report).parent, a.look, a.aspect))


def cmd_sfx_pack(a):
    from . import sfx
    made = sfx.build_starter_pack(a.dir)
    sfx.catalog(a.dir)
    print(f"{len(made)} placeholder SFX written to {a.dir} and catalogued")


def cmd_sfx_catalog(a):
    from . import sfx
    c = sfx.catalog(a.dir)
    by = {}
    for i in c["items"]:
        by[i["category"]] = by.get(i["category"], 0) + 1
    print(f"{len(c['items'])} files: {by}  ->  {Path(a.dir) / 'sfx_catalog.json'}")


def _paths(name, clips, music):
    d = PROJECTS / name
    clips = Path(clips) if clips else d / "clips"
    if not music:
        ms = sorted((d / "music").glob("*")) if (d / "music").exists() else []
        music = ms[0] if ms else None
    return d, clips, music


def cmd_plan_auto(a):
    style = planmod.load_style(a.style)
    d, clips, music = _paths(a.name, a.clips, a.music)
    if not music:
        sys.exit("need a music track (--music or projects/<name>/music/)")
    p = planmod.build_auto(a.name, clips, music, style, a.length)
    out = d / "plan.json"
    planmod.save(p, out)
    print(planmod.summary(p))
    print(f"plan: {out}")


def cmd_plan_ref(a):
    style = planmod.load_style(a.style)
    d, clips, music = _paths(a.name, a.clips, a.music)
    p = planmod.build_from_ref(a.name, a.ref, clips, music, style)
    out = d / "plan.json"
    planmod.save(p, out)
    print(planmod.summary(p))
    print(f"plan: {out}")


def cmd_add_overlay(a):
    p = planmod.load(a.plan)
    o = {"template": a.template, "start": a.start, "dur": a.dur, "params": json.loads(a.params or "{}"),
         "pop_at": a.pop_at}
    p["overlays"].append(o)
    p["overlays"].sort(key=lambda x: x["start"])
    for k, x in enumerate(p["overlays"]):
        x["id"] = f"ov{k + 1:02d}"
    planmod.save(p, a.plan)
    print(f"added {a.template} at {a.start}s for {a.dur}s ({len(p['overlays'])} overlays)")


def cmd_auto_sfx(a):
    from . import sfx, sound
    style = planmod.load_style(a.style)
    cat = Path(a.catalog)
    if not cat.exists():
        sys.exit(f"no SFX catalog at {cat}. Run `python -m editkit sfx-pack` or `sfx-catalog`.")
    p = planmod.load(a.plan)
    sound.auto_sfx(p, style, sfx.Picker(cat))
    planmod.save(p, a.plan)
    for c in p["sfx"]:
        print(f"  {c['id']} {c['category']:8} @{c['align_time']:6.2f}s  {c['gain_db']:+5.1f} dB  {Path(c['file']).name:34} {c['reason']}")
    for b in p["ambience"]:
        print(f"  amb {b['start']:.2f}-{b['end']:.2f}s {Path(b['file']).name} {b['reason']}")
    for f in p["fx"]:
        print(f"  fx {f['type']} {f['keys']}")


def cmd_overlays(a):
    from . import overlays
    p = planmod.load(a.plan)
    overlays.render_plan(p, proj_dir(a.plan) / "overlays", a.only)
    planmod.save(p, a.plan)
    print(f"rendered {len(p['overlays'])} overlays")


def cmd_still(a):
    from . import overlays
    print(overlays.render_one(a.template, a.out, a.w, a.h, 30, a.dur, json.loads(a.params or "{}"), still=a.t))


def cmd_mix(a):
    from . import mix
    p = planmod.load(a.plan)
    paths = mix.mix(p, planmod.load_style(a.style), proj_dir(a.plan) / "audio")
    p["audio"] = paths
    planmod.save(p, a.plan)
    print(json.dumps(paths, indent=1))


def cmd_previz(a):
    from . import render
    p = planmod.load(a.plan)
    audio = (p.get("audio") or {}).get("mix")
    out = render.previz(p, planmod.load_style(a.style), proj_dir(a.plan) / "previz", a.scale, audio=audio)
    print(out)


def cmd_build(a):
    from . import mix, overlays, render
    style = planmod.load_style(a.style)
    p = planmod.load(a.plan)
    d = proj_dir(a.plan)
    if p["overlays"]:
        overlays.render_plan(p, d / "overlays")
    p["audio"] = mix.mix(p, style, d / "audio")
    planmod.save(p, a.plan)
    print(render.previz(p, style, d / "previz", a.scale, audio=p["audio"]["mix"]))


def cmd_bake(a):
    from . import render
    p = planmod.load(a.plan)
    render.bake(p, planmod.load_style(a.style), proj_dir(a.plan) / "baked", a.codec, a.burn_motion)
    planmod.save(p, a.plan)
    print(f"baked {len(p['shots'])} shots -> {proj_dir(a.plan) / 'baked'}")


def cmd_premiere(a):
    from . import premiere
    p = planmod.load(a.plan)
    out, n, files = premiere.write(p, proj_dir(a.plan), p.get("audio"), a.map, a.audio)
    print(f"{out}: one pr_applyEditPlan call with {n} steps; {len(files)} files must exist on the Premiere machine "
          f"(listed in premiere_files.txt)")


def cmd_summary(a):
    print(planmod.summary(planmod.load(a.plan)))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="editkit")
    ap.add_argument("--style", default=None, help="style profile yaml (default editkit/style/profile.yaml)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("analyze-ref"); s.add_argument("video"); s.add_argument("--out"); s.set_defaults(f=cmd_analyze_ref)
    s = sub.add_parser("prompts"); s.add_argument("report"); s.add_argument("--out"); s.add_argument("--look", default="luxury_golden")
    s.add_argument("--aspect"); s.set_defaults(f=cmd_prompts)
    s = sub.add_parser("sfx-pack"); s.add_argument("--dir", default=str(SFX_DIR)); s.set_defaults(f=cmd_sfx_pack)
    s = sub.add_parser("sfx-catalog"); s.add_argument("--dir", default=str(SFX_DIR)); s.set_defaults(f=cmd_sfx_catalog)
    for nm, fn in (("plan-auto", cmd_plan_auto), ("plan-ref", cmd_plan_ref)):
        s = sub.add_parser(nm); s.add_argument("name"); s.add_argument("--clips"); s.add_argument("--music")
        if nm == "plan-ref":
            s.add_argument("--ref", required=True)
        else:
            s.add_argument("--length", type=float)
        s.set_defaults(f=fn)
    s = sub.add_parser("add-overlay"); s.add_argument("plan"); s.add_argument("--template", required=True)
    s.add_argument("--start", type=float, required=True); s.add_argument("--dur", type=float, default=2.5)
    s.add_argument("--params"); s.add_argument("--pop-at", type=float, default=0.15); s.set_defaults(f=cmd_add_overlay)
    s = sub.add_parser("auto-sfx"); s.add_argument("plan"); s.add_argument("--catalog", default=str(SFX_DIR / "sfx_catalog.json"))
    s.set_defaults(f=cmd_auto_sfx)
    s = sub.add_parser("overlays"); s.add_argument("plan"); s.add_argument("--only", nargs="*"); s.set_defaults(f=cmd_overlays)
    s = sub.add_parser("still"); s.add_argument("template"); s.add_argument("--t", type=float, default=1.5)
    s.add_argument("--dur", type=float, default=3); s.add_argument("--params"); s.add_argument("--w", type=int, default=1080)
    s.add_argument("--h", type=int, default=1920); s.add_argument("--out", required=True); s.set_defaults(f=cmd_still)
    s = sub.add_parser("mix"); s.add_argument("plan"); s.set_defaults(f=cmd_mix)
    s = sub.add_parser("previz"); s.add_argument("plan"); s.add_argument("--scale", type=float, default=0.5); s.set_defaults(f=cmd_previz)
    s = sub.add_parser("build"); s.add_argument("plan"); s.add_argument("--scale", type=float, default=0.5); s.set_defaults(f=cmd_build)
    s = sub.add_parser("bake"); s.add_argument("plan"); s.add_argument("--codec", default="prores", choices=["prores", "h264"])
    s.add_argument("--burn-motion", action="store_true"); s.set_defaults(f=cmd_bake)
    s = sub.add_parser("premiere"); s.add_argument("plan"); s.add_argument("--map", nargs="*")
    s.add_argument("--audio", default="stems", choices=["stems", "cues"]); s.set_defaults(f=cmd_premiere)
    s = sub.add_parser("summary"); s.add_argument("plan"); s.set_defaults(f=cmd_summary)
    a = ap.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
