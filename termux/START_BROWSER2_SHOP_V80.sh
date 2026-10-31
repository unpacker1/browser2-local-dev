#!/data/data/com.termux/files/usr/bin/bash
# Separate localhost SQL test. Existing native AUTH/GAME/DB untouched.
set -euo pipefail
ROOT="${HOME}/browser2-local-dev"
if [[ ! -f "$ROOT/server/browser2_wiki_shop_v80.py" ]]; then
  echo '[GITHUB] Repository checkout/update';
  if [[ -d "$ROOT/.git" ]]; then git -C "$ROOT" pull --ff-only origin main;
  else git clone --depth=1 https://github.com/unpacker1/browser2-local-dev.git "$ROOT"; fi
else
  git -C "$ROOT" pull --ff-only origin main
fi
PY="$ROOT/server/browser2_wiki_shop_v80.py"
TEST="$ROOT/server/test_browser2_wiki_shop_v80.py"
python3 -m py_compile "$PY" "$TEST"
(cd "$ROOT/server" && python3 -m unittest -q test_browser2_wiki_shop_v80.py)
DB="$HOME/BROWSER2_LOCAL_SERVER_DATA/wiki_shop_v80_ISOLATED.sqlite3"
DL="$HOME/storage/downloads"
if [[ -f "$DL/v70_wiki_shop_catalog.sqlite3" ]]; then SOURCE="$DL/v70_wiki_shop_catalog.sqlite3"
elif [[ -f "$DL/v70_catalog.json" ]]; then SOURCE="$DL/v70_catalog.json"
else
  echo '[EKSIK] v70_wiki_shop_catalog.sqlite3 veya v70_catalog.json Downloads klasorunde bulunamadi.'
  echo 'GitHub Actions sadece kodu test eder; orijinal wiki katalogu public repoda yayinlanmiyor.'
  exit 3
fi
python3 "$PY" import --source "$SOURCE" --db "$DB"
python3 "$PY" audit-native --db "$DB" || true
echo '[TEST] http://127.0.0.1:8990/__local__/shop-test'
exec python3 "$PY" serve --db "$DB" --port 8990