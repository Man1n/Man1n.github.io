---
name: sound-design
description: Place and tune SFX for a real-estate edit - whooshes matched to speed ramps, risers into the drop, impacts on hero shots, clicks, ambience beds, lowpass on the hook - and manage the SFX library. Use for any sound design request.
---

# Sound design

Rules live in `editkit/sound.py` and the numbers in `editkit/style/profile.yaml`.

| Moment | What goes there | Sync |
|---|---|---|
| speed ramp | whoosh, length ~ the fast stretch (A's ramp-out + B's ramp-in), louder for faster ramps | whoosh peak on the fastest frame (the cut) |
| hook cuts | click (tick / pop / shutter, rotating) | transient on the cut |
| hook scale-in | short whoosh, -12 dB | peak at end of the push |
| hook -> drop | riser ending exactly on the drop; music lowpassed (550 Hz) and swept open over the last beat | riser end = drop |
| drop / hero shot | impact with sub boom + camera shake on the same frame; music ducks 3 dB under it | transient on the cut |
| lifestyle shots | ambience bed (pool / birds / city / room tone from the clip name), faded | under the shots |
| graphic pop-in | click | on the pop (overlay `pop_at`) |
| body | everything -6 dB: the music leads | |

Workflow:
1. Library: `python -m editkit sfx-pack` makes placeholder sounds. Real ones go in `sfx/whooshes`, `sfx/risers`,
   `sfx/impacts`, `sfx/clicks`, `sfx/ambience` (any names; words in names become tags), then `python -m editkit sfx-catalog`.
   The catalog measures duration, onset, peak and the sync point.
2. `python -m editkit auto-sfx projects/<P>/plan.json` prints every cue with its reason. Re-running replaces only `auto` cues.
3. Manual tweaks: edit `plan.json` `sfx` entries (`start`, `gain_db`, `file`, `file_in`), or add your own without `"auto"`,
   they survive re-runs. To nudge sync, change `start`; `align_time` documents the intended moment.
4. Check by ear AND eye: `python -m editkit mix ...` then `analyze-ref` the previz; whoosh (W) marks should sit on ramp
   cuts, impact (I) on hero cuts, a yellow riser band ending on the drop.
5. Matching a reference: compare its report's sound events per cut (`sound_on_cut` column) to ours and adjust the
   style profile (e.g. impacts `at: end`, no clicks, longer whooshes).
