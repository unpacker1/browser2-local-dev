#!/data/data/com.termux/files/usr/bin/bash
# V90: Native ACCOUNT->PLAYER ownership-checked SQL gold/inventory display.
# Native binaries, SQL, original JS/WASM/models, V89 folder remain UNCHANGED.
set -euo pipefail
BASE='https://raw.githubusercontent.com/unpacker1/browser2-local-dev/main'
SRC="$HOME/CEMREEFE_BROWSER2_V89_ORIGINAL_ITEMS"
DST="$HOME/CEMREEFE_BROWSER2_V90_NATIVE_INVENTORY"
V82="$HOME/start_browser2_all_v82.sh"
URL='http://127.0.0.1:8986/__native__/play'
command -v curl >/dev/null && command -v python3 >/dev/null || { echo '[EKSIK] pkg install python curl' >&2;exit 3; }
if python3 - <<'PY'
import socket
s=socket.socket();s.settimeout(.5)
try: busy=s.connect_ex(('127.0.0.1',8986))==0
finally: s.close()
raise SystemExit(0 if busy else 1)
PY
then
  echo '[DURDUR] Eski oyun sunucusu 8986 portunda. Eski Termux penceresinde Ctrl+C yap.' >&2
  echo '[KORUMA] Calisan native servis, karakter veya SQLite degistirilmedi.' >&2
  exit 4
fi
if [[ -L "$SRC" || -L "$DST" ]];then echo '[HATA] Symlink kaynak/hedef reddedildi' >&2; exit 5;fi
for f in native_v69.py original_shop_v88.py native_shop_catalog_v69.py native_npc_ui_v86.py test_v69.py;do
  if [[ ! -f "$SRC/$f" || -L "$SRC/$f" ]];then echo "[EKSIK] V89 gerekli: $SRC/$f" >&2; exit 5;fi
done
mkdir -p "$DST"
if [[ ! -f "$DST/native_v69.py" ]];then
  for f in original_shop_v88.py native_shop_catalog_v69.py native_npc_ui_v86.py test_v69.py;do cp "$SRC/$f" "$DST/$f";done
  curl -fLsS "$BASE/server/native_player_sql_v90.py" -o "$DST/native_player_sql_v90.py"
  curl -fLsS "$BASE/server/patch_native_player_v90.py" -o "$DST/patch_native_player_v90.py"
  python3 "$DST/patch_native_player_v90.py" --source "$SRC/native_v69.py" --dest "$DST/native_v69.py"
else
  grep -Fq 'V90_OWNER_VERIFIED_READONLY_NATIVE_PLAYER_STATE' "$DST/native_v69.py" || { echo '[HATA] V90 local source verification failed' >&2; exit 6; }
  [[ -f "$DST/native_player_sql_v90.py" ]] || { echo '[HATA] V90 SQL module missing' >&2;exit 6; }
fi
python3 -m py_compile "$DST/native_v69.py" "$DST/native_player_sql_v90.py" "$DST/original_shop_v88.py"
(
  cd "$DST"
  python3 native_v69.py --selftest
  python3 test_v69.py
)
cat > "$DST/RUN_TERMUX.sh" <<'RUN'
#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
cd "$HOME/CEMREEFE_BROWSER2_V90_NATIVE_INVENTORY"
python3 native_v69.py --preflight
exec python3 native_v69.py --port 8986 --self-spawn-mode single
RUN
if [[ ! -f "$V82" ]];then curl -fLsS "$BASE/termux/start_browser2_all_v82.sh" -o "$V82";fi
python3 - "$V82" "$DST/START_NATIVE_V90.sh" <<'PY'
from pathlib import Path
import sys
source=Path(sys.argv[1]).read_text('utf-8')
a='V69="$HOME/CEMREEFE_BROWSER2_V69_NATIVE_SHOP_CATALOG"'
b='V69="$HOME/CEMREEFE_BROWSER2_V90_NATIVE_INVENTORY"'
if source.count(a)!=1 or 'native_runtime_start.py' not in source:
    raise SystemExit('[HATA] V82 launcher source changed, refusing')
Path(sys.argv[2]).write_text(source.replace(a,b,1),encoding='utf-8')
PY
echo '[V90] Original NPC shop remains; read-only native account/SQL inventory and Yang projection enabled when schema verifies.'
echo '[DURUM] http://127.0.0.1:8986/__native__/status'
echo '[SINIR] Inventory is a SQLite snapshot; native GAME purchase, movement, SELL/BUY remain UNIMPLEMENTED.'
echo "[OYUN] $URL"
exec bash "$DST/START_NATIVE_V90.sh"