#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V25 isolated Shinsoo-Yongan A1 trial for the independent Browser2 local GAME.

Trial only: (0,0) is the geometric map center, NOT a source-verified official
Shinsoo spawn. Uses a NEW private QA-only SQLite DB, never reads or changes
the current production local character database. Original game client JS,
WASM, map, models, shader and packet formats remain byte-identical.
Existing V22.3 port 8910 is unaffected. Loopback port 8911.
"""
from __future__ import annotations
import argparse
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
import urllib.request
import urllib.error
import browser2_public_world_asset_sync_v22 as v22
import browser2_map_geometry_audit_v24 as v24

VERSION="25.0"
PORT=8911
MAP="metin2_map_a1"
QA_X=0.0
QA_Z=0.0
BASE=v22.BASE
ROOT=v22.ROOT
REPORTS=v22.REPORTS
LOGS=v22.LOGS
PRIVATE=v22.v21.v20.v19.v18.v17.PRIVATE
QA_DIR=PRIVATE/'QA_A1_ISOLATED_V25'
QA_DB=QA_DIR/'local.sqlite3'
MAP_OVERLAY=BASE/'YEREL_SUNUCU/browser2_v16_map_overlay'

def prerequisites(root=ROOT,overlay=MAP_OVERLAY):
    data,source=v24.v23.original_map(root,overlay,MAP)
    if not isinstance(data,dict):return False,{'map_json':source}
    g=v24.geometry(data)
    half=g.get('half_extent_m')
    core={}
    for fn in ('map.json','heightmap.bin','collision.bin','env.json'):
        p=Path(root)/'assets/maps'/MAP/fn
        a=Path(overlay)/'assets/maps'/MAP/fn
        core[fn]='original' if p.is_file() else ('overlay' if a.is_file() else 'missing')
    valid=bool(half and len(half)==2 and
            all(isinstance(n,(int,float)) and n>100 for n in half) and
            all(v!='missing' for v in core.values()))
    return valid,{'map_json':source,'extent_half_m':half,'core_files':core,
                  'object_at_origin_distance_m':g.get('nearest_object_distance_m'),
                  'trial_coordinate_m':[QA_X,QA_Z],
                  'official_spawn_verified':False}

class QAStore(v22.v21.v20.v19.v18.v17.v16.base.Store):
    def ensure_bootstrap(self):
        result=super().ensure_bootstrap()
        character=result['character']
        # QA-only DB migration: this is a disposable copy, NEVER the original.
        if character['mapId']!='metin2_map_a1':
            with self.lock,self._db() as db:
                db.execute("UPDATE characters SET map_id=?,x=?,z=? WHERE id=?",
                    (MAP,QA_X,QA_Z,character['id']))
            character=dict(character,mapId=MAP,x=QA_X,z=QA_Z)
            result['character']=character
        return result

class Handler(v22.Handler):
    server_version='Browser2Local/25-QA'
    def do_GET(self):
        path=urllib.parse.urlsplit(self.path).path
        if path=='/catalogs/maps' or re.fullmatch(r'/world/[A-Za-z0-9_@-]+/catalogs/maps',path):
            ok,info=prerequisites(self.server.root,MAP_OVERLAY)
            if not ok:return self.json(503,{'error':'original_A1_map_assets_missing'})
            hx,hz=info['extent_half_m']
            return self.json(200,[{'id':MAP,'mapId':MAP,'name':MAP,
                'tileSet':MAP,'halfX':hx,'halfZ':hz,'npcs':[]}])
        if path=='/__local__/v25':
            ok,info=prerequisites(self.server.root,MAP_OVERLAY)
            return self.json(200,{'version':VERSION,'ready':ok,'map':MAP,
                'trial_type':'geometric_center_not_official_spawn',
                'map_info':info,
                'isolation':'Separate private QA-only local SQLite. Existing local database is untouched.',
                'original_files_modified':False,
                'last_game_metrics':{k:v for k,v in self.server.metrics.items()
                    if k.startswith(('world_','game_join'))},
                'active_world':self.server.active})
        return super().do_GET()

class Server(v22.Server):
    def __init__(self,bind,root,state,fetcher,locale_overlay=v22.v21.OVERLAY,
                 world_overlay=v22.OVERLAY,world_fetcher=None,qa_db=QA_DB):
        super().__init__(bind,root,state,fetcher,locale_overlay,world_overlay,world_fetcher)
        self.store=QAStore(Path(qa_db))
        self.RequestHandlerClass=Handler

def fetch_report(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/__local__/v25',timeout=3) as r:
            d=json.load(r)
        return d if d.get('version')==VERSION else None
    except (OSError,ValueError):
        return None

def report(port):
    d=fetch_report(port)
    if not d:raise SystemExit('[HATA] V25 QA sunucu calismiyor')
    REPORTS.mkdir(parents=True,exist_ok=True)
    boot=v22.v21.v20.fetch(port)
    out={'version':VERSION,'qa':d,'boot':boot,'original_db_untouched':True,
         'warning':'A1 map center is a test position only, not verified original spawn.'}
    p=REPORTS/'browser2_v25_a1_qa_raporu.json'
    p.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8')
    print('[RAPOR]',p)
    print('[QA]',d['map_info'])
    print('[GAME]',d['last_game_metrics'])
    if boot:print('[YUKLEME]',[x for x in boot.get('events',[])
                                if x.get('event') in ('world_ready','boot_failed','phase_seen')])

def selftest():
    assert QA_DB!=PRIVATE/'local.sqlite3'
    assert MAP=='metin2_map_a1'
    with tempfile.TemporaryDirectory() as td:
        t=Path(td);root=t/'original';root.mkdir();(root/'assets').mkdir()
        (root/'index.html').write_bytes(b'<html><head></head><body>original</body></html>')
        over=t/'map_overlay'
        p=over/'assets/maps'/MAP;p.mkdir(parents=True)
        (p/'map.json').write_text(json.dumps({'size_x':4,'size_y':5,'tile_m':256,
            'objects':[{'x_cm':51200,'y_cm':-64000}]}))
        for fn in ('heightmap.bin','collision.bin','env.json'):(p/fn).write_bytes(b'fixture')
        old_db=t/'existing_local.sqlite3'
        old_db.write_bytes(b'KEEP_ORIGINAL_DB_UNTOUCHED')
        test_db=t/'PRIVATE_QA/local.sqlite3'
        f=v22.v21.v20.v19.v18.v17.v16.Fetcher(root,t/'another_overlay')
        s=Server(('127.0.0.1',0),root,t/'state',f,
            locale_overlay=t/'locales',world_overlay=t/'world',qa_db=test_db)
        # Source-only geometry fixture. Tests must not depend on external network.
        previous=globals()['MAP_OVERLAY']
        globals()['MAP_OVERLAY']=over
        thread=threading.Thread(target=s.serve_forever,daemon=True);thread.start()
        try:
            base=f'http://127.0.0.1:{s.server_port}'
            with urllib.request.urlopen(base+'/world/metin2_map_a1/catalogs/maps') as r:
                rows=json.load(r)
                assert rows[0]['tileSet']==MAP and rows[0]['halfX']==512
            with urllib.request.urlopen(base+'/__local__/v25') as r:
                qa=json.load(r)
                assert qa['ready'] and not qa['map_info']['official_spawn_verified']
            boot=s.store.ensure_bootstrap()
            assert boot['character']['mapId']==MAP
            assert boot['character']['x']==QA_X and boot['character']['z']==QA_Z
            assert s.store.ensure_bootstrap()['character']['mapId']==MAP
            assert old_db.read_bytes()==b'KEEP_ORIGINAL_DB_UNTOUCHED'
            with urllib.request.urlopen(base+'/') as r:
                assert b'original' in r.read()
        finally:
            s.shutdown();s.server_close()
            globals()['MAP_OVERLAY']=previous
    print('[SELFTEST OK] V25 isolated first-village map catalog, QA-only SQLite, original files preserved')

def serve(port):
    v22.v21.v20.v19.v18.v17.prepare_env()
    ok,details=prerequisites()
    if not ok:raise SystemExit('[HATA] A1 map files not prepared: '+str(details))
    if not v22.v21.v20.v19.v18.v17.v16.prev.audit(ROOT):
        raise SystemExit('[HATA] Original client archive not found')
    QA_DIR.mkdir(parents=True,exist_ok=True)
    try:QA_DIR.chmod(0o700)
    except OSError:pass
    os.environ['BROWSER2_PRIVATE_DB']=str(QA_DB)
    for d in (REPORTS,LOGS,v22.OVERLAY):d.mkdir(parents=True,exist_ok=True)
    maps=v22.v21.v20.v19.v18.v17.v16.Fetcher(ROOT,MAP_OVERLAY)
    server=Server(('127.0.0.1',port),ROOT,BASE/'YEREL_SUNUCU',maps,qa_db=QA_DB)
    print(f'[V25 QA] http://127.0.0.1:{port}/__local__/',flush=True)
    print('[QA TEST] Independent A1 center test, normal local DB NEVER changed',flush=True)
    try:server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:server.server_close()

def start(port):
    d=fetch_report(port)
    if d:
        print(f'[V25 QA] Zaten acik: http://127.0.0.1:{port}/__local__/');return
    with socket.socket() as sk:
        if sk.connect_ex(('127.0.0.1',port))==0:
            raise SystemExit('[HATA] Port baska program tarafindan kullaniliyor')
    ok,info=prerequisites()
    if not ok:raise SystemExit('[HATA] First village original map is missing: '+str(info))
    LOGS.mkdir(parents=True,exist_ok=True)
    with (LOGS/'browser2_v25_a1_qa.log').open('ab') as out:
        subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'serve','--port',str(port)],
            stdout=out,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,
            env=os.environ.copy(),start_new_session=True,close_fds=True)
    for _ in range(40):
        if fetch_report(port):
            print(f'[V25 QA] Acildi: http://127.0.0.1:{port}/__local__/');return
        time.sleep(.2)
    raise SystemExit('[HATA] V25 QA cannot start. Check LOGS/browser2_v25_a1_qa.log')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('mode',choices=('selftest','start','serve','rapor'),nargs='?',default='start')
    p.add_argument('--port',type=int,default=PORT)
    a=p.parse_args()
    if not 1024<=a.port<=65535:raise SystemExit('invalid port')
    if a.mode=='selftest':selftest()
    elif a.mode=='start':start(a.port)
    elif a.mode=='serve':serve(a.port)
    else:report(a.port)

if __name__=='__main__':main()
