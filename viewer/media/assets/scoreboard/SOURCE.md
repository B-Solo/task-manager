# VodBox tm-scoreboard — vendored scoreboard kit

Portrait-frame components and reference source copied from upstream so the Viewer works fully offline.

| Field | Value |
| ----- | ----- |
| Upstream | [VodBox/tm-scoreboard](https://github.com/VodBox/tm-scoreboard) |
| Live demo | [vodbox.github.io/tm-scoreboard](https://vodbox.github.io/tm-scoreboard/) |
| Pinned commit | `5b87901b82fab36b14f5fc0c448f5967939bfe0d` (2022-03-29) |
| License | MIT — see [LICENSE](LICENSE) in this directory |

## What lives here

Scoreboard-specific pieces from upstream:

- `frame.png`, `blank.jpg`, `ref.jpg`, `background.jpg` (from upstream `images/`; `background.jpg` is the typewriter plate drawn behind the leaderboard)
- `reference/` — upstream CSS/JS/HTML kept as an animation and layout spec (not loaded at runtime)

The PySide6 Viewer reimplements behaviour from `reference/`; it does not embed the web app.

## Related assets elsewhere

Shared under `viewer/media/assets/` (not in this directory):

- **Wax seal (red)** — `seal.png`, from upstream `images/seal.png`
- **Wax seal (gold)** — `seal-gold.png`, project-derived: a hue/tone recolour of the red seal for series-leader emphasis (same shape/shading/alpha)
- **Veteran Typewriter font** — from upstream `fonts/`; see font license notes alongside the font files
- **Idle background** — project-owned, generated and composited in-repo under `assets/backgrounds/` (not derived from upstream)

## Refreshing from upstream

Re-download scoreboard files from the pinned commit into this directory; update seal and font under `assets/` separately if needed. Update the pinned commit hash here after verification.
