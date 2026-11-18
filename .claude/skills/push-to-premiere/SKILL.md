---
name: push-to-premiere
description: Build the finished EditKit plan as a Premiere Pro timeline through Filmit in one batched call (baked ramp shots on V1, graphics on V2+, music/SFX/ambience, Motion keyframes for scale and shake). Use when the user wants the edit in Premiere.
---

# Push to Premiere

1. `filmit_status`: Premiere must be listed as connected (Premiere open, Filmit panel > MCP tab > Connect). Note the daily
   allowance. Never spend calls exploring: plan for ONE `pr_applyEditPlan` plus at most 2-3 checks.
2. Bake: `python -m editkit bake projects/<P>/plan.json` (ProRes 422 HQ, one file per shot, exact length, ramps + motion blur
   baked in; `--codec h264` for smaller files; `--burn-motion` also bakes scale/shake).
   Make sure `build` (or `mix`) ran so `audio/music.wav`, `sfx.wav`, `ambience.wav` exist.
3. Files must exist on the computer running Premiere:
   - Running locally (EditKit cloned on their Mac/PC): paths already match, no `--map`.
   - From a cloud session: upload `baked/`, `overlays/` and `audio/` to Google Drive (Drive connector), the user syncs it with
     Google Drive for desktop, then map: `--map /home/user/Man1n.github.io/projects=/Users/<them>/Library/CloudStorage/GoogleDrive-.../My Drive/EditKit/projects`
     (ask for their real path once).
4. `python -m editkit premiere projects/<P>/plan.json [--map A=B] [--audio stems|cues]`
   - `stems` (default): 3 audio clips, lowpass + ducking already printed in. Fewest steps, most reliable.
   - `cues`: every SFX as its own clip on A2-A4 + ambience on A5 + Premiere's Lowpass effect keyframed on the music, so the
     user can re-time sounds by hand. More steps (still one call). Verify the effect/param name with `pr_findEffects` first.
5. Read `premiere_steps.json` and call `pr_applyEditPlan` with exactly its `input`. Report any failed steps from the result.
6. Verify cheaply: one `pr_getSequenceState` (clip counts per track, sequence length) and one `pr_exportFrame` at a ramp or
   overlay moment, Read the frame. Tell the user what was built and that each step is its own undo (a duplicate of their
   sequence is the safe way to experiment).
