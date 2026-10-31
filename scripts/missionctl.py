#!/usr/bin/env python3
"""One-command mission launch/restart/status. Uses the existing private SSH path."""
import argparse,json,os,secrets,signal,subprocess,sys,tarfile,time,urllib.request,webbrowser,fcntl,shlex
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/'.robot/runtime';CONTROL=ROOT/'.robot/control'
URL='http://127.0.0.1:8872'

def defaults():
    if os.environ.get('TURTBOT_TARGET'):return os.environ['TURTBOT_TARGET']
    try:
        c=json.loads((ROOT/'.robot/connection.json').read_text());return c['username']+'@'+c['host']
    except FileNotFoundError:
        # Mock development must work without copying a robot's private state.
        return 'turtle@turtlebot3.local'
def config():
    try:return json.loads((RUNTIME/'config.json').read_text())
    except (OSError,ValueError):return {'target':os.environ.get('TURTBOT_TARGET',defaults()),'mock':False,'allow_motion':False}
def base(c,batch=True):
    identity=ROOT/'.robot/id_ed25519'
    return ['ssh','-S',str(CONTROL),'-o','UserKnownHostsFile='+str(ROOT/'.robot/known_hosts'),'-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=5','-o','ServerAliveInterval=5','-o','ServerAliveCountMax=3']+(['-i',str(identity),'-o','IdentitiesOnly=yes'] if identity.exists() else [])+(['-o','BatchMode=yes'] if batch else [])+[c['target']]
def ssh(c,args,timeout=20):
    import shlex
    command='cd "$HOME/turtbot-dashboard" && '+shlex.join(args)
    result=subprocess.run(base(c)+[command],capture_output=True,text=True,timeout=timeout)
    if result.returncode:raise RuntimeError((result.stdout+result.stderr).strip()[-800:])
    return json.loads(result.stdout) if result.stdout.strip().startswith('{') else result.stdout

def health():
    try:
        with urllib.request.urlopen(URL+'/api/health',timeout=2) as r:return json.load(r)
    except Exception:return None

def terminate(proc):
    if proc.poll() is None:
        os.killpg(proc.pid,signal.SIGTERM)
        try:proc.wait(timeout=4)
        except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()

def supervisor_pid():
    try:
        pid=int((RUNTIME/'supervisor.pid').read_text());cmd=subprocess.check_output(['ps','-p',str(pid),'-o','command='],text=True)
        return pid if supervisor_command(cmd) else None
    except (OSError,ValueError,subprocess.CalledProcessError):return None

def supervisor_command(cmd):
    # macOS commonly reaches the same case-insensitive directory through both
    # Documents/Turtbot and documents/turtbot. Compare filesystem identities.
    for arg in shlex.split(cmd):
        if not arg.endswith('/scripts/supervisor.py'):continue
        try:
            if Path(arg).samefile(ROOT/'scripts/supervisor.py'):return True
        except OSError:pass
    return False

def ensure_transport(c,batch=True):
    check=subprocess.run(['ssh','-S',str(CONTROL),'-O','check',c['target']],capture_output=True,timeout=6)
    if check.returncode:
        command=base(c,batch)[:-1]+['-M','-fN','-o','ControlPath='+str(CONTROL),'-o','ControlPersist=12h',c['target']]
        result=subprocess.run(command,capture_output=batch,text=True,timeout=12 if batch else None,stdin=subprocess.DEVNULL if batch else None)
        if result.returncode:raise RuntimeError('SSH authentication or link unavailable; run ./scripts/restart.sh in a terminal to log in again. '+((result.stderr or '')[-200:]))
    # A master can survive with its local forward missing after another launcher
    # canceled it. Repair only this loopback forward, never replace another app.
    if health() is None:
        result=subprocess.run(['ssh','-S',str(CONTROL),'-O','forward','-L','127.0.0.1:8872:127.0.0.1:8765',c['target']],capture_output=True,text=True,timeout=6)
        if result.returncode:
            listeners=subprocess.run(['lsof','-nP','-iTCP:8872','-sTCP:LISTEN'],capture_output=True,text=True).stdout
            if 'Address already in use' not in result.stderr or 'ssh' not in listeners:raise RuntimeError('Could not restore dashboard tunnel: '+result.stderr.strip())

def stop(c,keep_hardware=False):
    pid=supervisor_pid()
    if pid:
        os.killpg(pid,signal.SIGTERM)
        for _ in range(50):
            if not supervisor_pid():break
            time.sleep(.1)
    if not c['mock']:
        try:print(json.dumps(ssh(c,['python3','scripts/pi_runtime.py','stop']+(['--backend-only'] if keep_hardware else [])),indent=2))
        except Exception as exc:print('Pi unreachable. Browser/ROS watchdog remains responsible for stopping:',exc)
    if not c['mock']:
        subprocess.run(['ssh','-S',str(CONTROL),'-O','cancel','-L','127.0.0.1:8872:127.0.0.1:8765',c['target']],capture_output=True)
    try:(RUNTIME/'supervisor.pid').unlink()
    except FileNotFoundError:pass

def start(c,no_browser=False):
    if supervisor_pid():print('Mission supervisor already running:',URL);return
    RUNTIME.mkdir(parents=True,exist_ok=True,mode=0o700)
    token=RUNTIME/'service.token'
    if not token.exists():token.write_text(secrets.token_urlsafe(32));token.chmod(0o600)
    if not c['mock']:
        ensure_transport(c,batch=False)
        archive=RUNTIME/'deploy.tar.gz'
        with tarfile.open(archive,'w:gz') as tar:
            for folder in ('dashboard','scripts','camera','models'):
                for path in (ROOT/folder).rglob('*'):
                    if path.is_file() and not any(part in ('__pycache__','captures','data') for part in path.relative_to(ROOT).parts) and path.suffix not in ('.png','.jpg','.raw') and path.name!='capture_worker':tar.add(path,arcname=str(path.relative_to(ROOT)),recursive=False)
            for name in ('README.md','OPERATOR.md','ARCHITECTURE.md','PERFORMANCE.md','MISSION_CHANGES.md'):
                if (ROOT/name).exists():tar.add(ROOT/name,arcname=name,recursive=False)
            tar.add(token,arcname='.runtime/service.token')
        with archive.open('rb') as f:
            subprocess.run(base(c)+['umask 077; mkdir -p "$HOME/turtbot-dashboard/.runtime"; cd "$HOME/turtbot-dashboard" && tar --warning=no-timestamp -xzf - && test -f /opt/ros/humble/setup.bash && test -x .venv/bin/python && cc -O2 camera/capture_worker.c -o camera/capture_worker.new && mv camera/capture_worker.new camera/capture_worker && cc -O2 camera/isp_worker.c -lm -o camera/isp_worker.new && mv camera/isp_worker.new camera/isp_worker'],stdin=f,check=True,timeout=40)
        # Reuse an already-working tunnel; never replace an unrelated local server.
        h=health()
        if h is None:
            forward=subprocess.run(['ssh','-S',str(CONTROL),'-O','forward','-L','127.0.0.1:8872:127.0.0.1:8765',c['target']],capture_output=True,text=True)
            if forward.returncode:
                listeners=subprocess.run(['lsof','-nP','-iTCP:8872','-sTCP:LISTEN'],capture_output=True,text=True).stdout
                if 'Address already in use' not in forward.stderr or 'ssh' not in listeners:raise RuntimeError('Port 8872 is occupied; refusing to attach an unrelated service. '+forward.stderr)
        elif h.get('mode')!='hardware':raise RuntimeError('Port 8872 contains a mock or unrelated app; stop it before hardware startup')
        print('Verifying ROS bringup and starting the backend…',flush=True)
        print(json.dumps(ssh(c,['python3','scripts/pi_runtime.py','start']+(['--allow-motion'] if c['allow_motion'] else [])+(['--bypass-obstacles'] if c.get('bypass_obstacles') else [])),indent=2))
        print('Applying the approved native camera mode…',flush=True)
        print(ssh(c,['python3','camera/configure.py','--width',str(c.get('camera_width',640)),'--height',str(c.get('camera_height',480)),'--gain',str(c.get('camera_gain',0)),'--fps',str(c.get('camera_fps',15))]))
    (RUNTIME/'config.json').write_text(json.dumps(c,indent=2))
    log=(RUNTIME/'supervisor.log').open('ab',buffering=0)
    proc=subprocess.Popen([sys.executable,str(ROOT/'scripts/supervisor.py')],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    deadline=time.monotonic()+25
    while time.monotonic()<deadline:
        h=health()
        if h and (c['mock'] or h['sensors']['camera']['status']=='live'):break
        if proc.poll() is not None:raise RuntimeError('Supervisor exited; inspect .robot/runtime/supervisor.log')
        time.sleep(.5)
    h=health();print('Dashboard:',URL,'\nMotion:','enabled but disarmed' if h and h['motion_enabled'] else 'LOCKED')
    if not h or h['sensors']['camera']['status']!='live':print('Degraded: camera not yet live; status.sh reports freshness and camera-relay.log contains errors.')
    if not no_browser:webbrowser.open(URL)

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['start','status','stop','restart','diagnose']);p.add_argument('--mock',action='store_true');p.add_argument('--no-browser',action='store_true');p.add_argument('--allow-motion',action='store_true');p.add_argument('--wheels-elevated',action='store_true');p.add_argument('--bypass-obstacles',action='store_true',help='Explicit manual override: LiDAR will not veto motion');a=p.parse_args();c=config()
    RUNTIME.mkdir(parents=True,exist_ok=True,mode=0o700)
    lock=(RUNTIME/'launcher.lock').open('a')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:p.error('Another mission startup/shutdown command is in progress')
    if a.action=='start':
        if a.bypass_obstacles and (not a.allow_motion or a.mock):p.error('--bypass-obstacles requires --allow-motion in hardware mode')
        if a.allow_motion and not (a.wheels_elevated or a.bypass_obstacles):p.error('Use --wheels-elevated for guarded initial testing, or explicitly select --bypass-obstacles for manual override')
        c={'target':os.environ.get('TURTBOT_TARGET',c['target']),'mock':a.mock,'allow_motion':a.allow_motion,'camera_path':os.environ.get('TURTBOT_CAMERA_PATH','auto'),'camera_width':int(os.environ.get('TURTBOT_CAMERA_WIDTH',640)),'camera_height':int(os.environ.get('TURTBOT_CAMERA_HEIGHT',480)),'camera_gain':int(os.environ.get('TURTBOT_CAMERA_GAIN',0)),'camera_fps':int(os.environ.get('TURTBOT_CAMERA_FPS',15))}
        c['bypass_obstacles']=a.bypass_obstacles
    try:
        if a.action in ('stop','restart'):stop(c,keep_hardware=a.action=='restart')
        if a.action in ('start','restart'):start(c,a.no_browser)
        elif a.action in ('status','diagnose'):
            result={'supervisor_pid':supervisor_pid(),'dashboard_url':URL,'health':health()}
            if not c['mock']:
                try:result['pi']=ssh(c,['python3','scripts/pi_runtime.py','status'],timeout=8)
                except Exception as exc:result['pi_error']=str(exc)
            if result['health']:
                result['health']['sensors']={k:{'status':v['status'],'hz':v['hz'],'age_s':v['age_s']} for k,v in result['health']['sensors'].items()}
            print(json.dumps(result,indent=2))
    except (OSError,RuntimeError,subprocess.SubprocessError) as exc:print('Mission startup/recovery failed:',exc,file=sys.stderr);raise SystemExit(1)
if __name__=='__main__':main()
