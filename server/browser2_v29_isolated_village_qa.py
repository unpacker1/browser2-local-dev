#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V29 reversible A1 village visual QA on original V28 client/assets.

The source 3D client is never modified. Existing normal local SQLite remains
untouched: this independent experiment uses its own PRIVATE QA-only database.
It proves neither official spawn coordinates nor full original NPC/mob logic.
"""
from __future__ import annotations
import argparse
import json
import math
import os
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
import http.cookies
from pathlib import Path

import browser2_local_base_v14 as base
import browser2_v28_local_site_v26 as v26
import browser2_v28_pack_compat_v27 as v27
import browser2_map_geometry_audit_v24 as geo

MAP='metin2_map_a1'
PORT=8931
PRIVATE=Path.home()/'BROWSER2_LOCAL_SERVER_DATA'/'QA_V29_A1'
CORE=('map.json','heightmap.bin','collision.bin','env.json')

def inspect_map(root):
    """Only ground the catalog in actual V28 map.json and core map files."""
    base_dir=Path(root)/'assets/maps'/MAP
    files={name:(base_dir/name).is_file() and (base_dir/name).stat().st_size>0
           for name in CORE}
    status={'map':MAP,'coreFiles':files,'ready':False,
            'officialSpawnVerified':False,'testPositionMeters':[0,0]}
    if not all(files.values()):return status
    try:
        p=base_dir/'map.json'
        if p.stat().st_size>16*1024*1024:return dict(status,error='map_too_large')
        with p.open(encoding='utf-8') as f:data=json.load(f)
        info=geo.geometry(data)
        half=info.get('half_extent_m')
        if not isinstance(half,list) or len(half)!=2 or not all(
              isinstance(v,(int,float)) and math.isfinite(v) and 100<v<100000
              for v in half):
            return dict(status,error='invalid_original_extent')
        status.update(ready=True,halfX=half[0],halfZ=half[1],
                      mapObjectCount=info.get('object_records'),
                      nearOrigin=info.get('near_origin_objects_m'),
                      notes='A1 geometric center is only a preview, not the official village spawn.')
    except (OSError,UnicodeError,ValueError,TypeError):
        status['error']='map_metadata_unreadable'
    return status

class QAStore(base.Store):
    """A fresh, isolated SQLite store; never point at the canonical database."""
    def ensure_bootstrap(self):
        result=super().ensure_bootstrap()
        char=result['character']
        # The test intentionally changes ONLY the QA database.
        with self.lock,self._db() as db:
            db.execute('UPDATE characters SET map_id=?,x=0,z=0 WHERE id=?',
                       (MAP,char['id']))
            row=db.execute('SELECT * FROM characters WHERE id=?',(char['id'],)).fetchone()
        result['character']=self.char_public(row)
        return result
    def create_char(self,user,data):
        raise base.Error(403,'QA-only: create characters in the normal local server')
    def del_char(self,user,charid):
        raise base.Error(403,'QA-only: deletion disabled')
    def save_pos(self,ch):
        # Test movement does not persist a new canonical or QA spawn.
        return None

class Handler(v27.Handler):
    server_version='Browser2Local/29-A1QA'
    def do_GET(self):
        p=urllib.parse.urlsplit(self.path).path
        if p=='/__local__/v29':
            with self.server.active_lock:active=self.server.active
            return self.json(200,{'version':'29.0','mode':'A1_original_map_isolated_QA',
                'map':self.server.map_info,
                'sqliteScope':'private_QA_only',
                'originalAssetsModified':False,
                'officialSpawnVerified':False,
                'worldActive':active,
                'gameMetrics':{k:v for k,v in self.server.metrics.items()
                               if k.startswith(('world_ws','game_join','world_initial'))}})
        if p=='/catalogs/maps' or re.fullmatch(
            r'/world/[A-Za-z0-9_@-]+/catalogs/maps',p):
            m=self.server.map_info
            if not m['ready']:
                return self.json(503,{'error':'original_A1_map_invalid'})
            return self.json(200,[{'id':MAP,'mapId':MAP,'name':MAP,'tileSet':MAP,
                                  'halfX':m['halfX'],'halfZ':m['halfZ'],'npcs':[]}])
        return super().do_GET()

class Server(v27.Server):
    def __init__(self,bind,root,state,fetcher,map_info):
        state=Path(state).resolve()
        # Prevent prior V17 env settings from accidentally redirecting SQLite.
        public=os.environ.get('BROWSER2_PUBLIC_STATE','')
        redirected=os.environ.get('BROWSER2_PRIVATE_DB','')
        if redirected and public and Path(public).expanduser().resolve()==state:
            raise RuntimeError('QA DB must never be a redirected production DB')
        super().__init__(bind,root,state,fetcher)
        self.store=QAStore(state/'local.sqlite3')
        self.map_info=map_info
        self.RequestHandlerClass=Handler

def make_server(root,port=PORT,state=PRIVATE):
    info=inspect_map(root)
    if not info['ready']:
        raise RuntimeError('Original first-village core/metadata not valid: '+json.dumps(info))
    state=Path(state)
    state.mkdir(parents=True,exist_ok=True)
    try:state.chmod(0o700)
    except OSError:pass
    fetcher=v27.v16.Fetcher(root,state/'map_overlay')
    return Server(('127.0.0.1',port),Path(root),state,fetcher,info)

def status(port=PORT):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/__local__/v29',timeout=3) as r:
            d=json.load(r)
        return d if d.get('version')=='29.0' else None
    except (OSError,ValueError):
        return None

def selftest():
    with tempfile.TemporaryDirectory() as temp:
        t=Path(temp)
        root=t/'original'
        (root/'assets').mkdir(parents=True)
        (root/'index.html').write_text(
            '<html><head><script src="/assets/game-T.js"></script>'
            '<link href="/assets/auth-T.js"></head><body>unchanged</body></html>')
        for n in ('game-T.js','auth-T.js','world-bridge-T.js'):
            (root/'assets'/n).write_text('/* test */')
        a=root/'assets/maps'/MAP;a.mkdir(parents=True)
        (a/'map.json').write_text(json.dumps({'size_x':4,'size_y':5,'tile_m':256,
               'objects':[{'x_cm':51200,'y_cm':-64000}]}))
        for n in CORE[1:]: (a/n).write_bytes(b'fixture')
        assert inspect_map(root)['ready']
        assert inspect_map(root)['halfX']==512
        normal=t/'canonical.sqlite3'
        normal.write_bytes(b'KEEP_OLD_CHARACTER_DB_UNCHANGED')
        qa=t/'QA_ONLY_PRIVATE'
        server=make_server(root,0,qa)
        worker=threading.Thread(target=server.serve_forever,daemon=True)
        worker.start()
        base_url=f'http://127.0.0.1:{server.server_port}'
        try:
            with urllib.request.urlopen(base_url+'/world/map1/catalogs/maps') as r:
                maps=json.load(r)
                assert maps[0]['mapId']==MAP and maps[0]['halfX']==512
            with urllib.request.urlopen(base_url+'/__local__/v29') as r:
                d=json.load(r)
                assert d['map']['ready'] and not d['officialSpawnVerified']
            with urllib.request.urlopen(base_url+'/__local__/') as r:
                cookie=r.headers['Set-Cookie']
                assert b'__ORIGINAL_AUTH_MODULE__' not in r.read()
            csrf=cookie.split('b2csrf=',1)[1].split(';',1)[0]
            request=urllib.request.Request(base_url+'/__local__/bootstrap',
                method='POST',data=b'{}',headers={'Content-Type':'application/json',
                    'Origin':base_url,'Cookie':'b2csrf='+csrf,'x-b2-csrf':csrf})
            with urllib.request.urlopen(request) as r:boot=json.load(r)
            assert boot['character']['mapId']==MAP
            assert boot['character']['x']==boot['character']['z']==0
            assert server.store.require(boot['session']['token'])
            with urllib.request.urlopen(base_url+'/__local__/v27') as r:
                assert json.load(r)['version']=='27.0'
            assert (qa/'local.sqlite3').is_file()
            assert normal.read_bytes()==b'KEEP_OLD_CHARACTER_DB_UNCHANGED'
        finally:
            server.shutdown();server.server_close()
        (a/'env.json').unlink()
        assert not inspect_map(root)['ready']
    print('[SELFTEST OK] V29 independent A1 original map, isolated local SQLite, unchanged original assets, V27 routes')

def main():
    p=argparse.ArgumentParser(description='V29 reversible original A1 first-village QA')
    p.add_argument('action',choices=('selftest','audit','serve','start','report'),nargs='?',default='audit')
    p.add_argument('--port',type=int,default=PORT)
    p.add_argument('--root',type=Path)
    args=p.parse_args()
    if args.action=='selftest':
        selftest();return
    if not 1024<=args.port<=65535:raise SystemExit('invalid port')
    if args.action=='report':
        d=status(args.port)
        if d is None:raise SystemExit('V29 QA server not running')
        print('[MAP]',json.dumps(d['map'],ensure_ascii=False))
        print('[GAME]',json.dumps(d['gameMetrics'],ensure_ascii=False))
        print('[DB]',d['sqliteScope'],'[ASSETS] original_unchanged')
        return
    try:root=v26.resolve_original(args.root)
    except ValueError as e:raise SystemExit('[ARCHIVE]',str(e))
    info=inspect_map(root)
    print('[A1 MAP]',json.dumps(info,ensure_ascii=False),flush=True)
    if not info['ready']:raise SystemExit('[ERROR] Original A1 map metadata/core files incomplete')
    if args.action=='audit':return
    if args.action=='start':
        if status(args.port) is not None:
            print('[RUNNING] http://127.0.0.1:'+str(args.port)+'/__local__/');return
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1',args.port))==0:
                raise SystemExit('[ERROR] Port occupied; no process killed')
        log=PRIVATE/'v29_a1_visual.log'
        PRIVATE.mkdir(parents=True,exist_ok=True)
        with log.open('ab') as f:
            subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'serve',
                 '--port',str(args.port),'--root',str(root)],
                 stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,
                 start_new_session=True,close_fds=True)
        for _ in range(30):
            if status(args.port) is not None:
                print('[V29 A1] http://127.0.0.1:'+str(args.port)+'/__local__/')
                print('[QA REPORT] http://127.0.0.1:'+str(args.port)+'/__local__/v29')
                return
            time.sleep(.3)
        raise SystemExit('[ERROR] QA server not started; inspect log in private QA directory')
    server=make_server(root,args.port)
    print('[V29 A1] http://127.0.0.1:'+str(args.port)+'/__local__/',flush=True)
    print('[DB] QA_PRIVATE ONLY; original local character SQLite untouched',flush=True)
    try:server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':
    main()
