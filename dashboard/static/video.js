'use strict';
const videoState={socket:null,meta:null,url:null,rendered:[],lastFrame:0,retry:null,recording:null,totalFrames:0};
function detectionOverlay(meta){
 const canvas=$('detectionCanvas'),box=canvas.getBoundingClientRect(),ratio=devicePixelRatio||1;
 canvas.width=box.width*ratio;canvas.height=box.height*ratio;const ctx=canvas.getContext('2d');ctx.scale(ratio,ratio);
 const w=meta.width||640,h=meta.height||480,scale=Math.min(box.width/w,box.height/h),ox=(box.width-w*scale)/2,oy=(box.height-h*scale)/2;
 for(const model of meta.models||[]){for(const d of model.detections||[]){
  ctx.strokeStyle=model.mock?'#f6bb55':'#53dec4';ctx.fillStyle=ctx.strokeStyle;ctx.lineWidth=2;
  let x=.02,y=.05;
  if(d.bbox){const [bx,by,bw,bh]=d.bbox;x=bx;y=by;ctx.strokeRect(ox+bx*w*scale,oy+by*h*scale,bw*w*scale,bh*h*scale);}
  for(const polygon of d.mask?.polygons||[]){ctx.beginPath();polygon.forEach(([px,py],i)=>{if(i)ctx.lineTo(ox+px*w*scale,oy+py*h*scale);else ctx.moveTo(ox+px*w*scale,oy+py*h*scale);});ctx.closePath();ctx.stroke();ctx.globalAlpha=.16;ctx.fill();ctx.globalAlpha=1;x=polygon[0][0];y=polygon[0][1];}
  ctx.font='12px ui-monospace,monospace';ctx.fillText(`${model.mock?'MOCK · ':''}${d.label} ${(d.confidence*100).toFixed(0)}%${model.result_age_ms?` · ${model.result_age_ms.toFixed(0)}ms old`:''}`,ox+x*w*scale,Math.max(15,oy+y*h*scale-7));
 }}
}
function connectVideo(){
 const socket=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/video`);videoState.socket=socket;
 socket.onmessage=async event=>{
  if(typeof event.data==='string'){videoState.meta=JSON.parse(event.data);return;}
  const meta=videoState.meta;if(!meta)return;
  const url=URL.createObjectURL(new Blob([event.data],{type:meta.mime||'image/jpeg'}));
  try{
   $('cameraImage').src=url;await $('cameraImage').decode();
   if(videoState.url)URL.revokeObjectURL(videoState.url);videoState.url=url;
   videoState.totalFrames++;$('videoStats').dataset.frames=String(videoState.totalFrames);$('videoStats').dataset.renderTime=String(performance.now());
   videoState.lastFrame=Date.now();const now=performance.now();videoState.rendered.push(now);videoState.rendered=videoState.rendered.filter(t=>now-t<5000);
   const n=videoState.rendered.length,rate=n>1?(n-1)*1000/(now-videoState.rendered[0]):0;
   $('videoStats').textContent=`${meta.mode==='mock'?'SIMULATED · ':''}${rate.toFixed(1)} fps displayed · ${fmt(meta.previous_ack_latency_ms,0)} ms ACK`;
   detectionOverlay(meta);if(typeof recordFrame==='function')recordFrame(meta);
   socket.send(JSON.stringify({frame_id:meta.frame_id}));
  }catch(error){URL.revokeObjectURL(url);socket.close();}
 };
 socket.onclose=()=>{if(videoState.socket!==socket)return;$('videoStats').textContent='Video disconnected · retrying';clearTimeout(videoState.retry);videoState.retry=setTimeout(connectVideo,1200);};
 socket.onerror=()=>socket.close();
}
connectVideo();
setInterval(()=>{if(videoState.lastFrame&&Date.now()-videoState.lastFrame>2200){$('videoStats').textContent='STALE VIDEO · reconnecting';$('cameraImage').classList.add('hidden');$('cameraUnavailable').classList.remove('hidden');}},700);
new ResizeObserver(()=>{if(videoState.meta)detectionOverlay(videoState.meta);}).observe($('detectionCanvas'));
