# CLAUDE.md

This repo is two things:
1. The owner's portfolio website (the `*.html`, `style.css` and images at the root). Leave it alone unless asked.
2. **EditKit** (`editkit/`): a system for editing real-estate videos for Premiere Pro, driven by Claude Code.

## The job

The user is a real-estate video editor. They give a **reference edit** and their **footage + music**. Our job:
recreate the reference's editing DNA (cut rhythm, speed ramps, scale punches, shakes, sound design, graphics)
with their material, then build it in Premiere Pro.

House style (encoded in `editkit/style/profile.yaml`, change values there rather than in code):
- Hooks are **fast**: a cut on every beat, scale punches alternating in/out, shakes, clicks on cuts, music lowpassed.
- A **riser** builds into the drop. At the drop the filter opens, an **impact** lands, and then **the music takes the lead**
  (cuts every 2 beats, SFX pulled back 6 dB).
- **Speed ramps** the proper way: shot A accelerates into the cut, the cut sits on the fastest frame, shot B lands fast and
  eases down. A **whoosh** whose loudest point is on that fastest frame, its length matched to the fast stretch.
- **Impacts** (+ shake) on meaningful / hero shots. **Ambience** under lifestyle shots. **Clicks** on graphic pop-ins.

## Pipeline (all commands from the repo root)

```
python -m editkit analyze-ref REF.mp4 --out projects/P/ref      # edit DNA: report.md, timeline.png, contact_sheet.jpg, frames/
python -m editkit prompts projects/P/ref/report.json            # first/last-frame prompts -> fill the [DESCRIBE] slots by LOOKING at frames
python -m editkit plan-ref P --ref projects/P/ref/report.json   # recreate the ref (clips from projects/P/clips, music from projects/P/music)
python -m editkit plan-auto P                                    # or: house-style edit with no reference
python -m editkit add-overlay projects/P/plan.json --template property_title --start 4.2 --dur 3 --params '{"title":"..."}'
python -m editkit auto-sfx projects/P/plan.json                 # sound design pass (manual cues are kept)
python -m editkit build projects/P/plan.json                    # overlays + mix + previz.mp4
python -m editkit bake projects/P/plan.json                     # one ProRes file per shot, ramps baked in
python -m editkit premiere projects/P/plan.json --map /local/prefix=/premiere/prefix
```

Skills in `.claude/skills/` walk through each stage: `analyze-reference`, `shot-prompts`, `build-edit`,
`sound-design`, `motion-graphics`, `push-to-premiere`. Use them.

## Project layout

```
projects/<name>/            (gitignored: media never goes in git)
  ref/        analysis of the reference (report.json is the source of truth)
  clips/      the user's footage. Name files <role>_<what>.mp4: hero_pool.mp4, lifestyle_coffee.mp4, detail_tap.mp4,
              interior_living.mp4, establishing_front.mp4. The role drives impacts / ambience / placement.
  music/      one track
  plan.json   THE EDIT. Edit it directly for fine changes, then re-run auto-sfx / build.
  overlays/ audio/ baked/ previz/    renders
sfx/          SFX library (gitignored). `sfx-pack` makes placeholders; real libraries go in sfx/<category>/, then `sfx-catalog`.
```

## How to work

- **Look before you claim.** After `analyze-ref`, Read `timeline.png` and `contact_sheet.jpg` and a few `frames/`. After
  `build`, extract frames from `previz/previz.mp4` around cuts, ramps and overlays and Read them. Sound-event labels from the
  analyzer are estimates from the spectrum. Say so, and ask the user to confirm by ear when it matters.
- Clicks, whooshes, impacts: sync point is the transient onset (clicks / impacts) or the loudest moment (whoosh / riser).
  The catalog stores it as `sync_time`. Never place by file start.
- The user generates AI clips from our first/last-frame prompts and uploads them. Check each upload: duration covers
  `generate_seconds`, aspect matches, camera move matches the ref shot. Say what's off.
- **Premiere / Filmit:** the user's Filmit plan is limited (free: 50 calls/day). Always build the whole timeline with ONE
  `pr_applyEditPlan` call from `premiere_steps.json`. Check `filmit_status` first; Premiere must be open with the Filmit panel
  connected. Paths in the steps must exist on the user's computer (see push-to-premiere skill).
- Premiere's scripting has no speed/time-remap control, so ramps are **baked** into per-shot files (with motion blur).
  Scale and shake arrive as editable Motion keyframes.
- Cloud sessions are ephemeral: commit code changes; deliver renders through Google Drive or by the user running EditKit
  locally (`pip install -r editkit/requirements.txt`; needs ffmpeg, node + playwright for overlays).
