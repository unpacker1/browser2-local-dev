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
