#!/usr/bin/env bash
# Native Browser2 GAME launcher; original client, AUTH/GAME and SQL unchanged.
set -euo pipefail
PORT=8986
URL="http://127.0.0.1:${PORT}/__native__/play"
SRC="$HOME/CEMREEFE_BROWSER2_V69_NATIVE_SHOP_CATALOG"
ARCHIVE="$HOME/storage/downloads/CEMREEFE_BROWSER2_V69_NATIVE_SHOP_CATALOG.zip"
echo "[GAME] $URL"
if ! command -v python3 >/dev/null 2>&1 || ! command -v curl >/dev/null 2>&1; then
  echo "[EKSIK] Termux: pkg install python curl" >&2
  exit 3
fi
if curl --noproxy '*' -fsS --max-time 3 "$URL" 2>/dev/null | grep -q 'Cemre Efe Native GAME'; then
  echo "[CALISIYOR] Chrome: $URL"
  echo "[DURUM] http://127.0.0.1:${PORT}/__native__/status"
  exit 0
fi
if python3 - "$PORT" <<'PY'
import socket,sys
s=socket.socket(); s.settimeout(.5)
try: code=s.connect_ex(('127.0.0.1',int(sys.argv[1])))
finally: s.close()
raise SystemExit(0 if code==0 else 1)
PY
then
  echo '[HATA] 8986 baska servis tarafindan kullaniliyor; kapatilmadi.' >&2
  exit 4
fi
if [[ ! -f "$SRC/native_v69.py" || ! -f "$SRC/RUN_TERMUX.sh" ]]; then
  if [[ -f "$ARCHIVE" ]]; then
    if ! command -v unzip >/dev/null 2>&1; then
      echo '[EKSIK] Termux: pkg install unzip' >&2
      exit 3
    fi
    unzip -oq "$ARCHIVE" -d "$HOME"
  fi
fi
if [[ ! -f "$SRC/native_v69.py" || ! -f "$SRC/RUN_TERMUX.sh" ]]; then
  echo "[EKSIK] Native oyun paketi bulunamadi: $SRC veya $ARCHIVE" >&2
  exit 5
fi
for p in "$HOME/CEMREEFE_NATIVE_STANDALONE" "$HOME/BROWSER2_V54_HARITALAR/browser2_v54_maps.py"; do
  if [[ ! -e "$p" ]]; then
    echo "[EKSIK] Native oyun bagimliligi: $p" >&2
    exit 6
  fi
done
echo "[OYUN] $URL"
echo "[DURUM] http://127.0.0.1:${PORT}/__native__/status"
echo '[UYARI] Native AUTH/GAME/DB calismali. Bu V69 oyunu V80 demo SQLite magazasi DEGIL.'
echo '[UYARI] Gercek GAME shop BUY/SELL entegrasyonu bu pakette henüz uygulanmadi.'
cd "$SRC"
exec bash "$SRC/RUN_TERMUX.sh"
