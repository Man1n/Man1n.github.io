---
name: real-estate-edit
description: Rules and workflow for editing real-estate videos in Premiere Pro through Filmit. Covers footage prep (cut wobbly or unstable camera moves, conform 50-60 fps clips to 50% on a 25 fps timeline, nest, Warp Stabilizer, nest again so speed ramps never break the warp), project organisation (bins AE ASSETS / AUDIO / NESTS / FOOTAGES / SEQUENCES / SFX and strict naming), the house editing style (fast hook, scale in/out, shakes, speed ramps, sound design) and AI shots used only to fill gaps. Use for any real-estate edit, footage prep, project cleanup or Premiere organisation request.
---

# Real-estate edit

Work like a meticulous assistant editor in the user's real Premiere project. Read state before changing anything,
never delete media, duplicate a sequence before big changes, and leave the project tidier than you found it.

## 0. Ground rules

1. **Existing footage first.** The edit is cut from the footage the user shot. AI-generated clips only fill a gap the
   footage can't cover (a missing establishing shot, a twilight exterior, a transition). Before writing any AI prompt,
   say which gap it fills and why no existing clip works.
2. **Only proper motion makes the cut.** Wobble, gimbal bounce, jerky starts and stops, corrections and direction changes
   are cut out before anything else happens (section 2).
3. **Timeline is 25 fps.** Every sequence and nest is 25p.
4. **Organised and named at every step** (section 1). Nothing is left in the project root and nothing keeps a default
   name like "Sequence 01" or "Nested Sequence 3".
5. **Filmit budget.** The free plan allows 50 calls a day. Check `filmit_status` first, read state once, then batch the
   work into as few `pr_applyEditPlan` calls as possible (one per phase). Never spend calls exploring.

## 1. Project organisation

### Bins (top level, exactly these names, in this order)
```
AE ASSETS     After Effects comps, graphics, titles, logos, overlays (.aep, .mov with alpha, .png)
AUDIO         MUSIC/  VO/
NESTS         every nest (see naming); sorted by shot number so A and B pairs sit together
FOOTAGES      DRONE/  EXTERIOR/  INTERIOR/  DETAILS/  LIFESTYLE/  AI GENERATED/
SEQUENCES     edit sequences + _TEMPLATES/
SFX           WHOOSH/  RISER/  IMPACT/  CLICK/  AMBIENCE/
```
The six top-level bins are fixed. Sub-bins keep each one tidy; create a sub-bin only when something goes in it.
Create the structure with `pr_createBin` and sort with `pr_moveItems`, all in one `pr_applyEditPlan`. Sort footage by what
it shows (look at the name and, if unclear, one frame), not by camera card.

### Naming
| item | pattern | example |
|---|---|---|
| edit sequence | `SEQ_<PROPERTY>_<FORMAT>_v<NN>` | `SEQ_1428OCEAN_9x16_v01` |
| sequence template | `_TEMPLATE_25P_<W>x<H>` | `_TEMPLATE_25P_3840x2160` |
| nest A (speed) | `<NNN>_<SUBJECT>_<MOVE>_A-SPD<pct>` | `012_KITCHEN_PUSHIN_A-SPD50` |
| nest B (stabilised) | `<NNN>_<SUBJECT>_<MOVE>_B-WARP` | `012_KITCHEN_PUSHIN_B-WARP` |
| AE asset | `AE_<PROPERTY>_<WHAT>_v<NN>` | `AE_1428OCEAN_PRICE_v01` |
| AI clip | `AI_<NNN>_<SUBJECT>_<MOVE>` | `AI_003_EXTERIOR_TWILIGHT_PULLOUT` |

- `NNN` is the shot number in edit order (001, 002...), so the NESTS bin reads like the edit.
- SUBJECT and MOVE in capitals, no spaces: `POOL`, `LIVING`, `FACADE`, `PRIMARYBED`; `PUSHIN`, `PULLOUT`, `TRUCKL`,
  `TRUCKR`, `ORBIT`, `RISE`, `TILTUP`, `LOCKED`.
- New versions bump `v01 -> v02` on a duplicate; never overwrite the previous version.
- Source footage keeps its camera file name (Filmit can't rename project items); the bin it sits in describes it.

## 2. Footage prep

Run this per clip, in edit order, before any creative editing.

### 2.1 Scan and keep only proper motion
With file access (Claude Code running on the editing computer, or the footage folder attached), run:
```
python .claude/skills/real-estate-edit/scripts/motion_scan.py "<footage folder>" --json footage_scan.json
```
For each clip it prints fps, size, the speed to use on 25p, and the clean ranges (`keep in-out`) with their move,
steadiness and speed consistency, plus the best one. It cuts:
- **wobble** (high-frequency jitter on top of the move: hand-held, gimbal bounce, wind on the drone)
- **gimbal start and stop** (the move easing in from rest or out to rest)
- **lurches and corrections** (sudden speed change, reversal or re-framing mid-move)

Rules on top of the numbers:
- Use the `best` range unless another range has the move the edit needs.
- Clean ranges under 1 s of source (2 s once at 50%) are rarely worth it. Flag them.
- `no clean segment`: still usable only if Warp can save it (slow move, little jitter). Otherwise drop the clip, tell the
  user, and note it as a gap (section 5).
- Without file access: ask the user to scrub the clips, or attach the folder. Don't guess in/out points blind.

### 2.2 Frame rate: 50% for 50-60 fps
| source fps | speed on the 25p timeline |
|---|---|
| 47-61 (50, 59.94, 60) | **50%** |
| 23-31 (23.976, 25, 29.97) | 100% |
| 100-120 | ask the user (25% gives full slow motion from 100 fps) |

The speed goes on the clip **inside NEST A**, never on the edit timeline clip.

### 2.3 Nest, stabilise, nest: so speed ramps never break the Warp
Premiere refuses Warp Stabilizer on a clip that has a speed change, and Warp needs the clip to match its sequence's frame
size. So every clip is built in two layers:

```
FOOTAGE clip (trimmed to the clean range)
  -> NEST A  `NNN_..._A-SPD50`   25p, footage's native size: the clip at 50% (or 100%)
       -> NEST B  `NNN_..._B-WARP`   25p, same size: NEST A with Warp Stabilizer applied
            -> SEQ_...           NEST B is what gets cut, reframed, scaled, shaken and SPEED RAMPED
```

Nests are 25p **at the footage's native frame size** (UHD footage gets UHD nests). The full frame is kept for warp crop
and for reframing to 9:16 in the edit sequence.

**Building nests with Filmit.** `pr_createSequence` copies the first clip's settings, which would give a 50 fps nest, so
nests are made by duplicating a 25p template:
1. Templates: `SEQUENCES/_TEMPLATES/_TEMPLATE_25P_<W>x<H>`, one per footage size, empty. If they don't exist, ask the
   user to create them once (File > New > Sequence > Settings: Timebase 25, frame size of the footage, then name them),
   or build one from a native 25 fps clip with `pr_createSequence {fromItems:[clip], empty:true}`.
2. Per clip, in one `pr_applyEditPlan`:
   - `pr_duplicateSequence` template -> `NNN_..._A-SPD50`, then `pr_placeClip` the footage into it at 0 with
     `sourceIn` / `sourceOut` = the clean range.
   - Speed 50%: read `pr_getClipProperties` on that clip once. If it lists a Time Remapping / Speed parameter, set it
     with `pr_setEffectProperties`. If not, Filmit can't set speed: finish the batch, then ask the user to select the
     clip inside each `A-SPD50` nest and set Clip > Speed/Duration > 50% (they can do them all in one pass). Never guess.
   - `pr_duplicateSequence` template -> `NNN_..._B-WARP`, `pr_placeClip` NEST A into it at 0.
   - `pr_applyEffect` "Warp Stabilizer" on that clip, then `pr_setEffectProperties` with real-estate settings (read the
     exact parameter names once with `pr_getClipProperties`):
     - Result: Smooth Motion. Smoothness: 10-20% (keep the intended move, kill the wobble).
     - Method: **Position, Scale, Rotation** (or Perspective). Subspace Warp bends straight architectural lines: use it
       only for organic shots (gardens, water) when the others fail.
     - Framing: Stabilize, Crop, Auto-scale. Watch auto-scale: over ~115% means the clip is too shaky. Go back to 2.1.
   - `pr_moveItems` both nests into `NESTS`.
3. Warp analyses in the background. Tell the user to let it finish before reviewing.

## 3. Editing style

**Hook (first 3-5 s, about 8 beats): fast and dynamic.**
- A cut on every beat (half-beats for the opening 2-3 shots if the track allows).
- **Scale punches alternating in and out**: land at 115-120% and snap to 100% in 4-6 frames (ease out), then the next
  shot lands at 100% and pushes in to ~110%. Keyframe Motion > Scale on the NEST B clip in the edit sequence.
- **Shakes** on hook cuts and impacts: position jitter about 20-30 px (at 1080 wide) decaying over 6-8 frames, plus
  ±0.5° rotation. Short and sharp, never a constant wobble.
- Music lowpassed under the hook (Lowpass about 500-600 Hz), opening over the last beat into the drop.

**Drop: the music takes the lead.**
- Riser ending exactly on the drop. Impact + shake on the first shot after it.
- Cuts every 2 beats (a bar on slower tracks). Let shots breathe; SFX about 6 dB lower than in the hook.
- Slow push-ins (100 -> 104%) keep locked-off shots alive.

**Speed ramps, the proper way** (on NEST B clips in the edit sequence, never on raw footage):
- Shot A accelerates over its last 30-40% into the cut. The cut sits on the fastest frame. Shot B lands at the same speed
  and decelerates over its first 25-35% back to normal.
- Ramp curves eased (bezier), peak around 400-600%. Match direction: a truck right into a truck right, a push-in into a
  push-in.
- Ramp on the beat: the fastest frame lands on a beat or downbeat.
- Filmit has no time-remap control unless `pr_getClipProperties` exposes one. Otherwise place markers at each ramp cut
  (`pr_addMarkers`, named `RAMP OUT / RAMP IN`) and tell the user which clips to ramp.

**Sound design.** Each sound goes where the picture asks for it:
| moment | sound | sync |
|---|---|---|
| speed ramp | whoosh as long as the fast stretch, louder for faster ramps | whoosh peak on the fastest frame |
| hook cuts, text pop-ins | click / tick | transient on the cut or pop |
| hook -> drop | riser | riser ends on the drop |
| hook | music lowpass, opens into the drop | open by the drop beat |
| meaningful / hero shot (the reveal, the view, the pool) | impact (sub boom) + shake | transient on the reveal |
| lifestyle shots | ambience bed (pool, birds, city, room tone) matched to the shot, faded in/out | under the shots |

Line up the transient (or a whoosh's peak), not the file start. Pull SFX from `SFX/<category>`.

## 4. Graphics

Address title after the drop, beds / baths / sq ft on an interior, location on an aerial, price near the end, a Just
Listed badge in the hook. They live in `AE ASSETS`, sit on V2 and above, and get a click on their pop-in.

## 5. AI shots: only to fill gaps

1. List the gaps: shots the edit needs that no clean footage range provides (from 2.1 and the reference/brief).
2. For each gap write a **first-frame prompt**, a **last-frame prompt** and a **motion prompt**:
   - match the real footage: same property, same light and time of day, same lens feel, so it intercuts
   - one camera move, steady, "no morphing architecture, straight lines stay straight"
   - length = timeline seconds × 2 for 50 fps output (or plus 1 s handles at 25 fps), so it can be conformed and ramped
3. Uploaded results go to `FOOTAGES/AI GENERATED` as `AI_<NNN>_...` and go through section 2 like any other clip.

## 6. Execution order (each phase is one batched Filmit call where possible)

1. `filmit_status` + `pr_getProjectState` (+ `pr_getSequenceState` if a sequence exists). Note allowance left.
2. **Organise**: bins + sort every item.
3. **Scan** footage (2.1). Show the user the keep / drop list before building nests.
4. **Nests** (2.3), one batch for all clips. Report any speed changes left for the user.
5. **Edit**: duplicate or create `SEQ_<PROPERTY>_<FORMAT>_v01` from the 25p template, place NEST B clips on beats, scale
   and shake keyframes, overlays, music on A1, SFX on A2-A4, ambience on A5.
6. **Verify**: one `pr_getSequenceState` and one `pr_exportFrame` at a ramp or punch. Report what was built, anything the
   user must do by hand (speed changes, ramps), and calls left.
