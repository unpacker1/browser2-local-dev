#!/usr/bin/env python3
# Browser2 V26: read-only V28 archive discovery + local website companion routes.
# Original JS/WASM/GLB/KTX2/maps are never changed. No remote AUTH/GAME calls.
from __future__ import annotations
import argparse
import base64
import html
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
import browser2_baglanti_duzeltme_v18 as v18
import browser2_gercek_oyun_tani_v17 as v17
import browser2_http_route_audit_v19 as v19

PORT=8899
SNAP='_BROWSER2_PUBLIC_API_V28'
MAX_SNAPSHOT=20*1024*1024
PORTAL=r'''<!doctype html><html lang="tr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Browser2 Yerel Portal</title>
<style>body{font:16px system-ui;background:#09101b;color:#e5edf5;margin:0;padding:18px;max-width:850px}a{color:#8ddbeb}nav{display:flex;gap:14px;flex-wrap:wrap}header{padding:16px 0;border-bottom:1px solid #41516a}section{margin:18px 0;padding:16px;background:#152033;border-radius:12px}li{padding:8px 0;border-bottom:1px solid #30405c}small{color:#becce1}strong{color:#fff}ul{padding-left:20px}button{font:inherit}h2{font-size:20px}</style>
<header><h1>Browser2 — Yerel Portal</h1><nav><a href="/__local__/">Oyuna giriş</a><a href="/wiki/">Wiki</a><a href="/forum/">Forum</a><a href="/leaderboard/">Lider tablosu</a><a href="/__local__/v26">Servis raporu</a></nav></header>
<section><small>Bu portal yalnızca telefondaki dosyaları ve yerel karakter verisini gösterir. Forum ve wiki kayıtları tarihli, salt okunur arşiv görüntüleridir; canlı Browser2 sunucusu değildir.</small></section>
<section><h2 id="title">Yükleniyor…</h2><div id="result"></div></section>
<script>
const area=document.getElementById('result'),title=document.getElementById('title');
const route=location.pathname, kind=route.startsWith('/wiki')?'wiki':route.startsWith('/forum')?'forum':'leaderboard';
title.textContent=kind==='wiki'?'Wiki (arşiv)':kind==='forum'?'Forum (arşiv)':'Yerel lider tablosu';
const el=(tag,txt,parent)=>{const n=document.createElement(tag);n.textContent=String(txt??'');parent.appendChild(n);return n};
async function read(url){const r=await fetch(url,{cache:'no-store'});if(!r.ok)throw new Error(url+' HTTP '+r.status);return r.json()}
(async()=>{
try{
if(kind==='leaderboard'){const x=await read('/__local__/leaderboard');el('p',x.note,area);const list=el('ul','',area);for(const c of x.items)el('li',c.name+' — Lv '+c.level+' — '+c.classId+' — krallık '+c.empire,list);if(!x.items.length)el('p','Henüz yerel karakter yok.',area);return;}
if(kind==='forum'){const ix=await read('/forum/v1/index');el('p','Arşiv revizyonu: '+(ix.contentRevision||'?'),area);const x=await read('/forum/v1/posts?limit=30');const list=el('ul','',area);for(const p of x.items||[])el('li',(p.title?.text||p.title||'(başlıksız)')+' — '+(p.status||'')+' — '+(p.authorCharacter||''),list);if(!x.items?.length)el('p','Arşivde gösterilebilir ileti bulunamadı.',area);return;}
const ix=await read('/wiki/v1/index');el('p','Arşiv revizyonu: '+(ix.contentRevision||'?'),area);
const x=await read('/wiki/v1/items?limit=30');const list=el('ul','',area);
for(const p of x.items||[])el('li',(p.name||'item')+' — '+(p.category||'')+' — '+(p.rootVnum??''),list);
if(!x.items?.length)el('p','Arşivde gösterilebilir eşya bulunamadı.',area);
}catch(e){el('p','Veri hazır değil: '+e.message,area);}
})();
</script></html>'''

def archive_candidates(requested=None):
    """Bounded directory-only discovery around known Browser2/Download locations.

    This does NOT scan device storage recursively and never reads proprietary
    asset bytes. It accepts the game root itself or a parent archive folder.
    """
    home=Path.home()
    downloads=home/'storage/downloads'
    anchors=([Path(requested).expanduser()] if requested is not None else [
        downloads/'BROWSER2_SIFIRDAN_TAM_SITE',
        home/'BROWSER2_SIFIRDAN_TAM_SITE',
        downloads/'BROWSER2_BAGIMSIZ/public_assets',
        downloads/'BROWSER2_BAGIMSIZ',
        home/'BROWSER2_BAGIMSIZ/public_assets',
    ])
    # Additional Browser2-named directories one level below Downloads only.
    if requested is None and downloads.is_dir():
        try:
            anchors.extend(sorted(p for p in downloads.iterdir()
                                  if p.is_dir() and 'browser2' in p.name.casefold())[:20])
        except OSError:
            pass
    seen=set()
    candidates=[]
    for anchor in anchors:
        queue=[(anchor,0)]
        visited=0
        while queue and visited<80:
            item,depth=queue.pop(0)
            try:real=item.resolve()
            except (OSError,RuntimeError):
                continue
            if real in seen or not real.is_dir():
                continue
            seen.add(real);visited+=1
            # Inspect directory entries (names only); never walk assets/trees.
            if (real/'index.html').is_file() or depth<=1:
                candidates.append(real)
            if depth>=4:continue
            try:
                children=sorted(p for p in real.iterdir()
                      if p.is_dir() and (
                        p.name.casefold() in ('site','browser2.to','public_assets',
                            'original','client','www','dist','build') or
                        'browser2' in p.name.casefold()))
            except (OSError,PermissionError):
                continue
            for child in children[:40]:
                queue.append((child,depth+1))
    return candidates

def archive_diagnostics(requested=None):
    reports=[]
    for path in archive_candidates(requested):
        assets=path/'assets'
        try:
            actual={kind:sorted(x.name for x in assets.glob(kind+'-*.js'))[:6]
                    for kind in ('auth','game','world-bridge')}
        except OSError:
            actual={}
        checks=base.check_sources(path)
        if (path/'index.html').is_file() or assets.is_dir():
            reports.append({'root':str(path),'checks':checks,
               'assetFiles':actual,
               'manifest':(assets/'packs/boot-manifest.json').is_file(),
               'mapRegistry':(assets/'maps/_registry.json').is_file(),
               'snapshot':(path/SNAP/'wiki/v1/index.json').is_file()})
    return reports

def resolve_original(requested=None):
    raw=requested or os.environ.get('BROWSER2_ORIGINAL_ROOT')
    candidates=archive_candidates(raw)
    valid=[]
    for path in candidates:
        checks=base.check_sources(path)
        if all(checks.values()):
            completeness=int((path/'assets/packs/boot-manifest.json').is_file())+int((path/'assets/maps/_registry.json').is_file())
            valid.append((completeness,path))
    if not valid:
        reports=archive_diagnostics(raw)
        if reports:
            problems=[(x['root'],[key for key,ok in x['checks'].items() if not ok])
                       for x in reports[:8]]
            raise ValueError('Client roots exist but required files are missing or build references mismatch: '+str(problems))
        raise ValueError('No extracted V28 index.html + assets/ root found under the known Browser2 folders. '
                         'Run: python server/browser2_v28_local_site_v26.py diagnose')
    valid.sort(key=lambda v:-v[0])
    return valid[0][1]

def snapshot_root(root):
    return root/SNAP

def read_json(path):
    if not path.is_file() or path.stat().st_size>MAX_SNAPSHOT:
        return None
    try:
        with path.open(encoding='utf-8') as stream:
            return json.load(stream)
    except (OSError, UnicodeError, ValueError):
        return None

def snapshot_data(root, service, section, params):
    if service not in ('wiki','forum') or not re.fullmatch(r'[a-z][a-z0-9-]{0,55}',section):
        return None
    folder=snapshot_root(root)/service/'v1'
    if section=='index':
        return read_json(folder/'index.json')
    resource=folder/section
    if not resource.is_dir():
        return None
    if section in ('guide-shops','guide-systems','shops') and (resource/'index.json').is_file():
        return read_json(resource/'index.json')
    data=read_json(resource/'tum_kayitlar.json')
    if isinstance(data,list):
        items=data;meta={}
    elif isinstance(data,dict) and isinstance(data.get('items'),list):
        items=data['items'];meta=data
    else:
        first=read_json(resource/'sayfalar/page_001.json') or read_json(resource/'ornek_limit1.json')
        if not isinstance(first,dict) or not isinstance(first.get('items'),list):
            return None
        items=first['items'];meta=first
        # Do not claim that a single archived page is a complete collection.
        incomplete=True
    if 'incomplete' not in locals():
        incomplete=False
    q=str(params.get('q',[''])[0]).strip().casefold()[:80]
    filtered=items
    if q:
        filtered=[x for x in filtered if q in str(x.get('name','') or x.get('title',{})).casefold()]
    for key in ('category','kind','status','area','slot','subtype'):
        value=str(params.get(key,[''])[0]).strip()
        if not value:
            continue
        field={'slot':'equipSlot','subtype':'protoSubType'}.get(key,key)
        filtered=[x for x in filtered if str(x.get(field,''))==value]
    try:
        limit=max(1,min(int(params.get('limit',['25'])[0]),100))
        cursor=str(params.get('cursor',[''])[0])
        pos=0
        if cursor:
            token=json.loads(base64.urlsafe_b64decode(cursor+'='*(-len(cursor)%4)).decode())
            if not isinstance(token,dict) or not isinstance(token.get('o'),int):
                raise ValueError('not a local pagination cursor')
            pos=token['o']
        if pos<0 or pos>len(filtered):
            raise ValueError('cursor out of bounds')
    except (TypeError,ValueError,UnicodeError,OverflowError,base64.binascii.Error):
        return {'error':'Invalid local snapshot cursor','status':400}
    chunk=filtered[pos:pos+limit]
    nextpos=pos+len(chunk)
    next_cursor=None if incomplete or nextpos>=len(filtered) else base64.urlsafe_b64encode(
        json.dumps({'o':nextpos}).encode()).decode().rstrip('=')
    return {'items':chunk,'total':len(filtered) if not incomplete else meta.get('total',len(chunk)),
            'nextCursor':next_cursor,'snapshotOnly':True,'partialArchive':incomplete,
            **({'totalCapped':False} if service=='forum' else {})}

def original_manifest_pack_paths(root):
    """Only paths present in original manifest are eligible for .pack.bin aliasing.

    Previous Chrome request audit observed logical .pack URLs while the user's
    downloaded original archive stores these same files as .pack.bin.
    Serving the original bytes at the logical URL is a transport compatibility
    layer, not a modification to the original game files or protocol.
    """
    manifest=read_json(Path(root)/'assets/packs/boot-manifest.json')
    result=set()
    def visit(node):
        if isinstance(node,dict):
            for val in node.values():visit(val)
        elif isinstance(node,list):
            for val in node:visit(val)
        elif isinstance(node,str) and re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.pack',node):
            if all(segment not in ('.','..') for segment in node.split('/')):
                result.add('/assets/packs/'+node)
    if isinstance(manifest,(dict,list)):visit(manifest)
    return frozenset(result)

class Handler(v19.Handler):
    server_version='Browser2Local/26'
    def do_GET(self):
        url=urllib.parse.urlsplit(self.path)
        p=urllib.parse.unquote(url.path)
        if p in ('/wiki/','/wiki','/forum/','/forum','/leaderboard/','/leaderboard','/__local__/portal/'):
            return self.sendbody(200,PORTAL.encode('utf-8'),'text/html; charset=utf-8',
                                 {'Cache-Control':'no-store'})
        if p=='/__local__/v26':
            root=self.server.root
            return self.json(200,{'version':'26.0','archive':'local_read_only',
                 'originalClient':base.check_sources(root),
                 'bootManifest':(root/'assets/packs/boot-manifest.json').is_file(),
                 'mapRegistry':(root/'assets/maps/_registry.json').is_file(),
                 'wikiSnapshot':(snapshot_root(root)/'wiki/v1/index.json').is_file(),
                 'forumSnapshot':(snapshot_root(root)/'forum/v1/index.json').is_file(),
                 'leaderboard':'local_sqlite_only','game':'partial_independent',
                 'originalAssetsModified':False,
                 'manifestPackPaths':len(self.server.manifest_pack_paths),
                 'manifestPackAliasesPresent':sum(
                    (root/(p.lstrip('/')+'.bin')).is_file()
                    for p in self.server.manifest_pack_paths),
                 'packAliasHits':self.server.metrics['manifest_pack_alias_served'],
                 'packAliasMissing':self.server.metrics['manifest_pack_alias_missing']})
        if p=='/__local__/leaderboard':
            with self.server.store.lock,self.server.store._db() as db:
                rows=db.execute('SELECT name,class_id,empire,level FROM characters ORDER BY level DESC,name ASC LIMIT 100').fetchall()
            return self.json(200,{'scope':'local_only','note':'These are LOCAL SQLite characters; not the official Browser2 rankings.',
                 'items':[{'name':r['name'],'classId':r['class_id'],'empire':r['empire'],'level':r['level']} for r in rows]})
        m=re.fullmatch(r'/(wiki|forum)/v1/([a-z][a-z0-9-]{0,55})/?',p)
        if m:
            obj=snapshot_data(self.server.root,m.group(1),m.group(2),
                              urllib.parse.parse_qs(url.query,keep_blank_values=True))
            if obj is None:
                return self.json(404,{'error':'No authorized offline archive snapshot for this endpoint'})
            if isinstance(obj,dict) and obj.get('status')==400:
                return self.json(400,{'error':obj['error']})
            data=json.dumps(obj,ensure_ascii=False,separators=(',',':')).encode('utf-8')
            return self.sendbody(200,data,'application/json; charset=utf-8',
                                 {'Cache-Control':'no-store','X-Local-Archive':'read-only-snapshot'})
        return super().do_GET()

    def static(self,p):
        # The manifest is the allowlist: no arbitrary disk paths, no guessed
        # pack names and no credential/session traffic is touched.
        if p in self.server.manifest_pack_paths:
            root=(self.server.root/'assets/packs').resolve()
            candidate=(root/(p[len('/assets/packs/'):] + '.bin')).resolve()
            if candidate.is_relative_to(root) and candidate.is_file():
                self.server.metrics['manifest_pack_alias_served']+=1
                return v17.v16.serve_file(self,candidate)
            self.server.metrics['manifest_pack_alias_missing']+=1
        return super().static(p)

class Server(v19.Server):
    def __init__(self,bind,root,state,fetcher):
        super().__init__(bind,root,state,fetcher)
        self.manifest_pack_paths=original_manifest_pack_paths(root)
        self.RequestHandlerClass=Handler

def make_server(root,port=PORT,state=None):
    state=state or v18.BASE/'YEREL_SUNUCU'
    fetcher=v17.v16.Fetcher(root,state/'browser2_v16_map_overlay')
    return Server(('127.0.0.1',port),root,state,fetcher)

def audit(root):
    return {'root':str(root),'client':base.check_sources(root),
            'packs':(root/'assets/packs/boot-manifest.json').is_file(),
            'maps':(root/'assets/maps/_registry.json').is_file(),
            'wiki':(snapshot_root(root)/'wiki/v1/index.json').is_file(),
            'forum':(snapshot_root(root)/'forum/v1/index.json').is_file()}

def selftest():
    with tempfile.TemporaryDirectory() as td:
        root=Path(td)/'site'; assets=root/'assets';assets.mkdir(parents=True)
        (root/'index.html').write_text('<script src="/assets/game-TEST.js"></script>'
          '<link href="/assets/auth-TEST.js">')
        for name in ('game-TEST.js','auth-TEST.js','world-bridge-TEST.js'):
            (assets/name).write_text('/* test */')
        for sub,data in [
            ('wiki/v1/index.json',{'schemaVersion':1,'contentRevision':'offline'}),
            ('forum/v1/index.json',{'schemaVersion':1,'contentRevision':'offline'}),
            ('wiki/v1/items/tum_kayitlar.json',{'items':[{'name':'Sword','category':'weapon'},{'name':'Shield','category':'armor'}],'total':2}),
            ('forum/v1/posts/sayfalar/page_001.json',{'items':[{'title':{'text':'Test'}}],'total':1,'nextCursor':'opaque'}),
        ]:
            f=root/SNAP/sub;f.parent.mkdir(parents=True,exist_ok=True)
            f.write_text(json.dumps(data),encoding='utf-8')
        assert all(base.check_sources(root).values())
        # Exact Chrome-observed logical pack URL versus the archive's .pack.bin:
        # the original file bytes must pass through untouched, with Range/HEAD.
        pack_payload=b'PACK'+bytes(range(100))
        pack_root=root/'assets/packs'
        pack_root.mkdir()
        pack_name='core-08d8acfd75.pack'
        (pack_root/(pack_name+'.bin')).write_bytes(pack_payload)
        (pack_root/'boot-manifest.json').write_text(
            json.dumps({'version':2,'packs':{'core':pack_name}}))
        assert original_manifest_pack_paths(root)==frozenset({
            '/assets/packs/'+pack_name})

        assert resolve_original(root)==root.resolve()
        # Parent archive paths must resolve nested original site/browser2.to.
        nested=Path(td)/'BROWSER2_SIFIRDAN_TAM_SITE/site/browser2.to'
        nested.parent.mkdir(parents=True)
        nested.symlink_to(root,target_is_directory=True)
        assert resolve_original(Path(td)/'BROWSER2_SIFIRDAN_TAM_SITE')==root.resolve()
        checks=archive_diagnostics(root)
        assert checks and all(checks[0]['checks'].values())
        # A missing active AUTH is described, not misreported as a missing directory.
        (assets/'auth-TEST.js').unlink()
        broken=archive_diagnostics(root)
        assert not broken[0]['checks']['auth_module']
        try:resolve_original(root);raise AssertionError('missing auth must reject')
        except ValueError as exc:assert 'auth_module' in str(exc)
        (assets/'auth-TEST.js').write_text('/* test */')

        assert snapshot_data(root,'wiki','items',{'limit':['1']})['nextCursor']
        assert len(snapshot_data(root,'wiki','items',{'category':['weapon']})['items'])==1
        assert snapshot_data(root,'forum','posts',{})['partialArchive']
        assert snapshot_data(root,'forum','unknown',{}) is None
        state=Path(td)/'private'
        srv=make_server(root,0,state)
        th=threading.Thread(target=srv.serve_forever,daemon=True);th.start()
        host='http://127.0.0.1:'+str(srv.server_port)
        try:
            for p in ('/__local__/','/__local__/v26','/wiki/','/forum/','/leaderboard/',
                      '/wiki/v1/index','/forum/v1/index','/wiki/v1/items?limit=1',
                      '/forum/v1/posts?limit=1','/__local__/leaderboard'):
                with urllib.request.urlopen(host+p,timeout=3) as r:
                    assert r.status==200,(p,r.status)

            pack_url='/assets/packs/'+pack_name
            with urllib.request.urlopen(host+pack_url,timeout=3) as resp:
                assert resp.status==200 and resp.read()==pack_payload
            with urllib.request.urlopen(
                urllib.request.Request(host+pack_url,method='HEAD'),timeout=3) as resp:
                assert resp.status==200 and int(resp.headers['Content-Length'])==len(pack_payload)
            with urllib.request.urlopen(
                urllib.request.Request(host+pack_url,headers={'Range':'bytes=4-13'}),timeout=3) as resp:
                assert resp.status==206 and resp.read()==pack_payload[4:14]
            # The original archive is unmodified; direct storage URL also works.
            with urllib.request.urlopen(host+pack_url+'.bin',timeout=3) as resp:
                assert resp.read()==pack_payload
            assert (pack_root/(pack_name+'.bin')).read_bytes()==pack_payload
            # A plausible but non-manifest pack name must not be exposed.
            try:
                urllib.request.urlopen(host+'/assets/packs/other-0000000000.pack',timeout=3)
            except urllib.error.HTTPError as ex:
                assert ex.code==404
            else:raise AssertionError('unlisted pack unexpectedly served')
            with urllib.request.urlopen(host+'/__local__/v19',timeout=3) as resp:
                status=json.load(resp)
                assert status['version']=='19.0'
                assert status['error_routes']
            with urllib.request.urlopen(host+'/__local__/v26',timeout=3) as resp:
                status=json.load(resp)
                assert status['manifestPackAliasesPresent']==1
                assert status['packAliasHits']>=3
            with urllib.request.urlopen(host+'/wiki/v1/items?limit=1') as r:
                obj=json.load(r);assert obj['nextCursor'] and obj['items'][0]['name']=='Sword'
            with urllib.request.urlopen(host+'/wiki/v1/items?limit=1&cursor='+obj['nextCursor']) as r:
                assert json.load(r)['items'][0]['name']=='Shield'
            try:
                urllib.request.urlopen(host+'/wiki/v1/items?cursor=invalid',timeout=3)
            except urllib.error.HTTPError as ex:assert ex.code==400
            else:raise AssertionError('invalid cursor should fail')
            try:
                urllib.request.urlopen(host+'/wiki/v1/unknown',timeout=3)
            except urllib.error.HTTPError as ex:assert ex.code==404
            else:raise AssertionError('unknown snapshot should fail')
            assert srv.store.list_char is not None
        finally:
            srv.shutdown();srv.server_close()
    print('[SELFTEST OK] V28 root validation, offline wiki/forum, local leaderboard, original launcher')

def main():
    ap=argparse.ArgumentParser(description='Browser2 V26 offline V28 launcher and local website')
    ap.add_argument('action',nargs='?',default='audit',choices=('selftest','diagnose','audit','serve'))
    ap.add_argument('--root',type=Path)
    ap.add_argument('--port',type=int,default=PORT)
    args=ap.parse_args()
    if args.action=='selftest':
        selftest();return
    if args.action=='diagnose':
        data=archive_diagnostics(args.root or os.environ.get('BROWSER2_ORIGINAL_ROOT'))
        print('[V28 ROOT DIAGNOSIS]',json.dumps(data,ensure_ascii=False,indent=2))
        if not data:
            print('[HINT] Extracted client folder (index.html and assets/) not found. Original archive is NOT downloaded by this script.')
        return
    if not 1024<=args.port<=65535:raise SystemExit('Invalid port')
    try:root=resolve_original(args.root)
    except ValueError as exc:
        print('[V28 ROOT DIAGNOSIS]',json.dumps(archive_diagnostics(args.root or os.environ.get('BROWSER2_ORIGINAL_ROOT')),
                     ensure_ascii=False,indent=2))
        raise SystemExit('[ARCHIVE NOT READY] '+str(exc))
    print('[V26 ARCHIVE AUDIT]',json.dumps(audit(root),ensure_ascii=False),flush=True)
    if args.action!='serve':return
    v17.prepare_env()
    (v18.BASE/'YEREL_SUNUCU').mkdir(parents=True,exist_ok=True)
    server=make_server(root,args.port)
    print('[LOCAL V28 SITE] http://127.0.0.1:'+str(args.port)+'/__local__/',flush=True)
    print('[WIKI / FORUM / LEADER] /wiki/ /forum/ /leaderboard/',flush=True)
    print('[NOTICE] Original public archive is read-only; game backend is partial.',flush=True)
    try:server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
