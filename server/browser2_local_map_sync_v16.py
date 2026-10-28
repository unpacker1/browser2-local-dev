#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Browser2 V16: original public map asset sync + read-only overlay for V15.
No tampering with original client, game protocol, account traffic or base archive.
Only static /assets/maps/* from https://browser2.to, no auth/cookies/session.
"""
from __future__ import annotations
import argparse
import collections
import hashlib
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import browser2_local_stack_v15 as prev
import browser2_local_base_v14 as base

VERSION='16.0'
ROOT=base.ROOT
STATE=base.STATE
PORT=8896
ORIGIN='https://browser2.to'
CORE=('map.json','heightmap.bin','collision.bin','env.json')
MAX_BYTES=128*1024*1024
MAX_TOTAL=768*1024*1024
ALLOWED_EXT={'.json','.bin','.webp','.png','.jpg','.jpeg','.ktx2','.pack','.glb','.dds','.tga'}
MAX_PATH=500


def valid_path(p):
    if not isinstance(p,str) or len(p)>MAX_PATH or not p.startswith('/assets/maps/'):
        return False
    return bool(re.fullmatch(r'/assets/maps/[A-Za-z0-9_./@-]+',p)) and all(x not in ('.','..','') for x in p[1:].split('/')) and Path(p).suffix.lower() in ALLOWED_EXT


def asset_kind(path):
    ext=Path(path).suffix.lower()
    if ext=='.json':return 'json'
    if ext=='.webp':return 'webp'
    if ext=='.png':return 'png'
    if ext in ('.jpg','.jpeg'):return 'jpeg'
    if ext=='.ktx2':return 'ktx2'
    if ext=='.glb':return 'glb'
    return 'binary'


def validate_file(path,kind):
    n=path.stat().st_size
    if n<4:raise ValueError('too_short')
    with path.open('rb') as f:head=f.read(40)
    if head.lstrip().lower().startswith((b'<html',b'<!doctype',b'<?xml')):raise ValueError('html_or_xml_instead_of_asset')
    if kind=='json':
        with path.open('rb') as f:body=json.load(f)
        if not isinstance(body,(dict,list)):raise ValueError('unexpected_json_root')
        if isinstance(body,dict) and ('error' in body or 'message' in body) and not ('tiles' in body or 'textures' in body):
            raise ValueError('api_error_json_not_asset')
    elif kind=='webp' and not(head.startswith(b'RIFF') and head[8:12]==b'WEBP'):raise ValueError('bad_webp')
    elif kind=='png' and not head.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('bad_png')
    elif kind=='jpeg' and not head.startswith(b'\xff\xd8\xff'):raise ValueError('bad_jpeg')
    elif kind=='ktx2' and not head.startswith(b'\xabKTX 20\xbb\r\n\x1a\n'):raise ValueError('bad_ktx2')
    elif kind=='glb' and not head.startswith(b'glTF'):raise ValueError('bad_glb')
    elif kind=='binary' and (n<16 or head.startswith(b'{')):raise ValueError('suspicious_binary')
    return n


class SameHostRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self,origin):super().__init__();self.origin=urllib.parse.urlsplit(origin)
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        u=urllib.parse.urlsplit(newurl)
        if u.scheme!='https' or u.hostname!=self.origin.hostname or (u.port not in (None,443)):
            raise urllib.error.HTTPError(newurl,403,'refused_cross_origin_redirect',headers,fp)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


class Fetcher:
    def __init__(self,original,overlay,origin=ORIGIN,total_budget=MAX_TOTAL):
        self.original=Path(original).resolve();self.overlay=Path(overlay).resolve()
        self.origin=origin.rstrip('/')
        self.lock=threading.RLock()
        self.attempts={};self.bytes=0;self.total_budget=total_budget
        self.opener=urllib.request.build_opener(SameHostRedirect(self.origin))
    def file(self,p):return self.overlay/p.lstrip('/')
    def original_file(self,p):return self.original/p.lstrip('/')
    def fetch(self,p,force=False):
        if not valid_path(p):return {'path':str(p)[:60],'status':'invalid_path'}
        kind=asset_kind(p)
        # All state (attempt cache, budget, concurrent downloads) stays under lock.
        with self.lock:
            original=self.original_file(p);over=self.file(p)
            if original.is_file():
                try:return {'path':p,'status':'original_present','bytes':validate_file(original,kind)}
                except (OSError,ValueError) as e:return {'path':p,'status':'original_invalid','reason':str(e)}
            if over.is_file():
                try:return {'path':p,'status':'overlay_present','bytes':validate_file(over,kind)}
                except (OSError,ValueError):return {'path':p,'status':'overlay_invalid'}
            if self.bytes>=self.total_budget:return {'path':p,'status':'budget_exhausted'}
            if not force and p in self.attempts:return dict(self.attempts[p])
            url=self.origin+p
            tmp=None
            try:
                req=urllib.request.Request(url,headers={'User-Agent':'Browser2-local-static-integrity-check/16.0','Accept':'application/octet-stream,application/json,*/*;q=0.2'})
                with self.opener.open(req,timeout=12) as r:
                    cl=r.headers.get('Content-Length','')
                    if cl.isdigit() and int(cl)>min(MAX_BYTES,self.total_budget-self.bytes):raise ValueError('resource_exceeds_limit')
                    over.parent.mkdir(parents=True,exist_ok=True)
                    with tempfile.NamedTemporaryFile(dir=over.parent,prefix='.b2v16-',suffix='.partial',delete=False) as f:
                        tmp=Path(f.name);h=hashlib.sha256();size=0
                        while True:
                            data=r.read(131072)
                            if not data:break
                            size+=len(data)
                            if size>min(MAX_BYTES,self.total_budget-self.bytes):raise ValueError('resource_exceeds_limit')
                            f.write(data);h.update(data)
                        f.flush();os.fsync(f.fileno())
                    validate_file(tmp,kind)
                    # Never overwrite anything written concurrently by another owner.
                    if not over.exists():os.replace(tmp,over);tmp=None
                    else:raise ValueError('file_appeared_during_download')
                    self.bytes+=size
                    result={'path':p,'status':'downloaded','bytes':size,'sha256':h.hexdigest()}
            except urllib.error.HTTPError as exc:result={'path':p,'status':f'http_{exc.code}'}
            except urllib.error.URLError as exc:result={'path':p,'status':'network_error','reason':type(exc.reason).__name__}
            except (ValueError,OSError,TimeoutError) as exc:result={'path':p,'status':'invalid_or_failed','reason':str(exc)[:100]}
            finally:
                if tmp is not None:
                    try:tmp.unlink(missing_ok=True)
                    except OSError:pass
            self.attempts[p]=result
            return dict(result)


def inspect_registry(root):
    p=Path(root)/'assets/maps/_registry.json'
    if not p.is_file():return {'present':False,'map_a2':'unknown'}
    try:
        data=json.loads(p.read_bytes())
        if isinstance(data,list):
            rows=[r for r in data if isinstance(r,dict)]
            found=[r for r in rows if r.get('name')=='map_a2' or r.get('id')=='map_a2']
            return {'present':True,'entries':len(rows),'map_a2':'listed' if found else 'not_listed', 'parent':found[0].get('parent') if found else None}
        return {'present':True,'format':type(data).__name__,'map_a2':'unknown'}
    except (ValueError,OSError) as exc:return {'present':True,'error':type(exc).__name__,'map_a2':'unknown'}


def scan_map_json(root,overlay,map_id):
    p=Path(root)/f'assets/maps/{map_id}/map.json'
    if not p.is_file():p=Path(overlay)/f'assets/maps/{map_id}/map.json'
    if not p.is_file():return []
    try:data=json.loads(p.read_bytes())
    except (OSError,ValueError):return []
    hits=set()
    # Recursively gather only explicit map-static paths. No guesses or fabricated files.
    def visit(node):
        if isinstance(node,str):
            s=node.split('?',1)[0].split('#',1)[0]
            if s.startswith('/assets/maps/') and valid_path(s):hits.add(s)
            elif s.startswith('assets/maps/') and valid_path('/'+s):hits.add('/'+s)
        elif isinstance(node,list):
            for v in node:visit(v)
        elif isinstance(node,dict):
            for v in node.values():visit(v)
    visit(data)
    return sorted(hits)


def make_sync_report(fetcher,root,map_id='map_a2',expand=200):
    rows=[]
    reg=inspect_registry(root)
    names=list(CORE)
    # Source client requests map.json, heightmap.bin, collision.bin and env.json.
    # Parent terrain maps are resolved by the ORIGINAL client using _registry.json.
    for name in names:rows.append(fetcher.fetch(f'/assets/maps/{map_id}/{name}'))
    extra=scan_map_json(root,fetcher.overlay,map_id)
    for p in extra[:expand]:rows.append(fetcher.fetch(p))
    core_status={r['path']:r['status'] for r in rows[:4]}
    mandatory=all(core_status.get(f'/assets/maps/{map_id}/{x}') in ('original_present','overlay_present','downloaded') for x in ('map.json','heightmap.bin'))
    return {'version':VERSION,'map_id':map_id,'root':str(root),'registry':reg,'core':rows[:4],
            'map_json_references_seen':len(extra),'map_json_references_checked':min(len(extra),expand),
            'additional_assets':rows[4:],'bytes_downloaded_this_run':fetcher.bytes,
            'required_terrain_present':mandatory,'original_client_modified':False,
            'note':'Core assets are necessary but may not be sufficient for world entry. Original GAME server still only partial.'}


def serve_file(handler,path):
    n=path.stat().st_size
    mime=mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
    if path.suffix=='.bin':mime='application/octet-stream'
    if path.suffix=='.ktx2':mime='image/ktx2'
    start,end=0,n-1;status=200
    rg=handler.headers.get('Range','')
    if rg:
        m=re.fullmatch(r'bytes=(\d+)-(\d*)',rg)
        if not m:raise base.Error(416,'Invalid byte range')
        start=int(m.group(1));end=int(m.group(2)) if m.group(2) else end
        if start>=n or end<start:raise base.Error(416,'Invalid byte range')
        end=min(end,n-1);status=206
    handler.send_response(status)
    handler.send_header('Content-Type',mime)
    handler.send_header('X-Content-Type-Options','nosniff')
    handler.send_header('Accept-Ranges','bytes')
    handler.send_header('Content-Length',str(end-start+1))
    if status==206:handler.send_header('Content-Range',f'bytes {start}-{end}/{n}')
    handler.send_header('Connection','close');handler.end_headers();handler.close_connection=True
    if handler.command!='HEAD':
        with path.open('rb') as f:
            f.seek(start);rem=end-start+1
            while rem:
                chunk=f.read(min(131072,rem))
                if not chunk:break
                handler.wfile.write(chunk);rem-=len(chunk)


class Handler(prev.Handler):
    server_version='Browser2Local/16'
    def do_GET(self):
        p=urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if p=='/__local__/v16':
            f=self.server.fetcher
            self.json(200,{'version':VERSION,'map_id':'map_a2','overlay_present':sum(1 for a in f.overlay.rglob('*') if a.is_file()),
                           'attempt_statuses':dict(collections.Counter(a['status'] for a in f.attempts.values())),
                           'registry':inspect_registry(self.server.root),'original_static_unchanged':True,
                           'game': 'Partial independent protocol implementation, not the original private server'})
            return
        super().do_GET()
    def static(self,p):
        # The original file ALWAYS wins. No write of original source files.
        if p.startswith('/assets/maps/') and valid_path(p):
            orig=self.server.root/p.lstrip('/')
            if not orig.is_file():
                f=self.server.fetcher
                over=f.file(p)
                if not over.is_file() and self.server.lazy_map_sync and self.command!='HEAD':f.fetch(p)
                if over.is_file():
                    try:validate_file(over,asset_kind(p))
                    except (ValueError,OSError):pass
                    else:return serve_file(self,over)
        return super().static(p)


class Server(prev.Server):
    def __init__(self,bind,root,state,fetcher,lazy_map_sync=True):
        super().__init__(bind,root,state)
        self.fetcher=fetcher;self.lazy_map_sync=lazy_map_sync
        self.RequestHandlerClass=Handler


def selftest():
    import urllib.request
    import urllib.error
    base.selftest();prev.selftest()
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)/'original';overlay=Path(td)/'overlay';state=Path(td)/'state'
        (root/'assets/maps/map_a2').mkdir(parents=True)
        (root/'assets/maps/_registry.json').write_text('[{"name":"map_a2"}]')
        (root/'assets/maps/map_a2/map.json').write_text('{"tiles":[],"textures":[]}')
        (overlay/'assets/maps/map_a2').mkdir(parents=True)
        payload=b'HMAP'+bytes(range(64))
        (overlay/'assets/maps/map_a2/heightmap.bin').write_bytes(payload)
        ff=Fetcher(root,overlay)
        assert inspect_registry(root)['map_a2']=='listed'
        assert ff.fetch('/assets/maps/map_a2/map.json')['status']=='original_present'
        assert ff.fetch('/assets/maps/map_a2/heightmap.bin')['status']=='overlay_present'
        assert not valid_path('/assets/maps/../private.json')
        server=Server(('127.0.0.1',0),root,state,ff,False)
        th=threading.Thread(target=server.serve_forever,daemon=True);th.start()
        u=f'http://127.0.0.1:{server.server_port}'
        try:
            with urllib.request.urlopen(u+'/assets/maps/map_a2/heightmap.bin',timeout=3) as r:assert r.status==200 and r.read()==payload
            with urllib.request.urlopen(urllib.request.Request(u+'/assets/maps/map_a2/heightmap.bin',headers={'Range':'bytes=5-9'}),timeout=3) as r:
                assert r.status==206 and r.read()==payload[5:10]
            with urllib.request.urlopen(u+'/assets/maps/map_a2/map.json',timeout=3) as r:
                assert json.load(r)['tiles']==[]
            with urllib.request.urlopen(u+'/__local__/v16',timeout=3) as r:assert json.load(r)['original_static_unchanged']
            try:urllib.request.urlopen(u+'/assets/maps/map_a2/collision.bin',timeout=3)
            except urllib.error.HTTPError as e:assert e.code==404
            else:raise AssertionError('missing map incorrectly available')
        finally:server.shutdown();server.server_close()
    print('[SELFTEST OK] V14 and V15 + V16 original map priority, overlay, HTTP Range, no fake maps')


def main():
    ap=argparse.ArgumentParser(description='Browser2 V16: original map static sync, independent overlay server, no JS patches')
    ap.add_argument('--root',type=Path,default=ROOT)
    ap.add_argument('--state',type=Path,default=STATE)
    ap.add_argument('--port',type=int,default=PORT)
    ap.add_argument('--selftest',action='store_true')
    ap.add_argument('--audit',action='store_true')
    ap.add_argument('--sync',action='store_true',help='Download only original publicly available map assets into a separate overlay')
    ap.add_argument('--serve',action='store_true')
    ap.add_argument('--report',action='store_true')
    ap.add_argument('--no-lazy-sync',action='store_true',help='Disable map fetch on demand')
    ap.add_argument('--map',default='map_a2')
    ap.add_argument('--expand',type=int,default=300)
    a=ap.parse_args()
    if a.selftest:selftest();return
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',a.map):raise SystemExit('Invalid map name')
    if not (1024<=a.port<=65535):raise SystemExit('Invalid port')
    root=a.root.expanduser().resolve();state=a.state.expanduser().resolve()
    overlay=state/'browser2_v16_map_overlay'
    fetcher=Fetcher(root,overlay)
    if a.audit or a.sync or a.serve:
        if not prev.audit(root):raise SystemExit('Original Browser2 client missing - not starting')
        print('[V16 MAP REGISTRY]',inspect_registry(root),flush=True)
    if a.sync:
        result=make_sync_report(fetcher,root,a.map,min(1500,max(0,a.expand)))
        state.mkdir(parents=True,exist_ok=True)
        report_dir=Path(os.environ.get('BROWSER2_REPORT_DIR',str(state))).expanduser();report_dir.mkdir(parents=True,exist_ok=True)
        p=report_dir/'browser2_v16_map_sync_report.json'
        p.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
        print('[MAP SYNC REPORT]',p,flush=True)
        for r in result['core']:print('[MAP]',r['status'],r['path'],flush=True)
        print('[MAP CORE READY]',result['required_terrain_present'],'additional:',len(result['additional_assets']),flush=True)
    if a.report:
        from urllib.request import urlopen
        try:
            with urlopen(f'http://127.0.0.1:{a.port}/__local__/missing',timeout=5) as r:m=json.load(r)
            with urlopen(f'http://127.0.0.1:{a.port}/__local__/v16',timeout=5) as r:health=json.load(r)
            state.mkdir(parents=True,exist_ok=True)
            report_dir=Path(os.environ.get('BROWSER2_REPORT_DIR',str(state))).expanduser();report_dir.mkdir(parents=True,exist_ok=True)
            out=report_dir/'browser2_v16_runtime_report.json'
            out.write_text(json.dumps({'missing':m,'health':health},ensure_ascii=False,indent=2))
            print('[REPORT]',out,flush=True)
            for row in m['missing'][:30]:print('[404]',row['hits'],row['path'])
        except Exception as exc:print('[REPORT ERROR]',type(exc).__name__,str(exc)[:100])
    if not a.serve:return
    server=Server(('127.0.0.1',a.port),root,state,fetcher,not a.no_lazy_sync)
    logging.basicConfig(level=logging.WARNING)
    print(f'[LOCAL GAME V16] http://127.0.0.1:{a.port}/__local__/',flush=True)
    print(f'[MAP CHECK] http://127.0.0.1:{a.port}/__local__/v16',flush=True)
    print('[ORIGINAL FILES] unchanged; map overlay only; partial private GAME implementation',flush=True)
    try:server.serve_forever(.3)
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
