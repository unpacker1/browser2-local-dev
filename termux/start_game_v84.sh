#!/data/data/com.termux/files/usr/bin/bash
# V84: isolated optional-NPC bridge recovery. Original native GAME/SQL untouched.
set -euo pipefail
BASE='https://raw.githubusercontent.com/unpacker1/browser2-local-dev/main'
SRC="$HOME/CEMREEFE_BROWSER2_V69_NATIVE_SHOP_CATALOG"
DST="$HOME/CEMREEFE_BROWSER2_V84_SAFE_LAB"
ZIP="$HOME/storage/downloads/CEMREEFE_BROWSER2_V69_NATIVE_SHOP_CATALOG.zip"
GAME='http://127.0.0.1:8986/__native__/play'
command -v python3 >/dev/null || { echo '[EKSIK] pkg install python' >&2; exit 3; }
command -v curl >/dev/null || { echo '[EKSIK] pkg install curl' >&2; exit 3; }
command -v unzip >/dev/null || { echo '[EKSIK] pkg install unzip' >&2; exit 3; }
if python3 - <<'PY'
import socket
s=socket.socket();s.settimeout(.5)
try: busy=s.connect_ex(('127.0.0.1',8986))==0
finally:s.close()
raise SystemExit(0 if busy else 1)
PY
then
  echo '[PORT 8986 AÇIK] V82/V69 tarayici servisini baslattigin Termux oturumunda Ctrl+C yap.' >&2
  echo '[KORUMA] Acik servise veya yerel SQL dosyalarina dokunulmadi.' >&2
  exit 4
fi
if [[ ! -f "$SRC/native_v69.py" || ! -f "$SRC/native_shop_catalog_v69.py" || ! -f "$SRC/test_v69.py" ]]; then
  if [[ -f "$ZIP" ]]; then
    echo '[V84] Orijinal V69 arşivi yerel Downloads dosyasından açılıyor.'
    unzip -nq "$ZIP" -d "$HOME"
  fi
fi
for name in native_v69.py native_shop_catalog_v69.py test_v69.py; do
  if [[ ! -f "$SRC/$name" || -L "$SRC/$name" ]]; then
    echo "[EKSIK] Güvenilir V69 kaynak dosyası: $SRC/$name" >&2
    exit 5
  fi
done
if [[ -L "$DST" ]]; then
  echo '[HATA] Izole V84 hedefi sembolik bag; durduruldu.' >&2; exit 6
fi
mkdir -p "$DST"
# Copy just the 2 supporting Python files. The main bridge gets source-checked and patched separately.
for name in native_shop_catalog_v69.py test_v69.py; do
  cp "$SRC/$name" "$DST/$name"
done
curl -fLsS "$BASE/server/native_shop_bridge_guard_v84.py" -o "$DST/native_shop_bridge_guard_v84.py"
python3 "$DST/native_shop_bridge_guard_v84.py" --source "$SRC/native_v69.py" --destination "$DST/native_v69.py"
python3 -m py_compile "$DST/native_v69.py" "$DST/native_shop_catalog_v69.py"
(
  cd "$DST"
  python3 native_v69.py --selftest
  python3 test_v69.py
)
cat > "$DST/RUN_TERMUX.sh" <<'RUN'
#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
cd "$HOME/CEMREEFE_BROWSER2_V84_SAFE_LAB"
python3 native_v69.py --selftest
python3 test_v69.py
python3 native_v69.py --preflight
exec python3 native_v69.py --port 8986 --self-spawn-mode single
RUN
# Use the existing verified V82 orchestrator, but point it to our isolated copy.
V82="$HOME/start_browser2_all_v82.sh"
if [[ ! -f "$V82" ]]; then
  curl -fLsS "$BASE/termux/start_browser2_all_v82.sh" -o "$V82"
fi
python3 - "$V82" "$DST/START_NATIVE_V84.sh" <<'PY'
from pathlib import Path
import sys
src=Path(sys.argv[1]).read_text('utf-8')
old='V69="$HOME/CEMREEFE_BROWSER2_V69_NATIVE_SHOP_CATALOG"'
new='V69="$HOME/CEMREEFE_BROWSER2_V84_SAFE_LAB"'
if src.count(old)!=1 or 'native_runtime_start.py' not in src or 'port 8986' not in src.lower() and '8986' not in src:
    raise SystemExit('[HATA] Orijinal V82 başlatıcısı değişmiş; otomatik uyarlama güvenli değil.')
dst=Path(sys.argv[2])
dst.write_text(src.replace(old,new,1),encoding='utf-8')
PY
echo '[V84] Tüm native servisler ve ayrı V84 Browser2 oyunu açılıyor.'
echo "[OYUN] $GAME"
exec bash "$DST/START_NATIVE_V84.sh"