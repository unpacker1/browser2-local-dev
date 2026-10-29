# Browser2 Local AUTH/GAME — Independent development

**Public repository contains only independently written Python server code and test automation.**
It **does not** contain the proprietary Browser2.to game client, its GLB/KTX2/WASM assets, maps, original backend, or any account databases, credentials, tokens or session logs.

## Status

- Local SQLite AUTH, character roster, ephemeral join tokens, binary WebSocket protocol handshake implemented and covered by self-tests.
- HTTP static file and range-serving compatibility code; the original assets must be supplied **locally with appropriate permission**.
- Local GAME is a **partial, independently written compatibility implementation**, not the original proprietary game service. Automated tests are not proof of successful gameplay or a fully populated world.
- Original browser client and data are not patched. The repository includes no service credentials.

## CI

On every push and PR the public GitHub Actions workflow runs Python 3.11 and 3.13 offline self-tests of V14–V18, checks for accidentally committed proprietary/private file extensions, then creates a **server-code-only** Termux artifact. Standard GitHub-hosted runners on public repos are free subject to GitHub terms and limits. See GitHub billing docs.

## Local test

```sh
python server/browser2_local_base_v14.py --selftest
python server/browser2_local_stack_v15.py --selftest
python server/browser2_local_map_sync_v16.py --selftest
python server/browser2_gercek_oyun_tani_v17.py selftest
python server/browser2_baglanti_duzeltme_v18.py selftest
```

## Termux

The phone's existing working directory is `~/storage/downloads/BROWSER2_BAGIMSIZ`. Only apply **reviewed** server code updates by running `bash termux/update_phone.sh` from the cloned repo. It backs up existing `TESTLER` Python modules before copying; it does not touch `public_assets` or the SQLite database. Updating scripts does not guarantee compatibility with the locally running server until restart.

## Security / distribution

Use `127.0.0.1` only. Never expose these prototype HTTP/WS endpoints to the internet. Do not put original game data, private account files or credentials into a public repository or Actions artifacts. Run personal login/3D tests only on your own phone; GitHub Actions runs software tests, not a live authenticated game.

## V28 AUTH/client entry compatibility (local-only)

The local launcher now discovers the active `auth-*.js` and `game-*.js` modules
from the **unmodified** original `index.html`; it also requires a compatible
local `world-bridge-*.js` file. It does not hardcode historical V14–V27
bundle hashes. An incomplete/ambiguous module set is rejected (HTTP 503
on the generated local launcher) instead of silently mixing builds.

The V18 generated page imports the original AUTH module and calls its
`a7.worldServerFor(mapId)` export, checks that the returned WebSocket URL
has the same origin as the local server, and uses the local SQLite
session created by the independent /__local__/bootstrap endpoint.
It **never** logs or copies any remote account credentials or joins a remote
server. The original V28 AUTH/GAME client bundles themselves are never patched.

On Termux (after you put an **authorized** original client archive at
`~/storage/downloads/BROWSER2_BAGIMSIZ/public_assets/browser2.to`):

```sh
python server/browser2_local_base_v14.py --selftest
python server/browser2_baglanti_duzeltme_v18.py selftest
python server/browser2_local_base_v14.py --audit
bash termux/update_phone.sh
python ~/storage/downloads/BROWSER2_BAGIMSIZ/TESTLER/browser2_baglanti_duzeltme_v18.py serve --port 8899
```

Visit `http://127.0.0.1:8899/__local__/` and inspect the safe, aggregated
status at `http://127.0.0.1:8899/__local__/v18`.
If a previous copy of the V18 server is already running, stop *that*
process before launching this version; its `start` command will not
silently replace a running service.

**Scope:** This change addresses V28 entry-point compatibility only.
It does not create the original private AUTH/GAME backend, replace its DB,
populate mobs or NPCs, correct the original first-village spawn, remove
duplicate character renderers, or guarantee mobile FPS. Server-side
WebSocket JoinAccepted is **not** evidence of a complete gameplay session.

## V26: local website, offline wiki/forum and local leaderboard

V26 searches the original V28 archive at these **local** paths (in order):

- `~/storage/downloads/BROWSER2_SIFIRDAN_TAM_SITE/site/browser2.to`
- `~/BROWSER2_SIFIRDAN_TAM_SITE/site/browser2.to`
- `~/storage/downloads/BROWSER2_BAGIMSIZ/public_assets/browser2.to`

A custom path can be given with `--root /full/path/to/browser2.to`.
A valid archive must have an unmodified `index.html` and the matching
AUTH/GAME/world-bridge JS modules; metadata checks also report the
original boot manifest and map registry. **Nothing is copied or rewritten.**

After updating the public server-only Python files to Termux:

```sh
python server/browser2_v28_local_site_v26.py selftest
python server/browser2_v28_local_site_v26.py audit
bash termux/update_phone.sh
python ~/storage/downloads/BROWSER2_BAGIMSIZ/TESTLER/browser2_v28_local_site_v26.py serve --port 8899
```

The local-only sites are:

- `http://127.0.0.1:8899/__local__/`: V28 launcher
- `http://127.0.0.1:8899/wiki/`: offline archived wiki browser
- `http://127.0.0.1:8899/forum/`: offline archived forum browser
- `http://127.0.0.1:8899/leaderboard/`: **LOCAL** SQLite leaderboard, not the real server
- `http://127.0.0.1:8899/__local__/v26`: read-only diagnostics

Wiki/forum pages use the original public GET snapshot files already present
in the private local archive under `_BROWSER2_PUBLIC_API_V28`.
They are **not** live services or usable write APIs. Missing endpoints
return 404; incomplete page archives are flagged `partialArchive`.
The playable GAME server remains independently developed and **partial**.
This module does not change first-village spawn, existing character rows,
graphics performance or the original native server behavior.

**Publication warning:** All GitHub public repository files are readable
and downloadable by anyone. Never push the private 4.5 GiB V28 archive,
assets, proprietary bundles, SQLite DBs, credentials or access tokens into
this repository, a public Actions artifact, or GitHub Pages.
GitHub Actions is a short-lived test/build environment and cannot host a
persistent playable AUTH/GAME server. Keep the prototype bound to
`127.0.0.1` unless separately engineered for secure deployment.
