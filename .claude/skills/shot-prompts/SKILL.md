---
name: shot-prompts
description: Write first-frame and last-frame image prompts plus motion prompts for AI video generation, one per reference shot, for a real-estate edit. Use after analyzing a reference, or when the user asks for prompts.
---

# First / last frame prompts

1. Generate the scaffold: `python -m editkit prompts projects/<P>/ref/report.json --look <look>`
   Looks: `luxury_golden` (default), `twilight`, `bright_interior`, `lifestyle`, `aerial`, or any free-text look.
2. The scaffold has measured facts (duration, camera move, ramp, how many seconds to generate) and `[DESCRIBE ...]` slots.
   **Fill every slot yourself** by Reading `frames/shotNN_first.jpg` and `frames/shotNN_last.jpg` for that shot, and using what
   the user told you about THEIR property (style, rooms, pool, view, location). Recreate the ref's composition and camera
   path, not its literal house.
3. Good real-estate prompts:
   - First frame: subject + space + composition + lens + light + materials. "Wide 16mm view of a double-height living room,
     floor-to-ceiling glass on the left looking onto an infinity pool, white oak floors, low sofa centred, golden hour sun
     raking across the floor, vertical lines straight, photorealistic, 9:16".
   - Last frame: the SAME scene where the move ends (closer / revealed / risen). Repeat light and materials word for word
     so the generator keeps them consistent.
   - Motion: one camera move only, its speed, "steady stabilized", "no morphing architecture", "keep straight lines straight".
   - Ramp shots: generate at real time with continuous motion and generate_seconds long (the ramp eats footage); the edit ramps it.
4. Rewrite `projects/<P>/ref/prompts.md` with the filled prompts and show the user. Ask them to name results
   `shotNN_<role>.mp4` (hero / lifestyle / detail / interior / establishing) and upload them to `projects/<P>/clips/`.
5. When clips arrive: probe each (`ffprobe`), check duration >= generate_seconds, aspect, and look at a frame from the start
   and end to confirm the move. Report anything that will not cut well.
