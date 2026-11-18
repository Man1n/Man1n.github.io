---
name: motion-graphics
description: Add, preview, tune or create code-generated motion graphics for real-estate edits (address titles, price reveal, stats, location pin, floor plan, Just Listed badge, light leaks), rendered as ProRes 4444 with alpha. Use when graphics or visual enhancement are asked for.
---

# Motion graphics

Templates: `editkit/overlays/templates/*.html`. Each one is a pure function of time (`window.seek(t)`), rendered with
Playwright frame by frame and encoded to ProRes 4444 with alpha, so it drops onto V2+ in Premiere.

| template | params (all optional) |
|---|---|
| `property_title` | eyebrow, title, sub, y (0-1), align left/center |
| `price_reveal` | label, price ("$2,450,000", digits roll like a slot machine), note, y |
| `stats_row` | items: [{icon: bed/bath/area/car/pool/acre, value, label, decimals, prefix, suffix}], y |
| `location_pin` | x, y, place, lines: [[name, time], ...] |
| `floorplan_draw` | title (html ok), rooms: [{name, dim, r:[x,y,w,h] 0-1}], y |
| `badge` | text ("Just Listed", "Sold", "Open House"), y, tilt |
| `light_leak` | peak_at (0-1 of its length), intensity, palette, direction, seed. Centre it on a cut |
| all | accent (default #d9b36c gold), ink (text colour) |

- Add: `python -m editkit add-overlay plan.json --template stats_row --start 8.1 --dur 2.6 --params '{"items":[...]}'`
- Preview one frame fast before rendering video: `python -m editkit still stats_row --t 1.2 --params '{...}' --out s.png`
  then Read the PNG (composite it over a frame of the shot if placement matters).
- Render all: `python -m editkit overlays plan.json` (or as part of `build`).
- Timing: graphics pop on beats. Keep 2.5-3.5 s on screen, the exit is the last 0.45 s. Avoid the bottom 15% on 9:16
  (platform UI).

New template contract: an HTML file that loads `_lib.js`, sets `window.DEFAULTS`, reads params from `P`, and defines
`window.seek = t => {...}` drawing the exact state at `t` (no CSS animations or timers). Use `win(t, start, dur, ease)` for
eased 0-1 progress, `exitK(t)` for the exit, `U` as 1px at a 1080 short edge so layouts scale to any resolution.
Check every new template with `still` at several times before using it.
