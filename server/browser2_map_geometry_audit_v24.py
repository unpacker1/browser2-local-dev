#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V24 read-only Browser2 map-coordinate/terrain provenance audit.

Uses original public map.json: computes scene object positions from observed
original client formula (game-mpPBZnwM.js: world x=x_cm/100-halfX,
z=-y_cm/100-halfZ, halfX=size_x*tile_m/2, halfZ=size_y*tile_m/2).
No spawn assumptions, no player movement, no original asset or SQLite edits.
Public HTTP source audit is optional and does not persist map files.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics
import urllib.parse
import urllib.request
import browser2_spawn_audit_v23 as v23

VERSION="24.0"
REPORTS=v23.REPORTS
MAPS=('map_a2','metin2_map_a1')
MAX_BYTES=10*1024*1024
SOURCE='https://browser2.to'

def number(v):
    return (isinstance(v,(int,float)) and not isinstance(v,bool)
            and math.isfinite(v))

def object_coordinates(meta):
    if not isinstance(meta,dict):return [],{'reason':'invalid_map_json'}
    sx=meta.get('size_x');sy=meta.get('size_y');tm=meta.get('tile_m')
    if not all(number(x) and x>0 for x in (sx,sy,tm)):
        return [],{'reason':'map_dimensions_unverified'}
    halfx=sx*tm/2;halfz=sy*tm/2
    points=[]
    structures=meta.get('objects')
    if not isinstance(structures,list):structures=[]
    for i,obj in enumerate(structures):
        if not isinstance(obj,dict):continue
        x,y=obj.get('x_cm'),obj.get('y_cm')
        if number(x) and number(y):
            wx=x*.01-halfx;wz=-y*.01-halfz
            if number(wx) and number(wz) and max(abs(wx),abs(wz))<1e7:
                points.append((wx,wz))
    info={'size_tiles':[sx,sy],'tile_m':tm,'half_extent_m':[halfx,halfz],
        'origin_inside_rectangular_extent':halfx>0 and halfz>0,
        'object_records':len(structures),'objects_with_original_coordinates':len(points),
        'coordinate_rule':'original_client_x_cm_y_cm_center_offset',
        'no_proven_spawn':True}
    return points,info

def geometry(meta):
    points,info=object_coordinates(meta)
    if not isinstance(meta,dict):return info
    base=meta.get('base_position_cm')
    if isinstance(base,(dict,list,tuple)):
        # Original map global base is reported without attempting to convert
        # into client-local spawn; source layout may vary between maps.
        if isinstance(base,dict):
            info['base_position_shape']={str(k):type(v).__name__ for k,v in list(base.items())[:12]}
            info['base_position_numeric']={str(k):v for k,v in list(base.items())[:12] if number(v)}
        elif isinstance(base,(list,tuple)):
            info['base_position_shape']='array'
            info['base_position_numeric']=[x for x in list(base)[:4] if number(x)]
    info['map_dimensions']={
        k:meta.get(k) for k in ('cell_m','tile_m','tile_cells','size_x','size_y',
            'height_min_m','height_max_m') if number(meta.get(k))}
    info['map_counts']={
        k:len(meta[k]) if isinstance(meta.get(k),list) else None
        for k in ('objects','tiles','textures','object_collisions','object_surfaces')}
    if points:
        distances=sorted(math.hypot(x,z) for x,z in points)
        info['near_origin_objects_m']={
            'within_5':sum(v<=5 for v in distances),
            'within_20':sum(v<=20 for v in distances),
            'within_50':sum(v<=50 for v in distances),
            'within_100':sum(v<=100 for v in distances)}
        info['nearest_object_distance_m']=round(distances[0],3)
        info['median_object_distance_m']=round(statistics.median(distances),3)
        info['object_bounds_m']={'x':[round(min(p[0] for p in points),2),round(max(p[0] for p in points),2)],
            'z':[round(min(p[1] for p in points),2),round(max(p[1] for p in points),2)]}
    for key in ('verified_rules','minimap','object_collision_source'):
        v=meta.get(key)
        info[key+'_present']=v is not None
    return info

def audit_from_disk(root=v23.ROOT,overlay=v23.OVERLAY):
    out={}
    for name in MAPS:
        meta,source=v23.original_map(root,overlay,name)
        out[name]={'source':source,**geometry(meta)}
    return out

def network_audit():
    result={}
    opener=urllib.request.build_opener(v23.v16.SameHostRedirect(SOURCE))
    for name in MAPS:
        path='/assets/maps/'+name+'/map.json'
        try:
            req=urllib.request.Request(SOURCE+path,headers={'Accept':'application/json',
                'User-Agent':'Browser2-local-readonly-public-map-geometry/24'})
            with opener.open(req,timeout=16) as r:
                u=urllib.parse.urlsplit(r.geturl())
                if u.scheme!='https' or u.hostname!='browser2.to' or u.path!=path or u.query:
                    raise ValueError('unexpected_redirect')
                if r.status!=200:raise ValueError('unexpected_status')
                payload=r.read(MAX_BYTES+1)
            if len(payload)>MAX_BYTES:raise ValueError('max_size_exceeded')
            data=json.loads(payload.decode('utf8'))
            if not isinstance(data,dict):raise ValueError('not_json_object')
            result[name]={'source':'official_public_https','sha256':hashlib.sha256(payload).hexdigest(),
                          **geometry(data)}
        except Exception as exc:
            # No HTTP response bodies, no credential-related data, no URL query logged.
            result[name]={'source':'unavailable','reason_type':type(exc).__name__}
    return result

def save(data,name='browser2_v24_geometri_audit.json'):
    REPORTS.mkdir(parents=True,exist_ok=True)
    p=REPORTS/name
    p.write_text(json.dumps({'version':VERSION,'maps':data,
         'local_game_default':{'map':'map_a2','x_m':0,'z_m':0},
         'provenance':'original map.json, formula inspected in original game JS',
         'warning':'This does not reveal a safe or authentic town spawn. No DB changes made.',
         'original_assets_modified':False,'private_db_modified':False},
        ensure_ascii=False,indent=2),encoding='utf-8')
    print('[RAPOR]',p)
    for name,v in data.items():
        print('[GEOMETRI]',name,'source=',v.get('source'),'half=',v.get('half_extent_m'),
              'near_origin=',v.get('near_origin_objects_m'), 'objects=',v.get('object_records'))
    print('[UYARI] Orijinal dogus noktasinin guvenli X/Z degeri henüz belirlenmedi.')
    return p

def selftest():
    meta={'size_x':4,'size_y':4,'tile_m':256,'objects':[
      {'x_cm':51200,'y_cm':-51200},
      {'x_cm':54200,'y_cm':-51200},
      {'x_cm':60000,'y_cm':-66000}]}
    o=geometry(meta)
    assert o['half_extent_m']==[512,512]
    assert o['objects_with_original_coordinates']==3
    assert o['near_origin_objects_m']['within_5']==1
    assert o['near_origin_objects_m']['within_50']==2
    assert o['nearest_object_distance_m']==0
    assert geometry({'size_x':'wrong','size_y':4,'tile_m':256})['reason']=='map_dimensions_unverified'
    assert geometry(meta)['no_proven_spawn'] is True
    print('[SELFTEST OK] V24 original centered-world coordinate formula and metadata audit')

def main():
    p=argparse.ArgumentParser(description='Read-only original map geometry audit')
    p.add_argument('action',nargs='?',choices=('audit','selftest','fetch-public'),default='audit')
    a=p.parse_args()
    if a.action=='selftest':selftest()
    elif a.action=='fetch-public':
        data=network_audit()
        # The CI source audit is reported in job logs only; no game assets committed.
        print('[PUBLIC GEOMETRY]',json.dumps(data,ensure_ascii=False))
        # If called from phone, write only summary into BROWSER2_BAGIMSIZ/RAPORLAR.
        if v23.ROOT.exists():save(data,'browser2_v24_public_geometri_audit.json')
    else:save(audit_from_disk())

if __name__=='__main__':main()
