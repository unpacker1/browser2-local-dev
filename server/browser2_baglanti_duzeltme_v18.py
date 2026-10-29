#!/usr/bin/env python3
# Browser2 V18. Read-only original client; new launcher derives world URL from original auth module.
# No credential, token, IP, websocket payload or player name logged.
from __future__ import annotations
import collections, html, http.cookies, json, os, re, secrets, socket, subprocess, sys, threading, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer
import browser2_gercek_oyun_tani_v17 as v17

BASE=Path.home()/'storage/downloads/BROWSER2_BAGIMSIZ'
REPORTS=BASE/'RAPORLAR';LOGS=BASE/'LOGS';ORIGINAL=BASE/'public_assets/browser2.to'
PORT=8899
CLIENT_HTML='<!doctype html><html lang="tr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Browser2 Yerel V18</title><style>body{background:#101824;color:#f2eee4;font:16px system-ui;padding:18px;max-width:660px;margin:auto}button{font:inherit;background:#27c49f;color:#091e1d;padding:14px;border:0;border-radius:9px;font-weight:bold}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#1f3041;padding:12px;border-radius:8px}small{color:#b7c8d8}</style><h2>Browser2 — Orijinal istemci / Yerel AUTH + GAME</h2><p>Giriş adresini orijinal AUTH modülünün <code>worldServerFor</code> fonksiyonundan hesaplar. Oyun JS dosyalarını değiştirmez.</p><button id="b">Yerel dünyaya gir</button><p><a href="/__local__/status" style="color:#9cdeff">Bağlantı durumu</a></p><pre id="s">Hazır. Yerel karakter kullanılır; gerçek site hesabı kullanılmaz.</pre><small>Yerel GAME sunucusu kısmi uyumluluk uygulamasıdır, tam oynanış garanti edilmez.</small><script type="module">\nconst button=document.getElementById(\'b\'), status=document.getElementById(\'s\');\nasync function note(ev){try{await fetch(\'/__local__/v18/event\',{method:\'POST\',headers:{\'content-type\':\'application/json\'},body:JSON.stringify({event:ev})})}catch{}}\nbutton.onclick=async()=>{button.disabled=true;status.textContent=\'Yerel oturum hazırlanıyor...\';try{\n  const csrf=document.cookie.split(\'; \').find(s=>s.startsWith(\'b2csrf=\'))?.split(\'=\')[1]||\'\';\n  const r=await fetch(\'/__local__/bootstrap\',{method:\'POST\',headers:{\'x-b2-csrf\':csrf,\'content-type\':\'application/json\'},body:\'{}\'});\n  if(!r.ok)throw Error(\'Yerel oturum isteği HTTP \'+r.status);\n  const j=await r.json(),c=j.character;\n  if(!c?.id||!c?.mapId||!j.session?.token)throw Error(\'Yerel karakter/oturum alanları eksik\');\n  localStorage.setItem(\'ymir.session.v1\',JSON.stringify(j.session));\n  let auth;try{auth=await import(\'__ORIGINAL_AUTH_MODULE__\')}catch(e){await note(\'auth_import_error\');throw Error(\'Orijinal AUTH modülü yüklenemedi: \'+e.message)}\n  const fn=auth?.a7?.worldServerFor;\n  if(typeof fn!==\'function\'){await note(\'auth_export_missing\');throw Error(\'Orijinal AUTH worldServerFor bulunamadı\')}\n  const server=fn(c.mapId);const u=new URL(server);\n  if(!/^wss?:$/.test(u.protocol)||u.host!==location.host||!/^\\/world\\/[A-Za-z0-9_@-]+$/.test(u.pathname))throw Error(\'Orijinal AUTH sunucu adresi beklenen yerel kökende değil\');\n  const cls=(c.classId===\'ninja\'?\'assassin\':c.classId)+\'_\'+(c.gender===\'w\'?\'w\':\'m\');\n  const q=new URLSearchParams({screen:\'game\',name:c.id,map:c.mapId,class:cls,empire:String(c.empire),server:u.href});\n  status.textContent=\'Orijinal AUTH sunucu yönlendirmesi doğrulandı. Oyun ekranı açılıyor...\';\n  await note(\'launch_using_original_auth\');location.assign(\'/?\'+q.toString());\n}catch(e){await note(\'launch_error\');status.textContent=\'Hata: \'+e.message;button.disabled=false}}\n</script></html>'
EVENTS={'auth_import_error','auth_export_missing','launch_using_original_auth','launch_error'}
class Handler(v17.Handler):
    server_version='Browser2Local/18'
    def send_response(self,code,message=None):
        kind=v17.category(self.path,self.command)
        if kind is not None:
            self.server.class_status[(kind,str(code))]+=1
        return super().send_response(code,message)
    def do_GET(self):
        p=urllib.parse.urlsplit(self.path).path
        if p=='/__local__/':
            # The active AUTH bundle is determined by the unmodified original
            # index.html, not a historical hash. Substitution only affects
            # this locally generated launcher response.
            bundles=v17.v16.base.discover_original_bundles(self.server.root)
            auth=bundles.get('auth')
            if not auth or 'game' not in bundles or 'world_bridge' not in bundles:
                return self.sendbody(503,b'Original client module set incomplete or ambiguous',
                                     'text/plain; charset=utf-8',{'Cache-Control':'no-store'})
            csrf=secrets.token_urlsafe(18)
            page=CLIENT_HTML.replace('__ORIGINAL_AUTH_MODULE__','/assets/'+auth)
            return self.sendbody(200,page.encode('utf-8'),'text/html; charset=utf-8',{
              'Set-Cookie':f'b2csrf={csrf}; Path=/__local__/; SameSite=Strict',
              'Cache-Control':'no-store',
              'Content-Security-Policy':"default-src 'none'; script-src 'self' 'unsafe-inline'; connect-src 'self'; style-src 'unsafe-inline'"})
        if p in ('/__local__/status','/__local__/v18'):
            public={'version':'18.0','source':'original client unchanged','status_by_route':[
                {'route_class':k,'http_status':int(code),'requests':n}
                for (k,code),n in sorted(self.server.class_status.items())],
                'trace_counters':dict(self.server.trace.counters),
                'backend_metrics':dict(self.server.metrics),
                'launcher_events':dict(self.server.launcher_events),
                'world_active':self.server.active,
                'notes':['WebSocket 101 + JoinAccepted is proof of server-side join only',
                    'Local GAME is partial, not the original proprietary game server',
                    'No secrets, body data, full URLs, headers, names or IPs retained']}
            return self.json(200,public)
        return super().do_GET()
    def do_POST(self):
        if urllib.parse.urlsplit(self.path).path=='/__local__/v18/event':
            try:
                self.require_origin()
                length=int(self.headers.get('Content-Length','0'))
                if length<1 or length>120:raise ValueError('size')
                d=json.loads(self.rfile.read(length));event=d.get('event')
                if event not in EVENTS:raise ValueError('invalid event')
                self.server.launcher_events[event]+=1
                return self.json(200,{'ok':True})
            except (ValueError,TypeError,KeyError,json.JSONDecodeError):return self.json(400,{'error':'Invalid event'})
            except v17.v16.base.Error as e:return self.err(e)
        return super().do_POST()

class Server(v17.Server):
    def __init__(self,bind,root,state,fetcher):
        super().__init__(bind,root,state,fetcher)
        self.class_status=collections.Counter()
        self.launcher_events=collections.Counter()
        self.RequestHandlerClass=Handler

def fetch(port=PORT):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/__local__/v18',timeout=3) as r:return json.load(r)
    except (OSError,ValueError):return None

def report(port=PORT):
    d=fetch(port)
    if not d:raise SystemExit(f'[HATA] V18 yerel sunucuya ulasilamadi: {port}')
    REPORTS.mkdir(parents=True,exist_ok=True)
    path=REPORTS/'browser2_v18_baglanti_raporu.json'
    path.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
    print('[RAPOR]',path)
    print('[DURUM]',d['status_by_route'])
    print('[OYUN]',{k:v for k,v in d['backend_metrics'].items() if k.startswith('game_join')})
    print('[BASLATICI]',d['launcher_events'])

def selftest():
    import tempfile
    assert 'worldServerFor' in CLIENT_HTML and 'ymir.session.v1' in CLIENT_HTML
    assert '__ORIGINAL_AUTH_MODULE__' in CLIENT_HTML and 'auth-C9as2-Nt.js' not in CLIENT_HTML
    assert 'launch_using_original_auth' in EVENTS
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)/'public';(root/'assets').mkdir(parents=True)
        (root/'index.html').write_text(
            '<script type="module" src="/assets/game-JWXJHqds.js"></script>'
            '<link rel="modulepreload" href="/assets/auth-JZfCWxzf.js">',
            encoding='utf-8')
        for name in ('game-JWXJHqds.js','world-bridge-DdvsLS6v.js'):
            (root/'assets'/name).write_text('// fixture',encoding='utf-8')
        (root/'assets/auth-JZfCWxzf.js').write_text('export const a7={};',encoding='utf-8')
        assert all(v17.v16.base.check_sources(root).values())
        envdb=Path(td)/'private/local.sqlite3';v17.os.environ['BROWSER2_PRIVATE_DB']=str(envdb)
        f=v17.v16.Fetcher(root,Path(td)/'overlay')
        s=Server(('127.0.0.1',0),root,Path(td)/'state',f)
        th=threading.Thread(target=s.serve_forever,daemon=True);th.start()
        try:
            host=f'http://127.0.0.1:{s.server_port}'
            with urllib.request.urlopen(host+'/__local__/') as r:
                page=r.read()
                assert r.status==200 and b'worldServerFor' in page
                assert b'/assets/auth-JZfCWxzf.js' in page
                assert b'__ORIGINAL_AUTH_MODULE__' not in page
            # A missing active module fails clearly and does not fall back to an old build.
            (root/'assets/auth-JZfCWxzf.js').unlink()
            try:
                urllib.request.urlopen(host+'/__local__/',timeout=3)
                raise AssertionError('missing original AUTH should not launch')
            except urllib.error.HTTPError as exc:
                assert exc.code==503
            (root/'assets/auth-JZfCWxzf.js').write_text('export const a7={};')
            with urllib.request.urlopen(host+'/__local__/v18') as r:
                d=json.load(r);assert d['version']=='18.0'
            with urllib.request.urlopen(host+'/') as r:assert r.status==200
            ev=urllib.request.Request(host+'/__local__/v18/event',method='POST',data=b'{"event":"launch_using_original_auth"}',headers={'Origin':host,'Content-Type':'application/json'})
            with urllib.request.urlopen(ev) as r:assert json.load(r)['ok'] is True
            assert s.launcher_events['launch_using_original_auth']==1
            assert s.class_status.get(('original_page','200'))==1
        finally:s.shutdown();s.server_close()
    print('[SELFTEST OK] Readonly original files, new auth-aligned launcher, per-route status counters, HTTP')

def serve(port):
    v17.prepare_env()
    for path in (REPORTS,LOGS,BASE/'YEREL_SUNUCU',v17.PRIVATE):path.mkdir(parents=True,exist_ok=True)
    if not v17.v16.prev.audit(ORIGINAL):raise SystemExit('Missing original Browser2 files')
    f=v17.v16.Fetcher(ORIGINAL,BASE/'YEREL_SUNUCU/browser2_v16_map_overlay')
    srv=Server(('127.0.0.1',port),ORIGINAL,BASE/'YEREL_SUNUCU',f)
    print('[V18] http://127.0.0.1:'+str(port)+'/__local__/',flush=True)
    try:srv.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:pass
    finally:srv.server_close()

def start(port):
    if fetch(port):return print('[V18] Zaten acik: http://127.0.0.1:'+str(port)+'/__local__/')
    with socket.socket() as sk:
        if sk.connect_ex(('127.0.0.1',port))==0:raise SystemExit('Port occupied by another program')
    LOGS.mkdir(parents=True,exist_ok=True);v17.prepare_env()
    with (LOGS/'browser2_v18_server.log').open('ab') as fp:
        subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'serve','--port',str(port)],
            stdin=subprocess.DEVNULL,stdout=fp,stderr=subprocess.STDOUT,
            env=os.environ.copy(),start_new_session=True,close_fds=True)
    for i in range(40):
        if fetch(port):return print('[V18] Acildi: http://127.0.0.1:'+str(port)+'/__local__/')
        time.sleep(.2)
    raise SystemExit('Server failed, see LOGS/browser2_v18_server.log')

def main():
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('action',nargs='?',default='start',choices=['selftest','start','serve','rapor'])
    ap.add_argument('--port',type=int,default=PORT)
    a=ap.parse_args()
    if a.action=='selftest':selftest()
    elif a.action=='start':start(a.port)
    elif a.action=='serve':serve(a.port)
    else:report(a.port)
if __name__=='__main__':main()
