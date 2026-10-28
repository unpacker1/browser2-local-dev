#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V24 reversible first-village preview, never rewrites the main local character DB.

Provisional spawn is computed from historical Metin2 Shinsoo start coordinates
(global centimetres) AND the original Browser2 first-village map's real
base_position_cm, size_x/size_y and tile_m. It is *only* an experiment, not
proof of an authentic Browser2 spawn. Invalid/out-of-map candidates abort.
The original database is backed up into a PRIVATE isolated preview copy.
Original client JS/WASM/world assets are never changed.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request

import browser2_public_world_asset_sync_v22 as v22
import browser2_spawn_audit_v23 as v23

VERSION='24.0'
PORT=8911
MAP_ID='metin2_map_a1'
# Classic Metin2 start coords, in GLOBAL CENTIMETRES, NOT Browser2 metres.
# https://metin2.dev/topic/7872-start-position-lycan/
# This is historical external evidence, not independently verified Browser2 spawn.
GLOBAL_START_CM=(469300,964200)
GLOBAL_CREATE_CM=(459800,953900)
PREVIEW_PRIVATE=v22.v21.v20.v19.v18.v17.PRIVATE/'v24_village_preview'
PREVIEW_DB=PREVIEW_PRIVATE/'preview.sqlite3'
PLAN_FILE=v22.REPORTS/'browser2_v24_koy_spawn_plani.json'
REPORT_FILE=v22.REPORTS/'browser2_v24_koy_onizleme_raporu.json'

base=v22.v21.v20.v19.v18.v17.v16.base

def finite(x):
    return isinstance(x,(float,int)) and not isinstance(x,bool) and math.isfinite(x)

def extract_base(value):
    if isinstance(value,(list,tuple)) and len(value)>=2:
        values=value[:2]
    elif isinstance(value,dict):
        x=value.get('x_cm',value.get('x'))
        y=value.get('y_cm',value.get('y',value.get('z_cm',value.get('z'))))
        values=(x,y)
    else:return None
    if all(finite(x) for x in values):return tuple(float(x) for x in values)
    return None

def build_plan(root=v22.ROOT,overlay=v23.OVERLAY,choice='start'):
    if choice not in ('start','create'):raise ValueError('invalid choice')
    data,source=v23.original_map(root,overlay,MAP_ID)
    if not isinstance(data,dict):raise ValueError('original a1 map JSON absent or invalid')
    fields=('size_x','size_y','tile_m')
    values=[data.get(x) for x in fields]
    if not all(finite(x) and x>0 and x<1000000 for x in values):
        raise ValueError('map dimensions or tile scale unavailable')
    count_x,count_y,tile_m=map(float,values)
    width=count_x*tile_m;height=count_y*tile_m
    if not (20<width<100000 and 20<height<100000):
        raise ValueError('map dimensions out of plausible metres range')
    original_base=extract_base(data.get('base_position_cm'))
    if original_base is None:raise ValueError('original map base_position_cm missing')
    if any(abs(n)>1e9 for n in original_base):raise ValueError('implausible map origin')
    point=GLOBAL_START_CM if choice=='start' else GLOBAL_CREATE_CM
    # Client renders original map objects at object_x_cm*.01-width/2;
    # original base_position_cm is a global CM offset, not world space.
    # Z orientation still requires visual confirmation; preview only.
    x=(point[0]-original_base[0])/100.-width/2
    z=(point[1]-original_base[1])/100.-height/2
    margin=10.
    within=all((-h+margin)<=p<=(h-margin) for p,h in ((x,width/2),(z,height/2)))
    return {'version':VERSION,'mapId':MAP_ID,'source':source,
        'original_map_size_m':{'width':width,'height':height},
        'original_base_position_cm':list(original_base),
        'historical_global_position_cm':list(point),
        'choice':choice,'client_local_candidate_m':{'x':round(x,3),'z':round(z,3)},
        'candidate_inside_terrain_bounds':within,
        'verified_original_browser2_spawn':False,
        'terrain_collision_checked':False,
        'assumption':'Global centimetres minus original map base, then centred world in metres; Z orientation requires visual confirmation',
        'safety':'Starts only with candidate inside the verified map bounds; never alters canonical character coordinates.'}

def persist_plan(plan,filename=PLAN_FILE):
    filename.parent.mkdir(parents=True,exist_ok=True)
    filename.write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    print('[PLAN]',filename)
    print('[KONUM]',plan.get('mapId'),plan.get('client_local_candidate_m'),
        'arazide=',plan.get('candidate_inside_terrain_bounds'),flush=True)
    if not plan['candidate_inside_terrain_bounds']:
        print('[GUVENLIK] Aday harita sinirlarinda degil; köy önizlemesi başlatılmaz.',flush=True)

def clone_private_database(original=v23.DB,destination=PREVIEW_DB):
    original=Path(original);destination=Path(destination)
    if not original.is_file():raise RuntimeError('Original local SQLite database missing')
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.parent.chmod(0o700)
    tmp=destination.with_name('preview_new.sqlite3')
    if tmp.exists():tmp.unlink()
    try:
        uri=original.resolve().as_uri()+'?mode=ro'
        with sqlite3.connect(uri,uri=True,timeout=8) as src,sqlite3.connect(tmp,timeout=8) as dst:
            src.backup(dst)
        with sqlite3.connect(tmp) as check:
            check.execute('SELECT map_id,x,z FROM characters LIMIT 1').fetchone()
        tmp.chmod(0o600)
        os.replace(tmp,destination)
    finally:tmp.unlink(missing_ok=True)
    return destination

class PreviewStore(base.Store):
    """Only session/join mutations to cloned preview DB; main character DB untouched."""
    def __init__(self,path,plan):
        super().__init__(path)
        self.preview_plan=plan
    def char_public(self,row):
        d=super().char_public(row)
        point=self.preview_plan['client_local_candidate_m']
        d.update({'mapId':MAP_ID,'x':point['x'],'z':point['z']})
        return d
    def save_pos(self,character):
        # Preview movement must never overwrite original player positions.
        return None
    def create_char(self,user,data):
        raise base.Error(409,'Create characters on the normal local server instead')
    def del_char(self,user,charid):
        raise base.Error(409,'Delete characters on the normal local server instead')

class Handler(v22.Handler):
    server_version='Browser2Local/24'
    def do_GET(self):
        p=urllib.parse.unquote(urllib.parse.urlsplit(self.path).path)
        if p=='/__local__/v24':
            with self.server.active_lock:active=self.server.active
            return self.json(200,{'version':VERSION,'mapId':MAP_ID,
                'candidate':self.server.preview_plan['client_local_candidate_m'],
                'historical_not_verified':True,'main_character_db_unchanged':True,
                'active_world':active,
                'game_metrics':{k:v for k,v in self.server.metrics.items()
                                 if k.startswith(('world_','game_join'))}})
        if p=='/catalogs/maps' or (p.endswith('/catalogs/maps') and
                __import__('re').fullmatch(r'/world/[A-Za-z0-9_@-]+/catalogs/maps',p)):
            plan=self.server.preview_plan
            size=plan['original_map_size_m']
            return self.json(200,[{'id':MAP_ID,'mapId':MAP_ID,'name':MAP_ID,
                'tileSet':MAP_ID,'halfX':size['width']/2,'halfZ':size['height']/2,'npcs':[]}])
        return super().do_GET()

class Server(v22.Server):
    def __init__(self,bind,root,state,fetcher,plan):
        super().__init__(bind,root,state,fetcher)
        self.preview_plan=plan
        # Parent server has already used private preview DB via environment.
        self.store=PreviewStore(PREVIEW_DB,plan)
        self.RequestHandlerClass=Handler

def health(port=PORT):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/__local__/v24',timeout=2) as r:
            obj=json.load(r)
        return obj if obj.get('version')==VERSION else None
    except (OSError,ValueError):return None

def report(port):
    r=health(port)
    if not r:raise SystemExit('[HATA] V24 önizleme sunucusu açık değil')
    v22.REPORTS.mkdir(parents=True,exist_ok=True)
    REPORT_FILE.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
    print('[RAPOR]',REPORT_FILE)
    print('[MAP]',r['mapId'],'[KONUM]',r['candidate'])
    print('[GAME]',r['game_metrics'])
    print('[ORIJINAL SQLITE] Degistirilmedi')

def serve(port,choice):
    v22.v21.v20.v19.v18.v17.prepare_env()
    plan=build_plan(choice=choice)
    persist_plan(plan)
    if not plan['candidate_inside_terrain_bounds']:
        raise SystemExit('[HATA] Baslangic konumu harita disinda; otomatik deneme yapilmadi')
    for name in ('map.json','heightmap.bin','collision.bin','env.json'):
        if not any((Path(p)/'assets/maps'/MAP_ID/name).is_file()
                   for p in (v22.ROOT,v23.OVERLAY)):
            raise SystemExit('[HATA] Orijinal birinci koy harita dosyasi eksik: '+name)
    clone_private_database()
    # Redirection ONLY within this subprocess. Main account/character DB not opened for writes.
    os.environ['BROWSER2_PRIVATE_DB']=str(PREVIEW_DB)
    for d in (v22.REPORTS,v22.LOGS,v22.OVERLAY,v22.BASE/'YEREL_SUNUCU'):
        d.mkdir(parents=True,exist_ok=True)
    maps=v22.v21.v20.v19.v18.v17.v16.Fetcher(
        v22.ROOT,v22.BASE/'YEREL_SUNUCU/browser2_v16_map_overlay')
    server=Server(('127.0.0.1',port),v22.ROOT,
        v22.BASE/'YEREL_SUNUCU',maps,plan)
    print(f'[V24] http://127.0.0.1:{port}/__local__/',flush=True)
    try:server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:server.server_close()

def start(port,choice):
    if health(port):
        return print(f'[V24] Zaten acik: http://127.0.0.1:{port}/__local__/')
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1',port))==0:
            raise SystemExit('[HATA] Port baska uygulama tarafindan kullaniliyor')
    plan=build_plan(choice=choice)
    persist_plan(plan)
    if not plan['candidate_inside_terrain_bounds']:
        raise SystemExit('[HATA] Koordinat dogrulanamadi; güvenli önizleme açılmadı')
    v22.LOGS.mkdir(parents=True,exist_ok=True)
    with (v22.LOGS/'browser2_v24_preview.log').open('ab') as out:
        subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'serve',
            '--port',str(port),'--choice',choice],stdin=subprocess.DEVNULL,
            stdout=out,stderr=subprocess.STDOUT,
            env=os.environ.copy(),start_new_session=True,close_fds=True)
    for _ in range(50):
        if health(port):return print(f'[V24] Acildi: http://127.0.0.1:{port}/__local__/')
        time.sleep(.2)
    raise SystemExit('[HATA] V24 baslatilamadi. LOGS/browser2_v24_preview.log')

def selftest():
    fixture={'size_x':4,'size_y':4,'tile_m':256,
             'base_position_cm':[400000,900000]}
    import tempfile
    with tempfile.TemporaryDirectory() as t:
        p=Path(t);root=p/'original';orig=root/'assets/maps'/MAP_ID
        orig.mkdir(parents=True)
        (orig/'map.json').write_text(json.dumps(fixture))
        plan=build_plan(root,p/'overlay','start')
        assert plan['candidate_inside_terrain_bounds']
        assert abs(plan['client_local_candidate_m']['x']-181)<1e-5
        assert abs(plan['client_local_candidate_m']['z']-130)<1e-5
        assert not plan['verified_original_browser2_spawn']
        # A safe remote world identity is presented without changing DB.
        src=p/'canonical.sqlite3'
        with sqlite3.connect(src) as db:
            db.execute('CREATE TABLE characters (id TEXT, map_id TEXT, x REAL,z REAL)')
            db.execute("INSERT INTO characters VALUES ('id1','map_a2',0,0)")
        dst=p/'private/preview.sqlite3'
        clone_private_database(src,dst)
        with sqlite3.connect(dst) as db:
            db.execute("UPDATE characters SET x=4,z=8 WHERE id='id1'")
        with sqlite3.connect(src) as db:
            assert db.execute('SELECT map_id,x,z FROM characters').fetchone()==('map_a2',0,0)
        outside=dict(fixture,base_position_cm=[0,0])
        (orig/'map.json').write_text(json.dumps(outside))
        assert not build_plan(root,p/'overlay','start')['candidate_inside_terrain_bounds']
    print('[SELFTEST OK] V24 historic candidate bounded by original map, isolated SQLite preview and source untouched')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('action',nargs='?',choices=('selftest','plan','start','serve','rapor'),default='plan')
    p.add_argument('--port',type=int,default=PORT)
    p.add_argument('--choice',choices=('start','create'),default='start')
    args=p.parse_args()
    if not 1024<=args.port<=65535:raise SystemExit('invalid port')
    if args.action=='selftest':selftest()
    elif args.action=='plan':persist_plan(build_plan(choice=args.choice))
    elif args.action=='start':start(args.port,args.choice)
    elif args.action=='serve':serve(args.port,args.choice)
    else:report(args.port)
if __name__=='__main__':main()
