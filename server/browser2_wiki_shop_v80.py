#!/usr/bin/env python3
"""Browser2 V80 local wiki-shop SQL projection and isolated transactional test.

No original JS/WASM/GLB/native GAME/ACCOUNT/PLAYER DB is touched.
No claim that this service implements native CG_SHOP/GC_SHOP or modifies player items.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import html
import json
import os
from pathlib import Path
from contextlib import contextmanager
import secrets
import sqlite3
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS wiki_shop(
  shop_id TEXT PRIMARY KEY, npc_vnum INTEGER NOT NULL UNIQUE,
  name TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'shop');
CREATE TABLE IF NOT EXISTS wiki_entry(
  shop_id TEXT NOT NULL REFERENCES wiki_shop(shop_id), slot INTEGER NOT NULL,
  tab_id TEXT NOT NULL, item_vnum INTEGER, template_id TEXT,
  name TEXT, icon_id TEXT, item_count INTEGER NOT NULL,
  price INTEGER NOT NULL, status TEXT NOT NULL, PRIMARY KEY(shop_id,slot));
CREATE TABLE IF NOT EXISTS demo_wallet(
  id INTEGER PRIMARY KEY CHECK(id=1), gold INTEGER NOT NULL CHECK(gold>=0));
CREATE TABLE IF NOT EXISTS demo_inventory(
  item_vnum INTEGER PRIMARY KEY, purchases INTEGER NOT NULL CHECK(purchases>=0),
  total_items INTEGER NOT NULL CHECK(total_items>=0));
CREATE TABLE IF NOT EXISTS demo_purchases(
  request_id TEXT PRIMARY KEY, shop_id TEXT NOT NULL, slot INTEGER NOT NULL,
  item_vnum INTEGER NOT NULL, item_count INTEGER NOT NULL,
  paid INTEGER NOT NULL, created_utc TEXT NOT NULL DEFAULT (datetime('now')));
'''
DEMO_GOLD=5_000_000
MAX_ENTRIES=5000
MAX_PRICE=1_000_000_000_000

class ShopError(Exception):
    def __init__(self, code:str):self.code=code;super().__init__(code)

@contextmanager
def connect(path:Path, readonly=False):
    if readonly:
        c=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=10)
        c.execute('PRAGMA query_only=ON')
    else:
        c=sqlite3.connect(path,timeout=10)
        c.execute('PRAGMA busy_timeout=10000')
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    try:
        yield c
        if not readonly and c.in_transaction:c.commit()
    except Exception:
        if c.in_transaction:c.rollback()
        raise
    finally:c.close()

def _valid_num(v,mi,ma,nullable=False):
    if nullable and v is None:return None
    if type(v) is not int or v<mi or v>ma:raise ShopError('invalid_catalog_integer')
    return v

def _text(v,limit=180):
    if v is None:return None
    if not isinstance(v,str) or len(v)>limit or '\x00' in v:raise ShopError('invalid_catalog_text')
    return v

def load_source(source:Path):
    if not source.is_file() or source.is_symlink():raise ShopError('catalog_file_missing')
    if source.stat().st_size>15_000_000:raise ShopError('catalog_too_large')
    if source.suffix.lower() in ('.sqlite3','.db'):
        with connect(source,True) as c:
            tables={r['name'] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'wiki_shop','wiki_entry'}<=tables:raise ShopError('wrong_wiki_sqlite_schema')
            shops=[dict(x) for x in c.execute('SELECT shop_id,npc_vnum,name,role FROM wiki_shop ORDER BY shop_id')]
            entries=[dict(x) for x in c.execute('SELECT shop_id,slot,tab_id,item_vnum,template_id,name,icon_id,item_count,price,status FROM wiki_entry ORDER BY shop_id,slot')]
    elif source.suffix.lower()=='.json':
        doc=json.loads(source.read_text('utf-8-sig'))
        if type(doc)!=dict or type(doc.get('shops'))!=list:raise ShopError('wrong_wiki_json_schema')
        shops=[];entries=[]
        for shop in doc['shops']:
            shops.append(dict(shop_id=shop['id'],npc_vnum=shop['npcVnum'],name=shop['name'],role=shop.get('role','shop')))
            for entry in shop['entries']:
                entries.append(dict(shop_id=shop['id'],slot=entry['slot'],tab_id=entry.get('tabId',''),item_vnum=entry.get('itemVnum'),template_id=entry.get('templateId'),name=entry.get('name'),icon_id=entry.get('iconId'),item_count=entry['count'],price=entry['price'],status=entry['status']))
    else:raise ShopError('unsupported_catalog_type')
    if len(shops)<1 or len(shops)>250 or not 1<=len(entries)<=MAX_ENTRIES:raise ShopError('catalog_count_out_of_bounds')
    for s in shops:
        s['shop_id']=_text(s['shop_id'],100);s['npc_vnum']=_valid_num(s['npc_vnum'],1,10_000_000)
        s['name']=_text(s['name'],160);s['role']=_text(s.get('role') or 'shop',60)
    for x in entries:
        x['shop_id']=_text(x['shop_id'],100);x['slot']=_valid_num(x['slot'],0,4095)
        x['tab_id']=_text(x['tab_id'],80);x['item_vnum']=_valid_num(x['item_vnum'],1,100_000_000,nullable=True)
        x['template_id']=_text(x['template_id'],100);x['name']=_text(x['name'],180)
        x['icon_id']=_text(x['icon_id'],100);x['item_count']=_valid_num(x['item_count'],1,1_000_000)
        x['price']=_valid_num(x['price'],0,MAX_PRICE);x['status']=_text(x['status'],80)
    return shops,entries

def install(source:Path,target:Path):
    """Atomic catalog replacement in a NEW/isolated database; never native SQLite."""
    if target.is_symlink():raise ShopError('target_symlink_not_allowed')
    native_root=(Path.home()/'CEMREEFE_NATIVE_STANDALONE'/'runtime'/'sqlite').resolve()
    if target.resolve().is_relative_to(native_root):raise ShopError('native_sql_dir_target_forbidden')
    if source.resolve()==target.resolve():raise ShopError('source_target_must_differ')
    shops,entries=load_source(source)
    # Do not populate a native database even if caller makes a mistake.
    if target.name in ('player.sqlite3','common.sqlite3','account.sqlite3','local.sqlite3'):
        raise ShopError('native_or_auth_db_target_forbidden')
    if 'ISOLATED' not in target.name.upper():raise ShopError('isolated_target_name_required')
    target.parent.mkdir(parents=True,exist_ok=True)
    with connect(target) as c:
        c.executescript(SCHEMA)
        c.execute('BEGIN IMMEDIATE')
        try:
            c.execute('DELETE FROM wiki_entry');c.execute('DELETE FROM wiki_shop')
            c.executemany('INSERT INTO wiki_shop(shop_id,npc_vnum,name,role) VALUES (:shop_id,:npc_vnum,:name,:role)',shops)
            c.executemany('''INSERT INTO wiki_entry(shop_id,slot,tab_id,item_vnum,template_id,name,icon_id,item_count,price,status)
                 VALUES (:shop_id,:slot,:tab_id,:item_vnum,:template_id,:name,:icon_id,:item_count,:price,:status)''',entries)
            c.execute('INSERT OR IGNORE INTO demo_wallet(id,gold) VALUES (1,?)',(DEMO_GOLD,))
            c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES ('catalog_sha256',?)",(hashlib.sha256(source.read_bytes()).hexdigest(),))
            c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES ('catalog_origin',?)",('original_wiki_offline_projection',))
            c.commit()
        except Exception:c.rollback();raise
    return stats(target)

def stats(path):
    with connect(path,True) as c:
        s=c.execute('SELECT COUNT(*) FROM wiki_shop').fetchone()[0]
        e=c.execute('SELECT COUNT(*) FROM wiki_entry').fetchone()[0]
        valid=c.execute("SELECT COUNT(*) FROM wiki_entry WHERE item_vnum IS NOT NULL AND status='vnum_confirmable'").fetchone()[0]
        sha=c.execute("SELECT value FROM meta WHERE key='catalog_sha256'").fetchone()
    return {'shops':s,'entries':e,'buyableDemoEntries':valid,'unresolved':e-valid,
            'sourceSha256':sha[0] if sha else None,'scope':'isolated_wiki_sql_demo','nativeGameConnected':False,
            'nativePlayerSqlModified':False,'nativePurchaseEnabled':False}

def shops(path):
    with connect(path,True) as c:
        return [dict(x) for x in c.execute('SELECT s.shop_id,s.npc_vnum,s.name,s.role,COUNT(e.slot) AS entries FROM wiki_shop s LEFT JOIN wiki_entry e ON e.shop_id=s.shop_id GROUP BY s.shop_id ORDER BY s.npc_vnum')]

def shop(path,npc):
    npc=_valid_num(npc,1,10_000_000)
    with connect(path,True) as c:
        s=c.execute('SELECT shop_id,npc_vnum,name,role FROM wiki_shop WHERE npc_vnum=?',(npc,)).fetchone()
        if s is None:raise ShopError('npc_shop_not_found')
        return {'shop':dict(s),'entries':[dict(x) for x in c.execute('SELECT slot,tab_id,item_vnum,template_id,name,icon_id,item_count,price,status FROM wiki_entry WHERE shop_id=? ORDER BY slot',(s['shop_id'],))]}

def audit_native(path:Path,native_folder:Path):
    """Read-only native shop/shop_item comparison, NOT a live GAME offer."""
    if native_folder.is_symlink() or not native_folder.is_dir():
        return {'state':'native_sqlite_not_found','nativeReadOnly':True}
    with connect(path,True) as dest:
        wiki={int(r['npc_vnum']):dict(r) for r in dest.execute('SELECT npc_vnum,shop_id FROM wiki_shop')}
        entries={r['shop_id']:[] for r in wiki.values()}
        for x in dest.execute('SELECT shop_id,item_vnum,item_count FROM wiki_entry WHERE item_vnum IS NOT NULL'):
            entries[x['shop_id']].append((int(x['item_vnum']),int(x['item_count'])))
    from collections import Counter
    for dbname in ('player','common'):
        candidate=native_folder/(dbname+'.sqlite3')
        if candidate.is_symlink() or not candidate.is_file():continue
        try:
            with connect(candidate,True) as native:
                t={r[0] for r in native.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('shop','shop_item')")}
                if t!={'shop','shop_item'}:continue
                sc={r['name'] for r in native.execute('PRAGMA table_info(shop)')}
                ic={r['name'] for r in native.execute('PRAGMA table_info(shop_item)')}
                if not {'vnum','npc_vnum'}<=sc or not {'shop_vnum','item_vnum','count'}<=ic:
                    return {'state':'native_sql_schema_unverified','nativeReadOnly':True}
                checked=[]
                for npc,ws in sorted(wiki.items()):
                    native_rows=list(native.execute('SELECT i.item_vnum,i.count FROM shop s JOIN shop_item i ON i.shop_vnum=s.vnum WHERE s.npc_vnum=? LIMIT 5001',(npc,)))
                    if len(native_rows)>5000:raise ShopError('native_shop_items_limit_exceeded')
                    ncounts=Counter((int(x[0]),int(x[1])) for x in native_rows)
                    wcounts=Counter(entries[ws['shop_id']])
                    matched=sum((ncounts & wcounts).values())
                    checked.append({'npcVnum':npc,'wikiVnumRows':sum(wcounts.values()),
                        'nativeSourceRows':len(native_rows),'matchedVnumAndCountRows':matched,
                        'wikiRowsNotInNative':sum((wcounts-ncounts).values())})
                return {'state':'native_shop_source_compared','sourceDatabase':dbname,
                    'nativeReadOnly':True,'gameShopOfferVerified':False,
                    'purchaseEnabled':False,'shops':checked}
        except (sqlite3.Error,OSError,ValueError,ShopError):
            return {'state':'native_sql_read_failed','nativeReadOnly':True}
    return {'state':'native_shop_schema_missing','nativeReadOnly':True}

def state(path):
    with connect(path,True) as c:
        w=c.execute('SELECT gold FROM demo_wallet WHERE id=1').fetchone()
        inv=[dict(x) for x in c.execute('SELECT item_vnum,purchases,total_items FROM demo_inventory ORDER BY item_vnum')]
        buys=[dict(x) for x in c.execute('SELECT request_id,shop_id,slot,item_vnum,item_count,paid,created_utc FROM demo_purchases ORDER BY rowid DESC LIMIT 20')]
    return {'gold':w[0] if w else 0,'inventory':inv,'purchases':buys,'testEnvironment':True}

def buy_demo(path,npc,slot,request_id):
    npc=_valid_num(npc,1,10_000_000);slot=_valid_num(slot,0,4095)
    if type(request_id) is not str or len(request_id)<8 or len(request_id)>90 or not all(ch.isalnum() or ch in '-_' for ch in request_id):raise ShopError('invalid_request_id')
    with connect(path) as c:
        c.execute('BEGIN IMMEDIATE')
        prior=c.execute('SELECT shop_id,slot,item_vnum,item_count,paid FROM demo_purchases WHERE request_id=?',(request_id,)).fetchone()
        item=c.execute('''SELECT e.shop_id,e.slot,e.item_vnum,e.item_count,e.price,e.status FROM wiki_entry e
          JOIN wiki_shop s ON e.shop_id=s.shop_id WHERE s.npc_vnum=? AND e.slot=?''',(npc,slot)).fetchone()
        if not item:raise ShopError('not_for_sale')
        if prior:
            if prior['shop_id']!=item['shop_id'] or prior['slot']!=slot:raise ShopError('request_id_reused_for_another_purchase')
            return {'accepted':True,'idempotent':True,'gold':c.execute('SELECT gold FROM demo_wallet WHERE id=1').fetchone()[0]}
        if item['item_vnum'] is None or item['status']!='vnum_confirmable':raise ShopError('item_vnum_unresolved')
        paid=item['price'];wallet=c.execute('SELECT gold FROM demo_wallet WHERE id=1').fetchone()
        if wallet is None:raise ShopError('demo_wallet_missing')
        if wallet[0]<paid:raise ShopError('insufficient_demo_gold')
        c.execute('UPDATE demo_wallet SET gold=gold-? WHERE id=1',(paid,))
        c.execute('''INSERT INTO demo_inventory(item_vnum,purchases,total_items) VALUES (?,?,?)
             ON CONFLICT(item_vnum) DO UPDATE SET purchases=purchases+1,total_items=total_items+excluded.total_items''',
             (item['item_vnum'],1,item['item_count']))
        c.execute('INSERT INTO demo_purchases(request_id,shop_id,slot,item_vnum,item_count,paid) VALUES(?,?,?,?,?,?)',
             (request_id,item['shop_id'],slot,item['item_vnum'],item['item_count'],paid))
        c.commit()
        return {'accepted':True,'idempotent':False,'gold':wallet[0]-paid,
                'itemVnum':item['item_vnum'],'count':item['item_count'],'paid':paid,'nativeGAMEPurchase':False}

PAGE='''<!doctype html><html lang="tr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Browser2 V80 — İzole NPC Mağaza Testi</title>
<style>body{font:16px system-ui;margin:30px auto;max-width:860px;padding:0 16px;background:#141a24;color:#f0f2f7}a{color:#aac9ff}header{padding:16px;background:#282c38;border-radius:12px}button,select{padding:8px 12px;border-radius:7px;background:#294b78;color:white;border:1px solid #6d83a2;cursor:pointer}button:disabled{opacity:.5;cursor:default}table{width:100%;border-collapse:collapse}td,th{padding:8px;border-bottom:1px solid #444;text-align:left}small{color:#a8bbcc}.warn{color:#ffd18d}</style>
<header><h2>NPC Mağazaları — V80</h2><p class="warn">İZOLE TEST: Wiki ürünlerini SQL'den gösterir. Satın alma yalnızca ayrı test envanterini değiştirir. Native GAME karakteri, Yang ve itemleri DEĞİŞMEZ.</p><p>Test Yang: <strong id="gold">—</strong> | <span id="counts"></span></p></header>
<p><label>NPC mağazası: <select id="shops"></select></label> <button id="reload">Yenile</button></p><p id="msg"></p><table><thead><tr><th>Slot</th><th>Ürün</th><th>Adet</th><th>Wiki fiyatı</th><th>Durum</th><th>İşlem</th></tr></thead><tbody id="items"></tbody></table>
<h3>Test envanteri</h3><pre id="inventory"></pre>
<script>
const token=SHOP_TOKEN;
async function request(url,body){let opts=body?{method:'POST',headers:{'content-type':'application/json','x-shop-test-token':token},body:JSON.stringify(body)}:{};let r=await fetch(url,opts),d=await r.json();if(!r.ok)throw Error(d.error||'HTTP '+r.status);return d}
const byId=id=>document.getElementById(id);
async function refreshState(){let d=await request('/api/state');byId('gold').textContent=d.gold.toLocaleString('tr-TR');byId('inventory').textContent=JSON.stringify(d.inventory,null,2)}
async function showShop(){const n=byId('shops').value;if(!n)return;let d=await request('/api/shop?npc='+encodeURIComponent(n));let body=byId('items');body.textContent='';for(let entry of d.entries){let tr=document.createElement('tr');for(let val of [entry.slot,entry.name||entry.template_id||'?',entry.item_count,entry.price.toLocaleString('tr-TR'),entry.status]){let td=document.createElement('td');td.textContent=val;tr.appendChild(td)}let td=document.createElement('td'),b=document.createElement('button');b.textContent='Test satın al';b.disabled=entry.status!=='vnum_confirmable'||entry.item_vnum==null;b.onclick=async()=>{b.disabled=true;try{let rid=crypto.randomUUID();let v=await request('/api/buy',{npc:Number(n),slot:entry.slot,requestId:rid});byId('msg').textContent='Test SQL satın alma başarılı: '+v.itemVnum+' / '+v.paid+' Yang (native GAME etkilenmedi)';await refreshState()}catch(e){byId('msg').textContent='Satın alma olmadı: '+e.message}finally{b.disabled=false}};td.appendChild(b);tr.appendChild(td);body.appendChild(tr)}}
byId('shops').onchange=showShop;byId('reload').onclick=async()=>{await showShop();await refreshState()};(async()=>{try{let data=await request('/api/shops');byId('counts').textContent=data.stats.shops+' NPC, '+data.stats.entries+' ürün ('+data.stats.unresolved+' eksik VNUM)';for(let s of data.shops){let o=document.createElement('option');o.value=s.npc_vnum;o.textContent=s.npc_vnum+' — '+s.name+' ('+s.entries+')';byId('shops').appendChild(o)}await showShop();await refreshState()}catch(e){byId('msg').textContent=e.message}})();
</script></html>'''

def serve(db:Path,port:int):
    token=secrets.token_urlsafe(32)
    if type(port)!=int or not 1024<=port<=65535:raise ShopError('port_bad')
    if not db.is_file():raise ShopError('catalog_not_imported')
    stats(db)
    class Handler(BaseHTTPRequestHandler):
        def send(self,status,obj):
            raw=json.dumps(obj,ensure_ascii=False).encode()
            self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(raw)));self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(raw)
        def check_host(self):
            return self.headers.get('Host','') in (f'127.0.0.1:{port}',f'localhost:{port}')
        def do_GET(self):
            if not self.check_host():return self.send(403,{'error':'localhost_only'})
            u=urllib.parse.urlsplit(self.path)
            try:
                if u.path in ('/','/__local__/shop-test'):
                    body=PAGE.replace('SHOP_TOKEN',json.dumps(token)).encode('utf-8')
                    self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Frame-Options','DENY');self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'unsafe-inline' 'self'; connect-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'");self.end_headers();self.wfile.write(body)
                elif u.path=='/api/shops':self.send(200,{'shops':shops(db),'stats':stats(db)})
                elif u.path=='/api/shop':
                    params=urllib.parse.parse_qs(u.query)
                    if sorted(params)!=['npc'] or len(params['npc'])!=1 or not params['npc'][0].isdigit():raise ShopError('bad_npc')
                    self.send(200,shop(db,int(params['npc'][0])))
                elif u.path=='/api/state':self.send(200,state(db))
                elif u.path=='/api/status':self.send(200,stats(db))
                else:self.send(404,{'error':'route_not_found'})
            except (ShopError,ValueError,sqlite3.Error) as ex:self.send(400,{'error':str(ex)})
        def do_POST(self):
            if not self.check_host():return self.send(403,{'error':'localhost_only'})
            if self.path!='/api/buy':return self.send(404,{'error':'route_not_found'})
            origin=self.headers.get('Origin')
            if origin not in (f'http://127.0.0.1:{port}',f'http://localhost:{port}'):return self.send(403,{'error':'origin_rejected'})
            if not secrets.compare_digest(self.headers.get('X-Shop-Test-Token',''),token):return self.send(403,{'error':'token_rejected'})
            try:
                if self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':raise ShopError('json_required')
                sz=int(self.headers.get('Content-Length','0'))
                if not 2<=sz<=2048:raise ShopError('invalid_body_size')
                body=json.loads(self.rfile.read(sz))
                if not isinstance(body,dict) or set(body)!={'npc','slot','requestId'}:raise ShopError('invalid_buy_fields')
                self.send(200,buy_demo(db,body['npc'],body['slot'],body['requestId']))
            except (ShopError,ValueError,TypeError,sqlite3.Error,json.JSONDecodeError) as ex:self.send(400,{'error':str(ex)})
        def log_message(self,fmt,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print(f'[V80] İZOLE SQL test sayfası: http://127.0.0.1:{port}/__local__/shop-test',flush=True)
    print('[V80] Native GAME, native envanter ve gerçek Yang değişmez.',flush=True)
    try:server.serve_forever()
    finally:server.server_close()

def default_source():
    d=Path.home()/'storage/downloads'
    for filename in ('v70_wiki_shop_catalog.sqlite3','v70_catalog.json'):
        if (d/filename).is_file():return d/filename
    return d/'v70_wiki_shop_catalog.sqlite3'

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['import','audit','audit-native','serve']);p.add_argument('--source',type=Path,default=default_source());p.add_argument('--db',type=Path,default=Path.home()/'BROWSER2_LOCAL_SERVER_DATA'/'wiki_shop_v80_ISOLATED.sqlite3');p.add_argument('--port',type=int,default=8990);p.add_argument('--native-folder',type=Path,default=Path.home()/'CEMREEFE_NATIVE_STANDALONE'/'runtime'/'sqlite')
    a=p.parse_args()
    try:
        if a.command=='import':print(json.dumps(install(a.source,a.db),ensure_ascii=False,indent=2))
        elif a.command=='audit':print(json.dumps(stats(a.db),ensure_ascii=False,indent=2))
        elif a.command=='audit-native':print(json.dumps(audit_native(a.db,a.native_folder),ensure_ascii=False,indent=2))
        elif a.command=='serve':serve(a.db,a.port)
    except (ShopError,sqlite3.Error,OSError) as e:print('ERROR:',e,file=sys.stderr);raise SystemExit(2)
if __name__=='__main__':main()