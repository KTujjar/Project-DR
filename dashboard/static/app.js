'use strict';
const $ = id => document.getElementById(id);
const state = {socket:null, connected:false, lastMessage:0, mode:null, telemetry:null, paused:false, scan:null, held:new Set(), captures:[], selected:null, reconnect:null, cameraRequest:0, cameraBusy:false};
const fmt = (value, digits=2) => Number.isFinite(value) ? value.toFixed(digits) : '—';
const escapeHTML = value => { const node=document.createElement('span'); node.textContent=String(value); return node.innerHTML; };
let toastTimer;
function toast(message,error=false){$('toast').textContent=message;$('toast').classList.remove('hidden');$('toast').classList.toggle('error',error);clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.add('hidden'),5500);}
function send(action, values={}){if(state.socket?.readyState===WebSocket.OPEN) state.socket.send(JSON.stringify({action,...values}));}
function releaseDirections(disarm=false){state.held.clear();document.querySelectorAll('.direction').forEach(button=>button.classList.remove('pressed'));send('release');if(disarm)send('disarm');}
function canDrive(){const control=state.telemetry?.control;return state.connected&&control?.enabled&&control.armed&&control.is_owner;}
function drive(){if(!canDrive())return;const linear=(state.held.has('forward')?1:0)-(state.held.has('backward')?1:0);const angular=(state.held.has('left')?1:0)-(state.held.has('right')?1:0);send('drive',{linear:linear*Number($('linearLimit').value),angular:angular*Number($('angularLimit').value)});}
function scheduleReconnect(){if(!state.reconnect)state.reconnect=setTimeout(()=>{state.reconnect=null;connect();},1300);}
function connect(){
 const socket=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws`);state.socket=socket;
 socket.onmessage=event=>{let message;try{message=JSON.parse(event.data);}catch{return;}if(message.type==='notice'){toast(message.message,true);return;}if(message.type!=='telemetry')return;state.connected=true;state.lastMessage=Date.now();state.telemetry=message;state.mode=message.mode;if(!state.paused)state.scan=message.sensors.scan;render();};
 socket.onclose=()=>{if(state.socket!==socket)return;state.connected=false;releaseDirections();render();scheduleReconnect();};
 socket.onerror=()=>{state.connected=false;render();};
}
function reading(name){return state.telemetry?.sensors[name]||{status:'missing',data:null,hz:null,age_s:null};}
function chip(id,text,kind=''){const node=$(id);node.textContent=text;node.className=`status-chip ${kind}`;}
function render(){
 $('connectionStatus').innerHTML=`<i></i>${state.connected?'Connected':'Disconnected'}`;
 $('connectionStatus').classList.toggle('offline',!state.connected);
 $('offlineBanner').classList.toggle('hidden',state.connected);
 const data=state.telemetry;if(!data)return;
 const mock=data.mode==='mock';
 $('robotName').textContent=mock?'DEVELOPMENT':data.metadata.robot?.toUpperCase()||'TURTLE19';
 $('connectionStatus').innerHTML=`<i></i>${state.connected?'Connected':'Disconnected'}`;
 $('connectionStatus').classList.toggle('offline',!state.connected);
 $('modeBadge').textContent=mock?'MOCK / DEVELOPMENT':'HARDWARE / ROS 2';$('modeBadge').classList.toggle('mock',mock);
 $('mockBanner').classList.toggle('hidden',!mock);$('offlineBanner').classList.toggle('hidden',state.connected);
 const battery=reading('battery'),odom=reading('odom'),scan=reading('scan'),camera=reading('camera');
 $('batteryValue').textContent=fmt(battery.data?.voltage);$('batteryPercent').textContent=battery.data?.percentage!=null?`${fmt(battery.data.percentage,0)}% ${mock?'simulated':'reported charge'}`:'Voltage from /battery_state';
 $('batteryState').textContent=state.connected?(mock?'MOCK':battery.status.toUpperCase()):'STALE';
 $('speedValue').textContent=fmt(odom.data?.linear);$('angularValue').textContent=`Angular ${fmt(odom.data?.angular)} rad/s`;
 $('poseValue').textContent=`${fmt(odom.data?.x)}, ${fmt(odom.data?.y)}`;$('headingValue').textContent=`Heading ${fmt(odom.data?.yaw*180/Math.PI,1)}°`;
 const valid=(scan.data?.ranges||[]).filter(value=>Number.isFinite(value)&&value>0&&value>=scan.data.range_min&&value<=scan.data.range_max);
 $('nearestValue').textContent=valid.length?fmt(Math.min(...valid)):'—';$('validReturns').textContent=`${valid.length} valid ${mock?'simulated ':''}returns`;
 const lidarLive=state.connected&&scan.status==='live'&&valid.length>0;
 chip('lidarStatus',!state.connected?'Disconnected':scan.status==='missing'?'No data':scan.status==='stale'?'Stale':!valid.length?'Invalid scan':mock?'Simulated':'Live scan',lidarLive?'live':'stale');
 $('lidarSource').textContent=mock?'SIMULATED POINT CLOUD':lidarLive?'LIVE /scan · LDS-01':scan.status==='missing'?'WAITING FOR /scan':'LAST RECEIVED /scan';
 $('scanRate').textContent=`${fmt(scan.hz,1)} Hz`;$('scanFrame').textContent=scan.data?.frame_id||'base_scan';
 $('scanEmpty').classList.toggle('hidden',valid.length>0);$('scanEmpty').textContent=scan.status==='missing'?'Waiting for /scan messages':'No valid distances in this scan';
 $('viewState').textContent=state.paused?'VIEW PAUSED · SENSORS CONTINUE':!state.connected||scan.status==='stale'?'STALE DATA · NOT A LIVE VIEW':'RAW SCAN · NO PERSISTENT MAP';
 const cameraReady=state.connected&&camera.status==='live'&&(mock||camera.data?.verified)&&(typeof videoState==='undefined'||(videoState.lastFrame&&Date.now()-videoState.lastFrame<2200));
 $('cameraImage').classList.toggle('hidden',!cameraReady);$('cameraUnavailable').classList.toggle('hidden',cameraReady);
 $('cameraImage').alt=mock?'Illustrated mock camera placeholder, not a real camera image':'Live image from the robot camera';
 chip('cameraStatus',mock?'Placeholder':cameraReady?'Live camera':camera.status==='stale'?'Stale image':'Needs attention',cameraReady&&!mock?'live':'warning');
 $('cameraSource').textContent=mock?'SIMULATED PLACEHOLDER':cameraReady?(camera.data?.path==='isp'?'VERIFIED IMX219 · HARDWARE ISP':'VERIFIED IMX219 · MAC PIPELINE'):'NO VERIFIED FEED';
 $('cameraReason').textContent=camera.status==='stale'?'Camera stream is stale. The supervisor is attempting recovery; inspect camera-relay.log if it persists.':data.metadata.camera_note||'No verified image stream is available.';
 $('cameraNote').lastChild.textContent=mock?' Illustration only. No hardware camera has been verified.':` ${data.metadata.camera_note||'Camera acquisition is unverified.'}`;
 if(!mock&&camera.data?.quality?.warning){$('cameraNote').lastChild.textContent+=` · ${camera.data.quality.warning}`;chip('cameraStatus','Check exposure','warning');}
 $('cameraResolution').textContent=cameraReady?`${camera.data.width} × ${camera.data.height}`:'— × —';
 $('cameraRate').textContent=mock?'Illustration · no video FPS':cameraReady?`${fmt(camera.hz,1)} fps ingest · ${fmt(camera.data?.pipeline_latency_ms,0)} ms pipeline`:'Not streaming';
 $('cameraCapture').disabled=!cameraReady;$('cameraCapture').lastChild.textContent=mock?'Save mock frame':'Capture frame';
 const control=data.control,owned=control.armed&&control.is_owner;
 const locked=!state.connected||!control.enabled||(control.armed&&!control.is_owner);
 $('armButton').disabled=locked;$('armButton').classList.toggle('armed',owned);$('armButton').lastChild.textContent=owned?'Disarm controls':!control.enabled?'Movement locked':control.armed?'In use by another browser':'Arm controls';
 chip('armStatus',owned?'Armed':!control.enabled?'Locked':'Disarmed',owned?'live':'');
 $('controlReason').textContent=control.reason;$('armButton').title=control.reason;
 document.querySelectorAll('.direction').forEach(button=>button.disabled=!canDrive());
 if(!owned&&state.held.size)releaseDirections();
 const joints=reading('joints').data;
 $('wheelInfo').textContent=joints?.velocities?.length?`Wheel rates ${joints.velocities.map(x=>fmt(x,2)).join(' / ')} rad/s`:'Wheel feedback pending';
 $('aiMode').textContent=mock?'MOCK ADAPTER':'NOT CONFIGURED';$('interpretButton').lastChild.textContent=mock?'Demo interpretation':'Interpret capture';
 $('footerProvenance').textContent=mock?'All sensor values are simulated. Movement is disabled.':'Hardware data only. Camera verification remains explicit.';
 const guard=control.obstacle_guard;
 $('guardStatus').textContent=mock?'Obstacle guard · hardware only':`Obstacle guard · ${guard?.status||'unavailable'} · unvalidated`;
 $('guardDetail').textContent=mock?'Simulated view. No hardware commands.':guard?.bypassed?'Manual override active: LiDAR obstacles, missing scans and coverage gaps will NOT stop movement. Release, Stop and the command watchdog remain active.':guard?.directions?Object.entries(guard.directions).map(([direction,reason])=>`${direction}: ${reason||'clear in scan plane'}`).join(' · '):'Awaiting hardware guard diagnostics.';
 $('guardStatus').classList.toggle('guard-bypassed',!!guard?.bypassed);
 $('lidarDetail').textContent=scan.data?`2D · ${scan.data.ranges.length} angular samples · ${fmt(Math.abs(scan.data.angle_increment)*180/Math.PI,1)}° spacing · ${fmt(scan.hz,1)} measured scans/s`:'2D · waiting for sample geometry';
 if(typeof updateMissionTelemetry==='function')updateMissionTelemetry();
 renderDiagnostics();drawLidar();
}
function renderDiagnostics(){
 const names={scan:'LiDAR /scan',odom:'Odometry /odom',imu:'IMU /imu',battery:'Battery',camera:'Camera',joints:'Wheel joints'};
 $('diagnosticRows').innerHTML=Object.entries(names).map(([name,label])=>{const sensor=reading(name);return `<tr><td>${label}</td><td>${state.connected?escapeHTML(sensor.status):'disconnected'}</td><td>${fmt(sensor.hz,1)} Hz</td><td>${fmt(sensor.age_s,2)} s</td></tr>`;}).join('');
 const metadata=state.telemetry?.metadata||{};
 $('systemDiagnostics').innerHTML=`<strong>Source</strong> ${escapeHTML(state.mode||'unknown')}<br><strong>Drivers</strong> ${escapeHTML(metadata.driver_status||'Waiting')}<br><strong>ROS domain</strong> ${escapeHTML(metadata.ros_domain_id??'Not applicable')}<br><strong>Other motor publishers</strong> ${escapeHTML(metadata.cmd_vel_other_publishers??'Not connected')}<br><strong>Camera</strong> ${escapeHTML(metadata.camera_note||'Unverified')}<br><strong>Errors</strong> ${escapeHTML((metadata.errors||[]).join('; ')||'None reported')}`;
}
function drawLidar(){
 const canvas=$('lidarCanvas'),rect=canvas.getBoundingClientRect();if(!rect.width||!rect.height)return;
 const ratio=window.devicePixelRatio||1;if(canvas.width!==Math.round(rect.width*ratio)||canvas.height!==Math.round(rect.height*ratio)){canvas.width=Math.round(rect.width*ratio);canvas.height=Math.round(rect.height*ratio);}
 if(typeof mapState!=='undefined'&&mapState.active&&mapState.grid){drawMap();return;}
 const ctx=canvas.getContext('2d');ctx.setTransform(ratio,0,0,ratio,0,0);
 const width=rect.width,height=rect.height,cx=width/2,cy=height/2+3,radius=Number($('zoom').value),scale=(Math.min(width,height)-65)/(radius*2);
 ctx.clearRect(0,0,width,height);ctx.fillStyle='#102a24';ctx.fillRect(0,0,width,height);
 const glow=ctx.createRadialGradient(cx,cy,0,cx,cy,Math.max(width,height)/2);glow.addColorStop(0,'#1a3c30');glow.addColorStop(1,'#102a24');ctx.fillStyle=glow;ctx.fillRect(0,0,width,height);
 ctx.lineWidth=.7;ctx.strokeStyle='#385948';ctx.setLineDash([2,5]);ctx.beginPath();ctx.moveTo(cx,38);ctx.lineTo(cx,height-32);ctx.moveTo(20,cy);ctx.lineTo(width-20,cy);ctx.stroke();ctx.setLineDash([]);
 for(let distance=1;distance<=radius;distance++){ctx.strokeStyle=distance===Math.floor(radius)?'#42604c':'#35513f';ctx.beginPath();ctx.arc(cx,cy,distance*scale,0,Math.PI*2);ctx.stroke();ctx.fillStyle='#7a9b79';ctx.font='7px ui-monospace,monospace';ctx.fillText(`${distance} m`,cx+distance*scale+4,cy-5);}
 const scan=state.scan?.data;const fresh=state.connected&&state.scan?.status==='live';
 if(scan){ctx.globalAlpha=fresh?1:.3;ctx.fillStyle='#c3eba4';ctx.shadowColor='#a1de88';ctx.shadowBlur=4;for(let i=0;i<scan.ranges.length;i++){const d=scan.ranges[i];if(!Number.isFinite(d)||d<=0||d<scan.range_min||d>scan.range_max||d>radius*1.5)continue;const angle=scan.angle_min+i*scan.angle_increment;ctx.fillStyle=d<=.36?'#ff8b79':'#c3eba4';const x=cx-Math.sin(angle)*d*scale,y=cy-Math.cos(angle)*d*scale;if(x<10||x>width-10||y<40||y>height-25)continue;ctx.beginPath();ctx.arc(x,y,1.55,0,Math.PI*2);ctx.fill();}ctx.shadowBlur=0;ctx.globalAlpha=1;}
 ctx.fillStyle='#123a2b';ctx.strokeStyle='#a0c88e';ctx.lineWidth=1;ctx.beginPath();ctx.arc(cx,cy,16,0,Math.PI*2);ctx.fill();ctx.stroke();ctx.fillStyle='#d1edb7';ctx.beginPath();ctx.moveTo(cx,cy-20);ctx.lineTo(cx-5,cy-12);ctx.lineTo(cx+5,cy-12);ctx.closePath();ctx.fill();ctx.fillStyle='#a8cf8f';ctx.fillRect(cx-5,cy-7,10,13);ctx.fillStyle='#7da268';ctx.fillRect(cx-10,cy-5,3,10);ctx.fillRect(cx+7,cy-5,3,10);
}
function downloadJSON(value,name){const link=document.createElement('a'),url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function request(path){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'}});if(!response.ok)throw new Error(`Request failed (${response.status})`);return response.json();}
async function capture(){
 $('snapshotButton').disabled=true;
 try{const snapshot=await request('/api/snapshots');state.captures.unshift(snapshot);state.captures=state.captures.slice(0,20);selectCapture(snapshot.id);toast(snapshot.mode==='mock'?'Simulated sensor capture saved.':snapshot.synchronized?'Approximately aligned hardware capture saved.':'Partial hardware capture saved; missing or stale sensors are recorded.');}
 catch(error){toast(error.message,true);}finally{$('snapshotButton').disabled=false;}
}
function selectCapture(id){state.selected=state.captures.find(item=>item.id===id);renderCaptures();$('interpretButton').disabled=!state.selected;$('downloadSnapshot').disabled=!state.selected;$('aiTitle').textContent=state.selected?.ai?.title||'Capture ready for review.';$('aiText').textContent=state.selected?.synchronized?'Camera, LiDAR and odometry were matched by their recorded timestamps. This is approximate synchronization.':'This is a partial capture. Check missing or stale sensors before interpreting it.';}
function renderCaptures(){
 $('captureList').innerHTML=state.captures.map((item,index)=>`<button class="capture-item ${item===state.selected?'selected':''}" data-capture="${item.id}"><strong><span>Capture ${String(state.captures.length-index).padStart(2,'0')}</span><em>${item.mode==='mock'?'SIMULATED':'HARDWARE'}</em></strong><small>${new Date(item.captured_at_utc).toLocaleTimeString()} · ${item.synchronized?'APPROX. ALIGNED':'PARTIAL CAPTURE'}</small></button>`).join('');
 $('captureList').querySelectorAll('button').forEach(button=>button.addEventListener('click',()=>selectCapture(button.dataset.capture)));
}
$('snapshotButton').addEventListener('click',capture);$('cameraCapture').addEventListener('click',capture);
$('interpretButton').addEventListener('click',async()=>{if(!state.selected)return;const selected=state.selected;$('interpretButton').disabled=true;try{const result=await request(`/api/snapshots/${selected.id}/interpret`);selected.ai=result;if(state.selected===selected){$('aiTitle').textContent=result.title;$('aiText').textContent=result.text;}}catch(error){toast(error.message,true);}finally{$('interpretButton').disabled=false;}});
$('downloadSnapshot').addEventListener('click',()=>{if(state.selected)downloadJSON(state.selected,`turtle-capture-${state.selected.id}.json`);});
$('exportScan').addEventListener('click',()=>{if(!state.scan?.data)return toast('No scan has been received yet.',true);downloadJSON({mode:state.mode,source:state.scan},`turtle-${state.mode}-scan.json`);});
$('zoom').addEventListener('input',()=>{$('zoomValue').textContent=`${Number($('zoom').value).toFixed(1)} m`;drawLidar();});
function expandLidar(expanded){$('lidar-panel').classList.toggle('expanded-lidar',expanded);document.body.classList.toggle('lidar-expanded',expanded);$('expandLidar').textContent=expanded?'Exit expanded view':'Expand view';drawLidar();}
$('expandLidar').addEventListener('click',()=>expandLidar(!$('lidar-panel').classList.contains('expanded-lidar')));
window.addEventListener('keydown',event=>{if(event.key==='Escape')expandLidar(false);});
$('fitScan').addEventListener('click',()=>{const scan=state.scan?.data;if(!scan)return;const distances=scan.ranges.filter(x=>Number.isFinite(x)&&x>0&&x<=scan.range_max);if(!distances.length)return;$('zoom').value=Math.min(6,Math.max(1,Math.ceil(Math.max(...distances)*2)/2));$('zoom').dispatchEvent(new Event('input'));});
$('pauseScan').addEventListener('click',()=>{state.paused=!state.paused;$('pauseScan').textContent=state.paused?'Resume view':'Pause view';if(!state.paused)state.scan=reading('scan');render();});
for(const [input,output,unit] of [['linearLimit','linearLimitValue','m/s'],['angularLimit','angularLimitValue','rad/s']])$(input).addEventListener('input',()=>{$(output).textContent=`${Number($(input).value).toFixed(2)} ${unit}`;});
$('armButton').addEventListener('click',()=>{if(state.telemetry?.control?.is_owner){releaseDirections(true);}else send('arm');});
$('stopButton').addEventListener('click',()=>{releaseDirections();send('stop');toast('Dashboard stop requested.');});
document.querySelectorAll('.direction').forEach(button=>{button.addEventListener('pointerdown',event=>{if(!canDrive())return;event.preventDefault();button.setPointerCapture(event.pointerId);state.held.add(button.dataset.drive);button.classList.add('pressed');drive();});for(const eventName of ['pointerup','pointercancel','lostpointercapture'])button.addEventListener(eventName,()=>{state.held.delete(button.dataset.drive);button.classList.remove('pressed');if(state.held.size)drive();else send('release');});});
const keyDirections={w:'forward',ArrowUp:'forward',a:'left',ArrowLeft:'left',s:'backward',ArrowDown:'backward',d:'right',ArrowRight:'right'};
window.addEventListener('keydown',event=>{if(event.target.matches('input,textarea')||$('helpDialog').open)return;if(event.code==='Space'){event.preventDefault();releaseDirections();send('stop');return;}const direction=keyDirections[event.key]||keyDirections[event.key.toLowerCase()];if(!direction||!canDrive())return;event.preventDefault();if(event.repeat)return;state.held.add(direction);document.querySelector(`[data-drive="${direction}"]`).classList.add('pressed');drive();});
window.addEventListener('keyup',event=>{const direction=keyDirections[event.key]||keyDirections[event.key.toLowerCase()];if(!direction)return;state.held.delete(direction);document.querySelector(`[data-drive="${direction}"]`).classList.remove('pressed');if(state.held.size)drive();else send('release');});
window.addEventListener('blur',()=>releaseDirections(true));window.addEventListener('pagehide',()=>releaseDirections(true));document.addEventListener('visibilitychange',()=>{if(document.hidden)releaseDirections(true);});
function diagnostics(show=true){$('diagnostics-panel').classList.toggle('hidden',!show);if(show)$('diagnostics-panel').scrollIntoView({behavior:'smooth',block:'center'});}
$('diagnosticsButton').addEventListener('click',()=>diagnostics($('diagnostics-panel').classList.contains('hidden')));$('closeDiagnostics').addEventListener('click',()=>diagnostics(false));
document.querySelectorAll('[data-scroll]').forEach(button=>button.addEventListener('click',()=>{document.querySelectorAll('.nav').forEach(node=>node.classList.remove('active'));button.classList.add('active');$(button.dataset.scroll).scrollIntoView({behavior:'smooth',block:'start'});}));
$('helpButton').addEventListener('click',()=>$('helpDialog').showModal());$('closeHelp').addEventListener('click',()=>$('helpDialog').close());
$('cameraImage').addEventListener('load',()=>state.cameraBusy=false);$('cameraImage').addEventListener('error',()=>{state.cameraBusy=false;$('cameraImage').classList.add('hidden');$('cameraUnavailable').classList.remove('hidden');});
new ResizeObserver(drawLidar).observe($('lidarCanvas'));
setInterval(()=>{send('heartbeat');if(state.held.size)drive();},100);
setInterval(()=>{$('clock').textContent=new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit',second:'2-digit'});if(state.connected&&Date.now()-state.lastMessage>2500){releaseDirections(true);state.connected=false;state.socket?.close();render();scheduleReconnect();}},1000);
drawLidar();connect();
