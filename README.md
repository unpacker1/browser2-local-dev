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

### One-command Termux start / local HTTP verification

From a checkout of the public **server-only** repository:

```sh
cd ~/browser2-local-dev
git switch main
git pull --ff-only origin main
bash termux/start_v26.sh
```

The script verifies V26 offline tests, locates the PRIVATE original archive
in the phone, backs up/copies only independently developed Python sources,
starts the localhost-only server in the background, and checks HTTP 200
for the launcher, wiki, forum and local rankings. It does **not** kill an
old process already using port 8899; stop that process manually before
running V26. Check `BROWSER2_BAGIMSIZ/LOGS/browser2_v26_site.log` on failure.
This is **not** a public website deployment and does not prove that a
character entered the world.

### If V26 stops at [ARCHIVE NOT FOUND] or [ARCHIVE NOT READY]

Run the read-only diagnostic (no Downloads deletion, no re-download):

```sh
cd ~/browser2-local-dev
python3 server/browser2_v28_local_site_v26.py diagnose
```

The output distinguishes **folder absent** from **index present but missing AUTH/GAME/bridge JS**. It checks both
`BROWSER2_SIFIRDAN_TAM_SITE` and `BROWSER2_BAGIMSIZ/public_assets`, with limited nested-folder discovery.
A known custom folder can be passed with `--root /absolute/path/to/archive-parent-or-browser2.to`.
The `audit` command now prints the same file-level diagnostic on failure.
The original archive is never altered or downloaded automatically.

## V27: pack-file compatibility and loading-stage diagnostics

The original V28 `boot-manifest.json` references `core-08d8acfd75.pack`
and other `.pack` names. Some extracted original files are retained as
`.pack.bin` files. V27 maps **only the exact original manifest-listed**
pack paths to the matching **existing** `.pack.bin` files; it provides
normal binary HTTP and byte ranges without copying, rewriting, replacing,
or generating game content. An existing original URL/file always wins.

It also tracks local HTTP 404 *categories*, and a bounded list of
missing static **pathnames only**, stripped of query strings.
No credentials, tokens, WebSocket payloads, account data, or IPs are stored.
This provides evidence for boot/asset failures without guessing game data.

On the phone:

```sh
cd ~/browser2-local-dev
git switch main && git pull --ff-only origin main
BROWSER2_LOCAL_PORT=8900 bash termux/start_v26.sh
```

We use port **8900** while an older 8899 listener may still be running.
Visit `http://127.0.0.1:8900/__local__/` and after one play attempt read
`http://127.0.0.1:8900/__local__/v27`.
The response reports manifest/core-file availability, missing static
paths by group, and whether a WebSocket/JoinAccepted ever occurred.
If manifest-listed packs are absent, the service reports them as missing
rather than fabricating replacements. If a 404 is a different route class,
investigate that path class rather than editing original JS.

Passing offline tests only verifies local compatibility and endpoints;
it does not prove gameplay or recreate the original proprietary GAME.


## V28 Chrome capture: manifest `.pack` vs archived `.pack.bin`

The captured original V28 asset flow requests logical pack URLs from
`/assets/packs/boot-manifest.json` (including `core-08d8acfd75.pack`),
whereas the private Android archive stores the pack bytes as
`core-08d8acfd75.pack.bin` and similarly for map `world-*.pack` and
`mobs-*.pack`. V26's localhost server now serves **the identical archived
bytes** at the manifest's logical `.pack` URL, but **only** for exact names
listed in the original boot manifest. Byte ranges (HTTP 206) and HEAD are
supported. Original archived files remain untouched; no proprietary content
is pushed into the public repository or CI.

For a clean, separate phone test, leave the old port 8899 service alone:

```sh
cd ~/browser2-local-dev
git switch main && git pull --ff-only origin main
BROWSER2_LOCAL_PORT=8917 bash termux/start_v26.sh
# Visit http://127.0.0.1:8917/__local__/ and try one world entry.
python3 server/browser2_v28_local_site_v26.py report --port 8917
```

The `report` command prints only pack-alias counts, coarsely redacted
HTTP 404 route shapes from the inherited V19 observer, and aggregated world
WebSocket/Join counters. It does not print query strings, character IDs,
tokens, cookies, raw WebSocket frames, private pathnames or credentials.

**Interpretation:** a `manifestPackAliasesPresent` count and successful
`packAliasHits` prove the manifest-to-archive HTTP transport shim works,
**not** that the original game entered the world. If the client still fails,
use `[HTTP ERROR]` route shapes, `[GAME]` and `[LAUNCH]` to locate the
next mismatch. In the 2026-10-29 phone capture, 132 HTTP 404s were classified
as `other_http`; their exact source is not yet confirmed. Avoid guessing
responses or modifying game protocol without this evidence.
