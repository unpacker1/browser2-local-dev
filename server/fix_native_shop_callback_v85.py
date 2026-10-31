#!/usr/bin/env python3
"""Exact-source hotfix for the V84 isolated Browser2 native bridge.

Corrects the verified NameError at native_v69.py line 1015.  It deliberately
*does not* fabricate a V28 shop frame, purchase, or native GAME acknowledgement.
Original V69, native AUTH/GAME, assets and player SQLite are never modified.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import os
from pathlib import Path
import shutil
import tempfile

EXPECTED_SHA256 = '60534762106319228bf12b9045d45bfe341bd1909d7f567ba794029cc3165960'
TARGET_LINE = 1015
CALL = '__v80_shop_from_native_event(ws, bridge, last_clicked_npc_vnum)'
MARKER = '# V85: undefined V80 preview is optional'



def patch_text(source: str, expected_hash: str = EXPECTED_SHA256) -> tuple[str, str]:
    """Fail closed on any source variation. Only the offending call is replaced."""
    if MARKER in source:
        compile(source, 'native_v69.py', 'exec')
        return source, 'already_patched'
    sha = hashlib.sha256(source.encode('utf-8')).hexdigest()
    if sha != expected_hash:
        raise ValueError(f'V84 source SHA differs; expected {expected_hash[:12]}..., got {sha[:12]}...')
    lines = source.splitlines()
    if len(lines) < TARGET_LINE or lines[TARGET_LINE - 1].strip() != CALL:
        raise ValueError('V84 line 1015 differs from verified NameError call')
    if source.count(CALL) != 1:
        raise ValueError('Expected only one undefined V80 callback call')
    if "bridge.last_optional_event_kind='source_shop_lookup'" not in source:
        raise ValueError('Expected V84 diagnostics are missing')
    try:
        ast.parse(source)
        line = lines[TARGET_LINE-1]
        indent = line[:len(line)-len(line.lstrip())]
        replacement = '\n'.join((
            indent + MARKER,
            indent + "bridge.metrics['v85_missing_shop_preview_skipped'] += 1",
            indent + "bridge.last_optional_event_kind = 'v80_shop_preview_not_installed'",
            indent + "bridge.last_optional_event_type = 'missing_callback'",
        ))
        updated = source.replace(line, replacement, 1)
        ast.parse(updated)
        compile(updated, 'native_v69.py', 'exec')
    except (SyntaxError, ValueError) as exc:
        raise ValueError('Original or patched script cannot compile') from exc
    return updated, 'patched'


def main():
    p = argparse.ArgumentParser(description='V85 exact-source NameError correction')
    p.add_argument('--source', type=Path,
                   default=Path.home() / 'CEMREEFE_BROWSER2_V84_SAFE_LAB/native_v69.py')
    p.add_argument('--check', action='store_true')
    args = p.parse_args()
    path = args.source.expanduser()
    if not path.is_file() or path.is_symlink():
        p.error('V84 isolated native_v69.py missing or is symlink')
    try:
        original = path.read_text('utf-8')
        modified, status = patch_text(original)
    except (OSError, UnicodeError, ValueError) as exc:
        p.error(str(exc))
    if args.check:
        print('[V85 CHECK]', status, 'source contract and Python syntax OK')
        return
    if status == 'already_patched':
        print('[V85] Already corrected. No files changed.')
        return
    backup = path.with_suffix('.py.V85_ORIGINAL_BACKUP')
    if backup.exists():
        p.error('V85 backup already exists; no files modified')
    # Fail rather than modify the native source when file changed since verification.
    if hashlib.sha256(path.read_bytes()).hexdigest() != EXPECTED_SHA256:
        p.error('V84 file changed during verification; no modifications made')
    shutil.copy2(path, backup)
    fd, tmpname = tempfile.mkstemp(prefix='.native_v69_v85_', suffix='.py', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(modified)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmpname, path.stat().st_mode)
        # The running GAME bridge must be restarted for the patch to take effect.
        os.replace(tmpname, path)
    finally:
        if os.path.exists(tmpname):
            os.unlink(tmpname)
    print('[V85 FIX] Undefined V80 shop callback safely disabled in isolated V84 bridge')
    print('[BACKUP]', backup)
    print('[UNCHANGED] Native AUTH/GAME/DB, player SQLite, original V69 source and client')
    print('[LIMIT] Native GAME shop BUY/SELL and V28 shop UI remain unimplemented')


if __name__ == '__main__':
    main()