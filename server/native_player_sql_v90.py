#!/usr/bin/env python3
"""Read-only, identity-verified native SQLite player snapshot for V28 rendering.

This is not the native GAME live inventory stream. Never authorizes moves,
spends, shop buys, sells or writes to player/item/account data.
"""
from __future__ import annotations
from contextlib import closing
from pathlib import Path
import re
import sqlite3

BAG_CAPACITY = 180  # Browser2 four bag pages of 45 slots
MAX_GOLD = (1 << 63) - 1
MAX_ITEM_VNUM = 100_000_000
MAX_ITEM_COUNT = 2_000_000_000
MAX_ROWS = 2500
LOGIN = re.compile(r'^[a-z0-9]{2,30}$')


def _open(directory: Path, name: str):
    path = directory / (name + '.sqlite3')
    if not path.is_file() or path.is_symlink():
        raise ValueError('native_sql_missing')
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
    db.execute('PRAGMA query_only=ON')
    db.execute('PRAGMA busy_timeout=1000')
    return db


def _cols(db, table):
    # table is fixed caller-controlled constant, not user input.
    return {r[1] for r in db.execute('PRAGMA table_info(' + table + ')')}


def player_state(directory, login, player_id):
    """Return only current login's own player gold and inventory snapshot.

    No data is ever projected if account+player ownership cannot be proven.
    `bag` is None on unknown inventory schema; no invented empty bag.
    Native Metin2 INVENTORY window is 1; alternate text 'INVENTORY' allowed.
    Other windows, including EQUIPMENT, are not projected before ABI proof.
    """
    result = {'status': 'not_verified', 'gold': None, 'bag': None,
              'itemCount': 0, 'unmappedWindowRows': 0,
              'source': 'native_player_sqlite_readonly'}
    if (not isinstance(login, str) or LOGIN.fullmatch(login) is None or
        type(player_id) is not int or not 1 <= player_id < 2**63):
        return {**result, 'status': 'invalid_identity'}
    directory = Path(directory)
    if not directory.is_dir() or directory.is_symlink():
        return {**result, 'status': 'sql_folder_unavailable'}
    try:
        with closing(_open(directory, 'account')) as a:
            if not {'id', 'login'} <= _cols(a, 'account'):
                return {**result, 'status': 'account_schema_unverified'}
            owners = a.execute('SELECT id FROM account WHERE login=? LIMIT 2', (login,)).fetchall()
            if len(owners) != 1 or type(owners[0][0]) is not int or owners[0][0] <= 0:
                return {**result, 'status': 'account_not_verified'}
            account_id = owners[0][0]
        with closing(_open(directory, 'player')) as p:
            if not {'id', 'account_id'} <= _cols(p, 'player'):
                return {**result, 'status': 'player_schema_unverified'}
            columns = _cols(p, 'player')
            has_gold = 'gold' in columns
            selected = 'id,account_id,gold' if has_gold else 'id,account_id'
            rows = p.execute('SELECT ' + selected + ' FROM player WHERE id=? AND account_id=? LIMIT 2',
                             (player_id, account_id)).fetchall()
            if len(rows) != 1:
                return {**result, 'status': 'player_owner_mismatch'}
            gold = rows[0][2] if has_gold else None
            if gold is not None and (type(gold) is not int or not 0 <= gold <= MAX_GOLD):
                return {**result, 'status': 'player_gold_invalid'}
            result['gold'] = gold
            if not {'id', 'owner_id', 'vnum', 'count', 'window', 'pos'} <= _cols(p, 'item'):
                return {**result, 'status': 'item_schema_unverified'}
            # Only current verified character's rows; LIMIT bounds resource usage.
            items = p.execute(
                'SELECT id,vnum,count,window,pos FROM item WHERE owner_id=? ORDER BY id LIMIT ?',
                (player_id, MAX_ROWS + 1)).fetchall()
            if len(items) > MAX_ROWS:
                return {**result, 'status': 'item_row_limit'}
            bag = [None] * BAG_CAPACITY
            unmapped = 0
            mapped = 0
            seen_ids = set()
            for uid, vnum, count, window, pos in items:
                if (type(uid) is not int or not 0 < uid < 2**63 or uid in seen_ids or
                    type(vnum) is not int or not 0 < vnum <= MAX_ITEM_VNUM or
                    type(count) is not int or not 0 < count <= MAX_ITEM_COUNT):
                    return {**result, 'status': 'item_values_invalid'}
                seen_ids.add(uid)
                if window in (1, 'INVENTORY'):
                    if type(pos) is not int or not 0 <= pos < BAG_CAPACITY or bag[pos] is not None:
                        return {**result, 'status': 'bag_position_invalid'}
                    bag[pos] = {'uid': str(uid), 'templateId': 'v2_' + str(vnum), 'quantity': count}
                    mapped += 1
                else:
                    unmapped += 1  # Never guess equipment, belt, soul windows.
            result.update(status='sql_inventory_snapshot', bag=bag,
                          itemCount=mapped, unmappedWindowRows=unmapped)
            return result
    except (sqlite3.Error, OSError, ValueError, TypeError, OverflowError):
        return {**result, 'status': 'native_sql_read_failed', 'gold': None, 'bag': None}