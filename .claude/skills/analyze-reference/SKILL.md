---
name: analyze-reference
description: Break down a reference real-estate edit (cuts, beat sync, speed ramps, scale punches, shakes, whooshes, risers, impacts, lowpass, drop) so it can be recreated. Use when the user uploads or points to a reference video.
---

# Analyze a reference edit

1. Put the file in `projects/<P>/ref_src/` (create the project name from the property or ask once). Run:
   `python -m editkit analyze-ref <video> --out projects/<P>/ref`
2. **Look at the outputs, don't just read numbers.** Read in this order:
   - `projects/<P>/ref/timeline.png`: shots (blue = hook, orange = speed ramp), motion/zoom curves (red bands = shake,
     dotted = scale punch), loudness + beat grid + drop, spectrogram with W/I/C marks and riser / lowpass bands.
   - `contact_sheet.jpg`: middle frame of every shot, with duration, camera move, ramp, punch.
   - `report.md`: the shot table and sound-event table.
   - For shots that matter (hook, ramps, hero reveals), Read `frames/shotNN_first.jpg` and `_last.jpg`.
3. Sanity-check the machine read against what you see:
   - A "ramp" right at a cut with a zoom spike may be a scale punch. The analyzer drops obvious cases but check.
   - Music kicks are labelled `kick`, SFX booms `impact`. Whooshes are high-band swells. Lowpass detection is the weakest
     signal: if the hook sounds muffled in the ref the user will know. Ask when unsure.
   - A light leak or flash shows up as a white line in the shots row, not a cut.
4. Write the user a short breakdown, the "recipe":
   - length, BPM, hook length (in beats and seconds), cut rhythm in hook vs body (beats per shot), % cuts on beat
   - every speed ramp: which cut, how fast (peak ratio), whoosh on it?
   - punches / shakes pattern, transitions (flash / leak / whip)
   - sound design layers in order: lowpass? riser into drop? impacts where? clicks? ambience?
   - graphics seen in the frames (titles, price, stats, map pins), with their timing
5. Offer next steps: `shot-prompts` (AI first/last-frame prompts per shot) and/or `build-edit` with their clips.
