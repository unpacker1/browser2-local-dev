#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
B2="$HOME/storage/downloads/BROWSER2_BAGIMSIZ"
DEST="$B2/TESTLER"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="$B2/GITHUB_PUBLIC/BACKUPS/$STAMP"
mkdir -p "$DEST" "$BACKUP"
for f in "$REPO"/server/*.py; do
  name="$(basename "$f")"
  [[ -f "$DEST/$name" ]] && cp -p "$DEST/$name" "$BACKUP/$name"
  cp -p "$f" "$DEST/$name"
done
printf '[OK] Sunucu betikleri güncellendi. Yedek: %s\n' "$BACKUP"
printf '[GUVENLIK] public_assets ve sqlite veritabanina dokunulmadi.\n'
