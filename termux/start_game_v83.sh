#!/data/data/com.termux/files/usr/bin/bash
# V83 replaces only a SHA-pinned local Python V69 bridge; does not change native GAME/SQL/client.
set -euo pipefail
TARGET="$HOME/CEMREEFE_BROWSER2_V69_NATIVE_SHOP_CATALOG"
PATCH="$HOME/BROWSER2_LOCAL_SERVER_DATA/fix_native_npc_disconnect_v83.py"
BASE="https://raw.githubusercontent.com/unpacker1/browser2-local-dev/main"
if ! command -v curl >/dev/null || ! command -v python3 >/dev/null; then
  echo "[EKSIK] pkg install python curl" >&2; exit 3
fi
if python3 - <<'PY'
import socket
s=socket.socket();s.settimeout(0.4)
try:busy=s.connect_ex(('127.0.0.1',8986))==0
finally:s.close()
raise SystemExit(0 if busy else 1)
PY
then
  echo '[OYUN AÇIK] Eski Browser2 sunucusu 8986 portunda. ONCE eski Termux sunucu penceresinde Ctrl+C yap.' >&2
  echo '[KORUMA] Calisan oturuma/dosyaya dokunmadim.' >&2
  exit 4
fi
if [[ ! -f "$TARGET/native_v69.py" || ! -f "$TARGET/test_v69.py" ]]; then
  echo '[EKSIK] Orijinal V69 paketi bulunamadi. V82 ile kuruldugu dizini kontrol et.' >&2
  exit 5
fi
mkdir -p "$(dirname "$PATCH")"
curl -fLsS "$BASE/server/fix_native_npc_disconnect_v83.py" -o "$PATCH"
python3 "$PATCH" --source "$TARGET/native_v69.py" --check
python3 "$PATCH" --source "$TARGET/native_v69.py"
python3 -m py_compile "$TARGET/native_v69.py"
python3 "$TARGET/test_v69.py"
LAUNCHER="$HOME/start_browser2_all_v82.sh"
if [[ ! -f "$LAUNCHER" ]]; then
  curl -fLsS "$BASE/termux/start_browser2_all_v82.sh" -o "$LAUNCHER"
fi
echo '[V83] Native DB/AUTH/GAME ve orijinal Browser2 oyunu baslatiliyor.'
echo '[OYUN] http://127.0.0.1:8986/__native__/play'
exec bash "$LAUNCHER"
