#!/usr/bin/env python3
"""V86 reversible native NPC visual projection; NOT a native GC_SHOP/CG_SHOP.

The original Browser2 client and native GAME, AUTH, DB binaries are unchanged.
All per-session state is stored in process memory, bound to a native login,
and can only be fetched with an existing authenticated local session token.
"""
import json
import re
import threading
import time
from pathlib import Path

TTL=180
MAX_ROWS=256
MAX_SHOPS=12


def attach(bridge):
    bridge.npc_v86_lock=threading.RLock()
    bridge.npc_v86_views={}
    bridge.npc_v86_seq=0


def _safe_string(v,cap):
    return (v[:cap] if isinstance(v,str) else '')


def _wiki_index():
    path=Path.home()/'storage/downloads/v70_catalog.json'
    if not path.is_file() or path.is_symlink() or path.stat().st_size>1_000_000:
        return {}
    try:
        data=json.loads(path.read_text('utf-8'))
        if not isinstance(data,dict) or not isinstance(data.get('shops'),list):return {}
        names={}
        for shop in data['shops'][:40]:
            if not isinstance(shop,dict) or type(shop.get('npcVnum'))!=int:continue
            key=shop['npcVnum']
            entries={}
            for row in shop.get('entries',[])[:400]:
                if not isinstance(row,dict):continue
                v=row.get('itemVnum');price=row.get('price')
                if type(v)!=int or not 1<=v<=100_000_000 or v in entries:continue
                if type(price)!=int or not 0<=price<=1_000_000_000_000:price=None
                entries[v]={'name':_safe_string(row.get('name'),80),'wikiPrice':price}
            names[key]=entries
        return names
    except (OSError,ValueError,TypeError):return {}


def _project(npc,cat):
    shops=[]
    if not isinstance(cat,dict):return shops
    if cat.get('state')!='source_catalog_verified':return shops
    wiki=_wiki_index().get(npc,{})
    for raw in cat.get('shops',[])[:MAX_SHOPS]:
        if not isinstance(raw,dict):continue
        sid=raw.get('shopVnum')
        if type(sid)!=int:continue
        rows=[]
        for item in raw.get('items',[])[:MAX_ROWS]:
            if not isinstance(item,dict):continue
            v=item.get('itemVnum');count=item.get('count')
            if type(v)!=int or type(count)!=int or not 0<v<=100_000_000 or not 0<count<=1_000_000:continue
            w=wiki.get(v,{})
            rows.append({'vnum':v,'count':count,'name':w.get('name',''),
                         'wikiPrice':w.get('wikiPrice'), 'priceFromGame':False})
        shops.append({'id':sid,'name':_safe_string(raw.get('name'),80),'items':rows})
    return shops


def clicked(bridge,login,npc,cat=None):
    if not isinstance(login,str) or not 1<=len(login)<=30 or type(npc)!=int or npc<=0:return
    with bridge.npc_v86_lock:
        old=bridge.npc_v86_views.get(login)
        if cat is None or not (isinstance(old,dict) and old.get('npcVnum')==npc and time.monotonic()-old['t']<15):
            bridge.npc_v86_seq+=1
            old={'seq':bridge.npc_v86_seq,'npcVnum':npc,'t':time.monotonic(),
                 'catalogState':'pending_sql_read','shops':[],'script':'','scriptReceived':False}
            bridge.npc_v86_views[login]=old
        if isinstance(cat,dict):
            old['catalogState']=_safe_string(cat.get('state'),60)
            old['shops']=_project(npc,cat)


def script(bridge,login,npc,event):
    if not isinstance(event,dict) or type(npc)!=int or not isinstance(login,str):return False
    raw=event.get('originalScriptBytesHex')
    if not isinstance(raw,str) or not 0<len(raw)<=12000 or len(raw)%2 or not re.fullmatch(r'[0-9A-Fa-f]+',raw):return False
    try:
        content=bytes.fromhex(raw).decode('cp949','replace')
    except (ValueError,UnicodeError):return False
    # Render only as literal textContent; never execute original quest markup.
    content=''.join(x for x in content if x=='\n' or x=='\t' or ord(x)>=32)[:1400]
    with bridge.npc_v86_lock:
        v=bridge.npc_v86_views.get(login)
        if not v or v['npcVnum']!=npc or time.monotonic()-v['t']>20:return False
        v['script']=content;v['scriptReceived']=True
    return True


def snapshot(bridge,login):
    blank={'seq':0,'npcVnum':None,'catalogState':'no_recent_native_npc_click',
           'shops':[],'script':'','scriptReceived':False,'purchaseEnabled':False,
           'liveShopPacketDecoded':False,'source':'native_sql_read_only'}
    if not isinstance(login,str):return blank
    with bridge.npc_v86_lock:
        row=bridge.npc_v86_views.get(login)
        if not row or time.monotonic()-row['t']>TTL:return blank
        return {**blank,'seq':row['seq'],'npcVnum':row['npcVnum'],
                'catalogState':row['catalogState'],'shops':row['shops'],
                'script':row['script'],'scriptReceived':row['scriptReceived']}


PLAY_EXTRA=r'''
<style>
#nativeNpc86Button{position:fixed;bottom:18px;right:18px;z-index:2147483646;border-radius:24px;
  background:#2b5069;border:1px solid #799cbd;color:white;padding:10px 16px;font:600 14px system-ui;display:none}
#nativeNpc86Panel{position:fixed;z-index:2147483647;top:8vh;left:50%;transform:translateX(-50%);
  width:min(90vw,490px);max-height:83vh;overflow:auto;background:#111c28;color:#f5f6fb;
  border:1px solid #71899e;border-radius:14px;padding:15px;box-shadow:0 10px 48px #000b;display:none;
  font:14px/1.5 system-ui;text-align:left}
#nativeNpc86Panel .n86top{display:flex;align-items:center;justify-content:space-between;gap:8px}
#nativeNpc86Panel button{background:#334f65;color:white;font:inherit;border:1px solid #8297aa;border-radius:8px;padding:6px 11px}
#nativeNpc86Panel .n86item{display:flex;justify-content:space-between;border-bottom:1px solid #344150;padding:6px 0;gap:15px}
#nativeNpc86Panel .n86price,#nativeNpc86Panel .n86notice{font-size:12px;color:#b8c6d4}
#nativeNpc86Panel pre{font:13px/1.5 system-ui;white-space:pre-wrap;overflow-wrap:anywhere;background:#243547;padding:10px;border-radius:7px}
</style>
<button id="nativeNpc86Button" type="button">NPC</button>
<section id="nativeNpc86Panel" role="dialog" aria-modal="false" aria-label="Native NPC mağaza görünümü">
 <div class="n86top"><strong id="nativeNpc86Title">NPC</strong><button id="nativeNpc86Close" type="button">Kapat ✕</button></div>
 <div id="nativeNpc86Text"></div>
 <div class="n86notice">Kaynak: yerel Cemre Efe SQLite (salt okunur). Wiki fiyatı, GAME fiyatı değildir. Gerçek alışveriş kapalıdır.</div>
</section>
<script>
(()=>{
 const dialog=document.getElementById('nativeNpc86Panel'),toggle=document.getElementById('nativeNpc86Button');
 const title=document.getElementById('nativeNpc86Title'),body=document.getElementById('nativeNpc86Text');
 let seq=0,last=null,dismissed=0,pending=false;
 document.getElementById('nativeNpc86Close').onclick=()=>{dismissed=seq;dialog.style.display='none'};
 toggle.onclick=()=>{if(last&&last.seq){render(last);dialog.style.display='block'}};
 function el(tag,text,parent,cls){const e=document.createElement(tag);if(cls)e.className=cls;e.textContent=String(text);parent.append(e);return e}
 function render(v){body.replaceChildren();title.textContent='NPC '+v.npcVnum;
   if(v.scriptReceived&&v.script)el('pre',v.script,body);
   if(v.shops.length){for(const shop of v.shops){el('h3',shop.name||('Mağaza '+shop.id),body);
    for(const i of shop.items){const r=document.createElement('div');r.className='n86item';
      const left=document.createElement('span');left.textContent=(i.name||('Item #'+i.vnum))+' ×'+i.count;
      const right=document.createElement('span');right.className='n86price';
      right.textContent=Number.isInteger(i.wikiPrice)?('Wiki: '+i.wikiPrice.toLocaleString('tr-TR')+' Yang'):'Fiyat: GAME onayı bekleniyor';
      r.append(left,right);body.append(r)}}
   }else el('p','Bu NPC için yerel SQL mağaza satırı bulunamadı veya henüz okunamadı: '+v.catalogState,body);
 }
 async function update(){if(pending)return;const iframe=document.getElementById('game');
   if(!iframe||iframe.style.display!=='block')return;
   let token;try{token=JSON.parse(localStorage.getItem('ymir.session.v1')||'null')?.token}catch(e){return}
   if(typeof token!=='string'||!token)return;
   pending=true;
   try{const r=await fetch('/__native__/npc-ui',{cache:'no-store',headers:{'x-session-token':token}});
     if(!r.ok)return;const v=await r.json();if(!Number.isInteger(v.seq)||v.seq<=0)return;
     last=v;toggle.style.display='block';
     if(seq!==v.seq){seq=v.seq;dismissed=0;render(v);dialog.style.display='block'}
     else if(dismissed!==seq&&dialog.style.display==='block')render(v);
   }catch(e){}finally{pending=false}
 }
 setInterval(update,850);
})()
</script>
'''