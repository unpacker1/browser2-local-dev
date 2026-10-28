#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""V21: sync unmodified, publicly accessible Browser2 locale JSON to a local overlay.

Original Browser2 assets always win, and are never modified.
Network sync is explicit and restricted to HTTPS browser2.to + fixed locale paths.
No cookies, auth, tokens, headers from game sessions, or generated translations.
No copied localization data is committed to the public repository.
"""
from __future__ import annotations
import argparse
import hashlib
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
import urllib.error
import urllib.parse
import urllib.request
import browser2_client_boot_probe_v20 as v20

VERSION="21.0"
PORT=8906
ROOT=v20.v19.v18.ORIGINAL
BASE=v20.v19.v18.BASE
REPORTS=v20.v19.v18.REPORTS
LOGS=v20.v19.v18.LOGS
OVERLAY=BASE/'YEREL_SUNUCU/browser2_v21_locale_overlay'
HOST="https://browser2.to"
LANGS=('en','tr')
NAMES=('client.intro','client.net_ui','system','game.world','game.item',
       'game.mob','game.skill','game.skill_extra','game.companion',
       'client.interface','client.game','game.quest','client.dungeons',
       'client.options','client.forum','client.minimap','client.tooltip',
       'client.cube','client.guild','game.shop_deco')
MAX_JSON=2*1024*1024

def allowed_path(path):
    if not isinstance(path,str):return False
    m=re.fullmatch(r'/locales/(en|tr)/([a-z][a-z0-9_.-]{0,49})\.json',path)
    return bool(m) and m.group(2) in NAMES

def checked_json(raw):
    if not isinstance(raw,bytes) or len(raw)<2 or len(raw)>MAX_JSON:
        raise ValueError('invalid_size')
    if raw.lstrip().lower().startswith((b'<html',b'<!doctype',b'<?xml')):
        raise ValueError('not_json_asset')
    try:v=json.loads(raw.decode('utf-8-sig'))
    except (ValueError,UnicodeError):raise ValueError('invalid_json')
    if not isinstance(v,dict) or not v or any(k in v for k in ('error','errors','statusCode')):
        raise ValueError('unexpected_catalog_shape')
    return v

def local_source(root,overlay,path):
    orig=Path(root)/path.lstrip('/')
    if orig.is_file():
        try:checked_json(orig.read_bytes());return orig,'original_present'
        except (OSError,ValueError):return None,'original_invalid'
    over=Path(overlay)/path.lstrip('/')
    if over.is_file():
        try:checked_json(over.read_bytes());return over,'overlay_present'
        except (OSError,ValueError):return None,'overlay_invalid'
    return None,'missing'

def opener():
    # Reuse the same-host HTTPS redirect gate from the existing V16 map downloader.
    return urllib.request.build_opener(v20.v19.v18.v17.v16.SameHostRedirect(HOST))

def sync(root=ROOT,overlay=OVERLAY,languages=LANGS,remote=None):
    results=[];fetch=remote or opener()
    for lang in languages:
        if lang not in LANGS:raise ValueError('unsupported_language')
        for name in NAMES:
            path=f'/locales/{lang}/{name}.json'
            target=Path(overlay)/path.lstrip('/')
            existing,status=local_source(root,overlay,path)
            if status!='missing':
                results.append({'path':path,'status':status})
                continue
            tmp=None
            try:
                req=urllib.request.Request(HOST+path,headers={
                    'Accept':'application/json',
                    'User-Agent':'Browser2-local-public-locale-integrity-check/21'})
                with fetch.open(req,timeout=12) as response:
                    final=urllib.parse.urlsplit(response.geturl())
                    if final.scheme!='https' or final.hostname!='browser2.to' or final.path!=path:
                        raise ValueError('unexpected_redirect')
                    length=response.headers.get('Content-Length','')
                    if length.isdigit() and int(length)>MAX_JSON:raise ValueError('too_large')
                    payload=response.read(MAX_JSON+1)
                checked_json(payload)
                target.parent.mkdir(parents=True,exist_ok=True)
                with tempfile.NamedTemporaryFile(mode='wb',dir=target.parent,
                    prefix='.original-locale-',suffix='.partial',delete=False) as f:
                    tmp=Path(f.name);f.write(payload);f.flush();os.fsync(f.fileno())
                if target.exists():
                    raise ValueError('target_appeared')
                os.replace(tmp,target);tmp=None
                results.append({'path':path,'status':'downloaded','bytes':len(payload),
                                'sha256':hashlib.sha256(payload).hexdigest()})
            except urllib.error.HTTPError as e:
                results.append({'path':path,'status':f'http_{e.code}'})
            except urllib.error.URLError as e:
                results.append({'path':path,'status':'network_error'})
            except (ValueError,OSError,TimeoutError) as e:
                results.append({'path':path,'status':'invalid_or_failed',
                                'reason':str(e)[:60] if isinstance(e,ValueError) else type(e).__name__})
            finally:
                if tmp is not None:tmp.unlink(missing_ok=True)
    return results

class Handler(v20.Handler):
    server_version='Browser2Local/21'
    def do_GET(self):
        if urllib.parse.urlsplit(self.path).path=='/__local__/v21':
            sources=[]
            for lang in LANGS:
                for name in NAMES:
                    p=f'/locales/{lang}/{name}.json'
                    _,state=local_source(self.server.root,self.server.locale_overlay,p)
                    sources.append({'path':p,'status':state})
            d={'version':VERSION,'sources':sources,
               'original_files_modified':False,
               'mode':'Original locale overlay only; no fake translations or client JS changes'}
            return self.json(200,d)
        return super().do_GET()
    def static(self,p):
        if allowed_path(p):
            src,status=local_source(self.server.root,self.server.locale_overlay,p)
            if src is not None and status=='overlay_present':
                # Only return an original JSON byte stream validated at sync time.
                return v20.v19.v18.v17.v16.serve_file(self,src)
        return super().static(p)

class Server(v20.Server):
    def __init__(self,bind,root,state,fetcher,overlay=OVERLAY):
        super().__init__(bind,root,state,fetcher)
        self.locale_overlay=Path(overlay)
        self.RequestHandlerClass=Handler

def report(port=PORT):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/__local__/v21',timeout=3) as r:
            d=json.load(r)
        if d.get('version')!=VERSION:raise ValueError('wrong_version')
    except (OSError,ValueError) as e:
        raise SystemExit('[HATA] V21 yerel sunucusu calismiyor') from e
    REPORTS.mkdir(parents=True,exist_ok=True)
    p=REPORTS/'browser2_v21_locale_raporu.json'
    p.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
    from collections import Counter
    print('[RAPOR]',p)
    print('[LOCALE]',dict(Counter(x['status'] for x in d['sources'])))
    # V20's underlying bootstrap event counters remain available.
    v20.report(port)

def write_sync_report(results):
    REPORTS.mkdir(parents=True,exist_ok=True)
    path=REPORTS/'browser2_v21_locale_sync_raporu.json'
    path.write_text(json.dumps({'version':VERSION,'sync':results,
        'original_files_modified':False},ensure_ascii=False,indent=2),encoding='utf-8')
    from collections import Counter
    print('[SENKRON RAPOR]',path)
    print('[DURUM]',dict(Counter(x['status'] for x in results)))
    print('[NOT] Yalnizca HTTP 200 ile alinmis, dogrulanmis orijinal JSON dosyalari kullanilir.')

def selftest():
    assert allowed_path('/locales/en/game.world.json')
    assert allowed_path('/locales/tr/system.json')
    assert not allowed_path('/locales/../system.json')
    assert not allowed_path('/locales/en/token.json')
    assert not allowed_path('/locales/en/%2e%2e/auth.json')
    assert checked_json(b'{"a":"text"}')=={'a':'text'}
    for value in (b'<html>blocked</html>',b'{}',b'{"error":"blocked"}',b'[]'):
        try:checked_json(value)
        except ValueError:pass
        else:raise AssertionError('invalid locale accepted')
    with tempfile.TemporaryDirectory() as td:
        base=Path(td);root=base/'original';root.mkdir();(root/'assets').mkdir()
        (root/'index.html').write_text('<html><head></head><body>original</body></html>')
        overlay=base/'locale';target=overlay/'locales/en/game.world.json'
        target.parent.mkdir(parents=True);target.write_bytes(b'{"original":"translation"}')
        # ORIGINAL always wins if also present.
        prev=os.environ.get('BROWSER2_PRIVATE_DB')
        os.environ['BROWSER2_PRIVATE_DB']=str(base/'private/local.sqlite3')
        try:
            f=v20.v19.v18.v17.v16.Fetcher(root,base/'map_overlay')
            s=Server(('127.0.0.1',0),root,base/'state',f,overlay)
            thread=threading.Thread(target=s.serve_forever,daemon=True);thread.start()
            try:
                url=f'http://127.0.0.1:{s.server_port}'
                with urllib.request.urlopen(url+'/locales/en/game.world.json') as r:
                    assert json.load(r)=={'original':'translation'}
                with urllib.request.urlopen(url+'/__local__/v21') as r:
                    assert json.load(r)['version']==VERSION
                genuine=root/'locales/en/game.world.json'
                genuine.parent.mkdir(parents=True)
                genuine.write_bytes(b'{"original":"archive_wins"}')
                with urllib.request.urlopen(url+'/locales/en/game.world.json') as r:
                    assert json.load(r)=={'original':'archive_wins'}
                assert target.read_bytes()==b'{"original":"translation"}'
            finally:s.shutdown();s.server_close()
        finally:
            if prev is None:os.environ.pop('BROWSER2_PRIVATE_DB',None)
            else:os.environ['BROWSER2_PRIVATE_DB']=prev
    print('[SELFTEST OK] V21 original locale first, verified overlay, no synthetic translations')

def serve(port):
    v20.v19.v18.v17.prepare_env()
    for d in (REPORTS,LOGS,OVERLAY,BASE/'YEREL_SUNUCU',v20.v19.v18.v17.PRIVATE):d.mkdir(parents=True,exist_ok=True)
    if not v20.v19.v18.v17.v16.prev.audit(ROOT):
        raise SystemExit('[HATA] Yerel orijinal oyun arsivi eksik')
    fetcher=v20.v19.v18.v17.v16.Fetcher(ROOT,BASE/'YEREL_SUNUCU/browser2_v16_map_overlay')
    s=Server(('127.0.0.1',port),ROOT,BASE/'YEREL_SUNUCU',fetcher)
    print(f'[V21] http://127.0.0.1:{port}/__local__/',flush=True)
    try:s.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:s.server_close()

def alive(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/__local__/v21',timeout=2) as r:
            return json.load(r).get('version')==VERSION
    except (OSError,ValueError):return False

def start(port):
    if alive(port):
        print(f'[V21] Zaten acik: http://127.0.0.1:{port}/__local__/');return
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1',port))==0:
            raise SystemExit('[HATA] Port baska sunucuda kullaniliyor')
    v20.v19.v18.v17.prepare_env();LOGS.mkdir(parents=True,exist_ok=True)
    with (LOGS/'browser2_v21_server.log').open('ab') as fp:
        subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'serve','--port',str(port)],
            stdin=subprocess.DEVNULL,stdout=fp,stderr=subprocess.STDOUT,
            env=os.environ.copy(),start_new_session=True,close_fds=True)
    for _ in range(40):
        if alive(port):
            print(f'[V21] Acildi: http://127.0.0.1:{port}/__local__/');return
        time.sleep(.2)
    raise SystemExit('[HATA] V21 sunucu baslatilamadi; LOGS/browser2_v21_server.log')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',nargs='?',choices=('selftest','sync','start','serve','rapor'),default='start')
    parser.add_argument('--port',type=int,default=PORT)
    parser.add_argument('--lang',choices=LANGS+('both',),default='en')
    a=parser.parse_args()
    if not 1024<=a.port<=65535:raise SystemExit('invalid port')
    if a.action=='selftest':selftest()
    elif a.action=='sync':
        langs=LANGS if a.lang=='both' else (a.lang,)
        write_sync_report(sync(languages=langs))
    elif a.action=='start':start(a.port)
    elif a.action=='serve':serve(a.port)
    else:report(a.port)

if __name__=='__main__':main()
