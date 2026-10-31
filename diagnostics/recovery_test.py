"""Non-motion fault injection. Refuses to run while motion is enabled."""
import argparse,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.missionctl import health,ssh,config
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('component',choices=['backend','camera']);a=p.parse_args();c=config();before=health()
if not before or before['motion_enabled'] or before['control']['armed']:raise SystemExit('Refusing fault test: server must be online with motion disabled')
status=ssh(c,['python3','scripts/pi_runtime.py','status']);driver_pids=status['drivers']
if a.component=='backend':pid=status['owned_processes']['dashboard']['pid'];expected='uvicorn dashboard.backend.app:app';sig=9
else:pid=before['sensors']['camera']['data']['pid'];expected='/camera/isp_worker';sig=15
script=f'''import os,signal,json
from pathlib import Path
pid={int(pid)}
cmd=Path(f'/proc/{{pid}}/cmdline').read_bytes().replace(b'\\0',b' ').decode()
assert {expected!r} in cmd, 'Process identity changed'
os.kill(pid,{sig});print(json.dumps({{'signalled_pid':pid}}))'''
start=time.monotonic();ssh(c,['python3','-c',script]);observed_outage=False
while time.monotonic()-start<40:
    h=health()
    if not h or h['sensors']['camera']['status']!='live':observed_outage=True
    if h and h['sensors']['camera']['status']=='live' and h['sensors']['scan']['status']=='live':
        if a.component=='camera':changed=h['sensors']['camera']['data']['pid']!=pid
        else:
            now=ssh(c,['python3','scripts/pi_runtime.py','status']);changed=now['owned_processes']['dashboard']['pid']!=pid
        if changed:break
    time.sleep(.3)
else:raise SystemExit('Recovery timed out; inspect supervisor/camera logs')
after=ssh(c,['python3','scripts/pi_runtime.py','status'])
assert after['drivers']==driver_pids,'Hardware driver identity changed unexpectedly'
assert not h['control']['armed'] and not h['motion_enabled']
result={'component':a.component,'recovery_seconds':time.monotonic()-start,'outage_observed':observed_outage,'hardware_drivers_unchanged':True,'driver_pids':driver_pids,'motion_enabled':h['motion_enabled'],'armed_after_recovery':h['control']['armed'],'camera_live':h['sensors']['camera']['status']=='live','scan_live':h['sensors']['scan']['status']=='live','test_scope':'Owned software process failure; no cable pull, camera unplug or physical motor test.'}
(ROOT/f'diagnostics/mission/recovery-{a.component}.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
