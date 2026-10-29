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
import browser2_client_boot_probe_v20 as v20
import browser2_local_locale_sync_v21 as v21
import http.cookies
import secrets

PORT=8899
PACK_BASE='/assets/packs/'
SAFE_PACK_RE=re.compile(r'[A-Za-z0-9_./@-]{1,220}\.pack')
SAFE_STATIC_RE=re.compile(r'/[A-Za-z0-9_./@+-]{1,240}\.(?:pack|bin|glb|ktx2|wasm|json|js|webp|png|jpg|mp3|ogg|wav)')
SAFE_PREFIXES=('/assets/','/packs/','/catalogs/','/maps/','/models/','/characters/','/textures/','/effects/','/sounds/','/ui/','/animations/')
MAX_SAMPLES=100
BOOT_EVENT_LIMIT=200
OBSERVED_EN_FILES=('client.net_ui','game.mob','game.companion','game.world',
                   'game.item','system','game.skill','game.skill_extra')


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
        parsed=urllib.parse.urlsplit(self.path)
        p=parsed.path
        if p=='/__local__/v20/observer.js':
            return self.sendbody(200,v20.OBSERVER.encode('utf-8'),'text/javascript; charset=utf-8',
                                 {'Cache-Control':'no-store'})
        if p=='/__local__/v28':
            locale={}
            for item in OBSERVED_EN_FILES:
                locale[item]=v21.local_source(
                    self.server.root,self.server.locale_overlay,
                    '/locales/en/'+item+'.json')[1]
            with self.server.boot_lock:
                boot=[{'event':event,'category':cat,'stage':stage,'count':n}
                      for (event,cat,stage),n in self.server.boot_events.most_common(70)]
            return self.json(200,{
                'version':'28.0-local-diagnostics',
                'localeSources':locale,
                'catalogMobsStaticPresent':(self.server.root/'assets/catalogs/mobs.json').is_file(),
                'catalogMobsBackendRoute':'not_verified',
                'browserBootEvents':boot,
                'bootObserverOptIn':True,
                'packAudit':self.server.packs.report(),
                'backendMetrics':{key:count for key,count in self.server.metrics.items()
                                  if key.startswith(('world_ws','game_join','world_initial'))},
                'originalAssetsModified':False,
                'notice':'Only fixed event categories; no request queries, headers, cookies or secrets stored'})
        if p=='/__local__/' and urllib.parse.parse_qs(parsed.query).get('b2diag')==['1']:
            # Modify only the locally generated launcher's HTTP response.
            # The original AUTH, GAME and HTML files on disk remain untouched.
            bundles=base.discover_original_bundles(self.server.root)
            if not all(x in bundles for x in ('auth','game','world_bridge')):
                return self.json(503,{'error':'Original V28 bundle set incomplete'})
            old="location.assign('/?'+q.toString());"
            launch=v26.v18.CLIENT_HTML
            if launch.count(old)!=1:
                return self.json(503,{'error':'Diagnostic launcher signature unavailable'})
            launch=launch.replace('__ORIGINAL_AUTH_MODULE__','/assets/'+bundles['auth'])
            launch=launch.replace(old,"q.set('b2diag','1');"+old)
            csrf=secrets.token_urlsafe(18)
            return self.sendbody(200,launch.encode('utf-8'),'text/html; charset=utf-8',{
                'Set-Cookie':f'b2csrf={csrf}; Path=/__local__/; SameSite=Strict',
                'Cache-Control':'no-store',
                'Content-Security-Policy':"default-src 'none'; script-src 'self' 'unsafe-inline'; connect-src 'self'; style-src 'unsafe-inline'"})
        if p=='/' and urllib.parse.parse_qs(parsed.query).get('b2diag')==['1']:
            index=self.server.root/'index.html'
            if index.is_file():
                # Optional in-memory observer from V20; it records event labels,
                # never messages or raw network packets.
                html=v20.inject(index.read_bytes())
                if html is not None:
                    return self.sendbody(200,html,'text/html; charset=utf-8',
                                         {'Cache-Control':'no-store'})
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

    def do_POST(self):
        if urllib.parse.urlsplit(self.path).path!='/__local__/v20/event':
            return super().do_POST()
        try:
            self.require_origin()
            length=int(self.headers.get('Content-Length','0'))
            if not 1<=length<=200:raise ValueError('bad event length')
            if self.headers.get('Content-Type','').split(';')[0].strip().lower()!='application/json':
                raise ValueError('must be JSON')
            payload=json.loads(self.rfile.read(length))
            if not isinstance(payload,dict):raise ValueError('bad event')
            ev,category,stage=(payload.get('event'),payload.get('category'),payload.get('stage'))
            if ev not in v20.EVENTS or category not in v20.CATEGORIES or stage not in v20.STAGES:
                raise ValueError('invalid fixed label')
            with self.server.boot_lock:
                if sum(self.server.boot_events.values())<BOOT_EVENT_LIMIT:
                    self.server.boot_events[ev,category,stage]+=1
            return self.json(200,{'ok':True})
        except (ValueError,TypeError,json.JSONDecodeError,base.Error):
            return self.json(400,{'error':'Invalid diagnostic event'})

    def static(self,p):
        if v21.allowed_path(p):
            # Genuine locale cache from previous V21 sync, never synthesized.
            path,kind=v21.local_source(self.server.root,self.server.locale_overlay,p)
            if path is not None and kind=='overlay_present':
                self.server.metrics['verified_locale_overlay_hits']+=1
                return v16.serve_file(self,path)
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
        self.locale_overlay=v21.OVERLAY
        self.boot_events=collections.Counter()
        self.boot_lock=threading.Lock()
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
            '<html><head><script src="/assets/game-TEST.js"></script>'
            '<link href="/assets/auth-TEST.js"></head><body>Original fixture</body></html>')
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
        # Separate fake locale overlay, isolated from the user's private archive.
        srv.locale_overlay=path/'verified-locale-cache'
        fixture_locale=srv.locale_overlay/'locales/en/client.net_ui.json'
        fixture_locale.parent.mkdir(parents=True)
        fixture_locale.write_text('{"message":"verified original fixture"}')
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
            # Debug is opt-in and injected into *HTTP response* only.
            with urllib.request.urlopen(url+'/__local__/?b2diag=1') as r:
                page=r.read()
                assert b"q.set('b2diag','1')" in page
                assert b'/assets/auth-TEST.js' in page
            with urllib.request.urlopen(url+'/?b2diag=1') as r:
                page=r.read()
                assert b'/__local__/v20/observer.js' in page
                assert (root/'index.html').read_bytes()!=page
            with urllib.request.urlopen(url+'/__local__/v20/observer.js') as r:
                assert b'boot_caught' in r.read()
            with urllib.request.urlopen(url+'/locales/en/client.net_ui.json') as r:
                assert json.load(r)['message']=='verified original fixture'
            with urllib.request.urlopen(url+'/__local__/v28') as r:
                d=json.load(r)
                assert d['localeSources']['client.net_ui']=='overlay_present'
                assert d['localeSources']['game.mob']=='missing'
                assert d['catalogMobsBackendRoute']=='not_verified'
            event=json.dumps({'event':'boot_caught','category':'catalog','stage':'manifest'}).encode()
            reqdiag=urllib.request.Request(url+'/__local__/v20/event',
                method='POST',data=event,headers={'Content-Type':'application/json','Origin':url})
            with urllib.request.urlopen(reqdiag) as r:
                assert json.load(r)['ok']
            with urllib.request.urlopen(url+'/__local__/v28') as r:
                d=json.load(r)
                assert any(x['event']=='boot_caught' and x['category']=='catalog'
                           for x in d['browserBootEvents'])
            # No payload values or original files copied into the server report.
            assert fixture_locale.read_text()=='{"message":"verified original fixture"}'
            assert b'/__local__/v20/observer.js' not in (root/'index.html').read_bytes()
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
    print('[SELFTEST OK] V28 manifest aliases, V21 original locale cache, opt-in V20 browser boot observer and sanitized telemetry')


def main():
    ap=argparse.ArgumentParser(description='Read-only V28 original pack compatibility and loading diagnostics')
    ap.add_argument('action',nargs='?',default='audit',choices=('selftest','audit','serve','report'))
    ap.add_argument('--root',type=Path)
    ap.add_argument('--port',type=int,default=PORT)
    args=ap.parse_args()
    if args.action=='selftest':
        selftest();return
    if not (1024<=args.port<=65535):raise SystemExit('Port must be 1024..65535')
    if args.action=='report':
        uri='http://127.0.0.1:'+str(args.port)
        for endpoint in ('v28','v27','v19'):
            try:
                with urllib.request.urlopen(uri+'/__local__/'+endpoint,timeout=4) as response:
                    d=json.load(response)
            except (OSError,ValueError) as exc:
                print('[REPORT UNAVAILABLE]',endpoint,type(exc).__name__)
                continue
            if endpoint=='v28':
                print('[LOCALES]',json.dumps(d.get('localeSources',{}),ensure_ascii=False))
                print('[CATALOG MOBS]',d.get('catalogMobsStaticPresent'),d.get('catalogMobsBackendRoute'))
                print('[BROWSER BOOT]',json.dumps(d.get('browserBootEvents',[]),ensure_ascii=False))
                print('[GAME]',json.dumps(d.get('backendMetrics',{}),ensure_ascii=False))
            elif endpoint=='v27':
                print('[PACKS]',{k:d.get('packAudit',{}).get(k) for k in
                                  ('manifestPackCount','availablePackCount','missingPackCount')})
                print('[404]',d.get('http404Categories',{}))
                print('[WORLD]',{k:d.get(k) for k in ('wsOpened','joinAccepted','joinRejected','initialStateSent')})
            else:
                print('[HTTP ERRORS]',json.dumps(d.get('error_routes',[])[:18],ensure_ascii=False))
        return
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
