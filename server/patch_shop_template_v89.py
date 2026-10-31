#!/usr/bin/env python3
"""V89: correct numeric V88 shop template IDs to original Browser2 V28 strings.
Original net-inventory vnumOfTemplate matches /^v2_(\\d+)$/, never bare integers.
Build an isolated version; leave original GAME, V88, DB and assets untouched.
"""
from __future__ import annotations
import argparse
import ast
import os
from pathlib import Path
import tempfile
BEFORE="entries.append({'slot':i,'templateId':vnum,'count':count,'price':0})"
AFTER="entries.append({'slot':i,'templateId':'v2_'+str(vnum),'count':count,'price':0})"
CHECK_BEFORE="return all(type(x.get('templateId')) is int for x in found['entries'])"
CHECK_AFTER="return all(isinstance(x.get('templateId'),str) and x['templateId'].startswith('v2_') and x['templateId'][3:].isdigit() for x in found['entries'])"
MARKER="# V89_VERIFIED_ORIGINAL_V28_ITEM_TEMPLATE_IDS"

def patch(source: str) -> str:
    if MARKER in source:
        ast.parse(source)
        return source
    if source.count(BEFORE)!=1 or source.count(CHECK_BEFORE)!=1:
        raise ValueError('Unknown V88 source; no patch applied')
    if "'state':'locked'" not in source or "def frames(" not in source:
        raise ValueError('V88 locked shop projection contract not found')
    ast.parse(source)
    source=source.replace(BEFORE,AFTER,1).replace(CHECK_BEFORE,CHECK_AFTER,1)
    result=MARKER+'\n'+source
    ast.parse(result)
    compile(result,'original_shop_v88.py','exec')
    return result

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--dest',type=Path,required=True)
    args=parser.parse_args()
    src=args.source.expanduser()
    dst=args.dest.expanduser()
    if not src.is_file() or src.is_symlink() or dst.is_symlink() or src.resolve()==dst.resolve():
        parser.error('Refusing missing/symlink source or overlapping destination')
    if dst.exists():
        parser.error('Refusing overwrite; V88 and V89 must remain separate')
    try:
        result=patch(src.read_text('utf-8'))
    except (OSError,ValueError,SyntaxError) as exc:
        parser.error(str(exc))
    dst.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.shop_v89_',suffix='.py',dir=dst.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as out:
            out.write(result)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp,dst)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    print('[V89] V28 shop template IDs fixed: v2_<VNUM>')
    print('[UNCHANGED] Native AUTH/GAME/DB/player SQLite, original JS, V88 installation')
    print('[LIMIT] Inventory, live Yang/prices and BUY/SELL still not bridged')

if __name__=='__main__':
    main()
