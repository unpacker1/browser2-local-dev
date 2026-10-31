#!/usr/bin/env python3
"""V83: guards optional NPC/render events against taking down the world stream.
Only alters pinned local V69 Python bridge with backup. Native GAME/DB/SQL untouched.
"""
from pathlib import Path
import argparse
import hashlib
import os
import re
import shutil
import time

ORIGINAL_SHA = "aefd34fa9e5b9599039ab8abe26470055f363b8b94d864c449d9c92b092ca4f3"
TAG = "# V83_OPTIONAL_NPC_EVENT_GUARD_AND_SAFE_ERROR_REASON"

def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError("V69 code marker mismatch; original unchanged")
    return source.replace(old, new, 1)

def build(source):
    if TAG in source:
        return source
    if hashlib.sha256(source.encode()).hexdigest() != ORIGINAL_SHA:
        raise ValueError("V69 original SHA mismatch; original unchanged")
    source = replace_once(source,
        "        self.last_stream_duration_seconds=0.;self.last_process_return_code=None\n",
        "        self.last_stream_duration_seconds=0.;self.last_process_return_code=None\n"
        "        self.last_bridge_error_type='none';self.last_bridge_error_file='none';self.last_bridge_error_line=0\n"
        "        self.last_optional_event_type='none';self.last_optional_event_kind='none'\n")
    source = replace_once(source,
        "                'nativeWorldTransportExceptions':self.metrics['native_ws_uncaught'],'nativeSqlDirectReadOnly':True,\n",
        "                'nativeWorldTransportExceptions':self.metrics['native_ws_uncaught'],'nativeSqlDirectReadOnly':True,\n"
        "                'nativeBridgeUnexpectedType':self.last_bridge_error_type,\n"
        "                'nativeBridgeUnexpectedSource':self.last_bridge_error_file,\n"
        "                'nativeBridgeUnexpectedLine':self.last_bridge_error_line,\n"
        "                'nativeOptionalEventsSkipped':self.metrics['native_optional_event_skipped'],\n"
        "                'nativeOptionalLastType':self.last_optional_event_type,\n"
        "                'nativeOptionalLastKind':self.last_optional_event_kind,\n"
        "                'nativeMalformedHelperEventsSkipped':self.metrics['native_helper_invalid_json_event'],\n")
    source = replace_once(source, "                                kind=event.get('type')\n",
        "                                if not isinstance(event,dict):\n"
        "                                    bridge.metrics['native_helper_invalid_json_event']+=1\n"
        "                                    continue\n"
        "                                kind=event.get('type')\n")
    begin = "                                if kind=='closed':\n"
    end = "                            if proc.poll() is not None:\n"
    if source.count(begin)!=1 or source.count(end)!=1:
        raise ValueError("V69 event anchors changed")
    a=source.index(begin)
    b=source.index(end,a)
    inner=source[a:b]
    indented=''.join('    '+line if line.strip() else line for line in inner.splitlines(keepends=True))
    guarded=(
      "                                try:\n"+indented+
      "                                except (ValueError,TypeError,KeyError,OverflowError,sqlite3.Error,ImportError,AttributeError,IndexError) as exc:\n"
      "                                    # Do not mask actual GAME closed/movement/protocol failures.\n"
      "                                    if kind not in ('npc_script','shop_event','actor_add','actor_move','actor_del','actor_command_sent'):\n"
      "                                        raise\n"
      "                                    bridge.metrics['native_optional_event_skipped']+=1\n"
      "                                    bridge.last_optional_event_kind=kind\n"
      "                                    bridge.last_optional_event_type=type(exc).__name__\n"
      "                                    continue\n"
    )
    source=source[:a]+guarded+source[b:]
    source=replace_once(source,
      "                    except Exception:\n"
      "                        bridge.metrics['native_ws_uncaught']+=1\n",
      "                    except Exception as exc:\n"
      "                        # Only safe class and source line; no payload, password, or SQL/log text.\n"
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
    result=TAG+'\n'+source
    compile(result,'native_v69.py','exec')
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source',type=Path,default=Path.home()/'CEMREEFE_BROWSER2_V69_NATIVE_SHOP_CATALOG/native_v69.py')
    p.add_argument('--check',action='store_true')
    a=p.parse_args()
    path=a.source.expanduser()
    if not path.is_file() or path.is_symlink():
        raise SystemExit('[HATA] V69 Python bridge file missing or symlink')
    original=path.read_text('utf-8')
    if TAG in original:
        print('[V83] Already patched')
        return
    try: result=build(original)
    except ValueError as e: raise SystemExit('[HATA] '+str(e)) from e
    if a.check:
        print('[V83 CHECK] SHA, event guard, status mapping, syntax OK')
        return
    backup=path.with_suffix('.py.V83_BACKUP_'+time.strftime('%Y%m%d_%H%M%S',time.gmtime()))
    shutil.copy2(path,backup)
    tmp=path.with_suffix('.py.V83_TEMP')
    try:
        tmp.write_text(result,'utf-8')
        compile(tmp.read_text('utf-8'),str(path),'exec')
        os.chmod(tmp,path.stat().st_mode)
        os.replace(tmp,path)
    finally:
        if tmp.exists():tmp.unlink()
    print('[V83 PATCH] Safe event guard and exception diagnostics installed')
    print('[BACKUP]',backup)
    print('[UNCHANGED] GAME/AUTH/DB native binaries, original client, SQLite')

if __name__=='__main__':
    main()
