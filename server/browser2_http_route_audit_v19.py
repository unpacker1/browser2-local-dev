#!/usr/bin/env python3
"""V19 safe HTTP failure-route audit for the independently written local server.
Never saves cookies, tokens, headers, queries, character names, IPs or WS payloads.
Original Browser2 game files are read-only and never redistributed.
"""
from __future__ import annotations
import argparse
import collections
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.error
import urllib.request
import browser2_baglanti_duzeltme_v18 as v18

PORT=8900
ERROR_LIMIT=100
STATIC_SEGMENT=re.compile(r'^[a-zA-Z][a-zA-Z0-9_.-]{0,30}$')
SENSITIVE=re.compile(r'(?i)(token|secret|password|session|cookie|authorization|passwd|credential|email|private|key)')

def _segment(s):
    if not STATIC_SEGMENT.fullmatch(s) or SENSITIVE.search(s):
        return ':value'
    return s

def safe_route(raw):
    path=urllib.parse.unquote(urllib.parse.urlsplit(raw).path)
    if path in ('/','/health'):return path
    if not path.startswith('/') or '\\' in path or '\x00' in path:return '/[invalid]'
    parts=path.strip('/').split('/')
    first=parts[0]
    if not STATIC_SEGMENT.fullmatch(first) or SENSITIVE.search(first):return '/[redacted]'
    if first in ('world','instance'):
        return '/'+first+'/:world'+('/'+'/'.join(_segment(p) for p in parts[2:5]) if len(parts)>2 else '')
    if first in ('auth','chars','catalogs','assets','locale','locales','i18n','sound','sounds','audio','fonts','ui','textures'):
        if first=='assets':
            category=_segment(parts[1]) if len(parts)>1 else '[root]'
            ext=Path(path).suffix.lower()
            if not re.fullmatch(r'\.[a-z0-9]{1,7}',ext):ext='[none]'
            return '/assets/'+category+'/*'+ext
        return '/'+'/'.join(_segment(p) for p in parts[:4])+('/*' if len(parts)>4 else '')
    return '/'+first+'/*' if len(parts)>1 else '/'+first

class Handler(v18.Handler):
    server_version='Browser2Local/19'
    def send_response(self,code,message=None):
        if code>=400:
            route=safe_route(self.path)
            with self.server.error_lock:
                key=(self.command,str(code),route)
                if key in self.server.error_counts or len(self.server.error_counts)<ERROR_LIMIT:
                    self.server.error_counts[key]+=1
        return super().send_response(code,message)
    def do_GET(self):
        if urllib.parse.urlsplit(self.path).path=='/__local__/v19':
            with self.server.error_lock:
                errors=[{'method':m,'http_status':int(c),'route_shape':p,'requests':n}
                        for (m,c,p),n in self.server.error_counts.most_common(ERROR_LIMIT)]
            return self.json(200,{
                'version':'19.0','original_client_unchanged':True,
                'error_routes':errors,
                'status_by_route':[{'route_class':k,'http_status':int(c),'requests':n}
                                   for (k,c),n in sorted(self.server.class_status.items())],
                'trace_counters':dict(self.server.trace.counters),
                'backend_metrics':dict(self.server.metrics),
                'launcher_events':dict(self.server.launcher_events),
                'active_world_connections':self.server.active,
                'privacy':'Coarsely grouped routes only. No queries, headers, IPs, raw paths, credentials or websocket payloads.',
                'limitation':'Offline tests are not evidence of successful real 3D gameplay.'})
        return super().do_GET()

class Server(v18.Server):
    def __init__(self,bind,root,state,fetcher):
        super().__init__(bind,root,state,fetcher)
        self.error_counts=collections.Counter()
        self.error_lock=threading.Lock()
        self.RequestHandlerClass=Handler

def report(port=PORT):
    d=v18.v17.fetch_json('/__local__/v19',port)
    if not d or d.get('version')!='19.0':raise SystemExit('[HATA] V19 calismiyor; once start.')
    v18.REPORTS.mkdir(parents=True,exist_ok=True)
    p=v18.REPORTS/'browser2_v19_http_hata_raporu.json'
    p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
    print('[RAPOR]',p)
    print('[BASLATICI]',d.get('launcher_events'))
    print('[GAME]',{k:v for k,v in d.get('backend_metrics',{}).items() if k.startswith('game_join')})
    for x in d.get('error_routes',[])[:25]:
        print('[HTTP]',x['requests'],x['method'],x['http_status'],x['route_shape'])

def selftest():
    assert safe_route('/auth/verify?token=SECRET')=='/auth/verify'
    assert safe_route('/chars/123e4567-e89b-12d3-a456-426614174000')=='/chars/:value'
    assert safe_route('/world/map_a2/catalogs/maps?token=abc')=='/world/:world/catalogs/maps'
    assert safe_route('/assets/foo-234/secret.jpg?a=1')=='/assets/foo-234/*.jpg'
    with tempfile.TemporaryDirectory() as td:
        t=Path(td);root=t/'original';root.mkdir()
        (root/'index.html').write_text('original unchanged')
        (root/'assets').mkdir()
        prior=os.environ.get('BROWSER2_PRIVATE_DB')
        os.environ['BROWSER2_PRIVATE_DB']=str(t/'private/local.sqlite3')
        try:
            f=v18.v17.v16.Fetcher(root,t/'overlay')
            s=Server(('127.0.0.1',0),root,t/'state',f)
            th=threading.Thread(target=s.serve_forever,daemon=True);th.start()
            try:
                u='http://127.0.0.1:'+str(s.server_port)
                for path,code in (('/missing_route?token=secret',404),('/chars/list',401)):
                    try:urllib.request.urlopen(u+path,timeout=3)
                    except urllib.error.HTTPError as e:assert e.code==code
                    else:raise AssertionError('Expected HTTP error')
                with urllib.request.urlopen(u+'/__local__/v19') as r:d=json.load(r)
                assert d['version']=='19.0'
                assert any(x['http_status']==404 and x['route_shape']=='/missing_route' for x in d['error_routes'])
                assert any(x['http_status']==401 and x['route_shape']=='/chars/list' for x in d['error_routes'])
                assert 'secret' not in json.dumps(d).lower()
                with urllib.request.urlopen(u+'/') as r:assert r.read()==b'original unchanged'
            finally:s.shutdown();s.server_close()
        finally:
            if prior is None:os.environ.pop('BROWSER2_PRIVATE_DB',None)
            else:os.environ['BROWSER2_PRIVATE_DB']=prior
    print('[SELFTEST OK] Safe 401/404 route shapes and read-only original client')

def serve(port):
    v18.v17.prepare_env()
    for p in (v18.REPORTS,v18.LOGS,v18.BASE/'YEREL_SUNUCU',v18.v17.PRIVATE):
        p.mkdir(parents=True,exist_ok=True)
    if not v18.v17.v16.prev.audit(v18.ORIGINAL):
        raise SystemExit('[HATA] Orijinal istemci arsivi bulunamadi')
    f=v18.v17.v16.Fetcher(v18.ORIGINAL,v18.BASE/'YEREL_SUNUCU/browser2_v16_map_overlay')
    s=Server(('127.0.0.1',port),v18.ORIGINAL,v18.BASE/'YEREL_SUNUCU',f)
    print('[V19] http://127.0.0.1:'+str(port)+'/__local__/',flush=True)
    try:s.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:s.server_close()

def start(port):
    if v18.v17.fetch_json('/__local__/v19',port):
        print('[V19] Zaten acik: http://127.0.0.1:'+str(port)+'/__local__/');return
    with socket.socket() as sk:
        if sk.connect_ex(('127.0.0.1',port))==0:raise SystemExit('[HATA] Port baska uygulamada kullanimda')
    v18.LOGS.mkdir(parents=True,exist_ok=True)
    v18.v17.prepare_env()
    with (v18.LOGS/'browser2_v19_server.log').open('ab') as log:
        subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'serve','--port',str(port)],
            stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
            env=os.environ.copy(),start_new_session=True,close_fds=True)
    for _ in range(40):
        if v18.v17.fetch_json('/__local__/v19',port):
            print('[V19] Acildi: http://127.0.0.1:'+str(port)+'/__local__/');return
        time.sleep(.2)
    raise SystemExit('[HATA] V19 baslatilamadi. LOGS/browser2_v19_server.log')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=('selftest','start','serve','rapor'),nargs='?',default='start')
    p.add_argument('--port',type=int,default=PORT)
    a=p.parse_args()
    if not 1024<=a.port<65536:raise SystemExit('invalid port')
    if a.action=='selftest':selftest()
    elif a.action=='start':start(a.port)
    elif a.action=='serve':serve(a.port)
    else:report(a.port)

if __name__=='__main__':main()
