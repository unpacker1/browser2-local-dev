#!/data/data/com.termux/files/usr/bin/bash
# V82: cold-start the user's existing native DB/AUTH/GAME plus V69 browser bridge.
# Does not reset any SQLite database or change original assets/native binaries.
set -euo pipefail
ROOT="$HOME/CEMREEFE_NATIVE_STANDALONE"
NATIVE_LAUNCHER="$HOME/CEMREEFE_WEB_V1/native_runtime_start.py"
V69="$HOME/CEMREEFE_BROWSER2_V69_NATIVE_SHOP_CATALOG"
V69_ZIP="$HOME/storage/downloads/CEMREEFE_BROWSER2_V69_NATIVE_SHOP_CATALOG.zip"
LOG_DIR="$HOME/BROWSER2_LOCAL_SERVER_DATA/START_V82_LOGS"
GAME_URL='http://127.0.0.1:8986/__native__/play'

if ! command -v python3 >/dev/null 2>&1; then
  echo '[EKSIK] Python yok. Termux: pkg install python' >&2; exit 3
fi
if [[ ! -f "$NATIVE_LAUNCHER" || ! -d "$ROOT/runtime" ]]; then
  echo '[EKSIK] Native baslatici veya runtime bulunamadi:' >&2
  echo "  $NATIVE_LAUNCHER" >&2
  echo "  $ROOT/runtime" >&2
  echo '[KORUMA] SQL sifirlanmadi; native kaynak indirilmedi.' >&2
  exit 4
fi
if [[ ! -f "$V69/native_v69.py" || ! -f "$V69/RUN_TERMUX.sh" ]]; then
  if [[ -f "$V69_ZIP" ]]; then
    command -v unzip >/dev/null 2>&1 || { echo '[EKSIK] pkg install unzip' >&2; exit 3; }
    echo '[BROWSER2] Download/V69 paketindeki eksik dosyalar aciliyor (mevcut dosyalar korunur).'
    unzip -nq "$V69_ZIP" -d "$HOME"
  fi
fi
if [[ ! -f "$V69/native_v69.py" || ! -f "$V69/RUN_TERMUX.sh" ]]; then
  echo "[EKSIK] V69 oyun koprusu: $V69 (veya $V69_ZIP)" >&2; exit 5
fi
if [[ ! -f "$HOME/BROWSER2_V54_HARITALAR/browser2_v54_maps.py" ]]; then
  echo '[EKSIK] Orijinal yerel V54 harita modulunu bulamadim; oyun baslatilmadi.' >&2
  exit 6
fi
mkdir -p "$LOG_DIR"
python3 - "$NATIVE_LAUNCHER" "$ROOT" "$V69" "$LOG_DIR" <<'PY'
import os, pathlib, shutil, signal, socket, subprocess, sys, time, urllib.request
native_launcher, native_root, v69, logdir = sys.argv[1:]
url = 'http://127.0.0.1:8986/__native__/play'
ports = (9000, 11000, 11011)
children = []
logs = []

def open_port(port):
    try:
        with socket.create_connection(('127.0.0.1',port),timeout=0.35): return True
    except OSError: return False

def game_ready():
    try:
        with urllib.request.urlopen(url,timeout=3) as r:
            data = r.read(120_000)
            return r.status == 200 and b'Cemre Efe Native GAME' in data
    except Exception: return False

def start(name, argv, logpath):
    log = open(logpath,'ab',buffering=0)
    logs.append(log)
    proc = subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=log,
                            stderr=subprocess.STDOUT,start_new_session=True)
    children.append((name,proc))
    print('[BASLATILDI]',name,'pid=',proc.pid,flush=True)
    return proc

def ready_or_fail(predicate, proc, label, max_seconds):
    for _ in range(max_seconds):
        if predicate(): return
        if proc.poll() is not None:
            raise RuntimeError(f'{label} baslatma islemi bitti (kod={proc.returncode}). Yerel LOGS klasorunu incele.')
        time.sleep(1)
    raise RuntimeError(f'{label} yanit vermedi; yerel LOGS klasorunu incele.')

def cleanup():
    for name,proc in reversed(children):
        if proc.poll() is None:
            try: proc.send_signal(signal.SIGINT)
            except ProcessLookupError: pass
    for name,proc in reversed(children):
        if proc.poll() is None:
            try: proc.wait(timeout=12)
            except subprocess.TimeoutExpired:
                print('[UYARI] Servis kapanisi tamamlanmadi:',name,flush=True)
    for handle in logs: handle.close()

try:
    flags = {p:open_port(p) for p in ports}
    print('[NATIVE_PORTLAR]',flags,flush=True)
    if all(flags.values()):
        print('[NATIVE] Uc servis zaten acik, hicbirini yeniden baslatmiyorum.',flush=True)
    elif any(flags.values()):
        raise RuntimeError('DB/AUTH/GAME portlarinin bir kismi acik. Bu servisleri bozmayip duruyorum.')
    else:
        proc = start('DB+AUTH+GAME', [sys.executable,native_launcher,'--root',native_root],
                     os.path.join(logdir,'native_runtime.out'))
        ready_or_fail(lambda: all(open_port(p) for p in ports),proc,'Native DB/AUTH/GAME',240)
        print('[NATIVE] DB 9000, AUTH 11000, GAME 11011 portlari acildi.',flush=True)
    if game_ready():
        print('[BROWSER2] Oyun sayfasi zaten acik.',flush=True)
    elif open_port(8986):
        raise RuntimeError('8986 portu dolu fakat beklenen Browser2 sayfasi degil. Mevcut sunucuyu durdurmadim.')
    else:
        proc = start('Browser2 V69', ['bash',os.path.join(v69,'RUN_TERMUX.sh')],
                     os.path.join(logdir,'browser2_v69.out'))
        ready_or_fail(game_ready,proc,'Browser2 oyunu',110)
    print('\n[OYUN HAZIR] '+url,flush=True)
    print('[DURUM] http://127.0.0.1:8986/__native__/status',flush=True)
    print('[NOT] Gercek native MAGAZA alisverisi halen tamamlanmamis olabilir.',flush=True)
    print('[NOT] Oyundayken bu Termux oturumunu acik birak. Durdurmak icin Ctrl+C.',flush=True)
    if shutil.which('termux-open-url'):
        try: subprocess.Popen(['termux-open-url',url],stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        except OSError: pass
    while True:
        for name,proc in children:
            if proc.poll() is not None:
                raise RuntimeError(f'{name} beklenmedik bicimde durdu (kod={proc.returncode}).')
        time.sleep(2)
except KeyboardInterrupt:
    print('\n[DURDURULUYOR] Bu oturumda baslatilan servisler kapatiliyor.',flush=True)
except Exception as e:
    print('[HATA]',e,file=sys.stderr,flush=True)
    sys.exit(1)
finally:
    cleanup()
PY