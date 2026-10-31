#!/data/data/com.termux/files/usr/bin/bash
# Targeted fix for verified V84 NameError at native_v69.py:1015.
# Original V69 and native SQL/GAME/AUTH/DB are not changed.
set -euo pipefail
LAB="$HOME/CEMREEFE_BROWSER2_V84_SAFE_LAB"
FIX="$LAB/fix_native_shop_callback_v85.py"
URL='http://127.0.0.1:8986/__native__/play'
RAW='https://raw.githubusercontent.com/unpacker1/browser2-local-dev/main/server/fix_native_shop_callback_v85.py'
command -v curl >/dev/null 2>&1 || { echo '[EKSIK] Termux: pkg install curl' >&2; exit 3; }
command -v python3 >/dev/null 2>&1 || { echo '[EKSIK] Termux: pkg install python' >&2; exit 3; }
if [[ ! -f "$LAB/native_v69.py" || ! -f "$LAB/START_NATIVE_V84.sh" ]]; then
  echo '[HATA] V84 izole oyun klasoru bulunamadi; hicbir dosya degismedi.' >&2
  exit 4
fi
if python3 - <<'PY'
import socket
s=socket.socket();s.settimeout(.5)
try: busy=(s.connect_ex(('127.0.0.1',8986))==0)
finally: s.close()
raise SystemExit(0 if busy else 1)
PY
then
  echo '[HATA] 8986 portunda oyun acik. Once oyunu baslattigin Termux penceresinde Ctrl+C yap.' >&2
  echo '[KORUMA] Acik oyuna, SQL dosyalarina veya native GAME servisine dokunulmadi.' >&2
  exit 5
fi
curl -fLsS "$RAW" -o "$FIX"
python3 "$FIX" --source "$LAB/native_v69.py" --check
python3 "$FIX" --source "$LAB/native_v69.py"
python3 -m py_compile "$LAB/native_v69.py"
echo '[V85] NPC kopmasina neden olan eksik fonksiyon cagrisi korumali hale getirildi.'
echo '[NOT] V28 gercek magazayi acma ve native BUY/SELL henuz etkin degil.'
echo "[OYUN] $URL"
exec bash "$LAB/START_NATIVE_V84.sh"