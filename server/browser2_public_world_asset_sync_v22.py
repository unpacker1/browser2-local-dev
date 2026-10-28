#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Browser2 V22: verify & locally cache missing PUBLIC world assets on demand.

Uses original Browser2 archive with absolute priority, unmodified. Only allows
certain public asset paths and HTTPS browser2.to, without session cookies,
credentials, queries, or request headers from the user's browser.
Does NOT create substitute assets or redistribute the game archive.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import io
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
import urllib.error
import urllib.parse
import urllib.request

import browser2_local_locale_sync_v21 as v21

VERSION="22.0"
PORT=8907
ROOT=v21.ROOT
BASE=v21.BASE
REPORTS=v21.REPORTS
LOGS=v21.LOGS
OVERLAY=BASE/'YEREL_SUNUCU/browser2_v22_world_overlay'
HOST="https://browser2.to"
MAX_SINGLE=64*1024*1024
MAX_TOTAL=384*1024*1024
CATALOGS=(
    '/assets/catalogs/catalog.json',
    '/assets/catalogs/skills.json',
    '/assets/catalogs/mobs.json',
    '/assets/catalogs/mob-collision.json',
    '/assets/catalogs/mobs-motion-index.json',
    '/assets/catalogs/guild-building-models.json',
)
RELATIVE=re.compile(r'^/assets/[A-Za-z0-9_./@-]{1,240}$')
VALID_BY_FOLDER={
    'catalogs':{'.json'},
    'scenery':{'.glb'},
    'trees':{'.glb'},
    'effects':{'.webp','.png','.ktx2'},
    'maps':{'.png','.webp','.jpg','.jpeg','.glb'},
}
SPECIAL='/assets/world/textures/special/spheremap.jpg'
BOOTSTRAP_ASSETS=CATALOGS+(SPECIAL,)

def allowed_path(path):
    if not isinstance(path,str) or not RELATIVE.fullmatch(path):return False
    segments=path[1:].split('/')
    if len(segments)<3 or any(x in ('.','..','') for x in segments):return False
    if path==SPECIAL:return True
    cat=segments[1]
    if cat not in VALID_BY_FOLDER:return False
    ext=Path(path).suffix.lower()
    if ext not in VALID_BY_FOLDER[cat]:return False
    if cat=='catalogs' and len(segments)!=3:return False
    return True

def validate(path):
    if not allowed_path(path):raise ValueError('disallowed_asset_path')
    return v21.v20.v19.v18.v17.v16.asset_kind(path)

def valid_file(file,path):
    kind=validate(path)
    return v21.v20.v19.v18.v17.v16.validate_file(Path(file),kind)

def local_asset(root,overlay,path):
    if not allowed_path(path):return None,'not_allowlisted'
    original=Path(root)/path.lstrip('/')
    if original.is_file():
        try:valid_file(original,path);return original,'original_present'
        except (ValueError,OSError):return None,'original_invalid'
    dst=Path(overlay)/path.lstrip('/')
    if dst.is_file():
        try:valid_file(dst,path);return dst,'overlay_present'
        except (ValueError,OSError):return None,'overlay_invalid'
    return None,'missing'

class PublicAssetFetcher:
    def __init__(self,root=ROOT,overlay=OVERLAY,remote=None,max_total=MAX_TOTAL):
        self.root=Path(root);self.overlay=Path(overlay)
        self.opener=remote or urllib.request.build_opener(v21.v20.v19.v18.v17.v16.SameHostRedirect(HOST))
        self.lock=threading.RLock()
        self.locks={}
        self.attempts={}
        self.counts=Counter()
        self.bytes=0
        self.total=max_total
        self.network_slots=threading.BoundedSemaphore(value=6)
    def _lock_for(self,path):
        with self.lock:
            if path not in self.locks:self.locks[path]=threading.Lock()
            return self.locks[path]
    def status(self):
        with self.lock:
            return {'bytes_downloaded_this_run':self.bytes,
                'statuses':dict(self.counts),
                'attempted':len(self.attempts),
                'attempt_results':list(self.attempts.values())[:200],
                'limits':{'per_asset_bytes':MAX_SINGLE,'total_bytes':self.total}}
    def fetch(self,path):
        if not allowed_path(path):return {'path_class':'disallowed','status':'invalid_path'}
        with self._lock_for(path):
            src,status=local_asset(self.root,self.overlay,path)
            if status in ('original_present','overlay_present'):
                return {'path':path,'status':status}
            if status in ('original_invalid','overlay_invalid'):
                return {'path':path,'status':status}
            with self.lock:
                if path in self.attempts:return self.attempts[path]
                if self.bytes>=self.total:return {'path':path,'status':'budget_exhausted'}
            dst=self.overlay/path.lstrip('/')
            temporary=None
            result=None
            with self.network_slots:
                try:
                    req=urllib.request.Request(HOST+path,headers={
                        'User-Agent':'Browser2-local-public-asset-check/22',
                        'Accept':'application/octet-stream,application/json,image/*;q=0.6'})
                    with self.opener.open(req,timeout=12) as r:
                        actual=urllib.parse.urlsplit(r.geturl())
                        if (actual.scheme!='https' or actual.hostname!='browser2.to'
                            or actual.port not in (None,443) or actual.path!=path or actual.query):
                            raise ValueError('unexpected_redirect')
                        size_header=r.headers.get('Content-Length','')
                        if size_header.isdigit() and int(size_header)>MAX_SINGLE:
                            raise ValueError('asset_exceeds_per_file_limit')
                        dst.parent.mkdir(parents=True,exist_ok=True)
                        with tempfile.NamedTemporaryFile(dir=dst.parent,
                            prefix='.browser2-public-',suffix='.partial',delete=False) as tmp:
                            temporary=Path(tmp.name);size=0;digest=hashlib.sha256()
                            while True:
                                data=r.read(131072)
                                if not data:break
                                size+=len(data)
                                if size>MAX_SINGLE:raise ValueError('asset_exceeds_per_file_limit')
                                tmp.write(data);digest.update(data)
                            tmp.flush();os.fsync(tmp.fileno())
                    valid_file(temporary,path)
                    with self.lock:
                        if self.bytes+size>self.total:
                            raise ValueError('asset_exceeds_total_budget')
                        if dst.exists():raise ValueError('asset_appeared_during_download')
                        os.replace(temporary,dst);temporary=None
                        self.bytes+=size
                    result={'path':path,'status':'downloaded','bytes':size,
                        'sha256':digest.hexdigest()}
                except urllib.error.HTTPError as e:
                    result={'path':path,'status':f'http_{e.code}'}
                except urllib.error.URLError:
                    result={'path':path,'status':'network_error'}
                except (OSError,ValueError,TimeoutError) as e:
                    result={'path':path,'status':'invalid_or_failed',
                        'reason':str(e)[:50] if isinstance(e,ValueError) else type(e).__name__}
                finally:
                    if temporary is not None:temporary.unlink(missing_ok=True)
            with self.lock:
                self.attempts[path]=result
                self.counts[result['status']]+=1
            return result

class Handler(v21.Handler):
    server_version='Browser2Local/22'
    def do_GET(self):
        p=urllib.parse.urlsplit(self.path).path
        if p=='/__local__/v22':
            return self.json(200,{'version':VERSION,
                'world_asset_cache':self.server.world_assets.status(),
                'catalogs':[dict(path=path,status=local_asset(
                    self.server.root,self.server.world_assets.overlay,path)[1]) for path in BOOTSTRAP_ASSETS],
                'original_files_modified':False,
                'warning':'Optional missing asset cache only; local GAME remains incomplete'})
        return super().do_GET()
    def static(self,p):
        if allowed_path(p):
            src,status=local_asset(self.server.root,self.server.world_assets.overlay,p)
            if status=='missing' and self.command!='HEAD':
                self.server.world_assets.fetch(p)
                src,status=local_asset(self.server.root,self.server.world_assets.overlay,p)
            if src is not None and status=='overlay_present':
                return v21.v20.v19.v18.v17.v16.serve_file(self,src)
        return super().static(p)

class Server(v21.Server):
    def __init__(self,bind,root,state,fetcher,locale_overlay=v21.OVERLAY,
        world_overlay=OVERLAY,world_fetcher=None):
        super().__init__(bind,root,state,fetcher,locale_overlay)
        self.world_assets=world_fetcher or PublicAssetFetcher(root,world_overlay)
        self.RequestHandlerClass=Handler

def catalog_sync():
    fetcher=PublicAssetFetcher()
    results=[fetcher.fetch(path) for path in BOOTSTRAP_ASSETS]
    REPORTS.mkdir(parents=True,exist_ok=True)
    p=REPORTS/'browser2_v22_catalog_sync.json'
    p.write_text(json.dumps({'version':VERSION,'results':results,
        'original_files_modified':False},indent=2,ensure_ascii=False),encoding='utf-8')
    print('[KATALOG SENKRON]',p)
    print('[SONUC]',dict(Counter(x['status'] for x in results)))
    for item in results:
        print('[KATALOG]',item['path'],item['status'])

def fetch_report(port):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/__local__/v22',timeout=3) as resp:
        d=json.load(resp)
    if d.get('version')!=VERSION:raise ValueError('Unexpected V22 version')
    return d

def report(port):
    try:d=fetch_report(port)
    except (OSError,ValueError):
        raise SystemExit('[HATA] V22 sunucusuna ulasilamadi')
    REPORTS.mkdir(parents=True,exist_ok=True)
    path=REPORTS/'browser2_v22_world_asset_raporu.json'
    path.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
    print('[WORLD]',path)
    print('[KATALOG]',[(x['path'],x['status']) for x in d['catalogs']])
    print('[CACHE]',d['world_asset_cache'])
    # Preserve prior V20.4 report instead of overwriting it.
    boot=v21.v20.fetch(port)
    if boot:
        boot_path=REPORTS/'browser2_v22_boot_raporu.json'
        boot_path.write_text(json.dumps(boot,ensure_ascii=False,indent=2),encoding='utf-8')
        print('[BOOT]',boot_path)
        print('[YUKLEME]',boot.get('events',[]))
        print('[GAME]',boot.get('backend_metrics',{}))

def selftest():
    assert allowed_path('/assets/catalogs/mobs-motion-index.json')
    assert allowed_path(SPECIAL)
    assert BOOTSTRAP_ASSETS[-1]==SPECIAL
    assert allowed_path('/assets/scenery/buildings/tree_101.glb')
    assert allowed_path('/assets/effects/spells/fire.webp')
    for path in ('/assets/../../local.sqlite3','/assets/catalogs/../../auth.json',
        '/assets/world/../local.sqlite3','/auth/login',
        '/assets/world/secret.jpg','/assets/catalogs/token.json.zip'):
        assert not allowed_path(path),path
    with tempfile.TemporaryDirectory() as td:
        test=Path(td);root=test/'original';overlay=test/'cache'
        root.mkdir();(root/'assets').mkdir()
        (root/'index.html').write_bytes(b'<html><head></head><body>ORIGINAL</body></html>')
        # No network: fixture substitutes only an in-memory fake HTTP response.
        class FakeResult(io.BytesIO):
            headers={}
            def geturl(self):return self.url
            def __enter__(self):return self
            def __exit__(self,*args):self.close()
        class FakeRemote:
            def open(self,req,timeout=0):
                result=FakeResult(b'{"motions":[{"id":1}]}')
                result.url=req.full_url
                return result
        f=PublicAssetFetcher(root,overlay,FakeRemote(),max_total=100000)
        a=f.fetch('/assets/catalogs/mobs-motion-index.json')
        assert a['status']=='downloaded',a
        src,status=local_asset(root,overlay,'/assets/catalogs/mobs-motion-index.json')
        assert status=='overlay_present' and json.load(src.open())['motions']
        orig=root/'assets/catalogs/mobs-motion-index.json'
        orig.parent.mkdir(parents=True);orig.write_bytes(b'{"original":true}')
        assert f.fetch('/assets/catalogs/mobs-motion-index.json')['status']=='original_present'
        assert orig.read_bytes()==b'{"original":true}'
        previous=os.environ.get('BROWSER2_PRIVATE_DB')
        os.environ['BROWSER2_PRIVATE_DB']=str(test/'private/local.sqlite3')
        try:
            map_fetcher=v21.v20.v19.v18.v17.v16.Fetcher(root,test/'maps')
            server=Server(('127.0.0.1',0),root,test/'state',map_fetcher,
                locale_overlay=test/'locale',world_overlay=overlay,world_fetcher=f)
            t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
            try:
                base=f'http://127.0.0.1:{server.server_port}'
                with urllib.request.urlopen(base+'/__local__/v22') as r:
                    assert json.load(r)['version']==VERSION
                with urllib.request.urlopen(base+'/assets/catalogs/mobs-motion-index.json') as r:
                    assert json.load(r)['original']
                with urllib.request.urlopen(base+'/') as r:
                    assert b'ORIGINAL' in r.read()
            finally:server.shutdown();server.server_close()
        finally:
            if previous is None:os.environ.pop('BROWSER2_PRIVATE_DB',None)
            else:os.environ['BROWSER2_PRIVATE_DB']=previous
    print('[SELFTEST OK] V22 verified public assets, bounded download, original priority, HTTP serving')

def serve(port):
    v21.v20.v19.v18.v17.prepare_env()
    for folder in (REPORTS,LOGS,OVERLAY,BASE/'YEREL_SUNUCU',v21.v20.v19.v18.v17.PRIVATE):
        folder.mkdir(parents=True,exist_ok=True)
    if not v21.v20.v19.v18.v17.v16.prev.audit(ROOT):
        raise SystemExit('[HATA] Original Browser2 source archive missing')
    maps=v21.v20.v19.v18.v17.v16.Fetcher(ROOT,BASE/'YEREL_SUNUCU/browser2_v16_map_overlay')
    server=Server(('127.0.0.1',port),ROOT,BASE/'YEREL_SUNUCU',maps)
    print(f'[V22] http://127.0.0.1:{port}/__local__/',flush=True)
    try:server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:server.server_close()

def alive(port):
    try:return fetch_report(port)['version']==VERSION
    except (OSError,ValueError):return False

def start(port):
    if alive(port):
        print(f'[V22] Zaten acik: http://127.0.0.1:{port}/__local__/');return
    with socket.socket() as s:
        if s.connect_ex(('127.0.0.1',port))==0:raise SystemExit('[HATA] Port already used')
    v21.v20.v19.v18.v17.prepare_env()
    LOGS.mkdir(parents=True,exist_ok=True)
    with (LOGS/'browser2_v22_server.log').open('ab') as out:
        subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'serve','--port',str(port)],
            stdin=subprocess.DEVNULL,stdout=out,stderr=subprocess.STDOUT,
            env=os.environ.copy(),start_new_session=True,close_fds=True)
    for _ in range(40):
        if alive(port):
            print(f'[V22] Acildi: http://127.0.0.1:{port}/__local__/');return
        time.sleep(.2)
    raise SystemExit('[HATA] See LOGS/browser2_v22_server.log')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('action',nargs='?',default='start',
        choices=('selftest','sync','start','serve','rapor'))
    p.add_argument('--port',type=int,default=PORT)
    a=p.parse_args()
    if not 1024<=a.port<=65535:raise SystemExit('Invalid port')
    if a.action=='selftest':selftest()
    elif a.action=='sync':catalog_sync()
    elif a.action=='start':start(a.port)
    elif a.action=='serve':serve(a.port)
    else:report(a.port)

if __name__=='__main__':main()
