"""Check dashboard/SSH stability; optional local-forward recovery test, no motion."""
import argparse,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.missionctl import config,health,ssh,CONTROL,supervisor_pid

def verify(seconds=45,exercise_forward=False):
    c=config();before=ssh(c,['python3','scripts/pi_runtime.py','status']);h=health()
    if not h:raise RuntimeError('Dashboard is unavailable before test')
    if exercise_forward and h['control']['armed']:raise RuntimeError('Disarm before deliberately interrupting the local forward')
    report={'supervisor_pid':supervisor_pid(),'forward_recovery_s':None,'samples':[]}
    if exercise_forward:
        started=time.monotonic()
        subprocess.run(['ssh','-S',str(CONTROL),'-O','cancel','-L','127.0.0.1:8872:127.0.0.1:8765',c['target']],capture_output=True,check=True,timeout=6)
        while time.monotonic()-started<30:
            h=health()
            if h and h['sensors']['camera']['status']=='live':break
            time.sleep(.5)
        else:raise RuntimeError('Local-forward recovery failed')
        report['forward_recovery_s']=time.monotonic()-started
        print('Local forward restored in %.2f seconds'%report['forward_recovery_s'],flush=True)
    start=time.monotonic()
    while time.monotonic()-start<seconds:
        h=health();sample={'elapsed_s':time.monotonic()-start,'connected':bool(h)}
        if h:sample.update(camera_live=h['sensors']['camera']['status']=='live',scan_live=h['sensors']['scan']['status']=='live',camera_hz=h['sensors']['camera']['hz'],armed=h['control']['armed'])
        report['samples'].append(sample);time.sleep(1)
    after=ssh(c,['python3','scripts/pi_runtime.py','status'])
    report.update(sample_seconds=time.monotonic()-start,backend_unchanged=before['owned_processes'].get('dashboard')==after['owned_processes'].get('dashboard'),hardware_drivers_unchanged=before['drivers']==after['drivers'],bringup_owner_unchanged=before['owned_processes'].get('bringup')==after['owned_processes'].get('bringup'),all_samples_connected=all(x['connected'] for x in report['samples']),all_samples_camera_and_scan_live=all(x.get('camera_live') and x.get('scan_live') for x in report['samples']),final_control=health()['control'])
    folder=ROOT/'diagnostics/connection';folder.mkdir(exist_ok=True);(folder/'stability.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ['samples','final_control']},indent=2))
    if not all(report[k] for k in ['backend_unchanged','hardware_drivers_unchanged','all_samples_connected','all_samples_camera_and_scan_live']):raise RuntimeError('Stability check failed; inspect local report')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--seconds',type=float,default=45);p.add_argument('--exercise-forward',action='store_true');a=p.parse_args();verify(a.seconds,a.exercise_forward)
