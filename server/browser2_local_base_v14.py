#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Browser2 V14: independent local AUTH/character/World prototype over ORIGINAL static archive.
Based on observed public client build endpoints / protocol. Does not reproduce private server logic.
Listens only on 127.0.0.1; all original assets read-only.
"""
from __future__ import annotations
import argparse, base64, hashlib, hmac, http.cookies, json, logging, math, mimetypes, os
import re, secrets, socket, sqlite3, struct, threading, time, urllib.parse, uuid, collections
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION="14.0"
PROTO=28
ROOT=Path.home()/"storage/downloads/BROWSER2_BAGIMSIZ/public_assets/browser2.to"
STATE=Path.home()/"BROWSER2_LOCAL_SERVER_DATA"
MAX_REQUEST=65536
MAX_FRAME=1048576
CLASS_ORDER={'warrior':0, 'ninja':1, 'sura':2, 'shaman':3, 'wolfman':0}
VALID_CLASS={'warrior','ninja','sura','shaman'}

class Error(Exception):
    def __init__(self,code,message): super().__init__(message); self.code=code

def jbytes(obj,tag=None):
    b=json.dumps(obj,ensure_ascii=False,separators=(',',':')).encode('utf8')
    return bytes([tag])+b if tag is not None else b

def encstr(v):
    b=str(v).encode('utf8');
    if len(b)>65535: raise ValueError('text too long')
    return struct.pack('<H',len(b))+b

def readstr(b,pos):
    if pos+2>len(b): raise ValueError('short string header')
    n=struct.unpack_from('<H',b,pos)[0]; pos+=2
    if pos+n>len(b): raise ValueError('short string')
    return b[pos:pos+n].decode('utf8'),pos+n

def decode_join(payload):
    if len(payload)<6 or payload[:2]!=b'\x0a\x01': raise ValueError('not intent join')
    char,p=readstr(payload,2)
    if len(payload)<p+2: raise ValueError('short class/empire')
    cls,empire=payload[p],payload[p+1]; p+=2
    token,p=readstr(payload,p) if p<len(payload) else ('',p)
    if p!=len(payload): raise ValueError('extra join bytes')
    return {'characterId':char,'classNum':cls,'empire':empire,'joinToken':token}

def make_self(x,z,hp,maxhp,handle):
    return struct.pack('<BiiBIIHIII',5,round(x*100),round(z*100),0,hp,maxhp,1,handle,0,0)

def encode_spawn(ch,handle):
    name=ch['name']; cls=CLASS_ORDER.get(ch['classId'],0)
    gender=1 if ch['gender']=='w' else 0
    # Exact little-endian field layout from client zb() / $b(): no changed client code.
    res=struct.pack('<IBIiihBIIHHHBBBB',handle,1,0,round(ch['x']*100),round(ch['z']*100),0,0,100,100,1,400,1,8,cls,gender,ch['empire'])
    # appearance: ten u32 plus refine/weapon sub type/specluar/horse flags/corruptions
    res+=struct.pack('<10I',0,0,0,0,0,0,0,0,0,0)
    res+=bytes([0,255,0,0,0,0,0,0,0])
    res+=encstr(name)+encstr('')+encstr('')
    res+=struct.pack('<hBIB',0,0,0,0)
    return res

def snapshot(tick, ch, handle, first, previous):
    buf=bytearray(struct.pack('<BIH',1,tick,1 if first else 0))
    if first:buf.extend(encode_spawn(ch,handle))
    dx=round((ch['x']-previous[0])*100); dz=round((ch['z']-previous[1])*100)
    changed=not first and (dx!=0 or dz!=0)
    buf.extend(struct.pack('<H',1 if changed else 0))
    if changed:
        if -32768 <= dx<=32767 and -32768<=dz<=32767:
            buf.extend(struct.pack('<IBhh',handle,1,dx,dz))
        else:
            buf.extend(struct.pack('<IBii',handle,17,round(ch['x']*100),round(ch['z']*100)))
    buf.extend(struct.pack('<H',0))
    return bytes(buf)

def password_hash(password,salt=None):
    salt=salt or secrets.token_bytes(16)
    return salt.hex()+':'+hashlib.pbkdf2_hmac('sha256',password.encode(),salt,210000).hex()

def password_verify(password,stored):
    try:
        salt,expected=stored.split(':',1)
        derived=password_hash(password,bytes.fromhex(salt)).split(':')[1]
        return hmac.compare_digest(derived,expected)
    except (ValueError,TypeError):return False

class Store:
    def __init__(self,path):
        self.path=path;path.parent.mkdir(parents=True,exist_ok=True)
        try:path.parent.chmod(0o700)
        except OSError:pass
        self.lock=threading.RLock()
        with self._db() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE,password_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS characters(id TEXT PRIMARY KEY,user_id TEXT NOT NULL,name TEXT UNIQUE,class_id TEXT NOT NULL,gender TEXT NOT NULL,empire INTEGER NOT NULL,map_id TEXT NOT NULL,x REAL NOT NULL,z REAL NOT NULL,level INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS joins(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL,character_id TEXT NOT NULL,expires REAL NOT NULL);
            ''')
        if path.exists():
            try:path.chmod(0o600)
            except OSError:pass
    def _db(self):
        c=sqlite3.connect(self.path,timeout=10)
        c.row_factory=sqlite3.Row
        return c
    @staticmethod
    def hash(t):return hashlib.sha256(t.encode()).hexdigest()
    def create_user(self,email,password):
        email=email.strip().lower()
        if not (3<=len(email)<=180 and '@' in email and 8<=len(password)<=256):raise Error(400,'Invalid email or password (minimum 8 characters)')
        with self.lock,self._db() as d:
            uid=str(uuid.uuid4())
            try:d.execute('INSERT INTO users VALUES (?,?,?)',(uid,email,password_hash(password)))
            except sqlite3.IntegrityError:raise Error(409,'Account already exists')
        return self.login(email,password)
    def login(self,email,password):
        with self.lock,self._db() as d:
            u=d.execute('SELECT * FROM users WHERE email=?',(email.strip().lower(),)).fetchone()
            if not u or not password_verify(password,u['password_hash']):raise Error(401,'Invalid local credentials')
            token=secrets.token_urlsafe(32)
            d.execute('INSERT INTO sessions VALUES (?,?,?)',(self.hash(token),u['id'],time.time()+86400*30))
        return {'token':token,'email':u['email'],'username':u['email'],'id':u['id'],'isGM':False}
    def change_password(self,email,old_password,new_password):
        if not (8<=len(new_password)<=256):raise Error(400,'New password must be at least 8 characters')
        with self.lock,self._db() as d:
            u=d.execute('SELECT * FROM users WHERE email=?',(email.strip().lower(),)).fetchone()
            if not u or not password_verify(old_password,u['password_hash']):raise Error(401,'Invalid local credentials')
            d.execute('UPDATE users SET password_hash=? WHERE id=?',(password_hash(new_password),u['id']))
            d.execute('DELETE FROM sessions WHERE user_id=?',(u['id'],))
        return self.login(email,new_password)
    def ensure_bootstrap(self):
        email='localplayer@browser2.invalid'
        with self.lock,self._db() as d:
            u=d.execute('SELECT id FROM users WHERE email=?',(email,)).fetchone()
            if not u:
                pwd=secrets.token_urlsafe(24)
                d.execute('INSERT INTO users VALUES (?,?,?)',(str(uuid.uuid4()),email,password_hash(pwd)))
            # This helper creates a real LOCAL session, never an original remote session.
            u=d.execute('SELECT id FROM users WHERE email=?',(email,)).fetchone()
            ch=d.execute('SELECT * FROM characters WHERE user_id=? ORDER BY rowid LIMIT 1',(u['id'],)).fetchone()
            if not ch:
                cid=str(uuid.uuid4())
                d.execute('INSERT INTO characters(id,user_id,name,class_id,gender,empire,map_id,x,z,level) VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (cid,u['id'],'LocalWarrior','warrior','m',1,'map_a2',0.0,0.0,1))
            token=secrets.token_urlsafe(32)
            d.execute('INSERT INTO sessions VALUES (?,?,?)',(self.hash(token),u['id'],time.time()+86400*30))
            ch=d.execute('SELECT * FROM characters WHERE user_id=? ORDER BY rowid LIMIT 1',(u['id'],)).fetchone()
        return {'session':{'token':token,'email':email,'username':email,'id':u['id'],'isGM':False}, 'character':self.char_public(ch)}
    def require(self,token):
        if not token:raise Error(401,'Local login required')
        with self.lock,self._db() as d:
            u=d.execute('''SELECT users.* FROM sessions JOIN users ON users.id=sessions.user_id WHERE token_hash=? AND expires>?''',(self.hash(token),time.time())).fetchone()
            if not u:raise Error(401,'Local session expired')
            return dict(u)
    def logout(self,token):
        with self.lock,self._db() as d:d.execute('DELETE FROM sessions WHERE token_hash=?',(self.hash(token),))
    @staticmethod
    def char_public(c):
        return {'id':c['id'],'name':c['name'],'classId':c['class_id'],'gender':c['gender'],'empire':c['empire'],'mapId':c['map_id'],'level':c['level'],'x':c['x'],'z':c['z']}
    def list_char(self,user):
        with self.lock,self._db() as d:
            return [self.char_public(r) for r in d.execute('SELECT * FROM characters WHERE user_id=? ORDER BY rowid',(user['id'],))]
    def create_char(self,user,data):
        name=str(data.get('name','')).strip()
        cls=str(data.get('classId',data.get('class','warrior'))).lower()
        gender=str(data.get('gender','m')).lower()
        empire=int(data.get('empire',1))
        if not re.fullmatch('[a-zA-Z0-9_]{3,20}',name) or cls not in VALID_CLASS or gender not in ('m','w') or empire not in (1,2,3):raise Error(400,'Invalid character fields')
        cid=str(uuid.uuid4())
        with self.lock,self._db() as d:
            count=d.execute('SELECT COUNT(*) FROM characters WHERE user_id=?',(user['id'],)).fetchone()[0]
            if count>=5:raise Error(409,'Character limit reached')
            try:
                d.execute('INSERT INTO characters(id,user_id,name,class_id,gender,empire,map_id,x,z,level) VALUES (?,?,?,?,?,?,?,?,?,?)',
                          (cid,user['id'],name,cls,gender,empire,'map_a2',0.,0.,1))
            except sqlite3.IntegrityError:raise Error(409,'Character name exists')
            c=d.execute('SELECT * FROM characters WHERE id=?',(cid,)).fetchone()
            return self.char_public(c)
    def del_char(self,user,charid):
        with self.lock,self._db() as d:d.execute('DELETE FROM characters WHERE user_id=? AND id=?',(user['id'],charid))
    def join_token(self,user,charid):
        with self.lock,self._db() as d:
            c=d.execute('SELECT * FROM characters WHERE user_id=? AND id=?',(user['id'],charid)).fetchone()
            if not c:raise Error(404,'Character not found')
            t=secrets.token_urlsafe(32)
            d.execute('INSERT INTO joins VALUES (?,?,?,?)',(self.hash(t),user['id'],charid,time.time()+120))
            return {'joinToken':t}
    def take_join(self,charid,token):
        if not token:raise Error(401,'Join token required')
        with self.lock,self._db() as d:
            j=d.execute('SELECT * FROM joins WHERE token_hash=? AND character_id=? AND expires>?',(self.hash(token),charid,time.time())).fetchone()
            if not j:raise Error(401,'Invalid or expired world token')
            # One-time token consumed; replay cannot join.
            d.execute('DELETE FROM joins WHERE token_hash=?',(self.hash(token),))
            c=d.execute('SELECT * FROM characters WHERE id=? AND user_id=?',(charid,j['user_id'])).fetchone()
            if not c:raise Error(404,'Character missing')
            return self.char_public(c)
    def save_pos(self,c):
        with self.lock,self._db() as d:
            d.execute('UPDATE characters SET x=?,z=? WHERE id=?',(c['x'],c['z'],c['id']))

class WS:
    def __init__(self,sock):self.sock=sock;self.sock.settimeout(.12);self.lock=threading.Lock()
    def send(self,data,opcode=2):
        h=bytes([0x80|opcode]);n=len(data)
        h+=bytes([n]) if n<126 else (b'\x7e'+struct.pack('!H',n) if n<65536 else b'\x7f'+struct.pack('!Q',n))
        with self.lock:self.sock.sendall(h+data)
    def receive(self):
        # Return (opcode, data); None when not ready. Socket timeout applies only to first byte.
        try:first=self.sock.recv(2)
        except socket.timeout:return None
        if not first:raise EOFError()
        if len(first)<2:first+=self.readexact(2-len(first))
        a,b=first; n=b&127
        if (a&0x70) or not(a&0x80):raise ValueError('fragmented/extension frame not supported')
        if not(b&0x80):raise ValueError('unmasked browser frame')
        if n==126:n=struct.unpack('!H',self.readexact(2))[0]
        if n==127:n=struct.unpack('!Q',self.readexact(8))[0]
        if n>MAX_FRAME:raise ValueError('frame too large')
        key=self.readexact(4)
        data=self.readexact(n)
        return (a&15,bytes(x^key[i&3] for i,x in enumerate(data)))
    def readexact(self,n):
        chunks=bytearray()
        # when frame started, short timeouts must not corrupt parsing.
        self.sock.settimeout(5)
        try:
            while len(chunks)<n:
                b=self.sock.recv(n-len(chunks))
                if not b:raise EOFError()
                chunks.extend(b)
            return bytes(chunks)
        finally:self.sock.settimeout(.12)

class Server(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=True
    def __init__(self,bind,root,state):
        # Compatibility-only: never place LOCAL session/password database in public Android Downloads.
        db_target=state/'local.sqlite3'
        public_state=os.environ.get('BROWSER2_PUBLIC_STATE')
        private_db=os.environ.get('BROWSER2_PRIVATE_DB')
        if public_state and private_db and Path(state).resolve()==Path(public_state).resolve():
            db_target=Path(private_db).expanduser().resolve()
        self.root=root.resolve();self.store=Store(db_target)
        self.active=0;self.active_lock=threading.Lock();self.metrics=collections.Counter()
        super().__init__(bind,Handler)

LOCAL_HTML=r'''<!doctype html><html lang="tr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Browser2 Yerel Oyun</title><style>body{font:16px system-ui;background:#101824;color:#f2eee4;padding:24px;max-width:700px;margin:auto}h1{font-size:26px}button{background:#33bca2;color:#071918;border:0;border-radius:10px;padding:16px 24px;font-weight:700;font-size:18px}pre{white-space:pre-wrap;word-break:break-word;background:#1c2938;padding:15px;border-radius:9px}small{color:#adb8c2}</style><h1>Browser2 — Yerel Sunucu</h1><p>Bu sayfa bağımsız yerel AUTH + GAME hizmetini kullanır; orijinal Browser2 istemci dosyaları değiştirilmez.</p><p><button id="play">Yerel Oyuna Gir</button></p><pre id="info">Hazır. İlk girişte yalnızca bu telefona ait bir hesap ve karakter oluşturulur.</pre><small>Yerel ağda paylaşılmaz. Gerçek Browser2.to hesabından bağımsızdır. Dünya sunucusu kısmi uyumluluk prototipidir; tam orijinal oyun davranışları garanti edilmez.</small><script>document.getElementById('play').addEventListener('click',async()=>{const b=document.getElementById('play');b.disabled=true;const s=document.getElementById('info');s.textContent='Yerel hesap ve dünya bağlantısı hazırlanıyor...';try{const csrf=document.cookie.split('; ').find(x=>x.startsWith('b2csrf='))?.split('=')[1]??'';const r=await fetch('/__local__/bootstrap',{method:'POST',headers:{'x-b2-csrf':csrf,'content-type':'application/json'},body:'{}'});const j=await r.json();if(!r.ok)throw Error(j.error||String(r.status));localStorage.setItem('ymir.session.v1',JSON.stringify(j.session));const c=j.character;const q=new URLSearchParams({screen:'game',name:c.id,map:c.mapId,class:(c.classId==='ninja'?'assassin':c.classId)+'_'+c.gender,empire:String(c.empire),server:`ws://${location.host}/world/map1`});location.assign('/?'+q.toString())}catch(e){s.textContent='Hata: '+e.message;b.disabled=false}})</script></html>'''

class Handler(BaseHTTPRequestHandler):
    server_version='Browser2Local/14'
    protocol_version='HTTP/1.1'
    def log_message(self,fmt,*args):
        # Never log credentials, tokens or query parameters.
        pass # No request URL, query, credential or token logging
    def sendbody(self,status,data,ctype='application/json; charset=utf-8',extra=None):
        if status>=400: self.server.metrics['http_error_'+str(status)]+=1
        self.send_response(status);self.send_header('Content-Type',ctype)
        self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
        for k,v in (extra or {}).items():self.send_header(k,v)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Connection','close');self.end_headers();self.close_connection=True
        if self.command!='HEAD':self.wfile.write(data)
    def json(self,status,obj):self.sendbody(status,jbytes(obj))
    def err(self,e):self.json(e.code,{'error':str(e)})
    def require_origin(self):
        expected=f'http://{self.headers.get("Host","")}'
        if self.headers.get('Origin')!=expected:raise Error(403,'Same-origin request required')
    def do_GET(self):
        u=urllib.parse.urlsplit(self.path);p=urllib.parse.unquote(u.path)
        try:
            if p=='/__local__/':
                csrf=secrets.token_urlsafe(18)
                self.sendbody(200,LOCAL_HTML.encode(),'text/html; charset=utf-8',{
                    'Set-Cookie':f'b2csrf={csrf}; Path=/__local__/; SameSite=Strict',
                    'Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'"})
                return
            if p=='/__local__/health':
                with self.server.active_lock:n=self.server.active
                self.json(200,{'server':'Browser2 LOCAL V14','proto':PROTO,'active_world_clients':n,'original_static_root':str(self.server.root),'static_found':(self.server.root/'assets/auth-C9as2-Nt.js').is_file(),'counts':dict(self.server.metrics),'limitations':'Partial private GAME recreation; not original backend'})
                return
            if p=='/health':
                self.json(200,{'protocolVersion':PROTO,'maintenance':None});return
            if p=='/chars/list':
                me=self.server.store.require(self.headers.get('x-session-token',''))
                self.json(200,self.server.store.list_char(me));return
            if p=='/catalogs/maps' or re.fullmatch(r'/world/[A-Za-z0-9_@-]+/catalogs/maps',p):
                # map catalog structure is provisional; client version needs live testing
                self.json(200,[{'id':'map_a2','mapId':'map_a2','name':'map_a2','tileSet':'map_a2','halfX':1000,'halfZ':1000,'npcs':[]}]);return
            if re.fullmatch(r'/world/[A-Za-z0-9_@-]+',p) and self.headers.get('Upgrade','').lower()=='websocket':
                self.websocket(p);return
            if p.startswith('/auth/') or p.startswith('/chars/') or p.startswith('/world/') or p.startswith('/__local__/'):
                raise Error(404,'Route not available')
            self.static(p)
        except Error as e:self.err(e)
        # Browser may cancel large GLB/image downloads after headers are sent.
        # A closed peer is not an internal server error; never send a second 500.
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):return
        except Exception as e:logging.exception('GET failed');self.err(Error(500,'Internal local server error'))
    do_HEAD=do_GET
    def do_POST(self):
        u=urllib.parse.urlsplit(self.path);p=u.path
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size<0 or size>MAX_REQUEST:raise Error(413,'Request too large')
            if self.headers.get('Content-Type','').split(';')[0].strip().lower()!='application/json':raise Error(415,'JSON required')
            self.require_origin()
            d=json.loads(self.rfile.read(size) or b'{}')
            if not isinstance(d,dict):raise Error(400,'JSON object required')
            store=self.server.store
            if p=='/__local__/bootstrap':
                jar=http.cookies.SimpleCookie()
                try:jar.load(self.headers.get('Cookie',''))
                except http.cookies.CookieError:pass
                cookie=jar.get('b2csrf');val=cookie.value if cookie else ''
                if not val or not hmac.compare_digest(val,self.headers.get('x-b2-csrf','')):raise Error(403,'Local page CSRF check required')
                self.json(200,store.ensure_bootstrap());return
            if p=='/auth/register':self.json(200,store.create_user(str(d.get('email','')),str(d.get('password',''))));return
            if p=='/auth/login':self.json(200,store.login(str(d.get('email','')),str(d.get('password',''))));return
            if p=='/auth/change-password':
                self.json(200,store.change_password(str(d.get('email','')),str(d.get('password','')),str(d.get('newPassword',''))));return
            if p in ('/auth/forgot','/auth/reset'):
                raise Error(501,'Local password recovery is not configured; no email service')
            t=self.headers.get('x-session-token','');me=store.require(t)
            if p=='/auth/logout':store.logout(t);self.json(200,{'ok':True});return
            if p=='/chars/create':self.json(200,store.create_char(me,d));return
            if p=='/chars/delete':store.del_char(me,str(d.get('characterId','')));self.json(200,{'ok':True});return
            if p=='/chars/token':self.json(200,store.join_token(me,str(d.get('characterId',''))));return
            raise Error(404,'Not implemented')
        except Error as e:self.err(e)
        except (ValueError,TypeError,json.JSONDecodeError):self.err(Error(400,'Invalid JSON'))
        except Exception:logging.exception('POST failed');self.err(Error(500,'Internal local server error'))
    def static(self,p):
        if p=='/':p='/index.html'
        if '\x00' in p or '\\' in p or any(x in ('..','.') for x in p.split('/')):raise Error(400,'Unsafe path')
        path=(self.server.root/p.lstrip('/')).resolve()
        if not path.is_relative_to(self.server.root) or not path.is_file():raise Error(404,'Static file not found')
        n=path.stat().st_size
        mime=mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
        if path.suffix=='.ktx2':mime='image/ktx2'
        if path.suffix=='.glb':mime='model/gltf-binary'
        if path.suffix=='.wasm':mime='application/wasm'
        if path.suffix=='.js':mime='text/javascript'
        start,end=0,n-1; status=200
        rg=self.headers.get('Range','')
        if rg:
            m=re.fullmatch(r'bytes=(\d+)-(\d*)',rg)
            if not m:raise Error(416,'Invalid byte range')
            start=int(m.group(1));end=int(m.group(2)) if m.group(2) else end
            if start>=n or end<start:raise Error(416,'Invalid byte range')
            end=min(end,n-1);status=206
        self.send_response(status)
        self.send_header('Content-Type',mime)
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Access-Control-Allow-Origin',f'http://{self.headers.get("Host", "127.0.0.1")}')
        self.send_header('Accept-Ranges','bytes')
        self.send_header('Content-Length',str(max(0,end-start+1)))
        if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{n}')
        self.send_header('Connection','close');self.end_headers();self.close_connection=True
        if self.command!='HEAD':
            with path.open('rb') as f:
                f.seek(start);left=end-start+1
                while left>0:
                    chunk=f.read(min(262144,left))
                    if not chunk:break
                    self.wfile.write(chunk);left-=len(chunk)
    def websocket(self,path):
        expected=f'http://{self.headers.get("Host","")}'
        if self.headers.get('Origin')!=expected:raise Error(403,'WebSocket origin refused')
        if self.headers.get('Sec-WebSocket-Version')!='13':raise Error(426,'WebSocket v13 required')
        key=self.headers.get('Sec-WebSocket-Key','')
        try:
            if len(base64.b64decode(key,validate=True))!=16:raise ValueError('bad key')
        except (ValueError,base64.binascii.Error):raise Error(400,'Invalid websocket key')
        accept=base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
        self.send_response(101,'Switching Protocols')
        self.send_header('Upgrade','websocket');self.send_header('Connection','Upgrade')
        self.send_header('Sec-WebSocket-Accept',accept);self.end_headers()
        self.close_connection=True
        with self.server.active_lock:self.server.active+=1
        try:self.world_loop(WS(self.connection))
        except (BrokenPipeError,ConnectionResetError,EOFError,socket.timeout):pass
        except Exception:logging.exception('world session failed')
        finally:
            with self.server.active_lock:self.server.active-=1
    def world_loop(self,ws):
        store=self.server.store
        ws.send(bytes([2,PROTO]))
        ch=None;last=(0.,0.);target=None;tick=0;handle=0x10001;last_frame=time.monotonic();last_move=time.monotonic();last_save=time.monotonic()
        while True:
            msg=ws.receive()
            if msg:
                op,data=msg
                if op==8:return
                if op==9:ws.send(data,opcode=10);continue
                if op!=2:continue
                if ch is None:
                    try:
                        info=decode_join(data)
                        ch=store.take_join(info['characterId'],info['joinToken'])
                        if info['classNum']!=CLASS_ORDER[ch['classId']] or info['empire']!=ch['empire']:raise Error(403,'Class/empire differs from local character')
                    except (Error,ValueError) as e:
                        self.server.metrics['game_join_rejected']+=1
                        ws.send(jbytes({'code':'join-refused','message':str(e),'retryable':False},12));return
                    self.server.metrics['game_join_accepted']+=1
                    last=(ch['x'],ch['z']);handle=0x10001
                    ws.send(jbytes({'characterId':ch['id'],'mapId':ch['mapId'],'handle':handle,'serverTimeMs':int(time.time()*1000)},11))
                    ws.send(make_self(ch['x'],ch['z'],100,100,handle))
                    ws.send(jbytes({'id':ch['id'],'name':ch['name'],'level':ch['level'],'skills':[],'buffs':[],'gold':0},3))
                    ws.send(jbytes({'items':[],'equipment':{},'gold':0},4))
                    ws.send(snapshot(1,ch,handle,True,last));tick=1
                    last_frame=time.monotonic();continue
                if data[:2]==b'\x0a\x02' and len(data)>=10:
                    x,z=struct.unpack_from('<ii',data,2)
                    target=(max(-20000.,min(20000.,x/100)),max(-20000.,min(20000.,z/100)))
                elif data[:2]==b'\x0a\x03' and len(data)>=3:pass # heading handled by client prediction
                elif data[:2]==b'\x0a\x0f':
                    try:
                        length=struct.unpack_from('<H',data,2)[0]
                        d=json.loads(data[4:4+length]);kind=d.get('t')
                        if kind=='ping':ws.send(jbytes({'m':'pong','d':{'clientTime':d.get('clientTime'),'serverTime':int(time.time()*1000),'timezoneOffsetMinutes':0}},9))
                    except (ValueError,TypeError,IndexError,json.JSONDecodeError):pass
            if ch is None:continue
            now=time.monotonic()
            if now-last_frame<.1:continue
            dt=min(.25,now-last_frame);last_frame=now
            if target is not None:
                dx=target[0]-ch['x'];dz=target[1]-ch['z'];r=math.hypot(dx,dz)
                if r<=.05:target=None
                else:
                    step=min(r,dt*4.0);ch['x']+=dx/r*step;ch['z']+=dz/r*step
            tick+=1
            ws.send(snapshot(tick,ch,handle,False,last))
            if (round(ch['x']*100),round(ch['z']*100)) != (round(last[0]*100),round(last[1]*100)):
                last=(ch['x'],ch['z'])
                ws.send(make_self(ch['x'],ch['z'],100,100,handle))
            if now-last_save>=3:
                store.save_pos(ch);last_save=now

def check_sources(root):
    source=(root/'assets')
    checks={'index':(root/'index.html').is_file()}
    for fn in ('auth-C9as2-Nt.js','game-mpPBZnwM.js','world-bridge-BplQPdB8.js'):
        checks[fn]=(source/fn).is_file()
    return checks

def selftest():
    import tempfile,urllib.request,urllib.error
    assert decode_join(b'\x0a\x01'+encstr('abc')+b'\x00\x01'+encstr('secret'))=={'characterId':'abc','classNum':0,'empire':1,'joinToken':'secret'}
    assert len(make_self(0,0,100,100,0x10001))==32
    assert snapshot(1,{'x':0.,'z':0.,'name':'Tester','classId':'warrior','gender':'m','empire':1},0x10001,True,(0,0))[0]==1
    assert password_verify('testpassword',password_hash('testpassword'))
    with tempfile.TemporaryDirectory() as t:
        root=Path(t)/'assetsroot';root.mkdir();(root/'index.html').write_text('<title>Original test fixture</title>');(root/'assets').mkdir();(root/'assets'/'test.ktx2').write_bytes(b'k'*100)
        store=Store(Path(t)/'local.sqlite3')
        ses=store.create_user('user@local.invalid','Password123')
        u=store.require(ses['token'])
        ch=store.create_char(u,{'name':'Tester','classId':'warrior','gender':'m','empire':1})
        assert len(store.list_char(u))==1
        jt=store.join_token(u,ch['id'])['joinToken']
        assert store.take_join(ch['id'],jt)['id']==ch['id']
        try:store.take_join(ch['id'],jt);raise AssertionError('token replay not rejected')
        except Error:pass
        server=Server(('127.0.0.1',0),root,Path(t))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        url=f'http://127.0.0.1:{server.server_port}'
        with urllib.request.urlopen(url+'/') as f:assert f.status==200
        with urllib.request.urlopen(url+'/assets/test.ktx2') as f:assert f.status==200 and f.read()==b'k'*100
        req=urllib.request.Request(url+'/assets/test.ktx2',headers={'Range':'bytes=10-19'})
        with urllib.request.urlopen(req) as f:assert f.status==206 and f.read()==b'k'*10
        with urllib.request.urlopen(url+'/__local__/health') as f:assert json.load(f)['proto']==28
        # Browser startup uses a real local CSRF cookie and persists a new SQLite user.
        with urllib.request.urlopen(url+'/__local__/') as f:
            local_html=f.read().decode('utf8');setcookie=f.headers['Set-Cookie']
            assert 'Yerel Oyuna Gir' in local_html and 'b2csrf=' in setcookie
        csrf=setcookie.split('b2csrf=',1)[1].split(';',1)[0]
        boot_req=urllib.request.Request(url+'/__local__/bootstrap',method='POST',data=b'{}',headers={
            'Content-Type':'application/json','Origin':url,'Cookie':f'b2csrf={csrf}','x-b2-csrf':csrf})
        with urllib.request.urlopen(boot_req) as f:boot=json.load(f)
        assert boot['session']['token'] and boot['character']['name']=='LocalWarrior'
        assert store.require(boot['session']['token'])['email']=='localplayer@browser2.invalid'
        with urllib.request.urlopen(url+'/health') as f:assert json.load(f)['protocolVersion']==28
        with urllib.request.urlopen(url+'/world/map1/catalogs/maps') as f:assert json.load(f)[0]['tileSet']=='map_a2'
        with urllib.request.urlopen(urllib.request.Request(url+'/chars/list',headers={'x-session-token':ses['token']})) as f:assert len(json.load(f))==1
        req=urllib.request.Request(url+'/chars/token',method='POST',data=jbytes({'characterId':ch['id']}),headers={'Content-Type':'application/json','Origin':url,'x-session-token':ses['token']})
        with urllib.request.urlopen(req) as f:ws_token=json.load(f)['joinToken']
        # Real RFC6455 upgrade and ORIGINAL version-28 join with masked client frame.
        sock=socket.create_connection(('127.0.0.1',server.server_port),timeout=5)
        key=base64.b64encode(secrets.token_bytes(16)).decode()
        hs=(f'GET /world/map1 HTTP/1.1\r\nHost: 127.0.0.1:{server.server_port}\r\n'
            f'Origin: {url}\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n'
            f'Sec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key}\r\n\r\n')
        sock.sendall(hs.encode('ascii'))
        resp=b''
        while not resp.endswith(b'\r\n\r\n'):
            resp+=sock.recv(1)
            assert len(resp)<4096
        assert resp.startswith(b'HTTP/1.1 101'),resp
        def recv_exact(n):
            q=bytearray()
            while len(q)<n:
                t=sock.recv(n-len(q))
                if not t:raise EOFError()
                q+=t
            return bytes(q)
        def recv_ws():
            h=recv_exact(2)
            n=h[1]&127
            if n==126:n=struct.unpack('!H',recv_exact(2))[0]
            if n==127:n=struct.unpack('!Q',recv_exact(8))[0]
            return h[0]&15,recv_exact(n)
        op,hello=recv_ws();assert op==2 and hello==bytes([2,28]),hello
        join=bytes([10,1])+encstr(ch['id'])+bytes([0,1])+encstr(ws_token)
        mask=secrets.token_bytes(4)
        wire=bytes([0x82,0x80|len(join)])+mask+bytes(z^mask[i%4] for i,z in enumerate(join))
        sock.sendall(wire)
        frames=[recv_ws()[1] for _ in range(5)]
        assert [x[0] for x in frames]==[11,5,3,4,1],[(x[0],len(x)) for x in frames]
        accepted=json.loads(frames[0][1:]);assert accepted['characterId']==ch['id'] and accepted['mapId']=='map_a2'
        assert len(frames[1])==32
        assert len(frames[4])>100 and frames[4][0]==1
        sock.close()
        server.shutdown();server.server_close()
    print('[SELFTEST OK] SQLite AUTH, one-use join, HTTP/Range, WebSocket upgrade, HELLO 28, JoinAccepted, SELF, INVENTORY, SNAPSHOT')

def main():
    p=argparse.ArgumentParser(description='Browser2 original-client compatible LOCAL AUTH + partial GAME prototype')
    p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--state',type=Path,default=STATE)
    p.add_argument('--port',type=int,default=8894)
    p.add_argument('--selftest',action='store_true')
    p.add_argument('--audit',action='store_true')
    p.add_argument('--serve',action='store_true')
    a=p.parse_args()
    if a.selftest:selftest();return
    root=a.root.expanduser().resolve()
    state=a.state.expanduser().resolve()
    results=check_sources(root)
    print('[SOURCE]',results,flush=True)
    if not all(results.values()):
        raise SystemExit('Original client archive incomplete. No files copied or changed.')
    if a.audit:
        print('[DESIGN] origin-local AUTH; SQLite sessions, characters and one-time join tokens; protocol 28 WebSocket')
        print('[LIMIT] GAME is a PARTIAL independent implementation, not the proprietary server.')
    if not a.serve:return
    if not 1024<=a.port<=65535:raise SystemExit('Invalid port')
    logging.basicConfig(level=logging.WARNING,format='%(levelname)s %(message)s')
    server=Server(('127.0.0.1',a.port),root,state)
    print(f'[LOCAL] http://127.0.0.1:{a.port}/__local__/',flush=True)
    print('[GAME] open that URL and tap Yerel Oyuna Gir; original assets never modified',flush=True)
    print('[SECURITY] Only 127.0.0.1. No remote Browser2 credentials, cookies, traffic or login',flush=True)
    try:server.serve_forever(poll_interval=.3)
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':main()
