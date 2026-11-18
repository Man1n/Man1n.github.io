---
name: build-edit
description: Build the real-estate edit (plan, speed ramps, scale punches, shakes, graphics, sound design, previz render) from a reference analysis or the house style. Use when the user has clips + music and wants the edit made or changed.
---

# Build the edit

Inputs: `projects/<P>/clips/` (role-named clips), `projects/<P>/music/<track>`, optionally `projects/<P>/ref/report.json`.

1. Plan:
   - recreate a ref: `python -m editkit plan-ref <P> --ref projects/<P>/ref/report.json`
   - house style: `python -m editkit plan-auto <P> [--length 30]`
   Read the printed shot list. Check: hook length, hero shots land on the drop and strong beats, no clip repeats back to back,
   "source short" notes (clip too short for its ramp: ask for a longer clip or accept the lowered peak).
2. Fine edits go straight into `plan.json` (schema at the top of `editkit/plan.py`): swap `src`/`in`, change `role`,
   `speed` (`{"ramp_in":true,"ramp_out":true,"peak":6}` or explicit `{"keys":[[0,1],[0.6,1],[1,6,"smooth"]]}`),
   `scale` keys `[[t, pct, ease]]` (timeline seconds), `shakes`.
3. Graphics: see the `motion-graphics` skill. Typical real-estate set: `badge` (Just Listed) in the hook, `property_title`
   right after the drop, `stats_row` on an interior, `location_pin` on an aerial, `price_reveal` near the end, `light_leak`
   centred on a cut (start = cut - dur/2).
4. Sound: `python -m editkit auto-sfx projects/<P>/plan.json` (see the `sound-design` skill), then
5. Render: `python -m editkit build projects/<P>/plan.json` -> `projects/<P>/previz/previz.mp4` (half-res review copy).
6. **Review it yourself before showing the user**: extract frames around the hook cuts, each ramp (cut +/- 3 frames), each
   overlay's middle, and Read them:
   `ffmpeg -i previz.mp4 -vf "select='between(t,3.8,4.2)',scale=270:-2,tile=12x1" -frames:v 1 check.jpg`
   Also run `analyze-ref` on the previz and compare its timeline.png to the reference's: rhythm, ramps and SFX should line up.
7. Deliver previz.mp4 to the user (SendUserFile) with a short list of what's where. Iterate on their notes.
