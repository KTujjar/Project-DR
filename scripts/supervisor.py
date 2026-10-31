#!/usr/bin/env python3
"""Mac mission supervisor: keep camera/backend alive; never retry motor bringup."""
import json,os,signal,subprocess,sys,time,urllib.request,fcntl
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/'.robot/runtime'
sys.path.insert(0,str(ROOT))
from scripts.missionctl import ssh,health,terminate,ensure_transport
stop=False

def main():
    global stop
    RUNTIME.mkdir(parents=True,exist_ok=True,mode=0o700)
    # Held for the daemon lifetime, even if a second launcher uses another
    # spelling/capitalization of this directory or a stale PID file exists.
    singleton=(RUNTIME/'supervisor.lock').open('a')
    try:fcntl.flock(singleton,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:singleton.close();print('Mission supervisor already running; duplicate refused.',flush=True);return
    (RUNTIME/'supervisor.pid').write_text(str(os.getpid()))
    config=json.loads((RUNTIME/'config.json').read_text());relay=None;backend=None;last_camera=time.monotonic();last_ensure=0
    def handler(*_):
        global stop
        stop=True
    signal.signal(signal.SIGTERM,handler);signal.signal(signal.SIGINT,handler)
    try:
        if config['mock']:
            env=os.environ.copy();env.update(TURTBOT_MODE='mock',TURTBOT_ALLOW_MOTION='0',TURTBOT_TOKEN_FILE=str(RUNTIME/'service.token'))
            backend=subprocess.Popen([sys.executable,'-m','uvicorn','dashboard.backend.app:app','--host','127.0.0.1','--port','8872'],cwd=ROOT,env=env)
        while not stop:
            if config['mock']:
                if backend.poll() is not None:raise RuntimeError('Mock backend exited; relaunch with start.sh --mock')
            else:
                now=time.monotonic();h=health()
                if now-last_ensure>4:
                    last_ensure=now
                    try:
                        ensure_transport(config)
                        ssh(config,['python3','scripts/pi_runtime.py','ensure']+(['--allow-motion'] if config['allow_motion'] else [])+(['--bypass-obstacles'] if config.get('bypass_obstacles') else []),timeout=12)
                    except Exception as exc:print('Backend/network degraded:',exc,flush=True)
                camera=(h or {}).get('sensors',{}).get('camera',{})
                if camera.get('status')=='live':last_camera=now
                if relay and (relay.poll() is not None or now-last_camera>15):
                    terminate(relay);relay=None;last_camera=now
                if relay is None:
                    log=(RUNTIME/'camera-relay.log').open('ab',buffering=0)
                    relay=subprocess.Popen([sys.executable,str(ROOT/'camera/relay.py'),'--target',config['target'],'--control',str(ROOT/'.robot/control'),'--url','http://127.0.0.1:8872','--token-file',str(RUNTIME/'service.token'),'--path',config.get('camera_path','auto')],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
            time.sleep(1)
    finally:
        if relay:terminate(relay)
        if backend:backend.terminate();backend.wait(timeout=4)
        try:
            if (RUNTIME/'supervisor.pid').read_text().strip()==str(os.getpid()):(RUNTIME/'supervisor.pid').unlink()
        except FileNotFoundError:pass
        singleton.close()
if __name__=='__main__':main()
