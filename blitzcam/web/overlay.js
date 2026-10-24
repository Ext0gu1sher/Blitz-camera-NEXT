"use strict";
const $=id=>document.getElementById(id);
const native=!!window.chrome?.webview;
const panel=new URLSearchParams(location.search).get("panel")||"all";
const model={data:null,busy:false,polling:false,ready:false,projectHash:"",durationEdited:false,previewReady:false,previewLoading:false,previewSequence:0};
let toastTimer,workbenchTimer;
document.querySelectorAll("[data-panel]").forEach(el=>el.hidden=panel!=="all"&&el.dataset.panel!==panel);
if(!native){
  document.body.classList.add("browser-preview");if(panel!=="all")document.body.classList.add("single");
  $("browserNote").hidden=false;["hide","settingsToggle"].forEach(id=>$(id).disabled=true);
}
const num=(v,n=3)=>typeof v==="number"&&Number.isFinite(v)?v.toFixed(n):"—";
const bridge=(command,extra={})=>window.chrome?.webview?.postMessage({command,...extra});
const preview=new BlitzMiniPreview.Preview($("miniCanvas"),(p,d,playing)=>{
  $("miniTime").textContent=`${num(p*d,2)} / ${num(d,2)} s`;
  $("miniSlider").value=p;$("miniPreview").textContent=playing?"Ⅱ 预览":"▶ 预览";
  renderSpeed(p,d);
});
function renderSpeed(progress=preview.progress,duration=preview.duration||0){
  const speed=model.data?.project?.replay_speed,live=model.data?.playback,start=preview.start||0,t=BlitzPreviewTime.atWindowCamera(start,start+duration,speed,start+duration*progress);
  const active=live?.active&&["playing","paused"].includes(live.state);
  const shooting=active?live.shooting_elapsed||0:t.shootingElapsed;
  BlitzPreviewTime.draw($("miniSpeedGraph"),speed,active?(shooting+(live.schedule_offset||0))/Math.max(.001,live.schedule_seconds??t.shootingDuration):t.shootingProgress);
  $("miniSpeedReadout").textContent=`${num(active?live.current_rate:t.rate,3)}× · 拍摄 ${num(shooting,2)} / ${num(active?live.shooting_duration??t.shootingDuration:t.shootingDuration,2)} s · 战斗 +${num(active?live.replay_elapsed:t.replayElapsed,2)} s`;
}
function toast(message,error=false){
  $("toast").textContent=message;$("toast").classList.toggle("error",error);$("toast").hidden=false;
  clearTimeout(toastTimer);toastTimer=setTimeout(()=>$("toast").hidden=true,error?6500:3000);
}
async function api(path,body){
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),15000);
  try{
    const r=await fetch(path,{method:body===undefined?"GET":"POST",headers:body===undefined?{}:{"Content-Type":"application/json"},body:body===undefined?undefined:JSON.stringify(body),signal:controller.signal,cache:"no-store"});
    const data=await r.json();if(!r.ok)throw new Error(data.error||"操作未完成");return data;
  }finally{clearTimeout(timeout);}
}
function buttons(){
  const d=model.data,c=d?.connection?.state==="connected",active=!!d?.playback?.active;
  const opening=['choosing','launching'].includes(d?.replay_launch?.state);
  const paused=d?.sample?.replay?.paused===true,disabled=model.busy||!model.ready||opening,hasPath=(d?.project?.keyframes?.length||0)>=2;
  $("openReplay").disabled=disabled||active||opening||d?.connection?.state==="connecting";
  const bound=d?.project?.replay_timeline?.replay_file;
  $("openReplay").textContent=opening?'打开中…':bound?'启动回放':'选择回放…';
  $("openReplay").title=bound?`启动已绑定回放：${bound}`:'当前项目未绑定回放，选择回放文件';
  $("connectToggle").textContent=c||d?.connection?.state==="connecting"||active?"断开":"连接";
  $("connectToggle").disabled=disabled;
  const guard=d?.keyframe_guard,blocked=guard?.enabled&&(guard.start_sec===null||d?.sample?.replay?.time<guard.start_sec-1e-6);
  $("capture").disabled=disabled||!c||!paused||!d?.sample?.camera||active||blocked;
  ["replace","captureTime"].forEach(id=>$(id).disabled=disabled||active);
  $("stop").hidden=!active;$("stop").disabled=!active||!model.ready;
  $("liveStop").disabled=!active||!model.ready;
  $("liveForward").disabled=$("liveReverse").disabled=disabled||active||!c||!paused||!d?.sample?.camera||!hasPath;
  $("liveSeekStart").hidden=d?.project?.shooting_mode==="camera_only";
  $("liveSeekStart").disabled=disabled||active||!c||!paused||!d?.sample?.camera||!d?.project?.replay_timeline;
  $("pathDuration").disabled=disabled||active||!hasPath;
  if(d?.project?.shooting_mode!=="camera_only"&&d?.project?.replay_timeline){$("pathDuration").readOnly=true;$("liveReverse").disabled=$('liveReverse').disabled||d.project.replay_speed.mode!=='paused';}
  else $("pathDuration").readOnly=false;
  $("captureTime").readOnly=d?.project?.shooting_mode!=="camera_only";
  document.querySelector('.capture-label').textContent=d?.project?.shooting_mode==="camera_only"?'记录到镜头时刻':'当前对局时间';
  if(d?.project?.shooting_mode==="camera_only")$("pathDuration").readOnly=true;
  $("miniPreview").disabled=$("miniSlider").disabled=!model.previewReady||active;
  $("captureHint").textContent=active?"接管中，请先停止播放。":!model.ready?"服务未连接。":!c?"未连接回放。":!paused?"请先在游戏中暂停回放。":blocked?guard.message:"";
}
function renderStatus(){
  const d=model.data,live=d?.playback,r=d?.sample?.replay,mode=d?.connection?.state,launch=d?.replay_launch,info=d?.replay_info||launch?.info,h=model.hostState;
  $("replaySummary").textContent=!model.ready?"":live?.active?"镜头接管中":r?`${r.paused?"已暂停":"播放中"} · ${num(r.rate,3)}×`:native&&h&&h.gameFound===false?"游戏未运行":"";
  const sl=$("statusLine");let text,cls="",title="";
  if(!model.ready){text="本地服务未响应，请重新启动工作台。";cls="launch-error";}
  else if(h?.warnings?.length){text=h.warnings.join("；");cls="launch-error";}
  else if(live?.active)text=`正在接管镜头 · ${live.message||live.state}`;
  else if(["choosing","launching","error","invalidated"].includes(launch?.state)){text=launch.message||"";cls=["error","invalidated"].includes(launch.state)?"launch-error":"";}
  else if(mode==="error"||mode==="connecting"){text=d.connection.message;cls=mode==="error"?"launch-error":"";}
  else if(info){text=`${info.name} · ${num(info.duration_sec,1)} 秒`;title=(info.replay_file?info.replay_file+"\n":"")+text;}
  else{text="未选择回放";cls="muted";}
  sl.textContent=text;sl.title=title||text;sl.className="message"+(cls?" "+cls:"");
}
let lastSummary;
function sendSummary(){
  if(!native)return;const d=model.data;let text="";
  if(panel==="connection")text=$("connectionLabel").textContent+($("replaySummary").textContent?" · "+$("replaySummary").textContent:"");
  else if(panel==="telemetry"){const r=d?.sample?.replay;text=r?`${num(r.time,3)} s`:"无数据";}
  else if(panel==="capture")text=$("captureHint").textContent||"可记录";
  else if(panel==="keyframes"){const live=d?.playback;text=live?.active?`播放中 ${Math.round((live.progress||0)*100)}%`:`${d?.project?.keyframes?.length||0} 个关键帧`;}
  if(text!==lastSummary){lastSummary=text;bridge("summary",{text});}
}
function render(){
  const d=model.data,s=d.sample,c=s?.camera,r=s?.replay,mode=d.connection.state,live=d.playback;
  $("connectionLabel").textContent=({connected:"已连接回放",connecting:"连接中",disconnected:"尚未连接",error:"连接未就绪"})[mode]||mode;
  $("connectionDot").className="dot "+mode;
  renderStatus();
  $("replayTime").textContent=num(r?.time)+" s";$("replayMode").textContent=r?`${r.paused?"Ⅱ 暂停":"▶ 播放"} · ${num(r.rate,3)}×`:"未读取";
  ["x","y","z"].forEach((id,i)=>$(id).textContent=num(c?.position?.[i]));
  ["yaw","pitch","roll"].forEach(id=>$(id).textContent=num(c?.[id+"_deg"],2)+"°");$("fov").textContent=num(c?.horizontal_fov_deg,2)+"°";
  $("dataQuality").textContent=c?"实时读取":"无数据";
  const speed=d.project.replay_speed,free=d.project.shooting_mode==="camera_only";
  for(const el of document.querySelectorAll(".mini-speed-heading, #miniSpeedGraph, #miniSpeedReadout"))el.toggleAttribute('hidden',free);
  $("clockLabel").textContent=speed?.mode!=="paused"&&speed?.camera_clock==="replay"?"战斗秒":"拍摄秒";
  $("speedModeLabel").textContent=!speed||speed.mode==="paused"?"战斗保持暂停":speed.mode==="fixed"?`战斗 ${num(speed.rate,3)}×` : "战斗按速度曲线";
  $("miniProgress").value=live.progress||0;
  $("miniLiveStatus").textContent=live.active||["error","completed","stopped"].includes(live.state)?live.message:!model.ready?"服务未连接。":mode!=="connected"?"未连接回放 · 可离线预览。":!r?.paused?"请先暂停回放。":"";
  $("miniLiveStatus").classList.toggle("error",live.state==="error");
  if(live.active&&model.previewReady){preview.pause();preview.setProgress(live.reverse?1-(live.progress||0):live.progress||0);}
  renderSpeed();
  $("attributeSummary").textContent=`${Object.values(d.camera_track_controls||{}).flat().length} 个属性关键帧`;buttons();sendSummary();
}
async function loadPreview(hash){
  if(panel!=="all"&&panel!=="keyframes")return;
  const sequence=++model.previewSequence;
  model.previewReady=false;model.previewLoading=true;preview.load([],[],[]);buttons();
  const revision=model.data.project_revision,frames=structuredClone(model.data.project.keyframes);
  const duration=frames.at(-1).time_sec-frames[0].time_sec;
  try{
    const result=await api("/api/sample",{rate_hz:Math.max(1,Math.min(30,3000/Math.max(1,duration))),expected_revision:revision});
    if(sequence!==model.previewSequence||hash!==model.projectHash)return;
    if(result.project_revision!==model.data.project_revision){model.projectHash="";return;}
    preview.load(result.samples,frames,result.keyframe_times,model.data.project.replay_speed,model.data.project.shooting_mode==='camera_only'?null:model.data.project.replay_timeline);model.previewReady=frames.length>=2;
  }catch(e){if(sequence===model.previewSequence&&hash===model.projectHash){model.projectHash="";toast("轨迹预览未更新："+e.message,true);}}
  finally{if(sequence===model.previewSequence)model.previewLoading=false;buttons();}
}
async function poll(force=false){
  if(model.polling||model.busy&&!force)return;model.polling=true;
  try{
    const data=await api("/api/state"),hash=JSON.stringify(data.project),changed=hash!==model.projectHash;
    model.data=data;model.ready=true;
    if(data.project.shooting_mode!=="camera_only"&&data.project.replay_timeline){const t=data.project.replay_timeline;$("pathDuration").value=Number((t.work_end_sec-t.work_start_sec).toFixed(6));}
    if(data.project.shooting_mode!=="camera_only"&&data.sample?.replay?.paused)$("captureTime").value=data.sample.replay.time.toFixed(6);
    if(changed){
      model.projectHash=hash;const frames=data.keyframe_controls||[];
      if((data.project.shooting_mode==="camera_only"||!data.project.replay_timeline)&&!model.durationEdited&&frames.length>=2)$("pathDuration").value=Number((frames.at(-1).time_sec-(data.project.shooting_mode==="camera_only"?0:frames[0].time_sec)).toFixed(6));
    }
    render();if(changed)loadPreview(hash);
  }catch(e){
    model.ready=false;$("connectionDot").className="dot error";$("connectionLabel").textContent="服务未连接";
    renderStatus();$("dataQuality").textContent="数据已过期";buttons();sendSummary();
  }finally{model.polling=false;}
}
async function action(task){
  if(model.busy)return;model.busy=true;buttons();
  try{await task();}catch(e){toast(e.name==="AbortError"?"请求超时，请先核对状态再重试。":e.message,true);}
  finally{model.busy=false;buttons();}
}
async function applyDuration(){
  if(model.data.project.shooting_mode==="camera_only"||model.data.project.replay_timeline)return model.data.project_revision;
  const raw=$("pathDuration").value,seconds=Number(raw);
  if(!raw.trim()||!Number.isFinite(seconds)||seconds<.5||seconds>120)throw new Error("整段时长需为 0.5–120 秒。");
  let revision=model.data.project_revision;const frames=model.data.project.keyframes;
  if(Math.abs(frames.at(-1).time_sec-frames[0].time_sec-seconds)>1e-8){
    await api("/api/project/retime",{seconds,expected_revision:revision});revision+=1;
  }
  model.durationEdited=false;return revision;
}
async function startLive(reverse,mode=reverse?'current':'auto'){
  const revision=await applyDuration();preview.pause();
  await api("/api/playback/start",{reverse,mode,orientation_enabled:true,fov_enabled:true,expected_revision:revision});
  await poll(true);
}
async function stopLive(){
  // Stop must remain available even while another UI request is pending.
  try{await api("/api/playback/stop",{});await poll(true);}catch(e){toast(e.message,true);}
}
$("connectToggle").onclick=()=>action(async()=>{const d=model.data,linked=d?.connection?.state==="connected"||d?.connection?.state==="connecting"||d?.playback?.active;await api(linked?"/api/disconnect":"/api/connect",{});await poll(true);});
$("openReplay").onclick=()=>action(async()=>{const path=model.data?.project?.replay_timeline?.replay_file;await api('/api/replay/open',path?{path}:{});await poll(true);});
$("stop").onclick=$("liveStop").onclick=stopLive;
$("pathDuration").oninput=()=>model.durationEdited=true;
$("capture").onclick=()=>action(async()=>{
  const raw=$("captureTime").value,time=Number(raw);if(!raw.trim()||!Number.isFinite(time))throw new Error("无法读取当前对局时间，请重新连接。");
  await api("/api/capture",{time_sec:time,replace_existing:$("replace").checked,expected_revision:model.data.project_revision});
  $("replace").checked=false;await poll(true);toast("已记录全部七项属性关键帧。");
});
$("miniPreview").onclick=()=>preview.toggle();$("miniSlider").oninput=()=>{const value=Number($("miniSlider").value);preview.pause();preview.setProgress(value);};
$("miniFit").onclick=()=>preview.fit();
document.querySelectorAll("[data-view]").forEach(button=>button.onclick=()=>{
  preview.view=button.dataset.view;preview.draw();document.querySelectorAll("[data-view]").forEach(b=>b.setAttribute("aria-pressed",String(b===button)));
});
$("pathDuration").addEventListener('number-end',()=>{if(model.durationEdited&&!$("pathDuration").readOnly&&!$("pathDuration").disabled)action(async()=>{await applyDuration();await poll(true);});});
$("liveForward").onclick=()=>action(()=>startLive(false));$("liveSeekStart").onclick=()=>action(()=>startLive(false,'locate'));$("liveReverse").onclick=()=>action(()=>startLive(true));
async function workbenchFallback(){try{await api("/api/desktop/workbench",{});}catch(e){toast(e.message,true);}}
$("workbench").onclick=()=>{
  if(native){bridge("workbench");clearTimeout(workbenchTimer);workbenchTimer=setTimeout(workbenchFallback,1800);}
  else location.assign("/");
};
$("hide").onclick=()=>bridge("hide");$("reset").onclick=()=>bridge("reset");
$("settingsToggle").onclick=()=>{const open=$("settings").hidden;$("settings").hidden=!open;$("settingsToggle").setAttribute("aria-expanded",String(open));bridge("settings-height",{open});};
$("opacity").oninput=()=>{$("opacityValue").textContent=$("opacity").value+"%";bridge("settings",{opacity:Number($("opacity").value)});};
$("saveKeys").onclick=()=>bridge("settings",{hideKey:$("hideKey").value,captureKey:$("captureKey").value});
if(native){
  window.chrome.webview.addEventListener("message",e=>{
    const h=e.data;
    if(h.type==="host-error"){clearTimeout(workbenchTimer);toast(h.message,true);return;}
    if(h.type==="host-action"&&h.action==="workbench"){clearTimeout(workbenchTimer);return;}
    if(h.type==="host-action"&&h.action==="capture"){poll(true);toast("已通过全局快捷键记录全部七项属性关键帧。");return;}
    if(h.type!=="host-state")return;
    model.hostState=h;
    $("hide").title=`Ctrl+Alt+${h.hideKey} 显示/隐藏`;
    $("capture").title=`Ctrl+Alt+${h.captureKey||'F8'} 记录全部七项属性关键帧`;
    if(document.activeElement!==$("opacity")){$("opacity").value=h.opacity;$("opacityValue").textContent=h.opacity+"%";}
    if(document.activeElement!==$("hideKey"))$("hideKey").value=h.hideKey;
    if(document.activeElement!==$("captureKey"))$("captureKey").value=h.captureKey||'F8';
    if(model.data)renderStatus();sendSummary();
  });bridge("ready");
}
document.addEventListener("keydown",e=>{if(e.key==="Escape"){if(model.data?.playback.active)stopLive();else if(document.activeElement instanceof HTMLInputElement)document.activeElement.blur();}});
poll();setInterval(poll,500);
