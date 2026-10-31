#!/usr/bin/env python3
"""Build a separate V88 copy from the known V87 native bridge. Never patch in-place."""
import argparse
import ast
import os
from pathlib import Path
import tempfile

MARK='# V88_ORIGINAL_V28_SHOPDIALOG_SOURCE_LOCKED'
PREV='# V86: authenticated read-only NPC game overlay'
OLD_INJECT="PLAY_HTML.replace('__ORIGINAL_AUTH_MODULE__','/assets/'+auth_module).replace('</html>',npcui.PLAY_EXTRA+'</html>').encode('utf-8')"
NEW_INJECT="PLAY_HTML.replace('__ORIGINAL_AUTH_MODULE__','/assets/'+auth_module).encode('utf-8')"
CATALOG_CALL="npcui.clicked(bridge,user['login'],last_clicked_npc_vnum,bridge.native_shop_last)"


def transform(s):
    if MARK in s:
        compile(s,'native_v69.py','exec');return s
    if PREV not in s or '# V85: undefined V80 preview is optional' not in s:
        raise ValueError('V87 bridge source contract missing, refusing unsafe patch')
    if s.count(OLD_INJECT)!=1 or s.count(CATALOG_CALL)!=1:
        raise ValueError('V87 original HTML and native shop-click source markers did not match')
    source_import='import native_npc_ui_v86 as npcui\n'
    if s.count(source_import)!=1:raise ValueError('V87 module import does not match')
    s=s.replace(source_import,source_import+'import original_shop_v88 as originalshop\n',1)
    # Revert only V86 injected HTML panel, preserving original game's iframe/JS.
    s=s.replace(OLD_INJECT,NEW_INJECT,1)
    # The trusted native VID -> VNUM and read-only SQLite lookup have already run.
    # The native helper CLICK was transmitted first. Never synthesize a native GAME ACK.
    line=next((a for a in s.splitlines(keepends=True) if CATALOG_CALL in a),None)
    if line is None or line.strip()!=CATALOG_CALL:raise ValueError('V87 NPC call changed')
    indent=line[:len(line)-len(line.lstrip())]
    extra=''.join([
        indent+MARK+'\n',
        indent+'for original_v28_frame in originalshop.frames(last_clicked_npc_vnum,bridge.native_shop_last):\n',
        indent+'    ws.send(original_v28_frame)\n',
        indent+"    bridge.metrics['v88_original_shop_push_sent'] += 1\n",
    ])
    s=s.replace(line,line+extra,1)
    ast.parse(s);compile(s,'native_v69.py','exec')
    return s


def main():
    a=argparse.ArgumentParser()
    a.add_argument('--source',required=True,type=Path)
    a.add_argument('--dest',required=True,type=Path)
    args=a.parse_args()
    src=args.source.expanduser();dst=args.dest.expanduser()
    if src.is_symlink() or not src.is_file() or dst.is_symlink() or src.resolve()==dst.resolve():
        a.error('Invalid source or destination symlink/overlap')
    text=src.read_text('utf-8')
    try:new=transform(text)
    except (ValueError,SyntaxError) as ex:a.error(str(ex))
    if dst.exists():a.error('Destination already exists: refuses overwrite')
    dst.parent.mkdir(parents=True,exist_ok=True)
    fd,temporary=tempfile.mkstemp(prefix='.native_v88_',suffix='.py',dir=dst.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(new)
        os.replace(temporary,dst)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)
    print('[V88] Isolated native Python bridge installed:',dst)
    print('[CLIENT] Original V28 shopdialog by real MSG_PUSH shop_catalog/open_shop')
    print('[SAFE] Every row locked, BUY/SELL unavailable; native GAME/SQL/original JS unchanged')
if __name__=='__main__':main()