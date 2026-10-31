#!/usr/bin/env python3
"""Strictly transform isolated V89 bridge into V90 without touching originals."""
import argparse
import ast
from pathlib import Path
import os
import tempfile

MARKER='# V90_OWNER_VERIFIED_READONLY_NATIVE_PLAYER_STATE'
ORIGINAL_COMMENT='                        # Native inventory packet representation differs; do not invent item IDs.'
ORIGINAL_FRAME="                        ws.send(base.jbytes({'items':[],'equipment':{},'gold':max(0,int(points.get('gold',0)))},4))"
CHARACTER_GOLD="'buffs':[],'gold':max(0,int(points.get('gold',0)))},3))"


def transform(code):
    if MARKER in code:
        ast.parse(code)
        return code
    if any(code.count(s)!=1 for s in (ORIGINAL_COMMENT,ORIGINAL_FRAME,CHARACTER_GOLD)):
        raise ValueError('V89 source contract changed, refusing patch')
    if code.count('import original_shop_v88 as originalshop')!=1 or code.count("bridge.engine.live(user['login'],user['password'],ch['_slot'])")!=1:
        raise ValueError('V89 authenticated/native source markers missing')
    code=code.replace('import original_shop_v88 as originalshop\n','import original_shop_v88 as originalshop\nimport native_player_sql_v90 as nativeplayer\n',1)
    status_anchor="                'nativeWorldTransportExceptions':self.metrics['native_ws_uncaught'],'nativeSqlDirectReadOnly':True,"
    if code.count(status_anchor)!=1:
        raise ValueError('Native status anchor changed')
    code=code.replace(status_anchor,status_anchor+"\n                'v90PlayerSqlLastState':getattr(self,'v90_last_sql_state','no_join_yet'),"+
                      "\n                'v90PlayerGoldSource':getattr(self,'v90_last_gold_source','unknown'),"+
                      "\n                'v90PlayerSqlInventoryRows':self.metrics['v90_sql_inventory_items_rendered'],"+
                      "\n                'v90PlayerSqlUnmappedWindowRows':self.metrics['v90_sql_other_windows_not_mapped'],"+
                      "\n                'v90NativeGamePurchaseMapped':False,",1)
    block='''                        # V90: verified login + character owner; SQLite is a read-only snapshot.
                        sqlstate=nativeplayer.player_state(bridge.runtime/'sqlite',user['login'],ch['_nativeId'])
                        bridge.metrics['v90_sql_state_'+sqlstate['status']]+=1
                        bridge.v90_last_sql_state=sqlstate['status']
                        native_gold=points.get('gold')
                        if type(native_gold) is int and 0<=native_gold<2**63:
                            shown_gold=native_gold
                            bridge.metrics['v90_gold_live_points']+=1
                            bridge.v90_last_gold_source='native_live_points'
                        elif type(sqlstate['gold']) is int:
                            shown_gold=sqlstate['gold']
                            bridge.metrics['v90_gold_sql_snapshot']+=1
                            bridge.v90_last_gold_source='native_sql_snapshot'
                        else:
                            shown_gold=None
                            bridge.metrics['v90_gold_unverified']+=1
                            bridge.v90_last_gold_source='unverified'
                        character_msg={'id':ch['id'],'name':ch['name'],
                          'level':int(points.get('level',ch['level'])),
                          'skills':[{'id':s['vnum'],'level':s['level']} for s in ready.get('nativeSkills',[]) if type(s.get('vnum'))==int],
                          'buffs':[]}
                        if shown_gold is not None:character_msg['gold']=shown_gold
                        ws.send(base.jbytes(character_msg,3))
                        if isinstance(sqlstate['bag'],list):
                            # Snapshot only. Native GAME purchase/moves are NOT enabled.
                            ws.send(base.jbytes({'bag':sqlstate['bag'],'equipment':{}},4))
                            bridge.metrics['v90_sql_inventory_items_rendered']+=sqlstate['itemCount']
                            bridge.metrics['v90_sql_other_windows_not_mapped']+=sqlstate['unmappedWindowRows']
'''
    # replace the whole character push and old empty inventory push together
    begin=code.index('                        ws.send(base.jbytes({\'id\':ch[\'id\']')
    end=code.index(ORIGINAL_FRAME,begin)+len(ORIGINAL_FRAME)
    block_before=code[begin:end]
    if CHARACTER_GOLD not in block_before or ORIGINAL_COMMENT not in block_before:
        raise ValueError('Unexpected V89 character + inventory message ordering')
    code=code[:begin]+block+code[end:]
    code=MARKER+'\n'+code
    ast.parse(code)
    compile(code,'native_v69.py','exec')
    return code


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source',required=True,type=Path)
    p.add_argument('--dest',required=True,type=Path)
    a=p.parse_args();source=a.source.expanduser();dest=a.dest.expanduser()
    if not source.is_file() or source.is_symlink() or dest.exists() or dest.is_symlink() or source.resolve()==dest.resolve():
        p.error('Missing/symlink source or destination already exists')
    try:new=transform(source.read_text('utf-8'))
    except (ValueError,SyntaxError,OSError) as e:p.error(str(e))
    dest.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.native_v90_',suffix='.py',dir=dest.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as out:
            out.write(new);out.flush();os.fsync(out.fileno())
        os.replace(tmp,dest)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    print('[V90] New isolated read-only player state bridge:',dest)
    print('[LIMIT] No native CG_SHOP BUY, no GAME-confirmed inventory changes')
if __name__=='__main__':main()