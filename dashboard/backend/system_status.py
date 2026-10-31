"""Read-only Pi host telemetry; no process or network configuration changes."""
import json,os,subprocess,time
from pathlib import Path
_previous=None
_network=None
_network_time=0

def read():
    global _previous,_network,_network_time
    result={'load_1m':os.getloadavg()[0]}
    try:
        values=[int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:]];total=sum(values);idle=values[3]+values[4]
        if _previous and total>_previous[0]:result['cpu_percent']=100*(1-(idle-_previous[1])/(total-_previous[0]))
        _previous=(total,idle)
        memory={line.split(':')[0]:int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()}
        result.update(ram_total_mb=memory['MemTotal']/1024,ram_used_mb=(memory['MemTotal']-memory['MemAvailable'])/1024)
        temp=Path('/sys/class/thermal/thermal_zone0/temp')
        if temp.exists():result['temperature_c']=int(temp.read_text())/1000
        if _network is None or time.monotonic()-_network_time>10:
            interfaces=json.loads(subprocess.check_output(['ip','-j','addr'],timeout=1))
            _network=[{'name':i['ifname'],'state':i['operstate'],'addresses':[a['local'] for a in i.get('addr_info',[]) if a['family']=='inet']} for i in interfaces if i['ifname']!='lo']
            _network_time=time.monotonic()
        result['interfaces']=_network
    except (OSError,ValueError,KeyError,subprocess.SubprocessError):pass
    return result
