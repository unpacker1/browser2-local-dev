#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V27 read-only manifest pack routing and privacy-safe loading diagnostics.

Does not edit original Browser2 JS/WASM/GLB/KTX2, archives, user sessions or
characters. Recognizes ONLY packs actually named in the original V28 manifest.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import browser2_local_base_v14 as base
import browser2_local_map_sync_v16 as v16
import browser2_gercek_oyun_tani_v17 as v17
import browser2_v28_local_site_v26 as v26

PORT=8899
PACK_BASE='/assets/packs/'
SAFE_PACK_RE=re.compile(r'[A-Za-z0-9_./@-]{1,220}\.pack')
SAFE_STATIC_RE=re.compile(r'/[A-Za-z0-9_./@+-]{1,240}\.(?:pack|bin|glb|ktx2|wasm|json|js|webp|png|jpg|mp3|ogg|wav)')
SAFE_PREFIXES=('/assets/','/packs/','/catalogs/','/maps/','/models/','/characters/','/textures/','/effects/','/sounds/','/ui/','/animations/')
MAX_SAMPLES=100


def canonical_pack_values(raw):
    """Flatten only manifest's 'packs' values, never arbitrary user paths."""
    values=set()
    def walk(obj):
        if isinstance(obj,dict):
            for value in obj.values():walk(value)
        elif isinstance(obj,list):
            for value in obj:walk(value)
        elif isinstance(obj,str) and SAFE_PACK_RE.fullmatch(obj):
            if all(part not in ('','.', '..') for part in obj.split('/')):
                values.add(obj)
    if isinstance(raw,dict):
        walk(raw.get('packs',{}))
    return values


class OriginalPackLookup:
    def __init__(self,root):
        self.root=Path(root).resolve()
        self.manifest=v26.read_json(self.root/'assets/packs/boot-manifest.json')
        self.names=canonical_pack_values(self.manifest)
        self.index={}
        for name in self.names:
            candidate=(self.root/'assets/packs'/(name+'.bin')).resolve()
            # Only filenames listed by the ORIGINAL manifest may be aliased.
            if candidate.is_relative_to(self.root/'assets/packs') and candidate.is_file():
                self.index[name]=candidate
        self.absent=sorted(self.names.difference(self.index))
        self.core=self.manifest.get('packs',{}).get('core') if isinstance(self.manifest,dict) else None

    def file_for_request(self,path):
        if not isinstance(path,str) or len(path)>310 or '\\' in path or '?' in path:
            return None
        if path.startswith(PACK_BASE):
            value=path[len(PACK_BASE):]
        elif path.startswith('/packs/'):
            value=path[len('/packs/'):]
        elif path.startswith('/'):
            value=path[1:]
        else:
            return None
        if value.endswith('.pack.bin'):
            value=value[:-4]
        if not SAFE_PACK_RE.fullmatch(value):
            return None
        if any(part in ('','.', '..') for part in value.split('/')):
            return None
        return self.index.get(value)

    def report(self):
        path=self.index.get(self.core)
        return {
            'manifestPresent':isinstance(self.manifest,dict),
            'manifestVersion':self.manifest.get('version') if isinstance(self.manifest,dict) else None,
            'manifestPackCount':len(self.names),
            'availablePackCount':len(self.index),
            'missingPackCount':len(self.absent),
            'missingPackNames':self.absent[:20],
            'coreManifestName':self.core,
            'coreStoredAs':str(path.relative_to(self.root)) if path else None,
            'coreBytes':path.stat().st_size if path else None,
            'originalFilesModified':False,
        }


def safe_missing_path(raw):
    """Store no query, token, account name, IP or arbitrary dynamic route."""
    p=urllib.parse.unquote(urllib.parse.urlsplit(raw).path)
    if len(p)>245 or not p.startswith(SAFE_PREFIXES) or not SAFE_STATIC_RE.fullmatch(p):
        return None
    if '..' in p.split('/') or re.search(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-',p):
        return None
    return p


def missing_kind(raw):
    p=urllib.parse.urlsplit(raw).path
    if p.startswith(('/assets/packs/','/packs/')) or p.endswith(('.pack','.pack.bin')):
        return 'packs'
    if p.startswith(('/assets/maps/','/maps/')):return 'maps'
    if p.startswith(('/assets/characters/','/characters/')):return 'characters'
    if p.startswith(('/assets/','/models/','/textures/','/effects/','/sounds/')):return 'static'
    if p.startswith('/catalogs/'):return 'catalogs'
    if p.startswith('/world/'):return 'world_routes'
    return 'other_nonstatic'


class Handler(v26.Handler):
    server_version='Browser2Local/27'

    def send_response(self,code,message=None):
        if code==404:
            safe=safe_missing_path(self.path)
            kind=missing_kind(self.path)
            with self.server.missing_lock:
                self.server.missing_classes[kind]+=1
                if safe and (safe in self.server.missing_paths or
                             len(self.server.missing_paths)<MAX_SAMPLES):
                    self.server.missing_paths[safe]+=1
        return super().send_response(code,message)

    def do_GET(self):
        p=urllib.parse.urlsplit(self.path).path
        if p=='/__local__/v27':
            with self.server.missing_lock:
                classes=dict(self.server.missing_classes)
                paths=[{'path':name,'hits':hits} for name,hits in
                       self.server.missing_paths.most_common(30)]
            metrics=dict(self.server.metrics)
            self.json(200,{
                'version':'27.0','mode':'local_original_pack_alias_and_safe_diagnostics',
                'packAudit':self.server.packs.report(),
                'http404Categories':classes,'missingStaticPaths':paths,
                'wsOpened':metrics.get('world_ws_opened',0),
                'wsClosed':metrics.get('world_ws_closed',0),
                'joinAccepted':metrics.get('game_join_accepted',0),
                'joinRejected':metrics.get('game_join_rejected',0),
                'initialStateSent':metrics.get('world_initial_state_sent',0),
                'source':'local_memory_counters_only',
                'noSecretsLogged':True,
                'privateGameServerReplicated':False,
                'note':'Zero world WebSockets means the client has not connected to local GAME. Asset loading and missing routes must be checked first.'
            })
            return
        return super().do_GET()

    def static(self,p):
        # Keep original path priority. If it exists, serve the original
        # path normally (including its Range response).
        direct=(self.server.root/p.lstrip('/')).resolve()
        if direct.is_relative_to(self.server.root) and direct.is_file():
            return super().static(p)
        packed=self.server.packs.file_for_request(p)
        if packed is not None:
            self.server.metrics['pack_manifest_alias_used']+=1
            return v16.serve_file(self,packed)
        return super().static(p)


class Server(v26.Server):
    def __init__(self,bind,root,state,fetcher):
        super().__init__(bind,root,state,fetcher)
        self.packs=OriginalPackLookup(self.root)
        self.missing_lock=threading.RLock()
        self.missing_classes=collections.Counter()
        self.missing_paths=collections.Counter()
        self.RequestHandlerClass=Handler


def make_server(root,port=PORT,state=None):
    state=state or v26.v18.BASE/'YEREL_SUNUCU'
    fetcher=v16.Fetcher(root,state/'browser2_v16_map_overlay')
    return Server(('127.0.0.1',port),root,state,fetcher)


def selftest():
    assert canonical_pack_values({'packs':{'core':'core-08d8acfd75.pack',
        'maps':{'map1':'maps/map1/world-123abc.pack'}}})=={
        'core-08d8acfd75.pack','maps/map1/world-123abc.pack'}
    assert canonical_pack_values({'packs':{'core':'../../bad.pack'}})==set()
    assert safe_missing_path('/assets/maps/map_a2/heightmap.bin?secret=PRIVATE')=='/assets/maps/map_a2/heightmap.bin'
    assert safe_missing_path('/chars/char-PRIVATE?secret=PRIVATE') is None
    assert safe_missing_path('/assets/maps/../private.bin') is None
    with tempfile.TemporaryDirectory() as temp:
        path=Path(temp)
        root=path/'root'
        assets=root/'assets'
        assets.mkdir(parents=True)
        (root/'index.html').write_text(
            '<script src="/assets/game-TEST.js"></script>'
            '<link href="/assets/auth-TEST.js">')
        for name in ('game-TEST.js','auth-TEST.js','world-bridge-TEST.js'):
            (assets/name).write_text('/* fixture only */')
        packdir=assets/'packs'
        packdir.mkdir()
        (packdir/'boot-manifest.json').write_text(json.dumps({
            'version':2,'packs':{'core':'core-08d8acfd75.pack',
                  'maps':{'map1':'maps/map1/world-123abc.pack'}}}))
        core=b'ORIGINAL_CORE_PACK_TEST_BYTES'
        (packdir/'core-08d8acfd75.pack.bin').write_bytes(core)
        nested=packdir/'maps/map1'
        nested.mkdir(parents=True)
        (nested/'world-123abc.pack.bin').write_bytes(b'WORLD_PACK_TEST_BYTES')
        lookup=OriginalPackLookup(root)
        assert lookup.report()['availablePackCount']==2
        assert lookup.report()['coreBytes']==len(core)
        for p in ('/core-08d8acfd75.pack.bin','/packs/core-08d8acfd75.pack.bin',
                  '/assets/packs/core-08d8acfd75.pack','/assets/packs/core-08d8acfd75.pack.bin'):
            assert lookup.file_for_request(p)==packdir/'core-08d8acfd75.pack.bin'
        assert lookup.file_for_request('/assets/packs/fake.pack') is None
        assert lookup.file_for_request('/assets/packs/../private.pack') is None
        srv=make_server(root,0,path/'private')
        th=threading.Thread(target=srv.serve_forever,daemon=True)
        th.start()
        url=f'http://127.0.0.1:{srv.server_port}'
        try:
            for req_path in ('/core-08d8acfd75.pack.bin',
                             '/packs/core-08d8acfd75.pack.bin',
                             '/assets/packs/core-08d8acfd75.pack',
                             '/assets/packs/core-08d8acfd75.pack.bin'):
                with urllib.request.urlopen(url+req_path,timeout=3) as r:
                    assert r.status==200 and r.read()==core
            req=urllib.request.Request(url+'/assets/packs/core-08d8acfd75.pack',
                                       headers={'Range':'bytes=2-7'})
            with urllib.request.urlopen(req,timeout=3) as r:
                assert r.status==206 and r.read()==core[2:8]
            for req_path in ('/assets/maps/map_a2/unknown.glb?secret=PASSWORD',
                             '/catalogs/inexistent','/packs/not-in-manifest.pack'):
                try:urllib.request.urlopen(url+req_path,timeout=3)
                except urllib.error.HTTPError as e:assert e.code==404
                else:raise AssertionError('unexpected synthetic source')
            with urllib.request.urlopen(url+'/__local__/v27',timeout=3) as r:
                diag=json.load(r)
                assert diag['packAudit']['availablePackCount']==2
                assert diag['http404Categories']['packs']>=1
                assert '/assets/maps/map_a2/unknown.glb' in {
                    a['path'] for a in diag['missingStaticPaths']}
                assert 'PASSWORD' not in json.dumps(diag)
                assert diag['wsOpened']==0
        finally:
            srv.shutdown()
            srv.server_close()
    print('[SELFTEST OK] V27 manifest-only core pack aliases, byte-range, 404 categories, no token/query logging')


def main():
    ap=argparse.ArgumentParser(description='Read-only V28 original pack compatibility and loading diagnostics')
    ap.add_argument('action',nargs='?',default='audit',choices=('selftest','audit','serve'))
    ap.add_argument('--root',type=Path)
    ap.add_argument('--port',type=int,default=PORT)
    args=ap.parse_args()
    if args.action=='selftest':
        selftest();return
    if not (1024<=args.port<=65535):raise SystemExit('Port must be 1024..65535')
    try:root=v26.resolve_original(args.root)
    except ValueError as e:raise SystemExit('[ARCHIVE NOT READY] '+str(e))
    pack=OriginalPackLookup(root)
    print('[V27 ARCHIVE]',json.dumps(v26.audit(root),ensure_ascii=False),flush=True)
    print('[V27 PACK AUDIT]',json.dumps(pack.report(),ensure_ascii=False),flush=True)
    if args.action=='audit':return
    v17.prepare_env()
    (v26.v18.BASE/'YEREL_SUNUCU').mkdir(parents=True,exist_ok=True)
    server=make_server(root,args.port)
    print(f'[V27 LOCAL SITE] http://127.0.0.1:{args.port}/__local__/',flush=True)
    print(f'[V27 LOADING REPORT] http://127.0.0.1:{args.port}/__local__/v27',flush=True)
    print('[SAFETY] Original archive unchanged; independent GAME remains partial',flush=True)
    try:server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':
    main()
