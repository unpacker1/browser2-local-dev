#!/data/data/com.termux/files/usr/bin/bash
# V89 isolated V28 shop item ID fix. Native GAME/DB/SQL and original assets untouched.
set -euo pipefail
BASE='https://raw.githubusercontent.com/unpacker1/browser2-local-dev/main'
SRC="$HOME/CEMREEFE_BROWSER2_V88_ORIGINAL_SHOP"
DST="$HOME/CEMREEFE_BROWSER2_V89_ORIGINAL_ITEMS"
V82="$HOME/start_browser2_all_v82.sh"
URL='http://127.0.0.1:8986/__native__/play'
command -v curl >/dev/null && command -v python3 >/dev/null || { echo '[EKSIK] pkg install python curl' >&2;exit 3; }
if python3 - <<'PY'
import socket
s=socket.socket();s.settimeout(.5)
try:busy=s.connect_ex(('127.0.0.1',8986))==0
finally:s.close()
raise SystemExit(0 if busy else 1)
PY
then
 echo '[DURDUR] Once eski oyun Termux penceresinde Ctrl+C yap; calisan servise dokunulmaz.' >&2
 exit 4
fi
if [[ -L "$SRC" || -L "$DST" ]];then echo '[HATA] Symbolic links rejected' >&2;exit 5;fi
for f in native_v69.py original_shop_v88.py native_shop_catalog_v69.py native_npc_ui_v86.py test_v69.py;do
 [[ -f "$SRC/$f" && ! -L "$SRC/$f" ]] || { echo "[EKSIK] V88 source: $SRC/$f" >&2;exit 5; }
done
mkdir -p "$DST"
if [[ ! -f "$DST/original_shop_v88.py" ]];then
 for f in native_v69.py native_shop_catalog_v69.py native_npc_ui_v86.py test_v69.py;do cp "$SRC/$f" "$DST/$f";done
 curl -fLsS "$BASE/server/patch_shop_template_v89.py" -o "$DST/patch_shop_template_v89.py"
 python3 "$DST/patch_shop_template_v89.py" --source "$SRC/original_shop_v88.py" --dest "$DST/original_shop_v88.py"
else
 grep -Fq 'V89_VERIFIED_ORIGINAL_V28_ITEM_TEMPLATE_IDS' "$DST/original_shop_v88.py" || { echo '[HATA] V89 isolated source not verified' >&2;exit 6; }
fi
python3 -m py_compile "$DST/native_v69.py" "$DST/original_shop_v88.py" "$DST/native_shop_catalog_v69.py"
(
 cd "$DST"
 python3 native_v69.py --selftest
 python3 test_v69.py
)
cat > "$DST/RUN_TERMUX.sh" <<'RUN'
#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
cd "$HOME/CEMREEFE_BROWSER2_V89_ORIGINAL_ITEMS"
python3 native_v69.py --preflight
exec python3 native_v69.py --port 8986 --self-spawn-mode single
RUN
if [[ ! -f "$V82" ]];then curl -fLsS "$BASE/termux/start_browser2_all_v82.sh" -o "$V82";fi
python3 - "$V82" "$DST/START_NATIVE_V89.sh" <<'PY'
from pathlib import Path
import sys
source=Path(sys.argv[1]).read_text('utf-8')
a='V69="$HOME/CEMREEFE_BROWSER2_V69_NATIVE_SHOP_CATALOG"'
b='V69="$HOME/CEMREEFE_BROWSER2_V89_ORIGINAL_ITEMS"'
if source.count(a)!=1 or 'native_runtime_start.py' not in source:raise SystemExit('[HATA] V82 launcher source changed; refusing')
Path(sys.argv[2]).write_text(source.replace(a,b,1),'utf-8')
PY
echo '[V89] Original Browser2 NPC Shop with v2_ item template IDs.'
echo '[SINIR] Native inventory, Yang, live GAME price, BUY/SELL still NOT implemented.'
echo "[OYUN] $URL"
exec bash "$DST/START_NATIVE_V89.sh"
