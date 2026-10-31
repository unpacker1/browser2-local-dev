#!/usr/bin/env python3
"""Wire-exact Browser2 V28 original shopdialog preview, SOURCE stock only.

Verified against owner's original V28 JavaScript source (private asset):
  server push frame: 0x09 + utf8 JSON {m:'shop_catalog',d:[shop,...]}
  follow-up: 0x09 + utf8 JSON {m:'open_shop',d:{shopId,view}}
  shop entries: templateId, count, slot, price.  Optional view rows:
  {slot,state,price,lock}; any state other than 'buyable' blocks client BUY.

This is NOT the live native GC_SHOP packet. Nothing here purchases an item,
changes Yang, injects a fake GAME acceptance, or modifies original assets.
"""
from __future__ import annotations
import json

MSG_PUSH=9
ROWS_PER_TAB=40
MAX_TABS=6
MAX_SHOPS=8
MAX_ITEM_VNUM=100_000_000
MAX_COUNT=1_000_000


def push(message: str, data):
    if message not in ('shop_catalog','open_shop'):
        raise ValueError('Unexpected V28 push message')
    raw=json.dumps({'m':message,'d':data},ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
    if len(raw)>64*1024:raise ValueError('V28 shop frame exceeds bounded limit')
    return bytes([MSG_PUSH])+raw


def project(npc_vnum:int, cat:dict):
    """Return client catalog+open pair ONLY for verified current native NPC source.

    Crucially, all rows are locked until the independent real GC_SHOP offer
    and GAME price are decoded and verified. Never use SQLite/wiki values as
    a live Yang price. The original client checks state before offering BUY.
    """
    if type(npc_vnum) is not int or not 1<=npc_vnum<=10_000_000:return None
    if not isinstance(cat,dict):return None
    if (cat.get('state')!='source_catalog_verified' or
        cat.get('npcVnum')!=npc_vnum or
        cat.get('purchaseEnabled') is not False or
        cat.get('liveShopPacketDecoded') is not False or
        not cat.get('source','').startswith('native_') or
        not isinstance(cat.get('shops'),list)):
        return None
    raw_shops=cat['shops'][:MAX_SHOPS]
    shops=[];chosen=None
    for native in raw_shops:
        if not isinstance(native,dict):return None
        sid=native.get('shopVnum');items=native.get('items')
        if type(sid) is not int or not 1<=sid<=10_000_000:return None
        if not isinstance(items,list) or len(items)>MAX_TABS*ROWS_PER_TAB:return None
        entries=[];view_rows=[];tabs=[]
        for i,item in enumerate(items):
            if not isinstance(item,dict):return None
            vnum=item.get('itemVnum');count=item.get('count')
            if (type(vnum) is not int or type(count) is not int or
                not 1<=vnum<=MAX_ITEM_VNUM or not 1<=count<=MAX_COUNT):return None
            # Catalog's source item count/VNUM remain exactly as verified in native SQLite.
            # Null/zero price means UNAVAILABLE and MUST be paired with locked state.
            entries.append({'slot':i,'templateId':vnum,'count':count,'price':0})
            view_rows.append({'slot':i,'state':'locked','price':0,
                              'lock':{'reason':'native_game_price_unverified'}})
        if not entries:continue
        for tab_i in range((len(entries)+ROWS_PER_TAB-1)//ROWS_PER_TAB):
            tabs.append({'id':'main' if tab_i==0 else 'tab'+str(tab_i+1),
                         'nameKey':'shop.tab.main' if tab_i==0 else 'shop.tab.'+str(tab_i+1)})
        shop_id=f'cemreefe-native-sql-{npc_vnum}-{sid}'
        # Original V28 window uses its own original sprites, grid and inventory controls.
        shop={'id':shop_id,'nameKey':'shop.title','entries':entries,'tabs':tabs}
        shops.append(shop)
        if chosen is None:
            chosen={'shopId':shop_id,'rows':view_rows,
                    'tabs':[{'id':x['id'],'locked':False} for x in tabs]}
    return (shops,{'shopId':chosen['shopId'],'view':chosen}) if shops and chosen else None


def frames(npc_vnum,cat):
    p=project(npc_vnum,cat)
    if p is None:return ()
    return (push('shop_catalog',p[0]),push('open_shop',p[1]))


def validate_client_contract(catalog_frame,open_frame):
    """Defensive internal test: BUY must remain disabled for every projected row."""
    if catalog_frame[:1]!=bytes([MSG_PUSH]) or open_frame[:1]!=bytes([MSG_PUSH]):return False
    catalog=json.loads(catalog_frame[1:]);op=json.loads(open_frame[1:])
    if catalog.get('m')!='shop_catalog' or op.get('m')!='open_shop':return False
    shops=catalog.get('d');data=op.get('d');view=data.get('view',{})
    if not isinstance(shops,list) or not isinstance(data,dict):return False
    found=next((s for s in shops if s.get('id')==data.get('shopId')),None)
    if not found:return False
    rows=view.get('rows')
    if not isinstance(rows,list) or len(rows)!=len(found['entries']):return False
    if any(r.get('state')=='buyable' for r in rows):return False
    return all(type(x.get('templateId')) is int for x in found['entries'])