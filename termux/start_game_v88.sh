#!/data/data/com.termux/files/usr/bin/bash
# V88: original unmodified Browser2 V28 shopdialog, no HTML overlay.
# Native game DB/AUTH/GAME and player SQLite unchanged. BUY intentionally blocked.
set -euo pipefail
BASE='https://raw.githubusercontent.com/unpacker1/browser2-local-dev/main'
SRC="$HOME/CEMREEFE_BROWSER2_V87_NPC_NAMES"
DST="$HOME/CEMREEFE_BROWSER2_V88_ORIGINAL_SHOP"
V82="$HOME/start_browser2_all_v82.sh"
GAME_URL='http://127.0.0.1:8986/__native__/play'
command -v curl >/dev/null || { echo '[EKSIK] pkg install curl' >&2;exit 3; }
command -v python3 >/dev/null || { echo '[EKSIK] pkg install python' >&2;exit 3; }
if python3 - <<'PY'
import socket
s=socket.socket();s.settimeout(.5)
try: busy=s.connect_ex(('127.0.0.1',8986))==0
finally:s.close()
raise SystemExit(0 if busy else 1)
PY
then
 echo '[DURDUR] 8986 acik: oyun sunucusunun Termux penceresinde Ctrl+C yap. Acik servise dokunmadim.' >&2
 exit 4
fi
for f in native_v69.py native_shop_catalog_v69.py test_v69.py native_npc_ui_v86.py;do
 if [[ ! -f "$SRC/$f" || -L "$SRC/$f" ]];then echo "[EKSIK] V87 dosyasi: $SRC/$f" >&2;exit 5;fi
done
if [[ -L "$DST" ]];then echo '[HATA] V88 hedef sembolik bag; durduruldu' >&2;exit 5;fi
mkdir -p "$DST"
if [[ ! -f "$DST/native_v69.py" ]];then
 for f in native_shop_catalog_v69.py test_v69.py native_npc_ui_v86.py;do cp "$SRC/$f" "$DST/$f";done
 curl -fLsS "$BASE/server/original_shop_v88.py" -o "$DST/original_shop_v88.py"
 curl -fLsS "$BASE/server/patch_v88_original_window.py" -o "$DST/patch_v88_original_window.py"
 python3 "$DST/patch_v88_original_window.py" --source "$SRC/native_v69.py" --dest "$DST/native_v69.py"
else
 grep -Fq '# V88_ORIGINAL_V28_SHOPDIALOG_SOURCE_LOCKED' "$DST/native_v69.py" || { echo '[HATA] Mevcut V88 dosyasi farkli; durduruldu' >&2;exit 6; }
fi
python3 -m py_compile "$DST/native_v69.py" "$DST/original_shop_v88.py"
(
 cd "$DST"
 python3 native_v69.py --selftest
 python3 test_v69.py
)
cat > "$DST/RUN_TERMUX.sh" <<'RUN'
#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
cd "$HOME/CEMREEFE_BROWSER2_V88_ORIGINAL_SHOP"
python3 native_v69.py --preflight
exec python3 native_v69.py --port 8986 --self-spawn-mode single
RUN
if [[ ! -f "$V82" ]];then curl -fLsS "$BASE/termux/start_browser2_all_v82.sh" -o "$V82";fi
python3 - "$V82" "$DST/START_NATIVE_V88.sh" <<'PY'
from pathlib import Path
import sys
source=Path(sys.argv[1]).read_text('utf-8')
a='V69="$HOME/CEMREEFE_BROWSER2_V69_NATIVE_SHOP_CATALOG"'
b='V69="$HOME/CEMREEFE_BROWSER2_V88_ORIGINAL_SHOP"'
if source.count(a)!=1 or 'native_runtime_start.py' not in source:raise SystemExit('[HATA] V82 baslatici degisti, guvenli degil')
Path(sys.argv[2]).write_text(source.replace(a,b,1),encoding='utf-8')
PY
echo '[V88] Orijinal Browser2 V28 NPC SHOPDIALOG. Uydurma HTML paneli yok.'
echo '[DIKKAT] SQL kaynak stok önizlemesi; GAME fiyatı yok, bütün satırlar KILITLI, alışveriş yok.'
echo "[OYUN] $GAME_URL"
exec bash "$DST/START_NATIVE_V88.sh"