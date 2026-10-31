#!/usr/bin/env python3
"""Isolated V84 compatibility patch for existing V69 Python bridge.

Does not overwrite user's active V69, native binaries, player SQL or original assets.
All edits require unique anchored source blocks and compile validation.
"""
import argparse
import ast
import hashlib
from pathlib import Path
import shutil
import sys
import time

TAG = '# V84_SAFE_NPC_BRIDGE_DIAGNOSTICS\n'


def unique(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Unverified V69 source structure: anchor not unique: '+repr(old[:70]))
    return text.replace(old,new,1)


def patch(source):
    if TAG in source:
        compile(source, 'native_v69.py', 'exec')
        return source
    # We deliberately don't trust an arbitrary SHA: some existing V69 local copies differ.
    # Instead require a strict structural contract for all 4 modifications.
    tree = ast.parse(source)
    classes = {node.name:node for node in tree.body if isinstance(node,ast.ClassDef)}
    for name in ('NativeBridge',):
        if name not in classes:
            raise ValueError('Missing verified V69 NativeBridge')
    if 'def world_loop(self,ws):' not in source or "def status(self):" not in source:
        raise ValueError('Missing verified native bridge handlers')
    s=source
    s=unique(s,
        "        self.last_stream_duration_seconds=0.;self.last_process_return_code=None\n",
        "        self.last_stream_duration_seconds=0.;self.last_process_return_code=None\n"
        "        self.last_bridge_error_type='none';self.last_bridge_error_file='none';self.last_bridge_error_line=0\n"
        "        self.last_optional_event_type='none';self.last_optional_event_kind='none'\n")
    s=unique(s,
        "                'nativeWorldTransportExceptions':self.metrics['native_ws_uncaught'],'nativeSqlDirectReadOnly':True,\n",
        "                'nativeWorldTransportExceptions':self.metrics['native_ws_uncaught'],'nativeSqlDirectReadOnly':True,\n"
        "                'nativeBridgeUnexpectedType':self.last_bridge_error_type,\n"
        "                'nativeBridgeUnexpectedSource':self.last_bridge_error_file,\n"
        "                'nativeBridgeUnexpectedLine':self.last_bridge_error_line,\n"
        "                'nativeOptionalEventsSkipped':self.metrics['native_optional_event_skipped'],\n"
        "                'nativeOptionalLastType':self.last_optional_event_type,\n"
        "                'nativeOptionalLastKind':self.last_optional_event_kind,\n"
        "                'nativeMalformedHelperEventsSkipped':self.metrics['native_helper_invalid_json_event'],\n")
    s=unique(s,
        "                                kind=event.get('type')\n",
        "                                if not isinstance(event,dict):\n"
        "                                    bridge.metrics['native_helper_invalid_json_event']+=1\n"
        "                                    continue\n"
        "                                kind=event.get('type')\n")
    # Click is already sent to native GAME by this point; a local read-only
    # shop lookup must never terminate the real player stream.
    old = (
        "                                                 import native_shop_catalog_v69 as shopcatalog\n"
        "                                                 bridge.native_shop_last=shopcatalog.catalogue_for_npc(\n"
        "                                                     bridge.runtime/'sqlite',last_clicked_npc_vnum)\n"
        "                                                 bridge.metrics['native_shop_catalog_after_verified_click']+=1\n"
    )
    # The legacy source uses 48 spaces, not 49. Anchor without hardcoding
    # whitespace in the snippet is deliberately NOT allowed.
    old = old.replace('                                                 ', '                                                ')
    if s.count(old) != 1:
        raise ValueError('V69 verified click SQL lookup is changed; no patch applied')
    new = (
        "                                                try:\n"
        "                                                    import native_shop_catalog_v69 as shopcatalog\n"
        "                                                    bridge.native_shop_last=shopcatalog.catalogue_for_npc(\n"
        "                                                        bridge.runtime/'sqlite',last_clicked_npc_vnum)\n"
        "                                                    bridge.metrics['native_shop_catalog_after_verified_click']+=1\n"
        "                                                except (sqlite3.Error,ValueError,TypeError,OSError,KeyError,ImportError) as exc:\n"
        "                                                    # Native CLICK was sent; SQL is only a READ-ONLY annotation.\n"
        "                                                    bridge.metrics['native_shop_source_optional_error']+=1\n"
        "                                                    bridge.last_optional_event_kind='source_shop_lookup'\n"
        "                                                    bridge.last_optional_event_type=type(exc).__name__\n"
        "                                                    bridge.native_shop_last={'state':'source_shop_lookup_failed',\n"
        "                                                      'shopCount':0,'itemCount':0,'npcVnum':last_clicked_npc_vnum}\n"
    )
    s=s.replace(old,new,1)
    # Do not alter anything outside this bounded native event loop.
    start="                                if kind=='closed':\n"
    end="                            if proc.poll() is not None:\n"
    if s.count(start)!=1 or s.count(end)!=1:
        raise ValueError('Unverified event loop structure; no patch applied')
    i=s.index(start);j=s.index(end,i)
    body=s[i:j]
    if not ("if kind=='npc_script':" in body and "if kind=='shop_event':" in body and "if kind=='actor_add':" in body):
        raise ValueError('Original native event set differs; no patch applied')
    guarded=''.join(('    '+x if x.strip() else x) for x in body.splitlines(keepends=True))
    guarded=("                                try:\n"+guarded+
       "                                except (ValueError,TypeError,KeyError,OverflowError,sqlite3.Error,ImportError,AttributeError,IndexError) as exc:\n"
       "                                    # Only optional NPC/actor UI events can be skipped.\n"
       "                                    if kind not in ('npc_script','shop_event','actor_add','actor_move','actor_del','actor_command_sent'):\n"
       "                                        raise\n"
       "                                    bridge.metrics['native_optional_event_skipped']+=1\n"
       "                                    bridge.last_optional_event_kind=kind\n"
       "                                    bridge.last_optional_event_type=type(exc).__name__\n"
       "                                    continue\n")
    s=s[:i]+guarded+s[j:]
    s=unique(s,
        "                    except Exception:\n"
        "                        bridge.metrics['native_ws_uncaught']+=1\n",
        "                    except Exception as exc:\n"
        "                        # Diagnostics only: class + code filename + line, NO exception text.\n"
        "                        bridge.last_bridge_error_type=type(exc).__name__[:48]\n"
        "                        tb=exc.__traceback__;name='none';lineno=0\n"
        "                        while tb is not None:\n"
        "                            base_name=Path(tb.tb_frame.f_code.co_filename).name\n"
        "                            if re.fullmatch(r'[A-Za-z0-9_]{1,64}\\.py',base_name):\n"
        "                                name=base_name;lineno=max(0,int(tb.tb_lineno))\n"
        "                            tb=tb.tb_next\n"
        "                        bridge.last_bridge_error_file=name\n"
        "                        bridge.last_bridge_error_line=lineno\n"
        "                        bridge.metrics['native_ws_uncaught']+=1\n")
    result=TAG+s
    compile(result,'native_v69.py','exec')
    ast.parse(result)
    return result


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--destination',type=Path,required=True)
    args=p.parse_args()
    src=args.source.expanduser().resolve(strict=True)
    dst=args.destination.expanduser()
    if not src.is_file() or args.source.is_symlink():
        p.error('Original V69 is not a regular file')
    if dst == src or dst.resolve()==src:
        p.error('Refusing to modify original V69 in-place')
    if dst.exists() and dst.is_symlink():
        p.error('Destination is a symlink')
    code=src.read_text('utf-8')
    try: modified=patch(code)
    except (ValueError,SyntaxError) as exc: p.error(str(exc))
    dst.parent.mkdir(parents=True,exist_ok=True)
    if dst.exists():
        backup=dst.with_suffix('.py.V84_SAVE_'+time.strftime('%Y%m%d%H%M%S',time.gmtime()))
        shutil.copy2(dst,backup)
    temp=dst.with_suffix('.py.V84_TEMP')
    try:
        temp.write_text(modified,'utf-8')
        compile(temp.read_text('utf-8'),str(dst),'exec')
        temp.replace(dst)
    finally:
        temp.unlink(missing_ok=True)
    print('[V84 OK] Isolated bridge patch applied; original V69 untouched')
    print('[SOURCE SHA256]',hashlib.sha256(code.encode()).hexdigest())
    print('[DESTINATION]',dst)

if __name__=='__main__':
    main()