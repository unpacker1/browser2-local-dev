#!/usr/bin/env python3
"""V20 optional browser boot observer for local Browser2 debugging.

Only port 8901. The original HTML, JS, WASM and assets on disk stay unchanged.
A diagnostic script is added to an in-memory HTML RESPONSE only when b2diag=1.
No raw browser errors, IDs, URLs, queries, headers or user data are collected.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import browser2_http_route_audit_v19 as v19

PORT=8902
EVENTS={'loaded','ready','checkpoint','script_error','promise_error','resource_error','ui_notice','phase_seen','boot_failed','world_ready','asset_failed'}
CATEGORIES={'none','webgpu','gpu_absent','shader','model','texture','terrain','map','auth','session','protocol','network','catalog','locale','resource','unknown','world','error_overlay'}
STAGES={'boot','ready','check08','check20','check40','unknown','manifest','terrain_env','player','world'}
OBSERVER=r"""(()=>{
'use strict';
const allowed=new Set(['loaded','ready','checkpoint','script_error','promise_error','resource_error','ui_notice','phase_seen','boot_failed','world_ready','asset_failed']);
function kind(v){
 const m=String(v||'').toLowerCase().slice(0,500);
 for(const [k,r] of [
 ['webgpu',/webgpu|gpu adapter|gpu device/],
 ['shader',/shader|wgsl|pipeline/],
 ['texture',/texture|ktx2|basis|astc/],
 ['terrain',/terrain|heightmap|collision/],
 ['model',/model|glb|gltf|bones|skinned/],
 ['map',/map catalog|map data|map unavailable/],
 ['auth',/auth|login|character validation/],
 ['session',/session|token expired/],
 ['protocol',/protocol|websocket/],
 ['network',/failed to fetch|network|http [45][0-9][0-9]/],
 ['catalog',/catalog/],
 ['locale',/translation|locale/]
 ])if(r.test(m))return k;
 return 'unknown';
}
function send(event,category='none',stage='unknown'){
 if(!allowed.has(event))return;
 try{fetch('/__local__/v20/event',{method:'POST',headers:{'Content-Type':'application/json'},
 body:JSON.stringify({event,category,stage}),credentials:'same-origin',keepalive:true}).catch(()=>{});}catch{}
}
window.addEventListener('error',e=>{
 if(e.target&&e.target!==window&&/^(IMG|SCRIPT|LINK)$/.test(e.target.tagName||'')){
  send('resource_error','resource');return;
 }
 send('script_error',kind(e.error?.message||e.message));
},true);
window.addEventListener('unhandledrejection',e=>send('promise_error',kind(e.reason?.message||e.reason)));
function check(stage){
 send('checkpoint',navigator.gpu?'webgpu':'gpu_absent',stage);
 const text=(document.body?.innerText||'').slice(0,3500).toLowerCase();
 if(/server map catalog unavailable/.test(text))send('ui_notice','catalog',stage);
 else if(/webgpu unavailable|gpu adapter unavailable/.test(text))send('ui_notice','webgpu',stage);
 else if(/world server|world connection/.test(text))send('ui_notice','world',stage);
 else if(/failed|error|unavailable/.test(text))send('ui_notice','error_overlay',stage);
}
send('loaded','none','boot');
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',()=>{
 send('ready','none','ready');check('ready');
},{once:true});
else {send('ready','none','ready');check('ready');}
for(const [ms,stage] of [[8000,'check08'],[20000,'check20'],[40000,'check40']])setTimeout(()=>check(stage),ms);
// Original client exposes a read-only loading ledger. Sample only its fixed states.
const stageMap={'manifest':'manifest','terrain+env':'terrain_env','player':'player','world':'world','ready':'ready'};
let lastPhase='',failureReported=false,assetFailureReported=false,worldReadyReported=false;
function inspectBoot(){
 try{
  const loader=globalThis.__loading;
  if(!loader)return;
  const stage=stageMap[loader.ledger?.currentPhase]||'unknown';
  if(stage!==lastPhase){lastPhase=stage;send('phase_seen','none',stage);}
  if(loader.failedBoot&&!failureReported){failureReported=true;send('boot_failed','unknown',stage);}
  if(loader.dissolved&&!worldReadyReported){worldReadyReported=true;send('world_ready','none',stage);}
  const failed=loader.ledger?.failed?.();
  if(Array.isArray(failed)&&failed.length&&!assetFailureReported){
   assetFailureReported=true;send('asset_failed','resource',stage);
  }
 }catch{}
}
inspectBoot();
const bootPoll=setInterval(inspectBoot,1000);
window.addEventListener('pagehide',()=>{inspectBoot();clearInterval(bootPoll);},{once:true});
})();"""

OLD_LAUNCH="location.assign('/?'+q.toString());"
NEW_LAUNCH="q.set('b2diag','1');location.assign('/?'+q.toString());"

def inject(html):
    m=re.search(br'<head(?:\s[^>]*)?>',html,re.I)
    if not m:return None
    return html[:m.end()]+b'<script src="/__local__/v20/observer.js"></script>'+html[m.end():]

class Handler(v19.Handler):
    server_version='Browser2Local/20'
    def do_GET(self):
        url=urllib.parse.urlsplit(self.path)
        if url.path=='/__local__/':
            src=v19.v18.CLIENT_HTML
            if OLD_LAUNCH not in src:return self.json(500,{'error':'V18 launcher signature changed'})
            csrf=secrets.token_urlsafe(18)
            return self.sendbody(200,src.replace(OLD_LAUNCH,NEW_LAUNCH).encode(),
                'text/html; charset=utf-8',{
                    'Set-Cookie':f'b2csrf={csrf}; Path=/__local__/; SameSite=Strict',
                    'Content-Security-Policy':"default-src 'none'; script-src 'self' 'unsafe-inline'; connect-src 'self'; style-src 'unsafe-inline'"})
        if url.path=='/__local__/v20/observer.js':
            return self.sendbody(200,OBSERVER.encode(),'text/javascript; charset=utf-8')
        if url.path=='/__local__/v20':
            with self.server.boot_lock:
                events=[dict(event=e,category=c,stage=s,requests=n)
                        for (e,c,s),n in self.server.boot_events.most_common(40)]
            with self.server.error_lock:
                errors=[dict(method=m,http_status=int(code),route_shape=p,requests=n)
                        for (m,code,p),n in self.server.error_counts.most_common(100)]
            return self.json(200,{'version':'20.1','events':events,
                'failed_routes':errors,'launcher_events':dict(self.server.launcher_events),
                'backend_metrics':dict(self.server.metrics),'active_world':self.server.active,
                'original_files_modified':False,
                'privacy':'Only fixed categories recorded; no original JS or raw error messages.',
                'limitation':'Handled application errors may not trigger browser error events.'})
        if url.path=='/' and urllib.parse.parse_qs(url.query).get('b2diag')==['1']:
            index=self.server.root/'index.html'
            if index.is_file():
                changed=inject(index.read_bytes())
                if changed is not None:
                    return self.sendbody(200,changed,'text/html; charset=utf-8',{'Cache-Control':'no-store'})
        return super().do_GET()
    def do_POST(self):
        if urllib.parse.urlsplit(self.path).path!='/__local__/v20/event':
            return super().do_POST()
        try:
            self.require_origin()
            ln=int(self.headers.get('Content-Length','0'))
            if not 1<=ln<=200:raise ValueError('size')
            if self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':
                raise ValueError('type')
            data=json.loads(self.rfile.read(ln))
            if not isinstance(data,dict):raise ValueError('body')
            e,c,s=data.get('event'),data.get('category'),data.get('stage')
            if e not in EVENTS or c not in CATEGORIES or s not in STAGES:raise ValueError('labels')
            with self.server.boot_lock:
                if sum(self.server.boot_events.values())<200:self.server.boot_events[e,c,s]+=1
            return self.json(200,{'ok':True})
        except Exception:
            return self.json(400,{'error':'Invalid observer event'})

class Server(v19.Server):
    def __init__(self,bind,root,state,fetcher):
        super().__init__(bind,root,state,fetcher)
        self.boot_lock=threading.Lock()
        self.boot_events=Counter()
        self.RequestHandlerClass=Handler

def fetch(port=PORT):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/__local__/v20',timeout=2) as r:
            d=json.load(r)
        return d if d.get('version')=='20.1' else None
    except (OSError,ValueError):return None

def report(port=PORT):
    d=fetch(port)
    if not d:raise SystemExit('[HATA] V20 calismiyor')
    p=v19.v18.REPORTS/'browser2_v20_tarayici_hata_raporu.json'
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
    print('[RAPOR]',p)
    print('[TARAYICI]',d['events'])
    print('[GAME]',{k:v for k,v in d['backend_metrics'].items() if k.startswith('game_join')})
    print('[HTTP]',d['failed_routes'][:12])

def selftest():
    assert OLD_LAUNCH in v19.v18.CLIENT_HTML
    assert inject(b'<html><head></head><body>original</body></html>') is not None
    # Node is available in GitHub Actions. Validate injected JavaScript syntax without executing it.
    if __import__('shutil').which('node'):
        checked=subprocess.run(['node','--check','--input-type=commonjs'],
            input=OBSERVER,text=True,capture_output=True,timeout=10)
        assert checked.returncode==0, checked.stderr
    with tempfile.TemporaryDirectory() as td:
        base=Path(td);root=base/'original';root.mkdir();(root/'assets').mkdir()
        original=b'<html><head></head><body>original</body></html>'
        (root/'index.html').write_bytes(original)
        prior=os.environ.get('BROWSER2_PRIVATE_DB')
        os.environ['BROWSER2_PRIVATE_DB']=str(base/'private'/'local.sqlite3')
        try:
            f=v19.v18.v17.v16.Fetcher(root,base/'overlay')
            server=Server(('127.0.0.1',0),root,base/'state',f)
            t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
            try:
                address='http://127.0.0.1:'+str(server.server_port)
                with urllib.request.urlopen(address+'/') as r:assert r.read()==original
                with urllib.request.urlopen(address+'/?b2diag=1') as r:
                    assert b'__local__/v20/observer.js' in r.read()
                with urllib.request.urlopen(address+'/__local__/') as r:
                    assert b"q.set('b2diag','1')" in r.read()
                data=json.dumps({'event':'loaded','category':'none','stage':'boot'}).encode()
                req=urllib.request.Request(address+'/__local__/v20/event',data=data,method='POST',
                    headers={'Origin':address,'Content-Type':'application/json'})
                with urllib.request.urlopen(req) as r:assert json.load(r)['ok']
                with urllib.request.urlopen(address+'/__local__/v20') as r:d=json.load(r)
                assert d['events'][0]['event']=='loaded'
                assert 'phase_seen' in OBSERVER and 'globalThis.__loading' in OBSERVER
                assert (root/'index.html').read_bytes()==original
            finally:server.shutdown();server.server_close()
        finally:
            if prior is None:os.environ.pop('BROWSER2_PRIVATE_DB',None)
            else:os.environ['BROWSER2_PRIVATE_DB']=prior
    print('[SELFTEST OK] V20.1 browser phase ledger observer, original disk files unmodified, no sensitive messages')

def serve(port):
    v19.v18.v17.prepare_env()
    for p in (v19.v18.REPORTS,v19.v18.LOGS,v19.v18.BASE/'YEREL_SUNUCU',v19.v18.v17.PRIVATE):
        p.mkdir(parents=True,exist_ok=True)
    if not v19.v18.v17.v16.prev.audit(v19.v18.ORIGINAL):
        raise SystemExit('[HATA] Original browser2 archive missing')
    f=v19.v18.v17.v16.Fetcher(v19.v18.ORIGINAL,v19.v18.BASE/'YEREL_SUNUCU/browser2_v16_map_overlay')
    server=Server(('127.0.0.1',port),v19.v18.ORIGINAL,v19.v18.BASE/'YEREL_SUNUCU',f)
    print(f'[V20] http://127.0.0.1:{port}/__local__/',flush=True)
    try:server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:server.server_close()

def start(port):
    if fetch(port):return print(f'[V20] Zaten acik: http://127.0.0.1:{port}/__local__/')
    with socket.socket() as sk:
        if sk.connect_ex(('127.0.0.1',port))==0:raise SystemExit('[HATA] Port meşgul')
    v19.v18.LOGS.mkdir(parents=True,exist_ok=True)
    v19.v18.v17.prepare_env()
    with (v19.v18.LOGS/'browser2_v20_server.log').open('ab') as log:
        subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'serve','--port',str(port)],
            stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
            env=os.environ.copy(),start_new_session=True,close_fds=True)
    for _ in range(40):
        if fetch(port):return print(f'[V20] Acildi: http://127.0.0.1:{port}/__local__/')
        time.sleep(.2)
    raise SystemExit('[HATA] V20 baslatilamadi; LOGS/browser2_v20_server.log')

def main():
    a=argparse.ArgumentParser()
    a.add_argument('mode',nargs='?',default='start',choices=['start','serve','rapor','selftest'])
    a.add_argument('--port',type=int,default=PORT)
    q=a.parse_args()
    if not 1024<=q.port<65536:raise SystemExit('invalid port')
    {'start':start,'serve':serve,'rapor':report,'selftest':lambda port:selftest()}[q.mode](q.port)

if __name__=='__main__':main()
