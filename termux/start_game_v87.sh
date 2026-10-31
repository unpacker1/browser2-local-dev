#!/data/data/com.termux/files/usr/bin/bash
# V87: preserve original V86, native DB AUTH GAME + original Browser2 client.
set -euo pipefail
BASE='https://raw.githubusercontent.com/unpacker1/browser2-local-dev/main'
SRC="$HOME/CEMREEFE_BROWSER2_V86_NPC_UI"
DST="$HOME/CEMREEFE_BROWSER2_V87_NPC_NAMES"
PORT=8986
if ! command -v curl >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1; then
 echo '[EKSIK] pkg install python curl' >&2; exit 3
fi
if python3 - <<'PY'
import socket
s=socket.socket();s.settimeout(.4)
try:busy=s.connect_ex(('127.0.0.1',8986))==0
finally:s.close()
raise SystemExit(0 if busy else 1)
PY
then
 echo '[DURDUR] Eski Termux sunucu oturumunda Ctrl+C yap; acik sunucuyu durdurmadim.' >&2
 exit 4
fi
if [[ -L "$SRC" || -L "$DST" ]]; then echo '[HATA] Sembolik bag reddedildi.' >&2;exit 5;fi
for f in native_v69.py native_shop_catalog_v69.py test_v69.py; do
 [[ -f "$SRC/$f" && ! -L "$SRC/$f" ]] || { echo "[EKSIK] $SRC/$f" >&2;exit 5; }
done
# Confirm the V86 bridge was actually installed. Do not patch arbitrary Python.
if ! grep -Fq '# V86: authenticated read-only NPC game overlay' "$SRC/native_v69.py";then
 echo '[HATA] V86 oyun dosyasi beklenen kaynak degil; degisiklik yapilmadi.' >&2;exit 6
fi
mkdir -p "$DST"
if [[ ! -f "$DST/native_v69.py" ]];then
 cp "$SRC/native_v69.py" "$DST/native_v69.py"
 cp "$SRC/native_shop_catalog_v69.py" "$DST/native_shop_catalog_v69.py"
 cp "$SRC/test_v69.py" "$DST/test_v69.py"
else
 grep -Fq '# V86: authenticated read-only NPC game overlay' "$DST/native_v69.py" || { echo '[HATA] Onceki V87 kopyasi farkli.' >&2;exit 6; }
fi
curl -fLsS "$BASE/server/native_npc_ui_v87.py" -o "$DST/native_npc_ui_v86.py"
python3 -m py_compile "$DST/native_v69.py" "$DST/native_npc_ui_v86.py" "$DST/native_shop_catalog_v69.py"
(
 cd "$DST"
 python3 native_v69.py --selftest
 python3 test_v69.py
)
cat > "$DST/RUN_TERMUX.sh" <<'RUN'
#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
cd "$HOME/CEMREEFE_BROWSER2_V87_NPC_NAMES"
python3 native_v69.py --preflight
exec python3 native_v69.py --port 8986 --self-spawn-mode single
RUN
V82="$HOME/start_browser2_all_v82.sh"
if [[ ! -f "$V82" ]];then curl -fLsS "$BASE/termux/start_browser2_all_v82.sh" -o "$V82";fi
python3 - "$V82" "$DST/START_NATIVE_V87.sh" <<'PY'
from pathlib import Path
import sys
source=Path(sys.argv[1]).read_text('utf-8')
old='V69="$HOME/CEMREEFE_BROWSER2_V69_NATIVE_SHOP_CATALOG"'
new='V69="$HOME/CEMREEFE_BROWSER2_V87_NPC_NAMES"'
if source.count(old)!=1 or 'native_runtime_start.py' not in source:
 raise SystemExit('[HATA] V82 baslaticisi beklenen yapida degil.')
Path(sys.argv[2]).write_text(source.replace(old,new,1),encoding='utf-8')
PY
echo '[V87] Gercek Cemre Efe DB/AUTH/GAME ve Browser2 baslatiliyor.'
echo '[NPC] Native item_proto adlari, SQL shop satirlari ve varsa AYRI wiki karsilastirmasi.'
echo '[UYARI] GAME BUY/SELL ve QUEST ANSWER henuz aktif degildir.'
echo '[OYUN] http://127.0.0.1:8986/__native__/play'
exec bash "$DST/START_NATIVE_V87.sh"