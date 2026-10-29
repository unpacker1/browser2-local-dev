#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V30 first-village texture QA: verified WebP aliases and public-only optional sync.

Original Browser2 V28 game assets (JS/WASM/GLB/KTX2/map packs) are immutable.
This independent server may serve an already-existing valid original WebP at
a matching map-layer URL; it never masquerades KTX2 bytes as a WebP.
The original local character DB is never opened.
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

import browser2_v29_isolated_village_qa as v29
import browser2_public_world_asset_sync_v22 as v22

MAP=v29.MAP
PORT=8935
PRIVATE=Path.home()/'BROWSER2_LOCAL_SERVER_DATA'/'QA_V30_A1'
# Exact filenames from a local Chrome trace of the first-village terrain.
# Deliberately no guessed assets, opaque paths or generic basename searching.
LAYERS=('001_field_01','002_field_02','003_field_03','004_field_04',
        '005_grass_01','006_grass_02','007_grass_03','008_stone01',
        '009_stone02','010_stone03','011_stone04','012_tile01',
        '013_tile02','014_beach_sand_01','015_beach_sand_02')
PREFIX='/assets/maps/'+MAP+'/terrain_layers/'
ALLOWED=frozenset(PREFIX+part+'.webp' for part in LAYERS)
V22_OVERLAY=v22.OVERLAY

def names(path):
    if path not in ALLOWED:return None
    leaf=path.rsplit('/',1)[-1]
    match=re.fullmatch(r'\d{3}_([A-Za-z0-9_]+)\.webp',leaf)
    return match.group(1) if match else None

def texture_candidates(root,overlay,path):
    """Report actual file formats only; an unrelated .ktx2 is NOT a WebP."""
    leaf=names(path)
    if not leaf:return None
    root=Path(root)
    original=root/path.lstrip('/')
    canonical=root/'assets/world/textures/terrain_layers'/MAP/(leaf+'.webp')
    cached=Path(overlay)/path.lstrip('/')
    compressed=root/'assets/world/textures/terrain_layers'/MAP/(leaf+'.ktx2')
    direct_ktx=root/'assets/maps'/MAP/'terrain_layers'/(Path(path).stem+'.ktx2')
    def valid(path,kind):
        if not path.is_file():return False
        try:v22.v21.v20.v19.v18.v17.v16.validate_file(path,kind);return True
        except (OSError,ValueError):return False
    return {'requestedWebP':path,
            'originalDirectWebP':valid(original,'webp'),
            'originalWorldWebP':valid(canonical,'webp'),
            'verifiedOverlayWebP':valid(cached,'webp'),
            'originalWorldKTX2':valid(compressed,'ktx2'),
            'originalMapKTX2':valid(direct_ktx,'ktx2'),
            'ktx2CannotBeServedAsWebP':True}

def real_webp_source(root,overlay,path):
    """Original direct file wins; then equivalent real WebP, then validated cache."""
    base=names(path)
    if not base:return None,'not_allowlisted'
    root=Path(root)
    options=(
        ('original_direct',root/path.lstrip('/')),
        ('original_webp_alias',root/'assets/world/textures/terrain_layers'/MAP/(base+'.webp')),
        ('verified_overlay',Path(overlay)/path.lstrip('/')))
    for label,file in options:
        if not file.is_file():continue
        try:
            # Do not accidentally send KTX2 or HTTP 404 text as a WebP.
            v22.v21.v20.v19.v18.v17.v16.validate_file(file,'webp')
            return file,label
        except (OSError,ValueError):
            pass
    return None,'no_valid_original_webp'

def report_files(root,overlay):
    rows=[texture_candidates(root,overlay,x) for x in sorted(ALLOWED)]
    counts=dict(collections.Counter(
        'original_webp' if r['originalDirectWebP'] or r['originalWorldWebP'] else
        'cached_webp' if r['verifiedOverlayWebP'] else
        'ktx2_only' if r['originalWorldKTX2'] or r['originalMapKTX2'] else
        'unavailable' for r in rows))
    return {'map':MAP,'requestedWebP':len(rows),'categories':counts,
            'layers':rows,'allOriginalFilesUnmodified':True,
            'note':'KTX2 is a different binary format and cannot be returned as WebP.'}

class Handler(v29.Handler):
    server_version='Browser2Local/30-A1Textures'
    def do_GET(self):
        p=urllib.parse.urlsplit(self.path).path
        if p=='/__local__/v30':
            data=report_files(self.server.root,self.server.texture_overlay)
            data['version']='30.0'
            data['service']='local_visual_qa'
            data['metrics']={key:v for key,v in self.server.metrics.items()
                if key.startswith(('v30_','world_ws','game_join','world_initial'))}
            return self.json(200,data)
        return super().do_GET()
    def static(self,p):
        if p in ALLOWED:
            source,kind=real_webp_source(self.server.root,self.server.texture_overlay,p)
            if source is not None:
                self.server.metrics['v30_texture_'+kind]+=1
                return v22.v21.v20.v19.v18.v17.v16.serve_file(self,source)
            self.server.metrics['v30_texture_unavailable']+=1
            # Unavailable original texture must remain 404, not grey fake image.
        elif v22.allowed_path(p):
            # Reuse an explicitly verified original public-asset cache for
            # other UI/scenery PNG/WebP assets. No live network requests.
            src,kind=v22.local_asset(self.server.root,self.server.texture_overlay,p)
            if kind=='overlay_present':
                self.server.metrics['v30_verified_asset_cache_hits']+=1
                return v22.v21.v20.v19.v18.v17.v16.serve_file(self,src)
        return super().static(p)

class Server(v29.Server):
    def __init__(self,bind,root,state,fetcher,map_info,overlay=V22_OVERLAY):
        super().__init__(bind,root,state,fetcher,map_info)
        self.texture_overlay=Path(overlay)
        self.RequestHandlerClass=Handler

def make_server(root,port=PORT,state=PRIVATE,overlay=V22_OVERLAY):
    original=v29.inspect_map(root)
    if not original.get('ready'):
        raise RuntimeError('A1 original metadata / map core not ready')
    state=Path(state);state.mkdir(parents=True,exist_ok=True)
    try:state.chmod(0o700)
    except OSError:pass
    fetcher=v22.v21.v20.v19.v18.v17.v16.Fetcher(
        root,state/'map_overlay')
    return Server(('127.0.0.1',port),Path(root),state,fetcher,original,overlay)

def optional_sync(root,overlay=V22_OVERLAY):
    """Explicit network operation only, with the existing validated V22 fetcher.

    Valid WebP magic, bounded size, same-origin HTTPS and exact path checks
    are inherited. Missing public files remain missing (no synthetic fallback).
    """
    fetcher=v22.PublicAssetFetcher(root,overlay,max_total=64*1024*1024)
    results=[]
    for path in sorted(ALLOWED):
        results.append(fetcher.fetch(path))
    return {'results':results,'counts':dict(collections.Counter(
            r['status'] for r in results)),
            'originalFilesModified':False,
            'doesNotConvertKTX2':True}

def selftest():
    assert len(ALLOWED)==15
    assert names(PREFIX+'010_stone03.webp')=='stone03'
    assert names(PREFIX+'../stone03.webp') is None
    assert names('/assets/world/secret.webp') is None
    with tempfile.TemporaryDirectory() as temp:
        t=Path(temp);root=t/'original';assets=root/'assets'
        assets.mkdir(parents=True)
        (root/'index.html').write_text(
            '<html><head><script src="/assets/game-T.js"></script>'
            '<link href="/assets/auth-T.js"></head><body>Original</body></html>')
        for n in ('game-T.js','auth-T.js','world-bridge-T.js'):
            (assets/n).write_text('/* fixture */')
        amap=assets/'maps'/MAP;amap.mkdir(parents=True)
        (amap/'map.json').write_text(
            json.dumps({'size_x':4,'size_y':5,'tile_m':256,'objects':[]}))
        for n in ('heightmap.bin','collision.bin','env.json'):
            (amap/n).write_bytes(b'Original map fixture')
        terrain=assets/'world/textures/terrain_layers'/MAP
        terrain.mkdir(parents=True)
        # Minimal valid WebP header. We verify transport, NOT render decoding.
        webp=b'RIFF'+(16).to_bytes(4,'little')+b'WEBPVP8 '+b'\0'*8
        (terrain/'stone03.webp').write_bytes(webp)
        # KTX2-only cannot be served disguised as another file format.
        ktx=b'\xabKTX 20\xbb\r\n\x1a\n'+b'\0'*80
        (terrain/'field_01.ktx2').write_bytes(ktx)
        overlay=t/'original-public-cache'
        hit=overlay/PREFIX.lstrip('/')
        hit.mkdir(parents=True)
        (hit/'002_field_02.webp').write_bytes(webp)
        normal_db=t/'canonical.sqlite3'
        normal_db.write_bytes(b'CANONICAL_UNTOUCHED')
        srv=make_server(root,0,t/'qa_only',overlay)
        th=threading.Thread(target=srv.serve_forever,daemon=True);th.start()
        url='http://127.0.0.1:'+str(srv.server_port)
        try:
            with urllib.request.urlopen(url+PREFIX+'010_stone03.webp') as r:
                assert r.status==200 and r.read()==webp
                assert r.headers['Content-Type']=='image/webp'
            with urllib.request.urlopen(urllib.request.Request(
                   url+PREFIX+'010_stone03.webp',headers={'Range':'bytes=0-11'})) as r:
                assert r.status==206 and r.read()==webp[:12]
            with urllib.request.urlopen(url+PREFIX+'002_field_02.webp') as r:
                assert r.status==200 and r.read()==webp
            for missing in ('001_field_01.webp','004_field_04.webp'):
                try:urllib.request.urlopen(url+PREFIX+missing)
                except urllib.error.HTTPError as e:assert e.code==404
                else:raise AssertionError('Missing WebP should not be faked')
            with urllib.request.urlopen(url+'/__local__/v30') as r:
                report=json.load(r)
                assert report['categories']['original_webp']==1
                assert report['categories']['cached_webp']==1
                assert report['categories']['ktx2_only']==1
                assert report['metrics']['v30_texture_original_webp_alias']>=2
            with urllib.request.urlopen(url+'/__local__/v29') as r:
                assert json.load(r)['version']=='29.0'
            assert (terrain/'stone03.webp').read_bytes()==webp
            assert (terrain/'field_01.ktx2').read_bytes()==ktx
            assert normal_db.read_bytes()==b'CANONICAL_UNTOUCHED'
        finally:
            srv.shutdown();srv.server_close()
    print('[SELFTEST OK] V30 genuine WebP alias/Range, verified cache, KTX2 remains separate, isolated SQLite')

def main():
    cli=argparse.ArgumentParser(description='Original A1 terrain layer WebP safety/compat QA')
    cli.add_argument('action',nargs='?',choices=('selftest','audit','sync','start','serve','report'),
                     default='audit')
    cli.add_argument('--port',type=int,default=PORT)
    cli.add_argument('--root',type=Path)
    opt=cli.parse_args()
    if opt.action=='selftest':selftest();return
    if not 1024<=opt.port<=65535:raise SystemExit('Bad port')
    if opt.action=='report':
        try:
            with urllib.request.urlopen('http://127.0.0.1:'+str(opt.port)+'/__local__/v30',
                                        timeout=4) as r:d=json.load(r)
        except (OSError,ValueError):raise SystemExit('V30 is not running on requested port')
        print('[TERRAIN]',json.dumps(d['categories'],ensure_ascii=False))
        print('[METRICS]',json.dumps(d.get('metrics',{}),ensure_ascii=False))
        for entry in d['layers']:
            if not entry['originalDirectWebP'] and not entry['originalWorldWebP'] and not entry['verifiedOverlayWebP']:
                print('[MISSING WEBP]',entry['requestedWebP'],
                    'ktx2=',entry['originalWorldKTX2'] or entry['originalMapKTX2'])
        return
    try:root=v29.v26.resolve_original(opt.root)
    except ValueError as e:raise SystemExit('[ARCHIVE] '+str(e))
    print('[ORIGINAL A1 TERRAIN]',json.dumps(report_files(root,V22_OVERLAY)['categories']),
          flush=True)
    if opt.action=='audit':return
    if opt.action=='sync':
        report=optional_sync(root)
        print('[PUBLIC WEBP SYNC]',json.dumps(report,ensure_ascii=False))
        return
    if opt.action=='start':
        if v29.status(opt.port):raise SystemExit('[PORT OCCUPIED] Old QA server; choose different port')
        # We do not kill, overwrite or restart any existing listener.
        import socket,subprocess,sys,time
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1',opt.port))==0:
                raise SystemExit('[PORT OCCUPIED] Choose another port')
        PRIVATE.mkdir(parents=True,exist_ok=True)
        log=PRIVATE/'v30_visual.log'
        with log.open('ab') as fp:
            subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'serve',
              '--port',str(opt.port),'--root',str(root)],stdin=subprocess.DEVNULL,
              stdout=fp,stderr=subprocess.STDOUT,close_fds=True,start_new_session=True)
        for _ in range(30):
            try:
                with urllib.request.urlopen('http://127.0.0.1:'+str(opt.port)+'/__local__/v30',
                                            timeout=2) as r:
                    d=json.load(r)
                if d.get('version')=='30.0':
                    print('[V30] http://127.0.0.1:'+str(opt.port)+'/__local__/?b2diag=1')
                    return
            except (OSError,ValueError):time.sleep(.3)
        raise SystemExit('[ERROR] V30 failed to start. Inspect private QA log.')
    srv=make_server(root,opt.port)
    print('[V30] http://127.0.0.1:'+str(opt.port)+'/__local__/?b2diag=1',flush=True)
    try:srv.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:pass
    finally:srv.server_close()

if __name__=='__main__':main()
