# MeshGopher — Meshtastic DM Gopher Navigator

MeshGopher lets you browse Gopher servers **via Meshtastic direct messages**.  
You DM the bot simple commands (like `u gopher://gopher.floodgap.com/1/`) and it replies with paged menus/files.

---

## Features

- **Direct Message only**: Listens for DMs and replies as DMs (won’t spam LongFast/broadcast).
- **Simple commands**:
  - `u <URL>` — open a Gopher URL
  - `n` / `p` — next / previous page
  - `b` — up directory / back
  - `0..9` — select an item on the current menu page
  - `s <terms>` — run search for a selected “type 7” item
- **Smart pagination**:
  - Menus: 10 items per page (skips non-selectable `i` lines)
  - Files: 20 lines per page
- **Ordered replies**: Multi-chunk messages are sent with short pacing to preserve order.

---

## Repo Layout

```
meshgopher/
  main.py         # DM command router + session management
  meshie.py       # Meshtastic TCP wrapper (DM detection, paced sending)
  gopherlib.py    # Minimal Gopher client (menu/file/search)
  meshie/         # Meshie package (client, chunker, filters)
  localgopher/    # Lightweight file-backed Gopher server
  server/         # Demo Gopher content (editable)
  requirements.txt
  Containerfile   # (Podman/Docker)
  README.md
```

---

## Requirements

- Python **3.10+** (3.11 recommended)
- A reachable **Meshtastic TCP API** (default port `4403`)
- The bot and your Meshtastic node must be on a network path where the bot can reach `MESH_HOST:MESH_PORT`

Python dependencies (installed via `requirements.txt`):
- `meshtastic>=2.3`
- `pypubsub>=4.0.3`

---

## Environment Variables

| Var                      | Required | Default    | Description                                                                 |
|--------------------------|----------|------------|-----------------------------------------------------------------------------|
| `MESH_HOST`              | **Yes**  | —          | Meshtastic node IP/hostname (TCP API).                                      |
| `MESH_PORT`              | No       | `4403`     | Meshtastic TCP port.                                                        |
| `LOCAL_GOPHER_ROOT`      | No       | `server`   | Filesystem path containing the demo/local Gopher content.                   |
| `LOCAL_GOPHER_HOST`      | No       | `0.0.0.0`  | Bind address for the bundled Gopher server.                                 |
| `LOCAL_GOPHER_PORT`      | No       | `7070`     | TCP port for the bundled Gopher server.                                     |
| `LOCAL_GOPHER_CLIENT_HOST` | No     | —          | Hostname used when generating `u local` links (falls back to host/localhost). |
| `LOCAL_GOPHER_URL`       | No       | —          | Explicit base Gopher URL to use for `u local` (overrides host/port logic).  |

> If `MESH_HOST` is not set, the app exits with an error.

---

## Running Locally (no container)

1) Create and activate a venv (recommended):
```bash
python3 -m venv .venv
. .venv/bin/activate
```

2) Install deps:
```bash
pip install -r requirements.txt
```

3) Export envs and run:
```bash
export MESH_HOST=192.168.1.50
export MESH_PORT=4403
python main.py
```

You should see logs like:
```
[Meshie] Connecting to 192.168.1.50:4403 …
[Meshie] connection.established; my_id=!abcd1234
```

Now DM your node from another device/user with commands like:
- `u gopher://gopher.floodgap.com/1/`
- `n`
- `0`
- `b`

---

## Using the Container

### Build

With **Podman** (or Docker):

```bash
podman build -t meshgopher -f Containerfile .
# or
docker build -t meshgopher -f Containerfile .
```

### Run

Use **host networking** (or ensure the container can reach your Meshtastic node IP/port):

```bash
# Podman
podman run --rm --network host   -e MESH_HOST=192.168.1.50   -e MESH_PORT=4403   meshgopher

# Docker (Linux host)
docker run --rm --network host   -e MESH_HOST=192.168.1.50   -e MESH_PORT=4403   meshgopher
```

If you can’t use `--network host`, ensure the container can route to `MESH_HOST:MESH_PORT` (e.g., same subnet or proper NAT/port-forwarding).

---

## DM Command Reference

```
u <URL>   Open a gopher URL (e.g., u gopher://gopher.floodgap.com/1/world, or u local)
n         Next page (menu items or file lines)
p         Previous page
b         Up one directory (or back to previous view)
0..9      Select visible menu entry (menus only)
s <terms> Run a search after selecting a type-7 (search) item
```

- When viewing a **file**, only `n`, `p`, `b`, `u` apply (no 0–9 items).
- Menus skip `i` (info) lines when numbering, so your first page shows real choices immediately.

---

## Notes on Message Ordering

- Replies are chunked to ~190 chars and **paced** between chunks.
- This avoids blocking on `waitForAckNak()` (which can hang over TCP) while still maintaining practical ordering and avoiding RF bursts.

You can adjust pacing:
```python
# in meshie.py after creating Meshie(...)
mesh.inter_chunk_delay_sec = 1.0
```

---

## Security & Etiquette

- The app **never** posts to LongFast by design—it only responds to DMs.
- Keep `MESH_HOST` on a trusted network. The Meshtastic TCP API is not authenticated by default.
- Be courteous on shared meshes—avoid excessive polling or rapid command bursts.

---

## Credits

- Built on the Meshtastic Python library.
- Gopher protocol implemented minimally for menus/files/search.
- `server/` ships with a minimal Gopher site served by the bundled local server.

---

## Local Demo Gopher Server

MeshGopher now ships with a tiny Gopher server that serves files from `server/`
by default. Each directory contains a `gophermap` describing its menu entries,
and `.txt` files provide the content referenced by type-0 menu items.

Environment variables:

| Variable            | Default  | Description                                |
|---------------------|----------|--------------------------------------------|
| `LOCAL_GOPHER_ROOT` | `server` | Root directory containing gophermap files. |
| `LOCAL_GOPHER_PORT` | `7070`   | TCP port for the local server.             |
| `LOCAL_GOPHER_HOST` | `0.0.0.0`| Bind address for the server.               |
| `LOCAL_GOPHER_CLIENT_HOST` | — | Hostname to use when generating `u local` URLs (falls back to host/`localhost`). |
| `LOCAL_GOPHER_URL`  | —        | Explicit gopher URL base (e.g., `gopher://meshbox:7070/1`). |

If the root path exists, the server starts automatically when you run the bot.
Customize the content by editing the files in `server/` or point
`LOCAL_GOPHER_ROOT` at another directory tree. While chatting with the bot you
can type `u local` (or `u local/some/path`) and it will expand to the local
server URL derived from the variables above.
