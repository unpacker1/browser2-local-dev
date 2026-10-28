#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V23 read-only spawn / map identity audit for the LOCAL Browser2 server.

Reports why a character at 0,0 in map_a2 is not evidence of village spawn.
Fetches only the original public first-village map files on explicit 'sync'.
Never edits SQLite, original JS, GLB, KTX2, map assets, or GAME packets.
Privacy: no account names, character names, IDs, tokens, or session data in reports.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import browser2_local_map_sync_v16 as v16
import browser2_gercek_oyun_tani_v17 as v17

VERSION='23.0'
ROOT=v17.ORIGINAL
BASE=v17.BASE
REPORTS=v17.REPORTS
OVERLAY=BASE/'YEREL_SUNUCU/browser2_v16_map_overlay'
DB=v17.PRIVATE/'local.sqlite3'
OLD_MAP='map_a2'
VILLAGE_MAP='metin2_map_a1'

def original_map(root,overlay,mapid):
    for base in (Path(root),Path(overlay)):
        p=base/'assets/maps'/mapid/'map.json'
        if p.is_file():
            try:
                if p.stat().st_size>32*1024*1024:raise ValueError('map_too_large')
                with p.open(encoding='utf-8') as f:d=json.load(f)
                if isinstance(d,dict):
                    return d,('original' if base==Path(root) else 'overlay')
            except (ValueError,OSError,UnicodeError):
                return None,'invalid'
    return None,'missing'

def scalar(n):
    return isinstance(n,(int,float)) and not isinstance(n,bool) and math.isfinite(n)

def anchors(value):
    """Only explicit player/town/spawn coordinate fields; no arbitrary tile centroid."""
    results=[]
    def rec(obj,prefix,depth):
        if not isinstance(obj,dict) or depth>3:return
        for key,item in obj.items():
            if not isinstance(key,str):continue
            k=key.lower().replace('-','_')
            if k in ('spawn','spawnpoint','spawn_point','player_spawn',
                     'town_spawn','town_center','village_center','start_position',
                     'start_pos','entry_point','player_start','safe_spawn') and isinstance(item,dict):
                x=item.get('x');z=item.get('z',item.get('y'))
                if scalar(x) and scalar(z):
                    results.append({'source_key':(prefix+'.'+key).strip('.'),
                        'x':float(x),'z':float(z),
                        'evidence':'explicit_metadata_key','map_units':'unverified'})
            if isinstance(item,dict) and k in ('world','player','entry','start',
                'spawn','town','village','metadata','settings','config'):
                rec(item,(prefix+'.'+key).strip('.'),depth+1)
    rec(value,'',0)
    return results[:12]

def db_summary(dbpath):
    if not Path(dbpath).is_file():return {'present':False,'characters':0}
    try:
        uri=Path(dbpath).absolute().as_uri()+'?mode=ro'
        with sqlite3.connect(uri,uri=True,timeout=2) as conn:
            rows=conn.execute('SELECT map_id,x,z FROM characters LIMIT 30').fetchall()
        by_map=Counter(str(r[0]) for r in rows)
        zeros=sum(1 for _,x,z in rows if scalar(x) and scalar(z) and abs(x)<1e-6 and abs(z)<1e-6)
        positions=[{'map':str(m),'x':round(x,3),'z':round(z,3)}
                   for m,x,z in rows[:10] if scalar(x) and scalar(z)]
        return {'present':True,'characters':len(rows),'by_map':dict(by_map),
                'at_zero_zero':zeros,'positions_no_identity':positions}
    except (sqlite3.Error,OSError,ValueError) as exc:
        return {'present':True,'error_type':type(exc).__name__}

def map_summary(root,overlay,mapid):
    d,source=original_map(root,overlay,mapid)
    files={}
    for fn in ('map.json','heightmap.bin','collision.bin','env.json'):
        p=Path(root)/'assets/maps'/mapid/fn
        alt=Path(overlay)/'assets/maps'/mapid/fn
        files[fn]='original' if p.is_file() else ('overlay' if alt.is_file() else 'missing')
    out={'map_id':mapid,'map_json_source':source,'files':files,
         'has_core':files['map.json']!='missing' and files['heightmap.bin']!='missing'}
    if isinstance(d,dict):
        out['top_level_fields']=[k for k in d.keys() if isinstance(k,str)][:90]
        out['explicit_spawn_anchors']=anchors(d)
        out['tile_count']=len(d['tiles']) if isinstance(d.get('tiles'),list) else None
        for key in ('width','height','halfX','halfZ','worldWidth','worldHeight','terrain_visible','parent'):
            v=d.get(key)
            if isinstance(v,(str,int,float,bool)) or v is None:
                out[key]=v
    return out

def atlas_check(root):
    p=Path(root)/'assets/teleport-atlas-data-DPsvjJBn.js'
    if not p.is_file():return {'present':False}
    b=p.read_bytes()
    return {'present':True,'mentions_yongan':b'yongan' in b,
            'mentions_first_village_map':b'metin2_map_a1' in b,
            'source':'original_teleport_atlas'}

def audit(root=ROOT,overlay=OVERLAY,db=DB,save=True):
    original=v16.inspect_registry(root)
    first=map_summary(root,overlay,VILLAGE_MAP)
    fallback=map_summary(root,overlay,OLD_MAP)
    characters=db_summary(db)
    report={'version':VERSION,'original_file_writes':False,'database_writes':False,
        'registry':original,'original_atlas':atlas_check(root),
        'first_village':first,'current_default_map':fallback,'local_characters':characters,
        'source_code_facts':{
          'bootstrap_default_map':OLD_MAP,'bootstrap_default_x':0.0,'bootstrap_default_z':0.0,
          'game_map_catalog_is_hardcoded_to':OLD_MAP,
          'original_client_world_map1_alias':OLD_MAP},
        'readiness':{
          'first_village_core_present':first['has_core'],
          'metadata_has_explicit_spawn':bool(first.get('explicit_spawn_anchors')),
          'can_safely_auto_relocate':False},
        'next_step':'Do not change player DB or map catalog until authentic start X/Z and world-id mapping are confirmed.'}
    if save:
        REPORTS.mkdir(parents=True,exist_ok=True)
        p=REPORTS/'browser2_v23_spawn_audit.json'
        p.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print('[RAPOR]',p)
    print('[HARITA]',VILLAGE_MAP,first['files'])
    print('[KARAKTER]',{'maps':characters.get('by_map',{}),
        'zero_zero':characters.get('at_zero_zero')})
    print('[ORIJINAL BASLANGIC KAYDI]',first.get('explicit_spawn_anchors',[]))
    print('[GUVELIK] Sadece okuma. Orijinal dosya/SQLite değiştirilmedi.')
    return report

def sync():
    ROOT.mkdir(parents=True,exist_ok=True) if False else None
    if not v16.prev.audit(ROOT):raise SystemExit('[HATA] Orijinal oyun arşivi bulunamadı')
    fetcher=v16.Fetcher(ROOT,OVERLAY)
    d=v16.make_sync_report(fetcher,ROOT,VILLAGE_MAP,expand=60)
    REPORTS.mkdir(parents=True,exist_ok=True)
    p=REPORTS/'browser2_v23_original_village_map_sync.json'
    p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
    print('[MAP SENKRON RAPORU]',p)
    print('[ORIJINAL KAYNAK]',VILLAGE_MAP,
          'map_core_ready=',d.get('required_terrain_present'))
    for item in d.get('core',[]):
        print('[HARITA DOSYASI]',item.get('status'),item.get('path'))
    return d

def selftest():
    assert anchors({'start_position':{'x':123.4,'z':567.8}})==[
        {'source_key':'start_position','x':123.4,'z':567.8,
         'evidence':'explicit_metadata_key','map_units':'unverified'}]
    assert not anchors({'tiles':[{'x':900,'z':900}],'npc':{'x':5,'z':6}})
    assert not anchors({'spawn':{'x':float('nan'),'z':2}})
    with tempfile.TemporaryDirectory() as tmp:
        t=Path(tmp);root=t/'original';over=t/'overlay'
        p=root/'assets/maps/metin2_map_a1/map.json'
        p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text('{"tiles":[{"x":0}],"spawn":{"x":111,"z":222}}')
        q=over/'assets/maps/metin2_map_a1/map.json'
        q.parent.mkdir(parents=True,exist_ok=True);q.write_text('{"spawn":{"x":999,"z":999}}')
        first=map_summary(root,over,VILLAGE_MAP)
        assert first['explicit_spawn_anchors'][0]['x']==111.0
        assert first['map_json_source']=='original'
        assert p.read_bytes()==b'{"tiles":[{"x":0}],"spawn":{"x":111,"z":222}}'
        db=t/'local.sqlite3'
        with sqlite3.connect(db) as c:
            c.execute('CREATE TABLE characters (map_id TEXT, x REAL, z REAL)')
            c.execute('INSERT INTO characters VALUES (?,?,?)',('map_a2',0,0))
        result=db_summary(db)
        assert result['by_map']=={'map_a2':1} and result['at_zero_zero']==1
        assert map_summary(root,over,OLD_MAP)['has_core'] is False
    print('[SELFTEST OK] V23 read-only map/spawn provenance, SQLite positions, original priority')

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('action',nargs='?',choices=('selftest','audit','sync'),default='audit')
    a=ap.parse_args()
    if a.action=='selftest':selftest()
    elif a.action=='sync':sync();audit()
    else:audit()
if __name__=='__main__':main()
