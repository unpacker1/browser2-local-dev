#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Browser2 V15: independent server-only boot-manifest fallback + missing static audit.
Original Browser2 JS/WASM/GLB/KTX2/map files remain byte-for-byte untouched.
No remote origin or account/network access. V14 is bundled unmodified as a base.
"""
from __future__ import annotations
import argparse
import collections
import json
import logging
from pathlib import Path
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request

import browser2_local_base_v14 as base

VERSION='15.0'
ROOT=base.ROOT
STATE=base.STATE
PORT=8895
PACK_PATH='/assets/packs/boot-manifest.json'
PACKLESS={'version':2,'packs':{}}

class Handler(base.Handler):
    server_version='Browser2Local/15'

    def do_GET(self):
        path=urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if path=='/__local__/missing':
            with self.server.missing_lock:
                pairs=sorted(self.server.missing_static.items(),key=lambda x:(-x[1],x[0]))
            self.json(200,{'version':VERSION,'mode':'local_missing_static_only',
                           'requests':sum(v for _,v in pairs),'unique':len(pairs),
                           'missing':[{'path':p,'hits':n} for p,n in pairs],
                           'disclaimer':'GET paths only. No queries, cookies, tokens or HTTP headers.'})
            return
        if path=='/__local__/v15':
            p=(self.server.root/PACK_PATH.lstrip('/'))
            self.json(200,{'version':VERSION,'boot_manifest':'original_file' if p.is_file() else 'synthetic_packless_fallback',
                           'original_files_modified':False,'maps_registry':(self.server.root/'assets/maps/_registry.json').is_file(),
                           'map_a2_json':(self.server.root/'assets/maps/map_a2/map.json').is_file(),
                           'game_is_partial':True})
            return
        super().do_GET()

    def static(self,p):
        # The ORIGINAL client accepts version:2 with empty packs and then falls
        # back to individual asset paths. Only synthesize when no original exists.
        if p==PACK_PATH and not (self.server.root/PACK_PATH.lstrip('/')).is_file():
            return self.sendbody(200,base.jbytes(PACKLESS),extra={'X-Local-Compat':'V15-packless-fallback',
                       'Cache-Control':'no-store'})
        try:
            return super().static(p)
        except base.Error as exc:
            if exc.code==404 and p.startswith('/assets/'):
                # Sanitize and bound: omit URL query, auth, and unbounded values.
                # Keep only permitted static asset path chars; paths are untrusted.
                if len(p)<=500 and all(c.isalnum() or c in '/._-@' for c in p):
                    with self.server.missing_lock:
                        if p in self.server.missing_static or len(self.server.missing_static)<3000:
                            self.server.missing_static[p]+=1
            raise

class Server(base.Server):
    def __init__(self,bind,root,state):
        super().__init__(bind,root,state)
        self.missing_lock=threading.Lock()
        self.missing_static=collections.Counter()
        self.RequestHandlerClass=Handler

def audit(root):
    source=base.check_sources(root)
    extra={
        'boot_manifest_original':(root/PACK_PATH.lstrip('/')).is_file(),
        'maps_registry':(root/'assets/maps/_registry.json').is_file(),
        'map_a2_json':(root/'assets/maps/map_a2/map.json').is_file(),
        'catalog_main':(root/'assets/catalogs/catalog.json').is_file(),
        'catalog_mobs':(root/'assets/catalogs/mobs.json').is_file(),
        'catalog_skills':(root/'assets/catalogs/skills.json').is_file(),
        'packless_manifest_used':not (root/PACK_PATH.lstrip('/')).is_file(),
    }
    print('[ORIGINAL CLIENT]',source,flush=True)
    print('[ASSET AUDIT]',extra,flush=True)
    print('[EXPLAIN] Empty local pack index enables ORIGINAL per-file fallback only; it is NOT the original boot-manifest.',flush=True)
    if not extra['maps_registry']:
        print('[WARN] Original map registry is missing. World may fail at terrain phase, regardless of manifest fix.',flush=True)
    return all(source.values())

def report(port,state):
    url=f'http://127.0.0.1:{port}/__local__/missing'
    try:
        with urllib.request.urlopen(url,timeout=5) as f:
            data=json.load(f)
    except (urllib.error.URLError,TimeoutError,ValueError) as e:
        print('[ERROR] Local V15 server is not reachable:',type(e).__name__)
        return False
    state.mkdir(parents=True,exist_ok=True)
    report_dir=Path(__import__('os').environ.get('BROWSER2_REPORT_DIR',str(state))).expanduser();report_dir.mkdir(parents=True,exist_ok=True)
    p=report_dir/'browser2_v15_missing_static.json'
    p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print('[MISSING STATIC]',data['unique'],'paths,',data['requests'],'requests')
    print('[REPORT]',p)
    for r in data['missing'][:15]:print('[404]',r['hits'],r['path'])
    return True

def selftest():
    # Existing V14 test verifies AUTH, SQLite, WebSocket and protocol binary frames.
    base.selftest()
    with tempfile.TemporaryDirectory() as temp:
        t=Path(temp); root=t/'static';state=t/'state';(root/'assets').mkdir(parents=True)
        (root/'index.html').write_text('<!doctype html><title>fixture</title>',encoding='utf-8')
        s=Server(('127.0.0.1',0),root,state)
        th=threading.Thread(target=s.serve_forever,daemon=True);th.start()
        u=f'http://127.0.0.1:{s.server_port}'
        try:
            with urllib.request.urlopen(u+PACK_PATH,timeout=3) as f:
                assert f.status==200 and f.headers.get('X-Local-Compat')=='V15-packless-fallback'
                assert json.load(f)==PACKLESS
            # Do not fabricate other asset paths.
            try:urllib.request.urlopen(u+'/assets/maps/_registry.json',timeout=3)
            except urllib.error.HTTPError as e:assert e.code==404
            else:raise AssertionError('Unexpected map registry')
            with urllib.request.urlopen(u+'/__local__/missing',timeout=3) as f:
                r=json.load(f)
            assert r['unique']==1 and r['missing'][0]['path']=='/assets/maps/_registry.json'
            (root/'assets/packs').mkdir()
            original=b'{"version":2,"packs":{"core":"original.pack"},"worldShared":{}}'
            (root/PACK_PATH.lstrip('/')).write_bytes(original)
            with urllib.request.urlopen(u+PACK_PATH,timeout=3) as f:
                assert f.status==200 and not f.headers.get('X-Local-Compat') and f.read()==original
            with urllib.request.urlopen(u+'/__local__/v15',timeout=3) as f:
                assert json.load(f)['boot_manifest']=='original_file'
        finally:
            s.shutdown();s.server_close()
    print('[SELFTEST OK] V14 AUTH/GAME + V15 packless index + unmodified original passthrough + 404 audit')

def main():
    p=argparse.ArgumentParser(description='Browser2 local AUTH/GAME V15: missing boot manifest compatibility layer')
    p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--state',type=Path,default=STATE)
    p.add_argument('--port',type=int,default=PORT)
    p.add_argument('--selftest',action='store_true')
    p.add_argument('--audit',action='store_true')
    p.add_argument('--report',action='store_true')
    p.add_argument('--serve',action='store_true')
    a=p.parse_args()
    if a.selftest:
        selftest();return
    root=a.root.expanduser().resolve(); state=a.state.expanduser().resolve()
    if a.report:
        report(a.port,state);return
    if a.audit or a.serve:
        if not audit(root):raise SystemExit('ERROR: Original Browser2 client files are incomplete; no files changed.')
    if not a.serve:return
    if not 1024<=a.port<=65535:raise SystemExit('Invalid port')
    logging.basicConfig(level=logging.WARNING,format='%(levelname)s %(message)s')
    server=Server(('127.0.0.1',a.port),root,state)
    print(f'[V15 LOCAL] http://127.0.0.1:{a.port}/__local__/',flush=True)
    print(f'[V15 CHECK] http://127.0.0.1:{a.port}/__local__/v15',flush=True)
    print(f'[V15 MISSING] http://127.0.0.1:{a.port}/__local__/missing',flush=True)
    print('[SECURITY] localhost only; original client assets read-only, original site credentials not used',flush=True)
    try:server.serve_forever(poll_interval=.3)
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
