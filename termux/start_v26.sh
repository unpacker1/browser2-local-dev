#!/data/data/com.termux/files/usr/bin/bash
# Read-only private archive: run only on localhost.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="$HOME/storage/downloads/BROWSER2_BAGIMSIZ"
DEST="$BASE/TESTLER"
LOG="$BASE/LOGS/browser2_v26_site.log"
PORT="${BROWSER2_LOCAL_PORT:-8899}"
if ! [[ "$PORT" =~ ^[0-9]{4,5}$ ]] || ((PORT < 1024 || PORT > 65535)); then
  echo "[HATA] Hatali port." >&2; exit 2
fi
command -v python3 >/dev/null || { echo "[HATA] pkg install python" >&2; exit 2; }
echo "[1/5] Offline V26 test"
python3 "$REPO/server/browser2_v28_local_site_v26.py" selftest
echo "[2/5] V28 private archive audit"
python3 "$REPO/server/browser2_v28_local_site_v26.py" audit
echo "[3/5] Back up and update server code"
bash "$REPO/termux/update_phone.sh"
mkdir -p "$BASE/LOGS"
echo "[4/5] Checking port"
if BROWSER2_CHECK_PORT="$PORT" python3 - <<'PY'
import os,sys,socket,json,urllib.request
p=int(os.environ['BROWSER2_CHECK_PORT'])
with socket.socket() as sock:
    if sock.connect_ex(('127.0.0.1',p))!=0:sys.exit(0)
try:
    with urllib.request.urlopen(f'http://127.0.0.1:{p}/__local__/v26',timeout=2) as resp:d=json.load(resp)
    if d.get('version')=='26.0':
        print('[OK] V26 already running')
        sys.exit(4)
except (OSError,ValueError):pass
print('[ERROR] Port occupied by other/older service. No process was killed.',file=sys.stderr)
sys.exit(5)
PY
then
  :
else
  rc=$?
  if [[ "$rc" == 4 ]]; then
    echo "[SITE] http://127.0.0.1:$PORT/__local__/"
    exit 0
  fi
  exit "$rc"
fi
echo "[5/5] Starting V26 on localhost"
nohup python3 "$DEST/browser2_v28_local_site_v26.py" serve --port "$PORT" >"$LOG" 2>&1 </dev/null &
echo "[PID] $! [LOG] $LOG"
BROWSER2_CHECK_PORT="$PORT" python3 - <<'PY'
import os,time,json,urllib.request
p=int(os.environ['BROWSER2_CHECK_PORT'])
base=f'http://127.0.0.1:{p}'
for _ in range(20):
    try:
        with urllib.request.urlopen(base+'/__local__/v26',timeout=1) as r: data=json.load(r)
        break
    except (OSError,ValueError):time.sleep(.3)
else:raise SystemExit('[ERROR] Site did not start. Check V26 log.')
for route in ('/__local__/','/wiki/','/forum/','/leaderboard/'):
    with urllib.request.urlopen(base+route,timeout=3) as r:print('[HTTP]',r.status,route)
print('[MODULES]',data['originalClient'])
print('[ARCHIVE]',{k:data[k] for k in ('bootManifest','mapRegistry','wikiSnapshot','forumSnapshot')})
print('[SITE]',base+'/__local__/')
print('[DIAG]',base+'/__local__/v18')
PY
