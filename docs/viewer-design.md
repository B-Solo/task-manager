# Taskmaster Show Control System — Viewer Design

This document defines the **Viewer** application: what appears on the TV, how display modes interact, and how the scoreboard animation is implemented. Wire messages are defined in the [protocol design doc](protocol-design.md); system context and folder layout are in the [High-Level Design](high-level-design.md).

Where the two design docs disagree on intent, the High-Level Design wins. Where they disagree on message or rendering detail, this document and the protocol doc win.

## 1. Scope

The Viewer:

- Listens for WebSocket commands on port `8765`
- Renders **one full-screen display mode** at a time on the HDMI output
- Reads all media from local disk under `viewer/media/`
- Sends `catalogue` (reply to `get_catalogue`) and `error` only — no success acknowledgements

The Viewer does not score tasks, store show progression, or expose operator controls. It executes commands deterministically.

## 2. Design principles

These follow the [High-Level Design §2](high-level-design.md#2-design-principles) and add Viewer-specific constraints.

### Seamless full-screen presentation

The Viewer is a single, borderless, full-screen surface on the TV. Everything the audience sees — the idle background, video, stills, leaderboard — renders in that one window. Video never opens in a separate player window or OS media chrome.

**"Background" means the idle screen.** There is no separate background image layered behind media or the scoreboard. The background is simply what is on the TV when nothing else is happening — the screen the show rests on and returns to. Media and the scoreboard are their own full-screen modes, not composited over it. It is defined in [§4.1](#41-background).

**The screen is never blank.** At every moment there must be something intentional on the display. When in doubt, show the **idle background**:

| Situation | What the audience sees |
| --------- | ------------------------ |
| App launch or process restart | Idle background |
| Between commands / idle | Whatever the last command left, or the idle background |
| Loading the next clip, still, or leaderboard | **Keep showing the previous content** until the new content is ready to paint |
| Load or playback failure | Previous content if still valid; otherwise the idle background |
| Video finished | Idle background (not black, not empty) |

**Seamlessness** means the audience never watches a spinner, a grey Qt widget, a flash of black, or an empty window while work happens off-screen. Prepare the next view first; switch only when the first frame (or equivalent) is ready. Mode changes are cuts or short cross-fades between fully rendered content — never a clear-to-empty step.

**No borders** means no window frame, title bar, resize handles, or cursor during a show. Videos are authored to fill the 16:9 display; any unavoidable letterbox/pillarbox is plain black — a steady frame, never a flash to blank.

### Audience-first rendering

What the audience sees must match Taskmaster studio presentation: full-screen video and stills, the idle background between segments, and a leaderboard that matches the [VodBox Taskmaster scoreboard](https://vodbox.github.io/tm-scoreboard/) look as closely as practical.

The **idle background** is a project-generated asset: an ornate red-and-gold flame backdrop with a central gold frame holding the current series' Taskmaster portrait, and a `TASKMASTER` nameplate below. It is fully ours (generated, then colour-graded and composited in-repo — no third-party licensing). See [§4.1](#41-background).

### Command-driven, no local decisions

The Viewer never infers scores, episode order, or “what should be on screen” except where the protocol explicitly defines automatic behaviour (for example, return to background when a video ends). Leaderboard ordering and tie-breaking use the `scores` payload and local display names only for alphabetical tie-break, matching the Controller.

### Offline and self-contained

All assets required to render are stored locally under `viewer/media/`. Nothing is fetched from the network during a show or at startup.

### Fail loudly to the Controller

Playback failures, missing files, and malformed commands produce an `error` message to the Controller. The TV never shows error text or diagnostic UI to the audience — only the last good frame or the idle background ([§2](#seamless-full-screen-presentation)).

## 3. Application structure

```
viewer/
  src/
    app.py              # entry point, QApplication, full-screen window
    websocket_server.py # listen :8765, parse JSON, dispatch commands
    display/
      window.py         # top-level QWidget, mode switching
      background.py     # idle background
      media.py          # video (QMediaPlayer -> QVideoSink surface) and still (QPixmap)
      scoreboard.py     # leaderboard widget (episode + series share one impl)
    catalogue.py        # scan media/, build catalogue payload
    assets.py           # paths, font registration, safe path resolution
  media/                # see High-Level Design §5
```

### Window and display

- One top-level `QWidget` (or equivalent) on the **external display** (HDMI TV): full-screen, frameless, no title bar, cursor hidden during show.
- The idle background widget is always available as the bottom layer and as the global fallback ([§2](#seamless-full-screen-presentation)).
- On launch, paint the **idle background** immediately — never an empty window while the WebSocket server or assets initialise.
- All modes (background, media, scoreboard) are children of this same window. `QMediaPlayer` output is embedded in the window (e.g. `QVideoWidget` / `QGraphicsVideoItem`), never a detached or native OS player window.
- When switching modes, **do not hide the current content until the next mode is ready**. Only one mode is visible to the audience at a time, but loading happens behind the last painted frame.

### WebSocket dispatch

Each incoming command maps to a handler that updates the display. Handlers may start async work (decode video, load images, build scoreboard rows). The handler returns without clearing the screen; the audience keeps seeing the previous command’s output until the new output is ready ([§2](#seamless-full-screen-presentation)). A new command **preempts** preparation of any earlier not-yet-shown content and replaces what is on screen once the new content is ready — or immediately if the new content is already prepared.

See [protocol §4–§5](protocol-design.md#4-connection-lifecycle) for connection lifecycle and command payloads.

## 4. Display modes

### 4.1 Background

**Command:** `background` ([protocol §5.3](protocol-design.md#53-background))

The **idle background** is the screen the show rests on whenever nothing else is displayed — at launch, between segments, and after a video ends. It is a display mode in its own right, not a layer drawn behind media or the scoreboard.

The asset shown at runtime is `assets/backgrounds/default.png`: the ornate red-and-gold flame backdrop with the current series' Taskmaster portrait composited into the central gold frame and a `TASKMASTER` nameplate below.

The asset is authored **16:9 (1920×1080)** to match the TV, so it is simply **cover-scaled** to fill the display (`KeepAspectRatioByExpanding`, centred). Any tiny aspect mismatch crops symmetrically and imperceptibly; the framed portrait and nameplate stay centred and full-size — no vertical zoom. The width beyond the original 3:2 framing is filled by extending the flame damask outward (reflected at build time), keeping the central frame untouched.

The other background files are **build-time sources**, not shown directly and never returned as selectable backgrounds:

| File | Role |
| ---- | ---- |
| `assets/backgrounds/default.png` | The idle background rendered on the TV (16:9, 1920×1080) |
| `assets/backgrounds/backdrop-base.png` | The plate with an **empty** central frame — base for compositing a new portrait each series (also 16:9) |
| `assets/taskmaster-backdrop.png` | The ornate flame backdrop plate (source used to produce the above) |
| `assets/taskmaster.png` | The current series' Taskmaster portrait dropped into the frame |

There is a single selectable background this season — the idle background (`default.png`) — so the `background` command carries no parameters ([protocol §5.3](protocol-design.md#53-background)). `backdrop-base` is a build-time template and is never shown at runtime.

### 4.2 Media

**Command:** `show_media` ([protocol §5.2](protocol-design.md#52-show_media))

| Input | Behaviour |
| ----- | --------- |
| Video | Play once. Rendered by painting the player's frames ourselves via a `QVideoSink` (not a `QVideoWidget`), because that lets us **retain the last decoded frame** — a plain video widget blanks to black the moment playback ends. Aspect ratio preserved; videos are authored to fill the 16:9 display, and any unavoidable letterbox/pillarbox is plain black. **At the start**, keep the previous mode (usually the idle background) visible and only cut to the clip once its **first frame has actually arrived** at the sink (with a short fallback), so there is no black flash on the way in. When playback **ends on its own**, **hold on that final frame for 1 s** (the surface keeps the last valid frame; the end-of-stream empty frame is ignored), then cut to the idle background and release the player. Any new command during that hold cancels it and takes over immediately. |
| Video with `preroll` | A **lead-in** clip (the series-wide `task_lead_in`) plays first, then chains **straight** into the main clip. The moment the lead-in ends we swap the player's source to the main clip and play — **no** 1 s freeze between them, and no black: the lead-in's last frame stays on the surface until the main clip's first frame paints. Only the **main** clip's natural end triggers the 1 s hold + return to background above. If the lead-in is missing or not a video, send `error` but play the main clip alone (the show never stalls). |
| Still | Shown until the next command; no auto-return to the idle background. **Contained and centred on black — never cropped, stretched, or rotated:** a portrait photo shows with black to its left and right rather than being cropped to fill. EXIF orientation is honoured (via `QImageReader` auto-transform) so phone photos display upright. **SVG** stills (e.g. a composited photo montage) are recognised too and rendered up to the TV resolution (rather than their small intrinsic size) so they stay crisp full-screen. Load off-screen; keep the previous frame visible until the still is decoded, then switch. |

When a new `show_media` arrives during playback, stop the current video **without** clearing the display; show the new media once its first frame is ready (or the still is loaded). If the new file fails, revert to previous content or the idle background and send `error`.

Path validation: resolve under `media/`, reject `..` and absolute paths → `error` `bad_request`.

### 4.3 Episode leaderboard

**Command:** `show_leaderboard` ([protocol §5.4](protocol-design.md#54-show_leaderboard))

Shows the scoreboard as its own full-screen mode, drawn over the **typewriter background plate** (`assets/scoreboard/background.jpg`), matching the VodBox reference. This is a distinct mode, not composited over the idle background. Build rows and load portraits off-screen; keep the previous display until the scoreboard’s first frame is ready, then switch. Resolve each contestant's name and portrait locally by id. Missing portrait → use a neutral placeholder and log locally (missing contestant entry → `error` `not_found`).

### 4.4 Series leaderboard

**Command:** `show_series_leaderboard` ([protocol §5.5](protocol-design.md#55-show_series_leaderboard))

Same widget and animation as the episode leaderboard, with two differences:

- **Scores** are cumulative series totals rather than a single episode's.
- **The leader's seal is gold.** Every contestant tied for the top score uses the **gold seal** (`assets/seal-gold.png`); everyone else keeps the standard red seal (`assets/seal.png`). If all scores are zero (season not yet started) no one is treated as the leader — all seals are red. The gold asset is a hue/tone recolour of the red seal, so it shares identical shape, shading, and alpha.
- **The gold seal is animated, not pre-set.** The board opens on the *previous* totals with the gold seal on the previous leader, then — as the scores count up and rows reorder — the gold crossfades to whoever leads on the *current* totals (and off anyone who has been overtaken). This is done by stacking the gold seal over the red one and animating its opacity, so the eventual leader is revealed by the animation rather than being obvious the instant the board appears. The episode board never goes gold.

## 5. Scoreboard visual specification

The target appearance is the [VodBox tm-scoreboard](https://vodbox.github.io/tm-scoreboard/) demo. Our implementation is PySide6, not an embedded browser, but **layout numbers, timing, and motion** are ported from the vendored VodBox reference sources in the repo (MIT — see [§8](#8-third-party-attribution)).

The scoreboard renders over the **typewriter background plate** (`assets/scoreboard/background.jpg`) — the sepia typewriter with the `TASKMASTER` sheet, matching the VodBox reference — cover-scaled to fill the screen. The framed portraits and score seals are composited on top of it.

The board itself is **composited at runtime** from the parts below (frames, seals, portraits, score text); only the background plate is a whole image on disk.

### Assets used by the scoreboard

| Part | Path | Notes |
| ---- | ---- | ----- |
| Background plate | `assets/scoreboard/background.jpg` | Typewriter backdrop, cover-scaled to fill the screen behind the board. Vendored from the VodBox kit ([§8](#8-third-party-attribution)). |
| Portrait frame | `assets/scoreboard/frame.png` | Gold frame overlaid at full column width. Part of the vendored VodBox kit ([§8](#8-third-party-attribution)). |
| Wax seal (red) | `assets/seal.png` | Default seal, all episode-leaderboard rows and non-leaders on the series board. |
| Wax seal (gold) | `assets/seal-gold.png` | Series leader(s) only ([§4.4](#44-series-leaderboard)). Hue/tone recolour of the red seal; identical shape/shading/alpha. |
| Contestant portrait | `assets/contestants/<id>.png` | Resolved by the `contestant` id from the leaderboard payload. Missing → neutral placeholder + local log. |
| Score font | `assets/fonts/veteran_typewriter/veteran_typewriter-webfont.ttf` | Registered at startup via `QFontDatabase` ([§5.4](#54-score-seal-and-typography)). |
| Layout/animation spec | `assets/scoreboard/reference/` | Upstream CSS/JS/HTML kept as the porting reference; **not loaded at runtime**. |
| Visual references | `assets/scoreboard/blank.jpg`, `assets/scoreboard/ref.jpg` | Upstream stills kept for eyeballing the target look; not used at runtime. (`ref.jpg` is a full-board screenshot; the clean plate is `background.jpg` above.) |

Provenance and refresh instructions for the vendored pieces are in `assets/scoreboard/SOURCE.md`.

### 5.1 Design canvas

The scoreboard lays out in a fixed logical coordinate system, then scales to the TV (see §5.6).

| Property | Value (from reference) |
| -------- | ---------------------- |
| `main` width | 1400 px |
| `main` height | 413 px |
| Contestant column width | 205 px |
| Horizontal slot pitch | 275 px (position `translateX(275 * index + 30)`) |
| Frame area height | 250 px (+ 25 px margin below frame before seal) |
| Portrait inset inside frame | 33 px padding on all sides from frame PNG |
| Score seal area | Full width of column; score text ~84 px, Veteran Typewriter |

Contestants are ordered **left to right by ascending score** (lowest on the left, winner on the right), matching upstream sort order.

**Tie-breaking for order:** when scores are equal, sort alphabetically by display name (Controller rule; Viewer applies the same when sorting for layout).

### 5.2 Portrait frame

Stack (back to front):

1. **Fill** — contestant portrait, cover-cropped, centred in the inset rect.
2. **Inner shadow** — inset shadow on the fill (`box-shadow: inset -5px 5px 7px rgba(0,0,0,0.5)`).
3. **Frame** — gold portrait frame PNG overlaid at full column width.

Frame container has `drop-shadow(15px 15px 3px rgba(0,0,0,0.4))`.

### 5.3 Wobble animation

Each frame gently rotates about its centre:

| Property | Value |
| -------- | ----- |
| Keyframes | −4° → +4° |
| Duration | 3 s |
| Easing | ease-in-out, alternate, infinite |
| Stagger | `animation-delay: -index * 1.25 s` so frames are out of sync |

In Qt: a custom paint transform per contestant driven by the board's master timer. The wobble is **continuous** — it runs the whole time the board is on screen, including after the count-up/reorder has settled (the timer must not stop when the score animation finishes).

No hover/click affordances from the interactive demo (+ button, exit, score edit, play button).

### 5.4 Score seal and typography

Below the frame:

1. **Wax seal** image, full column width. Two variants exist: red (`assets/seal.png`, default) and gold (`assets/seal-gold.png`). The episode leaderboard always uses red; the series leaderboard uses gold for the leader(s) — see [§4.4](#44-series-leaderboard).
2. **Score text** — white, Veteran Typewriter, ~84 px, slight shadow `1px 1px 3px rgba(0,0,0,0.2)`. Centre the glyph **ink** (tight font-metrics bounding box, not the item's full line box, which is padded by the font descent for digit-only text) on the seal's **visual centre** — a fraction ≈ (0.53, 0.52) of the seal art, measured from its alpha, rather than the geometric box centre — so the number reads as sitting in the middle of the wax.

Register the Veteran Typewriter font at startup via `QFontDatabase`.

### 5.5 Leader emphasis (scale)

After sorting, let `maxScore` be the highest current score (during animation, use the **target** score for ordering/emphasis at the end of the motion; during count-up, reference implementation reorders at animation start — see §6).

| Condition | Column scale |
| --------- | ------------ |
| Score equals `maxScore` and ≤2 tied for first | **1.2×** (`larger`) |
| Score equals `maxScore` and >2 tied for first | **1.1×** (`large`) |
| Otherwise | 1.0× |

The emphasis scales the **whole column together** — portrait frame **and** its seal + score — about the column's own visual centre, so a leader grows/shrinks in place as a unit rather than only the frame growing from its base. The board opens on the **previous** standings, so the *previous* leader is drawn bigger during the opening hold; as the scores count up and rows reorder, that leader shrinks back to 1.0× while the *new* leader grows to 1.2×/1.1×, letting the audience watch the lead change. Scale transitions use **2 s** duration (same as horizontal reorder).

### 5.6 Scaling to the TV

Match upstream `resize()` logic:

```
contestantCount = number of contestants in payload
wm = 1400 * (contestantCount / 5)
m  = min(windowWidth / wm, windowHeight / 1080)
```

Apply scale `m` to the scoreboard root; horizontally centre:

```
left = (windowWidth - wm * m) / 2
```

Vertical centring: reference pins `main` with `top: 0; bottom: 0; margin: auto 0` — equivalent to centring the 413 px-tall logical board in the window.

For fewer than five contestants, the board compresses horizontally so spacing stays consistent with the five-slot design.

## 6. Scoreboard animation timeline

Triggered on every `show_leaderboard` / `show_series_leaderboard` command.

**Inputs:** for each contestant, `previous` and `current` from the payload (integers; fractional points are not expected but if present, follow reference remainder handling below).

**Phase 0 — Immediate**

- Switch display mode to scoreboard.
- Build contestant row widgets with portraits and **initial displayed score = `previous`**.
- Layout rows at positions corresponding to **`previous` totals** (sort by previous, tie-break by name).
- Apply leader scale based on **previous** standings (optional polish; reference applies scale on transform after play — initial frame may show unscaled until play; for TV use, starting with previous order and previous scores is required).

**Phase 1 — Hold (1 s)**

- No score or position change. Matches upstream `setTimeout(..., 1000)` before animation.

**Phase 2 — Animate (2 s)**

Run concurrently:

1. **Score count-up** — for each contestant, interpolate displayed score from `floor(previous)` toward `floor(current)` over 2000 ms with easing:
   - `t' = min((now - start) / 2000, 1)`
   - `ease(t') = t' < 0.5 ? 2*t'*t' : -1 + (4 - 2*t')*t'` (reference `ease()`)
   - Display `round(ease(t', floor(previous), floor(current)))` plus fractional remainder crossfade in second half if non-integer scores exist.
2. **Reorder** — horizontal `translateX` to positions for **`current`** sort order, **2 s** transition.
3. **Leader scale** — animate `frame-scaler` to 1.2× / 1.1× / 1.0× per §5.5 based on **current** totals, **2 s** transition.

Reference calls `transformContestants()` once at the start of phase 2 (positions and scale target current scores immediately while numbers catch up). Replicate that: **motion targets final order from t = 0 of phase 2**.

**Phase 3 — Settle**

- After 2 s, snap displayed scores to exact `current` values.
- Hold until the next command.

**Preemption:** if a new command arrives during any phase, stop timers/animations and switch modes immediately.

## 7. Catalogue scan

**Trigger:** `get_catalogue` only ([protocol §5.1](protocol-design.md#51-get_catalogue)).

Scan rules are defined in [protocol §6.1](protocol-design.md#61-catalogue). The Viewer walks episode media, reads `contestants.json`, and returns the JSON catalogue. Warnings (unknown prize filename, etc.) go to the Viewer log only.

## 8. Third-party attribution

Scoreboard portrait-frame visuals and animation reference are derived from **[VodBox/tm-scoreboard](https://github.com/VodBox/tm-scoreboard)** (MIT, Copyright 2021 VodBox / Dillon Pentz). Vendored copies and license text live in the repo; the Viewer does not load the upstream site at runtime.

**Veteran Typewriter** (Magique Fonts) is used for score digits. DaFont lists it as [100% Free](https://www.dafont.com/veteran-typewriter.font) for personal and commercial use.

## 9. Errors and logging

Wire format: [protocol §6.2](protocol-design.md#62-error).

| Situation | Code |
| --------- | ---- |
| Missing media path | `not_found` |
| Path escapes `media/` | `bad_request` |
| Unplayable video | `unsupported_media` |
| Unknown command type | `unknown_type` |
| Oversized message | `too_large` |
| Unexpected failure | `internal` |

Log to stderr or a local log file: command type, path, and error detail. Do not log full WebSocket payloads in production unless debugging. On error, the display follows [§2](#seamless-full-screen-presentation): never blank, never show the failure to the audience.

## 10. Reconnect behaviour

On Controller reconnect, the Viewer does not replay state. The display stays on whatever the last command left (or the idle background if the Viewer itself restarted). There is no automatic state resync: the operator re-taps the action for the current intended screen and the next command repaints it ([protocol §4](protocol-design.md#4-connection-lifecycle)).

After a Viewer **process restart**, paint the idle background immediately on launch — same rule as [§2](#seamless-full-screen-presentation).

## 11. Out of scope (this document)

- Controller UI and score entry
- `show_state.json` schema
- Authentication, TLS, mDNS advertisement (hostname resolution is Controller-side per HLD)
- Sound effects, timers, OBS — [HLD §7](high-level-design.md#7-future-features)
