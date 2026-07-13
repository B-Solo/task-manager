# Taskmaster Show Control System

Two desktop apps that run a live Taskmaster-style show on a local network:

- **Viewer** (`viewer/`) — full-screen display on the TV. Hosts the media, owns
  the catalogue, and runs the WebSocket **server**. Renders the idle
  background, clips/stills, and the animated episode/series leaderboards.
- **Controller** (`controller/`) — the operator's touch UI. Runs the WebSocket
  **client**, owns the mutable show state (scores, progress), and sends
  fire-and-forget commands to the Viewer.

The design documents live in [`docs/`](docs/). This README covers setup and
running only.

## Requirements

- Python 3.12+ (developed against 3.14)
- Dependencies: `PySide6`, `websockets` (see each app's `requirements.txt`)

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r viewer/requirements.txt      # on the TV machine
pip install -r controller/requirements.txt  # on the operator machine
```

Both apps are self-contained deploy units — copy the folder for each machine.

## Running

### Viewer (TV machine)

```bash
python viewer/src/app.py
```

Opens full-screen (prefers an external/HDMI display when present) and listens on
`ws://0.0.0.0:8765`. All media is read from `viewer/media/` — see
[`docs/viewer-design.md`](docs/viewer-design.md) for the folder layout.

### Controller (operator machine)

```bash
python controller/src/app.py --host taskmaster-viewer.local
# same machine for testing:
python controller/src/app.py --host localhost
```

The host may be an mDNS name or a raw IP. It can also be set with the
`TM_VIEWER_HOST` environment variable. The Controller reconnects automatically
with backoff if the Viewer restarts.

## Data & state

- **Catalogue** — the Viewer scans `viewer/media/` and sends a catalogue to the
  Controller, which caches it at `controller/config/catalogue.json` and reuses
  it across reconnects. The cache lives under `controller/config/` and is **not**
  committed (it's generated locally); it is fetched on first connect and via the
  home screen's *Refresh catalogue* button.
- **Show state** — per-episode scores and progress persist to
  `controller/config/episodes/<episode>/show_state.json`. Series standings are
  **derived** from these files (there is no season-level state file).

## Tests

Headless smoke test of the full Controller flow (no network, uses a stub client
and the cached catalogue):

```bash
QT_QPA_PLATFORM=offscreen python controller/tests/smoke_flow.py
```

To regenerate the catalogue cache from the current media tree:

```bash
cd viewer/src && python -c "import json, catalogue; from pathlib import Path; \
Path('../../controller/config/catalogue.json').write_text( \
json.dumps(catalogue.build_catalogue(), ensure_ascii=False, indent=2))"
```
