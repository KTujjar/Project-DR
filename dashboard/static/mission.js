'use strict';
let missionRefresh=null,mapState={active:false,grid:null,saved:false},recording=null;
function expandCamera(expand){$('camera-panel').classList.toggle('expanded-camera',expand);document.body.classList.toggle('camera-expanded',expand);$('expandCamera').textContent=expand?'Exit expanded camera':'Expand camera';if(videoState.meta)detectionOverlay(videoState.meta);}
$('expandCamera').addEventListener('click',()=>expandCamera(!$('camera-panel').classList.contains('expanded-camera')));
window.addEventListener('keydown',event=>{if(event.key==='Escape')expandCamera(false);});
for(const id of ['quickStop','cameraStop','lidarStop'])$(id).addEventListener('click',()=>{releaseDirections();send('stop');toast('Dashboard motion stop requested.');});
async function refreshMission(){
 try{
  const result=await fetch('/api/mission/events').then(r=>r.json());
  $('eventList').innerHTML=result.events.length?result.events.slice(0,35).map(e=>`<article class="mission-event"><span class="event-kind">${escapeHTML(e.kind.toUpperCase())}</span><time>${escapeHTML(new Date(e.timestamp_utc).toLocaleTimeString())}</time><p>${escapeHTML(e.note)}</p>${e.context?.pose?.data?`<small>odom ${fmt(e.context.pose.data.x)}, ${fmt(e.context.pose.data.y)} m · ${escapeHTML(e.context.mode||'hardware')}</small>`:''}</article>`).join(''):'<p class="field-note">No mission observations yet. Save a note or sensor snapshot.</p>';
 }catch{/* Keep previous events while the connection recovers. */}
}
async function addObservation(kind){
 const note=$('missionNote').value.trim();if(!note){toast('Add an observation before saving.',true);return;}
 try{const r=await fetch('/api/mission/events',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,note})});if(!r.ok)throw Error('Observation was not saved');$('missionNote').value='';await refreshMission();toast(kind==='poi'?'Point of interest saved with sensor context.':'Observation saved.');}catch(error){toast(error.message,true);}
}
$('noteForm').addEventListener('submit',event=>{event.preventDefault();addObservation('annotation');});$('markPoi').addEventListener('click',()=>addObservation('poi'));
$('toggleMockDetector').addEventListener('click',async()=>{try{const value=await request('/api/v1/perception/mock');$('toggleMockDetector').textContent=value.enabled?'Disable mock detections':'Enable mock detections';$('toggleMockDetector').classList.toggle('mock-active',value.enabled);refreshMission();}catch(error){toast(error.message,true);}});
function updateMissionTelemetry(){
 const m=state.telemetry,s=m?.metadata.system||{},c=m?.control||{};
 $('systemCpu').textContent=`Pi CPU ${fmt(s.cpu_percent,0)}% · load ${fmt(s.load_1m,2)}`;
 $('systemRam').textContent=`RAM ${fmt(s.ram_used_mb,0)} / ${fmt(s.ram_total_mb,0)} MB`;
 $('systemTemp').textContent=`Temperature ${fmt(s.temperature_c,1)}°C`;
 $('systemNetwork').textContent=(s.interfaces||[]).map(i=>`${i.name}: ${i.state}${i.addresses.length?' '+i.addresses.join(','):''}`).join(' · ')||'Network awaiting telemetry';
 $('commandedVelocity').textContent=`Commanded ${fmt(c.linear)} m/s · ${fmt(c.angular)} rad/s`;
 const mockEnabled=(m?.models||[]).some(x=>x.model_id==='mock-demonstrator');$('toggleMockDetector').textContent=mockEnabled?'Disable mock detections':'Enable mock detections';$('toggleMockDetector').classList.toggle('mock-active',mockEnabled);
 $('modelStatus').textContent=(m?.models||[]).length?(m.models.map(x=>`${x.model_id}${x.mock?' [MOCK]':' [UNVALIDATED]'}`).join(' · ')):'Model API v1.0 · no live results';
 $('markPoi').disabled=reading('odom').status!=='live';
 if(mapState.active&&mapState.grid)drawMap();
}
const recordingCanvas=document.createElement('canvas');
function recordFrame(meta){
 if(!recording)return;recordingCanvas.width=meta.width;recordingCanvas.height=meta.height;
 const ctx=recordingCanvas.getContext('2d');ctx.drawImage($('cameraImage'),0,0,meta.width,meta.height);
 ctx.fillStyle='#07121cbb';ctx.fillRect(0,meta.height-24,meta.width,24);ctx.fillStyle='#e2ebf5';ctx.font='11px monospace';ctx.fillText(`${meta.mode.toUpperCase()} · ${meta.frame_id} · operator video`,8,meta.height-8);
}
$('recordVideo').addEventListener('click',()=>{
 if(recording){recording.stop();return;}
 if(!window.MediaRecorder||!recordingCanvas.captureStream){toast('Recording is unavailable in this browser.',true);return;}
 if(!videoState.lastFrame||Date.now()-videoState.lastFrame>2000){toast('Wait for a fresh video frame before recording.',true);return;}
 recordingCanvas.width=videoState.meta.width;recordingCanvas.height=videoState.meta.height;
 const stream=recordingCanvas.captureStream(15),chunks=[];
 const options=MediaRecorder.isTypeSupported('video/webm;codecs=vp8')?{mimeType:'video/webm;codecs=vp8'}:{};
 const recorder=new MediaRecorder(stream,options);recording=recorder;recordFrame(videoState.meta);
 recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
 recorder.onstop=()=>{stream.getTracks().forEach(t=>t.stop());const blob=new Blob(chunks,{type:recorder.mimeType}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`turtle-mission-${Date.now()}.webm`;a.click();setTimeout(()=>URL.revokeObjectURL(url),10000);recording=null;$('recordVideo').textContent='● Record';toast('Operator video downloaded.');};
 recorder.start(1000);$('recordVideo').textContent='■ Stop recording';setTimeout(()=>{if(recording===recorder)recorder.stop();},180000);toast('Recording locally in this browser; limited to 3 minutes.');
});
function drawMap(){
 const g=mapState.grid;if(!g)return;
 const canvas=$('lidarCanvas'),ctx=canvas.getContext('2d'),off=document.createElement('canvas');off.width=g.width;off.height=g.height;const o=off.getContext('2d'),image=o.createImageData(g.width,g.height);
 for(let y=0;y<g.height;y++)for(let x=0;x<g.width;x++){const v=g.data[(g.height-y-1)*g.width+x],i=(y*g.width+x)*4,t=v<0?65:255-Math.round(v*2.55);image.data[i]=t;image.data[i+1]=t;image.data[i+2]=t;image.data[i+3]=255;}o.putImageData(image,0,0);
 const ratio=devicePixelRatio||1;ctx.setTransform(1,0,0,1,0,0);ctx.fillStyle='#101824';ctx.fillRect(0,0,canvas.width,canvas.height);const scale=Math.min(canvas.width/g.width,canvas.height/g.height);ctx.imageSmoothingEnabled=false;ctx.drawImage(off,(canvas.width-g.width*scale)/2,(canvas.height-g.height*scale)/2,g.width*scale,g.height*scale);
 $('mapNote').textContent=`${mapState.saved?'SAVED MAP · not a live sensor':'ROS OCCUPANCY GRID'} · ${g.width}×${g.height} · ${g.resolution} m/cell · ${g.frame_id}. Robot odometry is not projected without a verified map transform.`;
}
$('toggleMap').addEventListener('click',async()=>{
 if(mapState.active){mapState.active=false;$('toggleMap').textContent='View occupancy map';$('mapNote').classList.add('hidden');$('saveMap').disabled=true;drawLidar();return;}
 try{const response=await fetch('/api/map').then(r=>r.json());if(!response.available){toast(response.note,true);return;}mapState={active:true,grid:response.map,saved:false};$('mapNote').classList.remove('hidden');$('toggleMap').textContent='Return to raw scan';$('saveMap').disabled=false;drawMap();}catch(error){toast('Map unavailable.',true);}
});
$('saveMap').addEventListener('click',()=>{if(mapState.grid)downloadJSON({type:'turtle-occupancy-map-v1',map:mapState.grid},`turtle-map-${Date.now()}.json`);});
$('loadMap').addEventListener('change',async event=>{
 const file=event.target.files[0];if(!file)return;
 try{if(file.size>12_000_000)throw Error('Map file too large');const v=JSON.parse(await file.text()),g=v.map;if(v.type!=='turtle-occupancy-map-v1'||!Number.isInteger(g.width)||!Number.isInteger(g.height)||g.width<1||g.height<1||g.width*g.height>1_000_000||!Array.isArray(g.data)||g.data.length!==g.width*g.height||!g.data.every(x=>Number.isInteger(x)&&x>=-1&&x<=100)||!Number.isFinite(g.resolution)||g.resolution<=0)throw Error('Invalid occupancy grid');mapState={active:true,grid:g,saved:true};$('mapNote').classList.remove('hidden');$('toggleMap').textContent='Return to raw scan';$('saveMap').disabled=false;drawMap();}catch(error){toast(error.message,true);}
});
fetch('/api/snapshots').then(r=>r.json()).then(v=>{state.captures=v.captures;renderCaptures();}).catch(()=>{});
refreshMission();missionRefresh=setInterval(refreshMission,4000);
