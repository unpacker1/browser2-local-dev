#!/usr/bin/env python3
"""V87 read-only native NPC item names + source-attributed wiki comparison.

Loaded in place of native_npc_ui_v86 in isolated V87; V86 bridge API preserved.
No native gameplay, buying, selling, game packets, character SQL writes, or original
assets are changed. Always keep native and wiki offers clearly separate.
"""
import json
import re
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

TTL=180
MAX_ROWS=256
MAX_SHOPS=12
MAX_PREVIEW=85


def attach(bridge):
    bridge.npc_v86_lock=threading.RLock()
    bridge.npc_v86_views={}
    bridge.npc_v86_seq=0


def _safe_string(v,cap):
    return v[:cap] if isinstance(v,str) else ''


def _decode_name(v):
    if isinstance(v,bytes):
        for enc in ('utf-8','cp949'):
            try: v=v.decode(enc);break
            except UnicodeError:continue
        else:return ''
    if not isinstance(v,str):return ''
    return ''.join(c for c in v if ord(c)>=32 and c!='\x7f')[:90].strip()


def _proto_names(folder, vnums):
    """Bounded readonly lookup in original native player.item_proto by exact VNUM."""
    wanted=sorted({v for v in vnums if type(v) is int and 0<v<=100_000_000})[:MAX_SHOPS*MAX_ROWS]
    if not wanted:return {}
    folder=Path(folder)
    if not folder.is_dir() or folder.is_symlink():return {}
    path=folder/'player.sqlite3'
    if not path.is_file() or path.is_symlink():return {}
    result={}
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('PRAGMA busy_timeout=2000')
            cols={str(r[1]) for r in db.execute('PRAGMA table_info(item_proto)')}
            if 'vnum' not in cols:return {}
            namecols=[s for s in ('locale_name','name') if s in cols]
            if not namecols:return {}
            for start in range(0,len(wanted),250):
                sl=wanted[start:start+250]
                # Column names come from a strict hardcoded whitelist above.
                query='SELECT vnum,'+','.join(namecols)+' FROM item_proto WHERE vnum IN ('+','.join('?'*len(sl))+')'
                for row in db.execute(query,sl):
                    if type(row[0]) is not int:continue
                    name=next((s for s in (_decode_name(v) for v in row[1:]) if s), '')
                    if name: result[row[0]]=name
    except (sqlite3.Error, OSError, ValueError):return {}
    return result


def _wiki_index():
    """Optional already-owned wiki export, never silently treated as native offers."""
    home=Path.home()
    choices=[home/'storage/downloads/v70_catalog.json',
             home/'storage/downloads/BROWSER2_V70_WIKI_NPC_SHOPS/v70_catalog.json',
             home/'storage/downloads/BROWSER2_SIFIRDAN_TAM_SITE/v70_catalog.json']
    data=None
    for path in choices:
        try:
            if not path.is_file() or path.is_symlink() or path.stat().st_size>1_000_000:continue
            data=json.loads(path.read_text('utf-8'))
            if isinstance(data,dict) and isinstance(data.get('shops'),list):break
        except (OSError,ValueError,TypeError):pass
    if not isinstance(data,dict) or not isinstance(data.get('shops'),list):return {}
    index={}
    for raw in data['shops'][:80]:
        if not isinstance(raw,dict) or type(raw.get('npcVnum')) is not int:continue
        rows=[]
        for item in raw.get('entries',[])[:MAX_ROWS]:
            if not isinstance(item,dict):continue
            v=item.get('itemVnum');price=item.get('price');count=item.get('count')
            if type(v) is not int or not 0<v<=100_000_000:continue
            if type(price) is not int or not 0<=price<=1_000_000_000_000:price=None
            if type(count) is not int or count<=0:count=1
            rows.append({'vnum':v,'name':_safe_string(item.get('name'),85),
                         'wikiPrice':price,'count':min(count,1_000_000)})
        index[raw['npcVnum']]={'name':_safe_string(raw.get('name'),90),'items':rows}
    return index


def _project(npc,cat,db_folder=None):
    if not isinstance(cat,dict) or cat.get('state')!='source_catalog_verified':return [],None
    wiki=_wiki_index().get(npc)
    wiki_by_vnum={row['vnum']:row for row in wiki['items']} if wiki else {}
    shops=cat.get('shops',[])
    if not isinstance(shops,list):return [],None
    vs=[item.get('itemVnum') for shop in shops[:MAX_SHOPS] if isinstance(shop,dict)
        for item in (shop.get('items') or [])[:MAX_ROWS] if isinstance(item,dict)]
    proto=_proto_names(db_folder,vs) if db_folder is not None else {}
    native_shops=[];native_vnums=set()
    for raw in shops[:MAX_SHOPS]:
        if not isinstance(raw,dict):continue
        sid=raw.get('shopVnum')
        if type(sid) is not int:continue
        rows=[]
        for item in (raw.get('items') or [])[:MAX_ROWS]:
            if not isinstance(item,dict):continue
            v=item.get('itemVnum');count=item.get('count')
            if type(v) is not int or type(count) is not int or not 0<v<=100_000_000 or not 0<count<=1_000_000:continue
            native_vnums.add(v)
            w=wiki_by_vnum.get(v)
            rows.append({'vnum':v,'count':count,
                         'name':proto.get(v) or (w['name'] if w else ''),
                         'nameSource':'native_item_proto' if v in proto else ('wiki_name' if w and w['name'] else 'vnum_only'),
                         'wikiPrice':w['wikiPrice'] if w else None,
                         'priceFromGame':False})
        native_shops.append({'id':sid,'name':_safe_string(raw.get('name'),80),'items':rows})
    compare=None
    if wiki:
        only=[row for row in wiki['items'] if row['vnum'] not in native_vnums]
        compare={'name':wiki['name'],'wikiTotal':len(wiki['items']),
                 'nativeMatchingVnums':len({x for x in native_vnums if x in wiki_by_vnum}),
                 'wikiOnly':only[:MAX_PREVIEW],
                 'note':'Wiki katalogu GAME magazasi veya oyuncu item veritabani degildir.'}
    return native_shops,compare


def clicked(bridge,login,npc,cat=None):
    if not isinstance(login,str) or not 1<=len(login)<=30 or type(npc) is not int or npc<=0:return
    with bridge.npc_v86_lock:
        old=bridge.npc_v86_views.get(login)
        if cat is None or not (isinstance(old,dict) and old.get('npcVnum')==npc and time.monotonic()-old['t']<15):
            bridge.npc_v86_seq+=1
            old={'seq':bridge.npc_v86_seq,'npcVnum':npc,'t':time.monotonic(),
                 'catalogState':'pending_sql_read','shops':[],'wikiCompare':None,
                 'script':'','scriptReceived':False,'questChoices':[]}
            bridge.npc_v86_views[login]=old
        if isinstance(cat,dict):
            old['catalogState']=_safe_string(cat.get('state'),60)
            old['shops'],old['wikiCompare']=_project(npc,cat,bridge.runtime/'sqlite')


def _quest_choices(raw):
    """QUESTION markup visual only. Never invent SCRIPT_ANSWER native packets."""
    if not isinstance(raw,str):return []
    s=raw.strip()
    if not s.startswith('[QUESTION ') or ']' not in s:return []
    s=s[len('[QUESTION '):s.index(']')]
    choices=[]
    # Format captured: [QUESTION 1;... |2;... |3;...]
    for part in s.split('|')[:12]:
        m=re.fullmatch(r'\s*(\d{1,2});\s*(.*?)\s*',part,re.S)
        if m and m.group(2):
            choices.append({'index':int(m.group(1)),'label':m.group(2)[:180]})
    return choices


def script(bridge,login,npc,event):
    if not isinstance(event,dict) or type(npc) is not int or not isinstance(login,str):return False
    raw=event.get('originalScriptBytesHex')
    if not isinstance(raw,str) or not 0<len(raw)<=12000 or len(raw)%2 or not re.fullmatch('[0-9A-Fa-f]+',raw):return False
    try:content=bytes.fromhex(raw).decode('cp949','replace')
    except (ValueError,UnicodeError):return False
    content=''.join(x for x in content if x=='\n' or x=='\t' or ord(x)>=32)[:1400]
    with bridge.npc_v86_lock:
        v=bridge.npc_v86_views.get(login)
        if not v or v['npcVnum']!=npc or time.monotonic()-v['t']>20:return False
        v['script']=content;v['scriptReceived']=True
        v['questChoices']=_quest_choices(content)
    return True


def snapshot(bridge,login):
    blank={'seq':0,'npcVnum':None,'catalogState':'no_recent_native_npc_click',
           'shops':[],'wikiCompare':None,'script':'','questChoices':[],
           'scriptReceived':False,'purchaseEnabled':False,'questAnswerEnabled':False,
           'liveShopPacketDecoded':False,'source':'native_sql_read_only'}
    if not isinstance(login,str):return blank
    with bridge.npc_v86_lock:
        row=bridge.npc_v86_views.get(login)
        if not row or time.monotonic()-row['t']>TTL:return blank
        return {**blank,'seq':row['seq'],'npcVnum':row['npcVnum'],
                'catalogState':row['catalogState'],'shops':row['shops'],
                'wikiCompare':row['wikiCompare'],
                'script':row['script'],'questChoices':row['questChoices'],
                'scriptReceived':row['scriptReceived']}

PLAY_EXTRA=r'''
<style>
#nativeNpc86Button{position:fixed;bottom:18px;right:18px;z-index:2147483646;border-radius:24px;
 background:#2b5069;border:1px solid #799cbd;color:white;padding:10px 16px;font:600 14px system-ui;display:none}
#nativeNpc86Panel{position:fixed;z-index:2147483647;top:8vh;left:50%;transform:translateX(-50%);
 width:min(90vw,490px);max-height:80vh;overflow:auto;background:#111c28;color:#f5f6fb;
 border:1px solid #71899e;border-radius:14px;padding:15px;box-shadow:0 10px 48px #000b;display:none;
 font:14px/1.5 system-ui;text-align:left;box-sizing:border-box}
#nativeNpc86Panel .n86top{position:sticky;top:-15px;background:#111c28;display:flex;align-items:center;
 justify-content:space-between;gap:8px;padding:6px 0 12px;z-index:1}
#nativeNpc86Panel button{background:#334f65;color:white;font:inherit;border:1px solid #8297aa;border-radius:8px;padding:6px 11px}
#nativeNpc86Panel .n86item{display:flex;justify-content:space-between;border-bottom:1px solid #344150;padding:7px 0;gap:12px}
#nativeNpc86Panel .n86price,#nativeNpc86Panel .n86notice{font-size:12px;color:#b8c6d4}
#nativeNpc86Panel .n87sub{color:#aabfd0;font:11px system-ui}
#nativeNpc86Panel .n87choice{border:1px solid #354b5c;border-radius:8px;padding:9px;margin:6px 0;background:#263444}
#nativeNpc86Panel details{margin:8px 0}
#nativeNpc86Panel summary{cursor:pointer}
</style>
<button id="nativeNpc86Button" type="button">NPC</button>
<section id="nativeNpc86Panel" role="dialog" aria-modal="false" aria-label="Cemre Efe NPC incelemesi">
<div class="n86top"><strong id="nativeNpc86Title">NPC</strong><button id="nativeNpc86Close" type="button">Kapat ✕</button></div>
<div id="nativeNpc86Text"></div>
<div class="n86notice">Native SQLite ve wiki referansları ayrıdır. Gerçek GAME mağaza fiyatı,
 satın alma ve görev seçimi henüz bağlı değildir.</div></section>
<script>
(()=>{
const dialog=document.getElementById('nativeNpc86Panel'),toggle=document.getElementById('nativeNpc86Button');
const title=document.getElementById('nativeNpc86Title'),body=document.getElementById('nativeNpc86Text');
let seq=0,last=null,dismissed=0,pending=false;
document.getElementById('nativeNpc86Close').onclick=()=>{dismissed=seq;dialog.style.display='none'};
toggle.onclick=()=>{if(last&&last.seq){render(last);dialog.style.display='block'}};
function el(tag,text,parent,cls){const e=document.createElement(tag);if(cls)e.className=cls;e.textContent=String(text);parent.append(e);return e}
function render(v){body.replaceChildren();title.textContent='NPC '+v.npcVnum;
 if(Array.isArray(v.questChoices)&&v.questChoices.length){
  el('p','GAME görevi — seçenekler (gönderim henüz etkin değil)',body,'n86notice');
  for(const ch of v.questChoices)el('div',ch.index+'. '+ch.label,body,'n87choice');
 }else if(v.scriptReceived&&v.script){el('pre',v.script,body)}
 if(v.shops.length){el('h3','Cemre Efe SQLite mağazası',body);
  for(const shop of v.shops){el('h4',shop.name||('Mağaza '+shop.id),body);
   for(const i of shop.items){const r=document.createElement('div');r.className='n86item';
    const left=document.createElement('div');el('div',i.name||('Item #'+i.vnum),left);
    el('div','VNUM '+i.vnum+' ×'+i.count+(i.nameSource==='wiki_name'?' · wiki adı':''),left,'n87sub');
    const right=document.createElement('span');right.className='n86price';
    right.textContent=Number.isInteger(i.wikiPrice)?('Wiki referans: '+i.wikiPrice.toLocaleString('tr-TR')+' Yang'):'GAME fiyatı henüz yok';
    r.append(left,right);body.append(r)} }
 }else if(!v.scriptReceived){el('p','Native SQL mağaza bulunamadı: '+v.catalogState,body)}
 if(v.wikiCompare){const w=v.wikiCompare;const d=document.createElement('details');
  const s=document.createElement('summary');s.textContent='Ayrı Browser2 wiki kataloğu ('+w.wikiTotal+' satır; '+w.nativeMatchingVnums+' VNUM eşleşiyor)';d.append(s);
  el('p','Bu ürünler native GAME mağazasına eklenmiş sayılmaz.',d,'n86notice');
  for(const i of w.wikiOnly){el('div',(i.name||'VNUM '+i.vnum)+' · VNUM '+i.vnum+' ×'+i.count+' · wiki '+
    (Number.isInteger(i.wikiPrice)?i.wikiPrice.toLocaleString('tr-TR'):'?')+' Yang',d,'n86price')}
  body.append(d)
 }
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
  else if(dismissed!==seq&&dialog.style.display==='block')render(v)
 }catch(e){}finally{pending=false}
}
setInterval(update,850);
})()
</script>
'''