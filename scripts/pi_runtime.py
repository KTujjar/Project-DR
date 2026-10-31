#!/usr/bin/env python3
"""User-owned Pi process management. No system service or repeated driver restart."""
import argparse,json,os,signal,subprocess,time,urllib.request,hashlib,fcntl
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/'.runtime';RUNTIME.mkdir(exist_ok=True,mode=0o700)
STATE=RUNTIME/'pi-processes.json'

def load():
    try:return json.loads(STATE.read_text())
    except (OSError,ValueError):return {}
def save(state):STATE.write_text(json.dumps(state,indent=2))
def identity(pid):
    try:
        stat=Path(f'/proc/{pid}/stat').read_text().split()
        return None if stat[2]=='Z' else {'pid':int(pid),'start':stat[21]}
    except (OSError,IndexError,ValueError):return None
def alive(record):return bool(record and identity(record['pid'])==record)
def command(pid):
    try:return Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0',b' ').decode()
    except OSError:return ''
def drivers():
    result={'lidar':[],'opencr':[]}
    for path in Path('/proc').glob('[0-9]*/cmdline'):
        try:args=path.read_bytes().split(b'\0');name=Path(args[0].decode()).name
        except (OSError,UnicodeError):continue
        key={'hlds_laser_publisher':'lidar','turtlebot3_ros':'opencr'}.get(name)
        if key:result[key].append(int(path.parent.name))
    return result

def spawn(name,args,env=None):
    log=(ROOT/(name+'.log')).open('ab',buffering=0)
    proc=subprocess.Popen(args,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    return identity(proc.pid)
def health():
    try:
        with urllib.request.urlopen('http://127.0.0.1:8765/api/health',timeout=2) as response:return json.load(response)
    except Exception:return None

def ensure(initial=False,allow_motion=False,bypass_obstacles=False):
    if bypass_obstacles and not allow_motion:raise ValueError('Obstacle override requires manual motion enabled')
    state=load();hardware=drivers()
    if any(len(v)>1 for v in hardware.values()):raise RuntimeError('Duplicate hardware drivers detected; manual recovery required')
    if initial and not any(hardware.values()):
        for device in ('/dev/ttyACM0','/dev/ttyUSB0'):
            if not Path(device).exists():raise RuntimeError('Missing '+device+'; reconnect hardware before startup')
        script='source /opt/ros/humble/setup.bash; source "$HOME/turtlebot3_ws/install/setup.bash"; export TURTLEBOT3_MODEL=burger LDS_MODEL=LDS-01 ROS_DOMAIN_ID=30 RMW_IMPLEMENTATION=rmw_fastrtps_cpp; exec ros2 launch turtlebot3_bringup robot.launch.py'
        state['bringup']=spawn('bringup',['bash','-c',script]);save(state)
    elif initial and not all(hardware.values()):raise RuntimeError('Partial hardware bringup present; refusing a competing launch')
    current=health()
    if current and current.get('version')!='mission-v1':raise RuntimeError('An older backend is running; stop that specific backend before launch')
    expected=hashlib.sha256(b''.join(p.read_bytes() for p in sorted((ROOT/'dashboard/backend').glob('*.py')))).hexdigest()[:16]
    settings_changed=current and (bool(current.get('motion_enabled'))!=allow_motion or bool(current.get('control',{}).get('obstacle_guard',{}).get('bypassed'))!=bypass_obstacles)
    if current and (current.get('source_revision')!=expected or settings_changed):
        record=state.get('dashboard')
        if not alive(record):
            try:legacy=int((ROOT/'dashboard.pid').read_text())
            except (OSError,ValueError):legacy=0
            if legacy and str(ROOT/'.venv') in command(legacy) and 'uvicorn dashboard.backend.app:app' in command(legacy):record=identity(legacy)
        if not alive(record):raise RuntimeError('Backend source changed but process ownership is unknown; inspect before restart')
        (os.killpg if os.getpgid(record['pid'])==record['pid'] else os.kill)(record['pid'],signal.SIGINT)
        for _ in range(40):
            if not alive(record):break
            time.sleep(.1)
        if alive(record):
            # A second SIGINT asks uvicorn to finish a stalled WebSocket shutdown.
            os.kill(record['pid'],signal.SIGINT)
            for _ in range(30):
                if not alive(record):break
                time.sleep(.1)
        if alive(record):raise RuntimeError('Backend did not shut down cleanly; no duplicate was started')
        current=None
    if not current:
        # Respect a still-starting owned process, but restart a crashed backend only.
        if not alive(state.get('dashboard')):
            try:legacy=int((ROOT/'dashboard.pid').read_text())
            except (OSError,ValueError):legacy=0
            if legacy and 'uvicorn dashboard.backend.app:app' in command(legacy):
                state['dashboard']=identity(legacy)
            else:
                env=os.environ.copy();env['TURTBOT_ALLOW_MOTION']='1' if allow_motion else '0'
                env['TURTBOT_BYPASS_OBSTACLES']='1' if bypass_obstacles else '0'
                state['dashboard']=spawn('dashboard',['bash','dashboard/start.sh','hardware'],env)
            save(state)
    elif not alive(state.get('dashboard')):
        # Adopt only this project's existing app, never arbitrary processes.
        try:pid=int((ROOT/'dashboard.pid').read_text())
        except (OSError,ValueError):pid=0
        if pid and str(ROOT/'.venv') in command(pid) and 'uvicorn dashboard.backend.app:app' in command(pid):state['dashboard']=identity(pid);save(state)
    return status()

def status():
    state=load();h=health()
    return {'host':os.uname().nodename,'drivers':drivers(),'owned_processes':{k:{**v,'alive':alive(v)} for k,v in state.items() if isinstance(v,dict) and 'pid'in v},
            'backend':None if not h else {'version':h.get('version'),'mode':h['mode'],'motion_enabled':h['motion_enabled'],'armed':h['control']['armed'],
                'sensors':{k:{'status':v['status'],'hz':v['hz'],'age_s':v['age_s']} for k,v in h['sensors'].items()}}}

def stop():
    state=load()
    # Shutdown uses the backend's own stop path, then signals only owned groups.
    try:
        token=(RUNTIME/'service.token').read_text().strip()
        request=urllib.request.Request('http://127.0.0.1:8765/api/control/stop',b'',headers={'Authorization':'Bearer '+token},method='POST')
        urllib.request.urlopen(request,timeout=2).read()
    except Exception:pass
    for name in ('dashboard','bringup'):
        record=state.get(name)
        if alive(record):
            (os.killpg if os.getpgid(record['pid'])==record['pid'] else os.kill)(record['pid'],signal.SIGINT)
            for _ in range(30):
                if not alive(record):break
                time.sleep(.1)
            if alive(record):(os.killpg if os.getpgid(record['pid'])==record['pid'] else os.kill)(record['pid'],signal.SIGTERM)
    save({});return status()

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['start','ensure','status','stop']);p.add_argument('--allow-motion',action='store_true');p.add_argument('--bypass-obstacles',action='store_true');a=p.parse_args()
    lock=(RUNTIME/'services.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX)
    try:
        result=stop() if a.action=='stop' else status() if a.action=='status' else ensure(a.action=='start',a.allow_motion,a.bypass_obstacles)
        print(json.dumps(result,indent=2))
    except Exception as exc:print(json.dumps({'error':str(exc)}));raise SystemExit(1)
if __name__=='__main__':main()
