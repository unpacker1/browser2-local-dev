#!/data/data/com.termux/files/usr/bin/bash
# V86 isolated native NPC in-game SQL viewer. Does NOT implement purchases.
set -euo pipefail
BASE='https://raw.githubusercontent.com/unpacker1/browser2-local-dev/main'
SRC="$HOME/CEMREEFE_BROWSER2_V84_SAFE_LAB"
DST="$HOME/CEMREEFE_BROWSER2_V86_NPC_UI"
GAME='http://127.0.0.1:8986/__native__/play'
command -v python3 >/dev/null || { echo '[EKSIK] pkg install python' >&2; exit 3; }
command -v curl >/dev/null || { echo '[EKSIK] pkg install curl' >&2; exit 3; }
if python3 - <<'PY'
import socket
s=socket.socket();s.settimeout(.5)
try:ready=s.connect_ex(('127.0.0.1',8986))==0
finally:s.close()
raise SystemExit(0 if ready else 1)
PY
then
  echo '[DURDUR] Oyun sunucusunu actigin eski Termux penceresinde Ctrl+C yap.' >&2
  echo '[KORUMA] Sunucuya, DB ye, oyuncu SQL ine dokunmadim.' >&2
  exit 4
fi
if [[ -L "$DST" || -L "$SRC" ]]; then echo '[HATA] Symlink kaynak/hedef guvenli degil.' >&2;exit 5;fi
for f in native_v69.py native_shop_catalog_v69.py test_v69.py; do
  if [[ ! -f "$SRC/$f" || -L "$SRC/$f" ]];then
    echo "[EKSIK] V85 kurulu V84 kaynagi gerekli: $SRC/$f" >&2;exit 5
  fi
done
mkdir -p "$DST"
if [[ ! -f "$DST/native_v69.py" ]];then
  for f in native_shop_catalog_v69.py test_v69.py; do cp "$SRC/$f" "$DST/$f";done
  curl -fLsS "$BASE/server/native_npc_ui_v86.py" -o "$DST/native_npc_ui_v86.py"
  curl -fLsS "$BASE/server/patch_native_ui_v86.py" -o "$DST/patch_native_ui_v86.py"
  python3 "$DST/patch_native_ui_v86.py" --source "$SRC/native_v69.py" --destination "$DST/native_v69.py"
else
  echo '[V86] Once kurulmus izole oyun kodu tekrar kullaniliyor.'
  for f in native_npc_ui_v86.py native_shop_catalog_v69.py test_v69.py;do
    [[ -f "$DST/$f" ]] || { echo "[HATA] Eksik V86 dosyasi: $f" >&2;exit 6; }
  done
fi
python3 -m py_compile "$DST/native_v69.py" "$DST/native_npc_ui_v86.py" "$DST/native_shop_catalog_v69.py"
(
  cd "$DST"
  python3 native_v69.py --selftest
  python3 test_v69.py
)
cat > "$DST/RUN_TERMUX.sh" <<'RUN'
#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
cd "$HOME/CEMREEFE_BROWSER2_V86_NPC_UI"
python3 native_v69.py --preflight
exec python3 native_v69.py --port 8986 --self-spawn-mode single
RUN
V82="$HOME/start_browser2_all_v82.sh"
if [[ ! -f "$V82" ]];then
  curl -fLsS "$BASE/termux/start_browser2_all_v82.sh" -o "$V82"
fi
python3 - "$V82" "$DST/START_NATIVE_V86.sh" <<'PY'
from pathlib import Path
import sys
raw=Path(sys.argv[1]).read_text('utf-8')
a='V69="$HOME/CEMREEFE_BROWSER2_V69_NATIVE_SHOP_CATALOG"'
b='V69="$HOME/CEMREEFE_BROWSER2_V86_NPC_UI"'
if raw.count(a)!=1 or 'native_runtime_start.py' not in raw:
    raise SystemExit('[HATA] V82 baslaticisi degismis, guvenli uyarlama yapilmadi.')
Path(sys.argv[2]).write_text(raw.replace(a,b,1),'utf-8')
PY
echo '[V86] Gercek DB / AUTH / GAME ve Browser2 oyun baslatiliyor.'
echo '[NPC] Oyun ekraninda NPC tiklamasi -> read-only SQL paneli.'
echo '[SINIR] Native GAME BUY/SELL henuz desteklenmiyor.'
echo "[OYUN] $GAME"
exec bash "$DST/START_NATIVE_V86.sh"