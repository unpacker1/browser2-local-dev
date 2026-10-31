#!/usr/bin/env python3
"""Inject an isolated, authenticated read-only NPC overlay into V85 bridge.

Original JS/WASM/GLB assets and Cemre Efe native GAME/AUTH/DB are never edited.
Fail closed if the V85 source layout is different. Does not implement BUY/SELL.
"""
import argparse
import ast
import hashlib
import os
from pathlib import Path
import re
import tempfile

MARK='# V86: authenticated read-only NPC game overlay'
REQUIRED='# V85: undefined V80 preview is optional'

def one(s,old,new):
    if s.count(old)!=1:raise ValueError('V85 source anchor does not match: '+old[:100])
    return s.replace(old,new,1)

def after_line(s,pattern,newline):
    matches=list(re.finditer(pattern,s,re.M))
    if len(matches)!=1:raise ValueError('V85 line anchor not unique: '+pattern)
    m=matches[0]
    spaces=m.group('indent')
    return s[:m.end()]+spaces+newline+'\n'+s[m.end():]

def transform(s):
    if MARK in s:
        compile(s,'native_v69.py','exec');return s,'already_installed'
    if REQUIRED not in s:raise ValueError('V85 NameError fix not present. Do not alter V69/V84.')
    if "def world_loop(self,ws):" not in s or "def status(self):" not in s:
        raise ValueError('V85 bridge structure unrecognized')
    ast.parse(s)
    s=one(s,'from pathlib import Path\n','from pathlib import Path\nimport native_npc_ui_v86 as npcui\n')
    s=one(s,'    bridge=NativeBridge(engine,root)\n','    bridge=NativeBridge(engine,root)\n    npcui.attach(bridge)\n')
    s=one(s,"PLAY_HTML.replace('__ORIGINAL_AUTH_MODULE__','/assets/'+auth_module).encode('utf-8')",
          "PLAY_HTML.replace('__ORIGINAL_AUTH_MODULE__','/assets/'+auth_module).replace('</html>',npcui.PLAY_EXTRA+'</html>').encode('utf-8')")
    s=one(s,"                if p=='/__native__/status':return self.json(200,bridge.status())\n",
          "                if p=='/__native__/npc-ui':\n"
          "                    u=bridge.sessions.require(self.headers.get('x-session-token',''))\n"
          "                    return self.json(200,npcui.snapshot(bridge,u['login']))\n"
          "                if p=='/__native__/status':return self.json(200,bridge.status())\n")
    # Show overlay on verified live actor click, even if source database has no shop.
    s=after_line(s,r'^(?P<indent>\s*)last_clicked_npc_at=now\n',
        "npcui.clicked(bridge,user['login'],last_clicked_npc_vnum)")
    # Add source SQLITE items once the independent read-only lookup succeeds.
    s=after_line(s,r"^(?P<indent>\s*)bridge\.metrics\['native_shop_catalog_after_verified_click'\]\+=1\n",
        "npcui.clicked(bridge,user['login'],last_clicked_npc_vnum,bridge.native_shop_last)")
    # Original CP949 script: decode into text, never execute script markup.
    s=after_line(s,r"^(?P<indent>\s*)bridge\.metrics\['native_npc_scripts_received'\]\+=1\n",
        "npcui.script(bridge,user['login'],last_clicked_npc_vnum,event)")
    s=MARK+'\n'+s
    ast.parse(s);compile(s,'native_v69.py','exec')
    return s,'patched'

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--destination',type=Path,required=True)
    a=p.parse_args()
    source=a.source.expanduser();dest=a.destination.expanduser()
    if not source.is_file() or source.is_symlink() or source.resolve()==dest.resolve():
        p.error('V85 source not regular file or destination overlaps original')
    if dest.is_symlink():p.error('Destination may not be a symlink')
    raw=source.read_bytes();content=raw.decode('utf-8')
    try:patched,what=transform(content)
    except (ValueError,SyntaxError) as exc:p.error(str(exc))
    # Re-read source to detect modifications during work.
    if hashlib.sha256(source.read_bytes()).digest()!=hashlib.sha256(raw).digest():
        p.error('Source changed while reading; refusing to write')
    dest.parent.mkdir(parents=True,exist_ok=True)
    if dest.exists():
        p.error('Output already exists; refusing to overwrite isolated V86')
    fd,tmp=tempfile.mkstemp(prefix='.native_v86_',suffix='.py',dir=dest.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            f.write(patched);f.flush();os.fsync(f.fileno())
        os.replace(tmp,dest)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    print('[V86]',what,'new isolated file:',dest)
    print('[KORUNDU] V85, original V69, native GAME/AUTH/DB, player SQLite, original client files')
    print('[SINIR] SQL preview and original NPC script text only; native game purchases DISABLED')

if __name__=='__main__':main()