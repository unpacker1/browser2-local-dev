#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V17 read-only diagnostics for the V16.1 standalone local server.
No account fields, session tokens, headers, queries, WebSocket payloads or IPs logged.
Original browser2.to static assets are never modified. This server remains a partial
independent implementation, not the original private GAME server.
"""
from __future__ import annotations
import argparse, collections, json, os, re, socket, subprocess, sys, threading, time
import urllib.error, urllib.parse, urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer

import browser2_local_map_sync_v16 as v16

BASE=Path.home()/'storage/downloads/BROWSER2_BAGIMSIZ'
TESTLER=BASE/'TESTLER'
REPORTS=BASE/'RAPORLAR'
LOGS=BASE/'LOGS'
OVERLAY_STATE=BASE/'YEREL_SUNUCU'
PRIVATE=Path.home()/'BROWSER2_LOCAL_SERVER_DATA'
ORIGINAL=BASE/'public_assets/browser2.to'
PORT=8898

class Trace:
    def __init__(self):
        self.lock=threading.RLock();self.counters=collections.Counter();self.events=collections.deque(maxlen=80)
    def add(self,kind,status=None):
        with self.lock:
            self.counters[kind]+=1
            if status is not None:self.counters[f'http_{status}']+=1
            self.events.append({'n':sum(self.counters.values()),'kind':kind,'status':status})
    def snapshot(self):
        with self.lock:return {'counters':dict(self.counters),'events':list(self.events)}

def category(raw,method):
    # Path only. Ignore query and never record user-provided path values.
    p=urllib.parse.unquote(urllib.parse.urlsplit(raw).path)
    if p=='/__local__/bootstrap':return 'local_bootstrap'
    if p.startswith('/__local__/'):return None
    if p=='/':return 'original_page'
    if p=='/auth/login':return 'auth_login'
    if p=='/chars/list':return 'characters_list'
    if p=='/chars/token':return 'join_token'
    if p=='/catalogs/maps' or re.fullmatch(r'/world/[A-Za-z0-9_@-]+/catalogs/maps',p):return 'world_map_catalog'
    if re.fullmatch(r'/world/[A-Za-z0-9_@-]+',p):return 'world_websocket' if method=='GET' else 'world_http'
    if p=='/assets/packs/boot-manifest.json':return 'boot_manifest'
    if p.startswith('/assets/maps/'):
        if re.fullmatch(r'/assets/maps/map_a2/(map\.json|heightmap\.bin|collision\.bin|env\.json)',p):
            return 'map_a2_'+p.rsplit('/',1)[-1]
        return 'other_map_asset'
    if p.startswith('/assets/'):
        ext=Path(p).suffix.lower()
        return 'static_'+(ext[1:] if ext in {'.json','.bin','.glb','.ktx2','.wasm','.js','.css','.webp','.png','.jpg','.gif','.wav','.mp3','.mp4','.webm'} else 'other')
    return 'other_http'

class Handler(v16.Handler):
    server_version='Browser2Local/17'
    def send_response(self,code,message=None):
        kind=category(self.path,self.command)
        if kind is not None:
            self.server.trace.add(kind,code)
        return super().send_response(code,message)
    def do_GET(self):
        if urllib.parse.urlsplit(self.path).path=='/__local__/v17':
            self.json(200,{'version':'17.0','mode':'protocol_and_asset_metadata_only',
              'trace':self.server.trace.snapshot(),
              'backend_metrics':dict(self.server.metrics),
              'active_world_connections':self.server.active,
              'original_files_modified':False,
              'disclaimer':'No tokens, credentials, URLs with queries, IPs, payloads, headers or world packet bytes collected. Game server remains partial.'})
            return
        return super().do_GET()
    def world_loop(self,ws):
        self.server.trace.add('world_loop_started')
        try:return super().world_loop(ws)
        finally:self.server.trace.add('world_loop_closed')

class Server(v16.Server):
    def __init__(self,bind,root,state,fetcher):
        super().__init__(bind,root,state,fetcher,lazy_map_sync=False)
        self.trace=Trace(); self.RequestHandlerClass=Handler

def prepare_env():
    os.environ['BROWSER2_PUBLIC_STATE']=str(OVERLAY_STATE)
    os.environ['BROWSER2_PRIVATE_DB']=str(PRIVATE/'local.sqlite3')
    os.environ['BROWSER2_REPORT_DIR']=str(REPORTS)

def fetch_json(path,port=PORT,timeout=3):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}',timeout=timeout) as f:return json.load(f)
    except (ValueError,OSError,TimeoutError,urllib.error.HTTPError):return None

def static_check(path,port=PORT):
    req=urllib.request.Request(f'http://127.0.0.1:{port}{path}',method='HEAD')
    try:
        with urllib.request.urlopen(req,timeout=6) as r:
            return {'status':r.status,'size':int(r.headers.get('Content-Length','0') or 0)}
    except urllib.error.HTTPError as e:return {'status':e.code}
    except (OSError,TimeoutError):return {'status':'not_reachable'}

def interpretation(trace,metrics,missing):
    c=trace.get('counters',{});m=metrics or {};out=[]
    if not c.get('original_page',0):out.append('Orijinal istemci bu sunucudan henuz yuklenmemis; oyunu 8898 uzerinden dene.')
    if c.get('local_bootstrap',0)==0:out.append('Yerel oynat butonundan basarili hesap/karakter hazirlama istegi henuz gorulmedi.')
    if c.get('local_bootstrap',0)>0 and not c.get('world_websocket',0):out.append('Giris basladi fakat WebSocket dunya baglantisi gorulmedi; istemci kaynak/oturum akisina bakilmali.')
    if c.get('world_websocket',0)>0 and not m.get('game_join_accepted',0):out.append('WebSocket denendi ama JoinAccepted sayaci sifir; join token ve sinif/empire esitligi kontrol edilmeli.')
    if m.get('game_join_rejected',0):out.append('GAME join reddi mevcut; yerel sunucu tarafinda token veya karakter baglantisi sorunu olabilir.')
    if m.get('game_join_accepted',0):out.append('GAME join sunucu tarafinda kabul edilmis. Bu oyun dunyasinin cizildigini kanitlamaz.')
    if missing and missing.get('unique',0):out.append('Statik 404 kayitlari var; eksik kaynaklar devam ediyor.')
    if m.get('game_join_accepted',0) and not (missing or {}).get('unique',0):out.append('Join var ve kayitli statik 404 yok. Dunya hala acilmiyorsa oncelik GAME snapshot/renderer/hazirlik akisi.')
    return out

def report(port=PORT):
    REPORTS.mkdir(parents=True,exist_ok=True)
    live=fetch_json('/__local__/v17',port)
    if not live:
        print(f'[HATA] V17 sunucusuna ulasilamadi: 127.0.0.1:{port}')
        return False
    miss=fetch_json('/__local__/missing',port)
    mapcheck=fetch_json('/__local__/v16',port)
    manifest=fetch_json('/__local__/v15',port)
    cores={f:static_check('/assets/maps/map_a2/'+f,port) for f in ('map.json','heightmap.bin','collision.bin','env.json')}
    metrics=live.get('backend_metrics',{});trace=live.get('trace',{})
    result={
        'version':'17.0','original_client_untouched':True,'local_port':port,
        'game_backend':'partial independent compatibility server, not original private backend',
        'trace':trace,'backend_metrics':metrics,'active_world_connections':live.get('active_world_connections',0),
        'map_static_check':cores,'manifest':manifest,'map_overlay_health':mapcheck,
        'missing_static':miss,'conclusions':interpretation(trace,metrics,miss),
        'privacy':'Route classes/statuses and safe counters only; no full URLs, query, headers, packets, IPs or credentials.'
    }
    p=REPORTS/'browser2_v17_canli_oyun_tanisi.json'
    p.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('[RAPOR]',p)
    print('[GAME]',{k:metrics.get(k,0) for k in ('game_join_accepted','game_join_rejected')})
    print('[IZ]',{k:v for k,v in trace.get('counters',{}).items() if k in ('original_page','local_bootstrap','world_websocket','world_loop_started','world_loop_closed','boot_manifest','world_map_catalog','join_token','characters_list')})
    print('[HARITA]',{k:v['status'] for k,v in cores.items()})
    print('[404]',(miss or {}).get('unique','bilinmiyor'))
    for x in result['conclusions']:print('[SONUC]',x)
    return True

def selftest():
    import tempfile
    assert category('/auth/login?secret=abc','POST')=='auth_login'
    assert category('/assets/maps/map_a2/map.json?token=secret','GET')=='map_a2_map.json'
    assert category('/world/map1','GET')=='world_websocket'
    assert category('/__local__/v17','GET') is None
    t=Trace();t.add('original_page',200);t.add('local_bootstrap',200);t.add('world_websocket',101)
    assert t.snapshot()['counters']['http_101']==1
    with tempfile.TemporaryDirectory() as td:
        p=Path(td);orig=p/'orig';state=p/'state';over=p/'overlay'
        (orig/'assets/maps/map_a2').mkdir(parents=True)
        (orig/'assets/maps/map_a2/map.json').write_text('{"tiles":[]}')
        (orig/'index.html').write_text('test')
        f=v16.Fetcher(orig,over)
        os.environ['BROWSER2_PRIVATE_DB']=str(p/'private.sqlite3')
        os.environ['BROWSER2_PUBLIC_STATE']=str(state)
        s=Server(('127.0.0.1',0),orig,state,f)
        th=threading.Thread(target=s.serve_forever,daemon=True);th.start()
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{s.server_port}/') as r:assert r.status==200
            with urllib.request.urlopen(f'http://127.0.0.1:{s.server_port}/__local__/v17') as r:body=json.load(r)
            assert body['trace']['counters']['original_page']==1
            assert static_check('/assets/maps/map_a2/map.json',s.server_port)['status']==200
        finally:s.shutdown();s.server_close()
    print('[SELFTEST OK] Safe path classes; HTTP trace; local trace endpoint; map HEAD; original source untouched')

def serve(port=PORT):
    for p in (REPORTS,LOGS,OVERLAY_STATE,PRIVATE):p.mkdir(parents=True,exist_ok=True)
    prepare_env()
    if not v16.prev.audit(ORIGINAL):raise SystemExit('[HATA] Orijinal Browser2 istemci dosyalari bulunamadi')
    fetcher=v16.Fetcher(ORIGINAL,OVERLAY_STATE/'browser2_v16_map_overlay')
    s=Server(('127.0.0.1',port),ORIGINAL,OVERLAY_STATE,fetcher)
    print('[V17 OYUN] http://127.0.0.1:'+str(port)+'/__local__/',flush=True)
    print('[UYARI] Orijinal oyun sunucusu DEGIL, kismi yerel GAME. Dosyalar degistirilmez.',flush=True)
    try:s.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:pass
    finally:s.server_close()

def start(port=PORT):
    found=fetch_json('/__local__/v17',port)
    if found:return print('[V17] Zaten acik:',f'http://127.0.0.1:{port}/__local__/')
    # Do not kill other servers or hijack a port we do not own.
    with socket.socket() as sk:
        if sk.connect_ex(('127.0.0.1',port))==0:raise SystemExit('[HATA] Port dolu, mevcut sunucuya dokunulmadi')
    LOGS.mkdir(parents=True,exist_ok=True);prepare_env()
    log=LOGS/'browser2_v17_server.log'
    with log.open('ab') as f:
        subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'serve','--port',str(port)],
          stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,env=os.environ.copy(),
          start_new_session=True,close_fds=True)
    for _ in range(30):
        if fetch_json('/__local__/v17',port,1):
            print('[V17] Sunucu basladi:',f'http://127.0.0.1:{port}/__local__/')
            return
        time.sleep(.2)
    raise SystemExit('[HATA] Sunucu baslamadi. Gunluk: '+str(log))

def main():
    ap=argparse.ArgumentParser(description='Browser2 V17 safe local game phase diagnostics')
    ap.add_argument('action',choices=['selftest','start','serve','rapor'],nargs='?',default='start')
    ap.add_argument('--port',type=int,default=PORT)
    a=ap.parse_args()
    if not (1024<=a.port<65536):raise SystemExit('port invalid')
    if a.action=='selftest':selftest()
    elif a.action=='start':start(a.port)
    elif a.action=='serve':serve(a.port)
    else:report(a.port)
if __name__=='__main__':main()
