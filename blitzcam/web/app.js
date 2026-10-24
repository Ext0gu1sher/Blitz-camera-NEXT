"use strict";

// Reading, offline preview and explicitly requested in-game position playback.
const $ = id => document.getElementById(id);
const state = {
  speedFrames: [{progress:0,rate:1},{progress:.25,rate:.25},{progress:.75,rate:.25},{progress:1,rate:1}],
  speedRange:null,
  connection: {state: "disconnected", message: ""}, sample: null, serviceReady: false, playback: {active:false,state:"idle"},
  controls: [], savedControls: [], project: null, projectHash: null, pendingProject: null,
  dirty: false, busy: false, loaded: false, captureTimeEdited: false,
  samples: [], previewTime: 0, playing: false, loop: false, playbackAnchor: 0,
  playbackStart: 0, previewRate: 60, view: "3d", yaw: -0.58, elevation: 0.65,
  zoom: 1, pan: [0, 0], center: [0, 0, 0], baseScale: 20, extent: 20,
  bounds: {min: [-10, -10, 0], max: [10, 10, 0]}, canvasWidth: 1, canvasHeight: 1,
  stateSequence: 0, appliedSequence: 0, previewSequence: 0, previewPlaySequence: 0, pollInFlight: false, animationRequest: 0, serverRevision: null,
  shootingMode: "replay", rateMode: "curve", tracks: null, timeline: null, replayInfo: null, replayLaunch: null, appliedLaunchId: null, savingTimeline: false,
};
let toastTimeout, sequenceEditor, draftTimer, speedCurveEditor, finishEaseDrag;
let replayPreviewPane=null;
let autoSaveTimer=null,autoSavePromise=null,editorSavePromise=null,pendingEditorRestore=null,pendingPreviewRestore=null,lastEditorSignature='';
let lastEditorError='';
let applicationSettings=null,settingsLoading=false;
let nativeHostState=null;
let globalKeysEdited=false;
let startupServiceError='',startupSamples={ready:false,error:''};
let homeItems=[],homeLoading=false,homeError='',homeRequest=0,homeOpening=false,homeMenuItem=null,homeMenuTrigger=null;
function setIcon(button,name){const u=button?.querySelector("use");if(u)u.setAttribute("href","#"+name);}
function syncReplayPreview(){
  replayPreviewPane?.update({mode:state.shootingMode,time:state.previewTime,tracks:state.tracks,
    smooth:$("interpolationSelect").value==='smooth',easing:$("easingSelect").value,
    samples:state.samples,replayFile:state.timeline?.replay_file,projectPath:state.projectPath});
}
function mountReplayPreview(){
  if(replayPreviewPane||!window.BlitzReplayPreview)return;
  replayPreviewPane=window.BlitzReplayPreview.mount({
    locked:()=>state.busy||state.playback.active||!state.serviceReady,
    pause:()=>stopPlayback(),
    ready:()=>restorePreviewSession(),
    bindSource:info=>{stopPlayback();if(!applyReplayInfo(info))throw Error('所选回放未能绑定现有时间轴。请先检查关键帧是否超出新回放长度。');notify('预览已绑定所选回放。');},
    record:(pose,time)=>{
      if(isCameraOnly()||state.busy||state.playback.active)return;
      stopPlayback();const values={x:pose.position[0],y:pose.position[1],z:pose.position[2],yaw:pose.yaw,pitch:pose.pitch,roll:pose.roll,zoom:pose.zoom};
      const replaced=Object.values(sequenceEditor.doc.tracks).flat().some(k=>Math.abs(k.time_sec-time)<1e-5);
      const recorded=sequenceEditor.edit(()=>{
        for(const [name,value] of Object.entries(values)){
          const row=sequenceEditor.doc.tracks[name],key=row.find(k=>Math.abs(k.time_sec-time)<1e-5);
          if(key)key.value=value;else row.push({time_sec:time,value,_id:++sequenceEditor.ids});
        }
      });
      if(recorded)notify(replaced?`已在 ${time.toFixed(3)} 秒替换预览镜头属性。`:`已在 ${time.toFixed(3)} 秒记录预览镜头的全部属性。`);
    }
  });syncReplayPreview();
}
window.addEventListener('blitz-replay-preview-ready',mountReplayPreview);
$("openOverlay").addEventListener("click", () => action(async () => {
  await api("/api/desktop/open", {});
  notify("悬浮窗已启动；默认 Ctrl+Alt+F8 记录关键帧、Ctrl+Alt+F9 显隐，可在设置中更改。");
}));

function finite(value) { return typeof value === "number" && Number.isFinite(value); }
function numberText(value, digits = 3) { return finite(value) ? value.toFixed(digits) : "—"; }
function degrees(value) { return finite(value) ? `${value.toFixed(2)}°` : "—"; }
function copy(value) { return JSON.parse(JSON.stringify(value)); }
function keyframeGuardFor(doc={timeline:state.timeline,mode:state.shootingMode}){
  const t=doc.timeline;
  if(doc.mode==='camera_only'||!t?.replay_file)return {enabled:false};
  const manual=state.replayKeyframeStartSeconds;
  if(finite(manual))return {enabled:true,start_sec:manual,source:'manual',message:`比赛开始：${manual.toFixed(3)} 秒（手动）；此前不能设置入点或添加、移动摄像机关键帧。`};
  if(t.replay_file===state.keyframeGuard?.replay_file)return state.keyframeGuard;
  if(t.battle_start_status==='identified'&&finite(t.battle_start_sec))return {enabled:true,start_sec:t.battle_start_sec,source:'replay_event',message:`比赛开始：${t.battle_start_sec.toFixed(3)} 秒；此前不能设置入点或添加、移动摄像机关键帧。`};
  return {enabled:true,start_sec:null,source:'unavailable',message:t.battle_start_reason||'未识别到比赛开始事件，请在设置中手动填写赛前片段长度后设置入点或添加关键帧。'};
}
function tracksFromFrames(frames){
  return Object.fromEntries(BlitzTimeline.CHANNELS.map(([name],i)=>[name,frames.map(f=>({time_sec:f.time_sec,value:[...f.position,f.yaw_deg,f.pitch_deg,f.roll_deg,f.horizontal_fov_deg][i]}))]));
}
function editPayload(){
  return {keyframes:copy(state.controls),camera_track_controls:copy(state.tracks),timing:'keyframes',
    replay_timeline:copy(state.timeline),shooting_mode:state.shootingMode,
    easing:$("easingSelect").value,position_interpolation:$("interpolationSelect").value,replay_speed:speedSettings()};
}
async function refreshDraftPreview(){
  clearTimeout(draftTimer);draftTimer=null;
  if(!state.tracks||!state.dirty)return;
  const sequence=++state.previewSequence;
  try{
    const result=await api('/api/sample/draft',{...editPayload(),rate_hz:state.previewRate});
    if(sequence!==state.previewSequence)return;
    state.controls=copy(result.keyframe_controls);state.savedControls=copy(result.keyframe_controls);updateKeyframeCount();setSamples(result.samples,result);
    $("samplingIndicator").textContent=`${state.previewRate} Hz · 草稿预演`;
  }catch(error){if(sequence===state.previewSequence)notify('草稿预演：'+error.message,true);}
}
function queueDraftPreview(){if(sequenceEditor?.numberEdit&&draftTimer)return;clearTimeout(draftTimer);draftTimer=setTimeout(refreshDraftPreview,sequenceEditor?.numberEdit?100:180);}
function applyTimelineChange(data){
  stopPlayback();state.tracks=copy(data.tracks);state.timeline=copy(data.timeline);state.shootingMode=data.mode;state.speedFrames=copy(data.speed.keyframes);
  state.speedRange=data.speed.time_range?copy(data.speed.time_range):null;
  state.rateMode=data.speed.mode==='paused'?'curve':data.speed.mode;setRateOption(data.speed.rate);
  $("speedInterpolation").value=data.speed.interpolation;
  $("timelineRateInterpolation").value=data.speed.interpolation;
  updateModeUI();updatePreviewRange();
  updateKeyframeCount();setDirty(true);renderSpeedRows();updateSpeedExplanation();queueDraftPreview();
}
function setRateOption(rate){
  $("replayFixedRate").value=String(rate);
  if(!$("replayFixedRate").value){$("replayFixedRate").add(new Option(`${rate}×`,String(rate)));$("replayFixedRate").value=String(rate);}
}
function notify(message, error = false) {
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.toggle("error", error);
  toast.hidden = false;
  clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => { toast.hidden = true; }, error ? 6500 : 3500);
}
function showServiceError(message) {
  $("serviceError").textContent = message;
  $("serviceError").hidden = !message;
}

async function api(path, body, opts = {}) {
  const controller = new AbortController();
  const timeout = opts.timeout === 0 ? null : setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(path, {method: body === undefined ? "GET" : "POST",
      headers: body === undefined ? {} : {"Content-Type": "application/json"},
      body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal,
      cache: "no-store"});
    const data = await response.json().catch(() => null);
    if (!response.ok) throw new Error(data?.error || `本地服务返回错误（${response.status}）。`);
    if (!data && body === undefined) throw new Error("本地服务返回了无法识别的数据。");
    return data || {};
  } catch (error) {
    if (error.name === "AbortError") throw new Error("本地服务响应超时，请确认工作台服务仍在运行。");
    if (error instanceof TypeError) throw new Error("无法访问本地服务，请确认工作台服务仍在运行。");
    throw error;
  } finally { if (timeout) clearTimeout(timeout); }
}

function updateButtons() {
  const live = state.playback.active === true;
  const opening = ['choosing','launching'].includes(state.replayLaunch?.state);
  const editing = state.busy || live || opening;
  const connecting = state.connection.state === "connecting";
  const connected = state.connection.state === "connected";
  $("openReplayButton").disabled = editing || connecting || !state.serviceReady;
  $("openReplayButton").querySelector("[data-label]").textContent = opening ? (state.replayLaunch.state==='choosing'?'选择回放中…':'正在启动游戏…') : '打开回放文件…';
  $("openReplayButton").title = opening ? "正在打开回放" : "打开回放文件";
  const boundReplay=state.timeline?.replay_file;
  $("playProjectReplay").disabled=editing||connecting||!state.serviceReady||!boundReplay;
  $("playProjectReplay").title=opening?'正在打开回放':boundReplay?`在游戏中播放项目回放 · ${boundReplay.split(/[\\/]/).at(-1)}`:'当前项目尚未绑定回放';
  $("connectButton").disabled = state.busy || opening || connecting || connected || !state.serviceReady;
  $("disconnectButton").disabled = state.busy || (!connected && !connecting && !live);
  const hasCamera = !!state.sample?.camera;
  const paused = state.sample?.replay?.paused === true;
  const captureGuard=keyframeGuardFor(),captureBlocked=captureGuard.enabled&&(captureGuard.start_sec===null||state.sample?.replay?.time<captureGuard.start_sec-1e-6);
  $("captureButton").disabled = editing || !connected || !hasCamera || !paused || !state.serviceReady || captureBlocked;
  $("newPathButton").disabled = $("captureButton").disabled;
  $("saveButton").disabled = editing || !state.dirty || !state.serviceReady;
  sequenceEditor?.lock(editing);
  const locateButton=document.querySelector('[data-action=locate]');
  if(locateButton)locateButton.disabled=editing||!connected||!hasCamera||!paused||!state.serviceReady||isCameraOnly()||!state.timeline;
  $("addKeyframeButton").disabled = editing;
  $("importButton").disabled = editing || !state.serviceReady;
  $("exportButton").disabled = state.busy || !state.project || !state.serviceReady;
  $("reloadProjectButton").disabled = state.busy;
  document.querySelectorAll(".trajectory-settings select, [name=shootingMode], #captureTime, #replaceExisting")
    .forEach(element => { element.disabled = editing; });
  const canPrepare = !editing && connected && hasCamera && state.serviceReady && state.controls.length >= 2;
  const canPlay = canPrepare && (isCameraOnly() ? paused : !!state.timeline);
  $("liveForward").disabled = !canPlay;
  const now=state.sample?.replay?.time,timeline=state.timeline;
  const inRange=timeline&&finite(now)&&now>=timeline.work_start_sec-.05&&now<timeline.work_end_sec;
  $("liveForward").title=isCameraOnly()?'播放镜头动画':!paused?'等待游戏暂停后播放':inRange?(timeline.work_end_sec-now<.5?'距离出点不足 0.5 秒，剩余区间太短':'从当前游戏时刻播放至出点'):timeline&&finite(now)&&now>=timeline.work_end_sec?'已到出点，请先跳转到入点':'准备入点并播放';
  $("liveForward").setAttribute('aria-label',$("liveForward").title);
  $("liveReverse").disabled = !canPlay || !isCameraOnly();
  $("liveStop").disabled = !live;
  $("livePause").disabled = !live || !state.playback.replay_controlled || !["playing","paused"].includes(state.playback.state);
  const pausedLive = state.playback.state === "paused";
  setIcon($("livePause"), pausedLive ? "i-play" : "i-pause");
  $("livePause").title = pausedLive ? "继续联动" : "暂停联动";
  $("livePause").setAttribute("aria-label", $("livePause").title);
  document.querySelectorAll(".replay-speed-panel input, .replay-speed-panel select, #resetReplaySpeed, #speedPreset, #timelineSpeedPreset, #addSpeedFrame, #speedRows button").forEach(el=>el.disabled=editing);
  speedCurveEditor?.refresh();
  const sceneReady=!isCameraOnly()&&replayPreviewPane?.status==='ready';
  $("playButton").disabled = state.samples.length < 2&&!sceneReady;
  $("timelineSlider").disabled = state.samples.length < 2&&!sceneReady;
  replayPreviewPane?.syncFlightUI();
  updateSettingsControls();
  updateHomeControls();
  if (!connected || !hasCamera) $("captureButton").title = "连接客户端并暂停本地回放后可用。";
  else if (!paused) $("captureButton").title = "请先在游戏中暂停回放，以记录当前摄像机属性。";
  else if(captureBlocked)$("captureButton").title=captureGuard.message;
  else $("captureButton").title = state.dirty ? "记录前会先保存当前关键帧草稿。" : "一次记录全部七项属性关键帧。";
}

function updateTelemetry(data) {
  const previousPlayback=state.playback;
  state.playback = data.playback || {state:"idle",active:false};
  const live = state.playback;
  const liveLabels = {idle:"手动控制",preparing:"准备中",waiting_replay:"等待暂停",seeking_replay:"实验跳转中",reconnecting_replay:"重新连接",advancing_replay:"定位入点",positioning:"正在就位",playing:"播放中",paused:"联动已暂停",stopping:"正在停止",completed:"已完成",stopped:"已停止",error:"播放中断"};
  const interrupted=live.state==='error',hasInterval=finite(live.timeline_start)&&finite(live.timeline_end);
  const stoppedAt=live.replay_controlled&&finite(live.actual_replay_time)?live.actual_replay_time:live.timeline_position;
  const stopContext=interrupted&&hasInterval&&finite(stoppedAt)?`${live.replay_controlled?'对局':'镜头'} ${stoppedAt.toFixed(3)} s / 出点 ${live.timeline_end.toFixed(3)} s：`:'';
  const liveMessage=stopContext+(live.message||'');
  $("liveBadge").textContent = liveLabels[live.state] || "手动控制";
  $("liveBadge").title = liveMessage;
  $("liveBadge").classList.toggle('error',interrupted);
  $("liveBadge").classList.toggle("paused",live.active === true);
  $("liveProgress").value = finite(live.progress) ? live.progress : 0;
  $("liveMessage").textContent = liveMessage || "连接并暂停回放，在至少两个不同时刻记录属性关键帧后可播放。";
  $("liveMessage").title = liveMessage;
  $("liveMessage").classList.toggle("live-error",interrupted);
  $("liveElapsed").textContent = `${numberText(live.elapsed || 0,2)} / ${numberText(live.duration || 0,2)} s`;
  $("liveControls").title = live.preparing_replay ? live.message : isCameraOnly()?"回放保持暂停，镜头按独立时间播放至最后一个关键帧；可正放、倒放，Esc 停止。":"主播放在工作区内从当前暂停时刻继续；入点之前先准备到入点再开拍。实验性跳转可向前或向后跳至工作区入点，可能导致客户端崩溃。Esc 停止。";
  state.connection = data.connection || {state: "disconnected", message: "尚未连接"};
  state.sample = data.sample || null;
  state.replayInfo = data.replay_info || null;
  state.replayLaunch = data.replay_launch || null;
  state.replayKeyframeStartSeconds=data.replay_keyframe_start_seconds??null;
  state.keyframeGuard={...data.keyframe_guard,replay_file:data.project?.replay_timeline?.replay_file};
  const launch=state.replayLaunch,info=state.replayInfo||launch?.info;
  $("openedReplayFile").textContent=info?`${info.name} · ${info.duration_sec.toFixed(3)} 秒`:'—';
  $("openedReplayFile").title=info?.replay_file||'';
  $("replayLaunchMessage").textContent=info?.verification==='runtime_replay'?'已识别游戏当前打开的回放。可手动打开回放后连接；切换回放后请重新连接。':launch?.state==='idle'&&info?'已读取回放启动信息；切换回放后请重新连接。':launch?.message||'可先在游戏中打开回放，再连接；也可从这里选择回放启动。';
  $("replayLaunchMessage").classList.toggle('launch-error',launch?.state==='error'||launch?.state==='invalidated');
  if(live.active && live.replay_controlled) $("liveElapsed").textContent=`拍摄 ${numberText(live.shooting_elapsed || 0,2)} s · 战斗 +${numberText(live.replay_elapsed || 0,2)} s · ${numberText(live.current_rate ?? 1,3)}×`;
  if(live.preparing_replay) $("liveElapsed").textContent=`${numberText((live.current_time || 0)+(live.state==='advancing_replay'?(live.replay_elapsed || 0):0),3)} → ${numberText(live.target_time,3)} s`;
  const mode = state.connection.state;
  const labels = {disconnected: "尚未连接", connecting: "正在连接", connected: "已连接客户端", error: "连接未就绪"};
  $("connectionLabel").textContent = labels[mode] || "状态未知";
  $("connectionDot").className = `status-dot ${["connected", "connecting", "error"].includes(mode) ? mode : ""}`;
  document.querySelectorAll("[data-conn-dot]").forEach(d => { d.className = $("connectionDot").className; });
  $("connectionMessage").textContent = state.connection.message || "连接只读采样器，读取本地回放中的相机。";
  const sample = state.sample;
  const camera = sample?.camera;
  const replay = sample?.replay;
  if(!isCameraOnly()&&replay?.paused && finite(replay.time))$("captureTime").value=replay.time.toFixed(6);
  $("captureTime").readOnly=!isCameraOnly();
  $("replayTime").replaceChildren(document.createTextNode(numberText(replay?.time)), Object.assign(document.createElement("small"), {textContent: "s"}));
  $("replayPaused").textContent = !replay ? "未读取" : replay.paused ? "Ⅱ 已暂停" : "▶ 播放中";
  $("replayPaused").classList.toggle("paused", replay?.paused === true);
  $("replayRate").textContent = finite(replay?.rate) ? `${replay.rate}×` : "—";
  ["cameraX", "cameraY", "cameraZ"].forEach((id, i) => { $(id).textContent = numberText(camera?.position?.[i]); });
  $("cameraYaw").textContent = degrees(camera?.yaw_deg);
  $("cameraPitch").textContent = degrees(camera?.pitch_deg);
  $("cameraRoll").textContent = degrees(camera?.roll_deg);
  $("cameraFov").textContent = degrees(camera?.horizontal_fov_deg);
  $("telemetryStatus").textContent = camera ? "实时读取" : "等待数据";
  const quality = sample?.quality;
  const unverified = [];
  if (quality?.active_root_verified !== true) unverified.push("当前画面所属场景");
  if (quality?.frame_synchronized !== true) unverified.push("逐帧同步");
  $("connectionDot").title = camera
    ? `回放摄像机对象链已匹配。${unverified.length ? unverified.join("、") + "尚未独立验证。" : ""}捕获仅保存数值，不改变游戏构图。`
    : "连接后将核验回放摄像机对象链；当前画面所属场景和逐帧同步尚未独立验证。";
  $("sessionLine").hidden = !sample?.session_id;
  $("sessionId").textContent = sample?.session_id ? String(sample.session_id).slice(0, 18) : "";
  const terminal=!live.active&&!live.preparing_replay&&!live.experimental_seek&&['completed','stopped','error'].includes(live.state);
  const terminalId=terminal?JSON.stringify([live.run_path,live.state,live.message]):null;
  const newTerminal=terminal&&state.appliedLiveTerminalId!==terminalId;
  if(newTerminal)state.appliedLiveTerminalId=terminalId;
  const terminalTransition=newTerminal&&previousPlayback?.active;
  if(state.samples.length&&((live.active&&['playing','paused'].includes(live.state))||(terminalTransition&&hasInterval))){
    stopPlayback();const first=live.timeline_start??state.samples[0].time_sec,last=live.timeline_end??state.samples.at(-1).time_sec;
    const progress=terminal&&live.state==='completed'?1:Math.max(0,Math.min(1,live.progress||0));
    state.previewTime=terminalTransition&&live.state!=='completed'&&finite(live.timeline_position)?live.timeline_position:first+(live.reverse?1-progress:progress)*(last-first);
    updateTimeline();drawCanvas();
  }
  if(terminalTransition&&interrupted)notify('播放中断：'+liveMessage,true);
  if(live.experimental_seek&&live.state==='completed'&&live.run_path!==state.appliedSeekId){
    state.appliedSeekId=live.run_path;stopPlayback();seek(live.target_time);
  }
  updateButtons();drawSpeedGraph();
  if(sequenceEditor?.doc){
    const signature=JSON.stringify(keyframeGuardFor(sequenceEditor.data()));
    if(signature!==state.guardSignature){state.guardSignature=signature;sequenceEditor.render();}
  }
  if(state.settingsOpen)renderBattleStartStatus();
}

function setDirty(dirty) {
  state.dirty = dirty;
  window.chrome?.webview?.postMessage({command:"dirty",value:dirty});
  $("savedLabel").textContent = dirty ? "未保存草稿" : "已保存";
  $("savedLabel").classList.toggle("dirty", dirty);
  $("dirtyDot").hidden = !dirty;
  $("draftPreviewNote").hidden = !dirty;
  $("saveButton").title = $("saveButton").ariaLabel = state.pendingProject ? "覆盖并保存" : "保存 Ctrl+S";
  updateButtons();
  if(dirty)queueAutoSave();else clearTimeout(autoSaveTimer);
}

function loadProject(data) {
  const switched=state.projectPath!==data.project_path;
  state.projectPath=data.project_path;
  if(switched){
    state.appliedLaunchId=data.replay_launch?.state==='launched'?data.replay_launch.id:null;
    const saved=BlitzEditorSession.newest(data.editor_state,BlitzEditorSession.readLocal(localStorage,state.projectPath));
    pendingEditorRestore=saved||null;pendingPreviewRestore=saved?.preview||null;lastEditorSignature='';
    state.previewTime=Number.isFinite(saved?.timeline?.playhead)?Math.max(0,saved.timeline.playhead):0;
  }
  state.project = data.project || null;
  $("projectName").textContent = data.project_name || "未命名项目";
  state.projectHash = JSON.stringify(data.project || null);
  state.controls = copy(data.keyframe_controls || []);
  state.tracks = copy(data.camera_track_controls || tracksFromFrames(state.controls));
  state.shootingMode=data.project?.shooting_mode || (data.project?.replay_timeline?"replay":"camera_only");
  const end=Math.max(1,...Object.values(state.tracks).flat().map(k=>k.time_sec));
  const first=Math.max(0,Math.min(...Object.values(state.tracks).flat().map(k=>k.time_sec)));
  state.timeline=copy(data.project?.replay_timeline || {time_basis:'replay',duration_sec:Math.max(end,first+.5),work_start_sec:first,work_end_sec:Math.max(end,first+.5)});
  $("replayFilePath").value=state.timeline.replay_file||'';
  const seqSource=$("sequenceEditor").querySelector('[data-source]');
  seqSource.textContent=seqSource.title=data.project?.replay_timeline?.replay_file?'已保存的整场回放时间轴':'全片长度待确认：读取回放文件以取得全片长度。';
  updatePreviewRange();
  state.savedControls = copy(state.controls);
  state.pendingProject = null;
  state.loaded = true;
  $("externalChange").hidden = true;
  $("timingSelect").value = data.project?.timing || "keyframes";
  $("easingSelect").value = data.project?.easing || "linear";
  $("interpolationSelect").value = data.project?.position_interpolation || "smooth";
  const speed=data.project?.replay_speed;
  state.speedRange=speed?.time_range?copy(speed.time_range):null;
  state.rateMode=speed?.mode==='fixed'?'fixed':'curve';
  $("replayFixedRate").value=String(speed?.rate ?? .25);
  if(!$("replayFixedRate").value){const opt=new Option(`${speed.rate}×`,String(speed.rate));$("replayFixedRate").add(opt);$("replayFixedRate").value=String(speed.rate);}
  $("cameraClock").value="replay";
  $("speedInterpolation").value=speed?.interpolation || "smooth";
  $("timelineRateInterpolation").value=$("speedInterpolation").value;
  state.speedFrames=copy(speed?.mode==='paused'&&state.shootingMode==='replay'?[{progress:0,rate:1},{progress:1,rate:1}]:speed?.keyframes||[{progress:0,rate:1},{progress:1,rate:1}]);
  renderSpeedRows();updateSpeedExplanation();
  const frames=state.controls;
  $("captureTime").value = isCameraOnly()?0:state.sample?.replay?.time??first;
  $("captureTime").readOnly=!isCameraOnly();
  sequenceEditor?.load(state.tracks,speedSettings(),!switched||state.savingTimeline,state.timeline,state.shootingMode);
  updateModeUI();setDirty(false);
  updateKeyframeCount();
  updateTimingExplanation();
  refreshPreview();
}

async function refreshState(forceProject = false) {
  const sequence = ++state.stateSequence;
  const data = await api("/api/state");
  if (sequence < state.appliedSequence) return;
  state.appliedSequence = sequence;
  state.serviceReady = true;
  startupServiceError='';
  showServiceError("");
  updateTelemetry(data);
  // A poll may see our pending save on disk before its acknowledgement arrives.
  // Let that acknowledgement establish the saved snapshot and revision first.
  if(state.loaded&&autoSavePromise&&!forceProject)return;
  state.serverRevision = data.project_revision;
  const hash = JSON.stringify(data.project || null);
  const interacting=editorInteracting();
  const editing=state.dirty||interacting;
  if (!state.loaded || forceProject || (!editing && (state.projectPath!==data.project_path||hash !== state.projectHash))) loadProject(data);
  else if (editing && (state.projectPath!==data.project_path||hash !== state.projectHash)) {
    state.pendingProject = data;
    $("externalChange").hidden = false;
    $("saveButton").title = $("saveButton").ariaLabel = "覆盖并保存";
  }
  // Merge a fresh launch's source into this project's unsaved edits only after
  // the service bound it. Remembered launches never own a different project.
  const launch=data.replay_launch;
  if(!interacting&&!state.busy&&!state.playback.active&&launch?.state==='launched'&&
      data.project_path===state.projectPath&&launch.project_path===state.projectPath&&launch.id!==state.appliedLaunchId){
    state.appliedLaunchId=launch.id;
    const info=launch.info;
    if(!isCameraOnly()&&info&&data.project?.replay_timeline?.replay_file===info.replay_file&&state.timeline?.replay_file!==info.replay_file)applyReplayInfo(info);
  }
}

async function poll() {
  if (state.pollInFlight || state.busy) return;
  state.pollInFlight = true;
  try { await refreshState(); }
  catch (error) {
    state.serviceReady = false;
    startupServiceError=error.message;
    $("telemetryStatus").textContent = state.sample ? "数据已过期" : "服务未连接";
    showServiceError(error.message);
    updateButtons();
  } finally { state.pollInFlight = false; }
}

async function action(task) {
  if (state.busy) return;
  state.busy = true;
  updateButtons();
  try { await task(); }
  catch (error) { notify(error.message || "操作未完成，请重试。", true); }
  finally {
    state.busy = false; updateButtons();
  }
}

function updateKeyframeCount() {
  $("keyframeCount").textContent = Object.values(state.tracks || {}).flat().length + ' 点';
}

function updateTimingExplanation() {
  $("paneCurve").title="七条属性轨道各自遵守关键帧时间。平滑位置使用保形三次曲线，各坐标不越过相邻关键帧数值；角度和缩放按各自时间插值，缓动应用到相邻关键帧段。";
}

async function saveProject(allowOverwrite = false) {
  clearTimeout(autoSaveTimer);
  if(autoSavePromise)await autoSavePromise;
  if (state.pendingProject && state.dirty && !allowOverwrite) throw new Error("其他窗口已更新项目，请先载入服务端项目，或点击“覆盖并保存”。");
  const previewView=BlitzEditorSession.capturePreview(replayPreviewPane),path=state.projectPath;
  clearTimeout(draftTimer);state.previewSequence++;
  await api("/api/project/edit", {...editPayload(), expected_revision: state.serverRevision});
  state.savingTimeline=true;
  try{await refreshState(true);}finally{state.savingTimeline=false;}
  if(state.projectPath===path&&previewView)BlitzEditorSession.restorePreview(replayPreviewPane,previewView);
}

function queueAutoSave(){
  clearTimeout(autoSaveTimer);
  autoSaveTimer=setTimeout(()=>autoSaveDraft(),1500);
}
function editorInteracting(){return !!(sequenceEditor?.drag||sequenceEditor?.numberEdit||speedCurveEditor?.drag);}
async function autoSaveDraft(){
  if(!state.loaded||!state.dirty||state.busy||state.playback.active||!state.serviceReady||state.pendingProject||editorInteracting()){if(state.dirty)queueAutoSave();return;}
  if(autoSavePromise){queueAutoSave();return autoSavePromise;}
  const path=state.projectPath,payload=editPayload(),signature=JSON.stringify(payload),revision=state.serverRevision;
  autoSavePromise=(async()=>{
    try{
      const data=await api('/api/project/edit',{...payload,expected_revision:revision});
      if(state.projectPath!==path)return;
      state.stateSequence++;state.appliedSequence=state.stateSequence;
      state.serverRevision=data.project_revision;state.project=data.project;state.projectHash=JSON.stringify(data.project);
      state.pendingProject=null;$('externalChange').hidden=true;
      // Direct drags live in the editor until release, so the last committed
      // payload can still equal this older save while a newer edit is visible.
      setDirty(editorInteracting()||JSON.stringify(editPayload())!==signature);
      lastEditorError='';
    }catch(error){
      if(error.message!==lastEditorError){lastEditorError=error.message;notify('自动保存未完成：'+error.message,true);}
      if(state.projectPath===path&&state.dirty)queueAutoSave();
    }finally{autoSavePromise=null;}
  })();
  return autoSavePromise;
}
function captureEditorSession(){
  if(!state.loaded||!state.projectPath||!sequenceEditor?.doc)return null;
  const preview=state.shootingMode==='replay'?(BlitzEditorSession.capturePreview(replayPreviewPane)||pendingPreviewRestore):null;
  return {schema_version:1,timeline:BlitzEditorSession.captureTimeline(sequenceEditor,state.previewTime),
    path_view:{view:state.view,yaw:state.yaw,elevation:state.elevation,zoom:state.zoom,pan:[...state.pan]},
    preview,inspector:Object.keys(TAB_PANES).find(n=>$('tab'+n).classList.contains('active'))||'Camera',splits:{v:splitV,h:splitH}};
}
function restorePreviewSession(){if(!pendingEditorRestore&&pendingPreviewRestore&&BlitzEditorSession.restorePreview(replayPreviewPane,pendingPreviewRestore))pendingPreviewRestore=null;}
function restoreEditorSession(){
  if(!pendingEditorRestore||!state.loaded||!sequenceEditor?.doc||sequenceEditor.scroll.clientWidth<=0)return;
  const saved=pendingEditorRestore;pendingEditorRestore=null;
  if(saved.splits&&Number.isFinite(saved.splits.v)&&Number.isFinite(saved.splits.h)){splitV=Math.max(.1,Math.min(.85,saved.splits.v));splitH=Math.max(.1,Math.min(.9,saved.splits.h));applySplits();}
  BlitzEditorSession.restoreTimeline(sequenceEditor,saved.timeline);
  const v=saved.path_view;
  if(v&&['3d','xy','xz','yz'].includes(v.view)&&[v.yaw,v.elevation,v.zoom,...(v.pan||[])].every(Number.isFinite)&&v.pan?.length===2){state.view=v.view;state.yaw=v.yaw;state.elevation=v.elevation;state.zoom=Math.max(.08,Math.min(40,v.zoom));state.pan=[...v.pan];document.querySelectorAll('.view-button[data-view]').forEach(b=>{const active=b.dataset.view===state.view;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});}
  if(TAB_PANES[saved.inspector]&&(!isCameraOnly()||saved.inspector!=='Speed'))showTab(saved.inspector);
  updateTimeline();drawCanvas();restorePreviewSession();
}
async function persistEditorSession(keepalive=false,withDraft=false){
  const value=captureEditorSession();if(!value||pendingEditorRestore)return;
  const signature=JSON.stringify(value),path=state.projectPath;
  value.saved_at=Date.now();BlitzEditorSession.writeLocal(localStorage,path,value);
  if(!keepalive&&editorSavePromise){await editorSavePromise;return persistEditorSession(false,withDraft);}
  if(!keepalive&&signature===lastEditorSignature)return;
  const body={project_path:path,value};
  if(withDraft&&state.dirty&&!state.pendingProject&&!state.playback.active&&!autoSavePromise&&!editorInteracting()){body.draft=editPayload();body.expected_revision=state.serverRevision;}
  const request=fetch('/api/ui/editor',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),keepalive});
  if(keepalive){request.catch(()=>{});return;}
  editorSavePromise=(async()=>{const response=await request;if(!response.ok){const data=await response.json();throw Error(data.error||'编辑器状态保存失败。');}lastEditorSignature=signature;})();
  try{await editorSavePromise;}finally{editorSavePromise=null;}
}
window.BlitzFlushEditorSession=async()=>{
  window.BlitzNumbers?.finish();finishEaseDrag?.(false);
  clearTimeout(autoSaveTimer);if(autoSavePromise)await autoSavePromise;
  if(state.dirty)await saveProject();
  // A final state request is awaited by the desktop host before it closes the service.
  lastEditorSignature='';await persistEditorSession();return true;
};

async function refreshPreview() {
  const sequence = ++state.previewSequence;
  startupSamples={ready:false,error:''};
  stopPlayback();
  if (!state.savedControls.length) { setSamples([], null); startupSamples.ready=true; return; }
  $("samplingIndicator").textContent = "正在计算轨迹…";
  try {
    const result = await api("/api/sample", {rate_hz: state.previewRate});
    if (sequence !== state.previewSequence) return;
    const samples = result.samples || [];
    if (!samples.every(s => finite(s.time_sec) && Array.isArray(s.position) && s.position.length === 3 && s.position.every(finite)
      && Array.isArray(s.quaternion) && s.quaternion.length === 4 && s.quaternion.every(finite) && finite(s.horizontal_fov_deg))) {
      throw new Error("轨迹采样数据格式不正确，无法预演。");
    }
    setSamples(samples, result);
    startupSamples.ready=true;
    if(state.dirty)queueDraftPreview();
  } catch (error) {
    if (sequence !== state.previewSequence) return;
    setSamples([], null);
    startupSamples.error=error.message;
    $("samplingIndicator").textContent = "采样未完成";
    notify(`轨迹预演：${error.message}`, true);
  }
}

function setSamples(samples, metadata) {
  state.samples = samples;
  const start = samples[0]?.time_sec ?? 0;
  const end = samples.at(-1)?.time_sec ?? start;
  // Saving/re-sampling a path must not seek the editor's playhead.
  state.previewTime = isCameraOnly()?Math.max(0,state.previewTime):Math.max(0,Math.min(state.timeline?.duration_sec??end,state.previewTime));
  $("pathLength").textContent = numberText(metadata?.length, 3);
  $("pathDuration").textContent = numberText(isCameraOnly()?samples.at(-1)?.time_sec:metadata?.duration, 3);
  $("sampleCount").textContent = samples.length ? String(samples.length) : "—";
  $("samplingIndicator").textContent = samples.length ? `${state.previewRate} Hz · 离线采样` : "等待轨迹";
  updatePreviewRange();
  $("canvasEmpty").hidden = samples.length > 0;
  updateTimeline(); updateButtons(); fitView(false);restoreEditorSession();
}
function updatePreviewRange(){const start=0,end=isCameraOnly()?Math.max(1,state.previewTime,state.samples.at(-1)?.time_sec||0):state.timeline?.duration_sec??state.samples.at(-1)?.time_sec??1;$("timelineStart").textContent=`${start.toFixed(3)} s`;$("timelineEnd").textContent=`${end.toFixed(3)} s`;$("timelineSlider").min=start;$("timelineSlider").max=end;}

function updateTimeline() {
  $("timelineSlider").value = state.previewTime;
  $("timelineCurrent").textContent = `${state.previewTime.toFixed(3)} s`;
  sequenceEditor?.updatePlayhead(state.previewTime);
  drawSpeedGraph();
}
function stopPlayback() {
  state.previewPlaySequence++;
  state.playing = false;
  if (state.animationRequest) cancelAnimationFrame(state.animationRequest);
  state.animationRequest = 0;
  setIcon($("playButton"), "i-play"); $("playButton").setAttribute("aria-label", "播放离线预演");
}
function seek(time) {
  stopPlayback();
  if (!state.samples.length&&!replayPreviewPane?.sampler) return;
  state.previewTime = isCameraOnly()?Math.max(0,time):Math.max(0,Math.min(state.timeline?.duration_sec??state.samples.at(-1)?.time_sec??1,time));
  if(isCameraOnly()){$("captureTime").value=state.previewTime.toFixed(6);updatePreviewRange();}
  updateTimeline(); drawCanvas();
}
function offlinePreviewClock(speed=speedSettings()) {
  const end=state.samples.at(-1)?.time_sec??0;
  const timeline=!isCameraOnly()&&state.timeline?state.timeline:{duration_sec:end,work_start_sec:0,work_end_sec:end};
  return new BlitzTimeline.ClockMap(state.tracks||{x:state.samples},speed,timeline);
}
async function play() {
  if (state.playing) { stopPlayback(); return; }
  const sequence=++state.previewPlaySequence;
  if(state.dirty)await refreshDraftPreview();
  if(sequence!==state.previewPlaySequence||sequenceEditor?.drag?.kind==='work')return;
  if (state.samples.length < 2&&(isCameraOnly()||replayPreviewPane?.status!=='ready')) return;
  if (!BlitzPreviewTime.valid(speedSettings())) {notify("请修正速度关键帧后预览。",true);return;}
  const clock=offlinePreviewClock();
  if (!(clock.seconds>0)) return;
  if (state.previewTime >= clock.end || state.previewTime<clock.start) state.previewTime = clock.start;
  state.playing = true; state.playbackStart = state.previewTime; state.playbackAnchor = performance.now();
  setIcon($("playButton"), "i-pause"); $("playButton").setAttribute("aria-label", "暂停离线预演");
  state.animationRequest = requestAnimationFrame(animate);
}
function animate(now) {
  state.animationRequest = 0;
  if (!state.playing) return;
  const clock=offlinePreviewClock();
  const speed = Number($("previewSpeed").value);
  let elapsed=clock.atTime(state.playbackStart)+(now-state.playbackAnchor)/1000*speed;
  if (elapsed >= clock.seconds) {
    if (state.loop&&clock.seconds>0) elapsed%=clock.seconds;
    else {elapsed=clock.seconds;stopPlayback();}
  }
  state.previewTime = clock.atSeconds(elapsed); updateTimeline(); drawCanvas();
  if (state.playing) state.animationRequest = requestAnimationFrame(animate);
}
function nearestSample(time) {
  let lo = 0, hi = state.samples.length - 1;
  while (lo < hi) { const mid = Math.floor((lo + hi) / 2); if (state.samples[mid].time_sec < time) lo = mid + 1; else hi = mid; }
  if (lo > 0 && time - state.samples[lo - 1].time_sec < state.samples[lo].time_sec - time) lo--;
  return {sample: state.samples[lo], index: lo};
}

// World-coordinate camera paths on an auxiliary grid, offline only.
const canvas = $("pathCanvas");
const ctx = canvas.getContext("2d");
function basisProject(point) {
  const [x, y, z] = point;
  if (state.view === "xy") return [x, -y];
  if (state.view === "xz") return [x, -z];
  if (state.view === "yz") return [y, -z];
  const c = Math.cos(state.yaw), s = Math.sin(state.yaw), e = Math.sin(state.elevation), ce = Math.cos(state.elevation);
  return [x * c + y * s, x * s * e - y * c * e - z * ce];
}
function project(point) {
  const value = basisProject(point.map((v, i) => v - state.center[i]));
  const scale = state.baseScale * state.zoom;
  return [state.canvasWidth / 2 + value[0] * scale + state.pan[0], state.canvasHeight / 2 + value[1] * scale + state.pan[1]];
}
function resizeCanvas() {
  const rect = canvas.parentElement.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const ratio = window.devicePixelRatio || 1;
  const w = Math.round(rect.width * ratio), h = Math.round(rect.height * ratio);
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  state.canvasWidth = Math.max(1, rect.width); state.canvasHeight = Math.max(1, rect.height);
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  fitView(false);
}
function fitView(reset=true) {
  const points = state.samples.map(s => s.position);
  if (!points.length) points.push([-10, -10, 0], [10, 10, 0]);
  const min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity];
  points.forEach(p => p.forEach((v, i) => { min[i] = Math.min(min[i], v); max[i] = Math.max(max[i], v); }));
  state.bounds = {min, max}; state.center = min.map((v, i) => (v + max[i]) / 2);
  state.extent = Math.max(4, ...max.map((v, i) => v - min[i]));
  const screen = points.map(p => basisProject(p.map((v, i) => v - state.center[i])));
  const lo = [Infinity, Infinity], hi = [-Infinity, -Infinity];
  screen.forEach(p => p.forEach((v, i) => { lo[i] = Math.min(lo[i], v); hi[i] = Math.max(hi[i], v); }));
  const dx = Math.max(4, hi[0] - lo[0]);
  const dy = Math.max(4, hi[1] - lo[1]);
  state.baseScale = Math.min(Math.max(100, state.canvasWidth - 160) / dx, Math.max(100, state.canvasHeight - 125) / dy);
  if(reset){state.zoom=1;state.pan=[0,0];}drawCanvas();
}
function line(a, b, color, width = 1, dash = []) {
  const pa = project(a), pb = project(b);
  ctx.beginPath(); ctx.moveTo(...pa); ctx.lineTo(...pb); ctx.strokeStyle = color; ctx.lineWidth = width; ctx.setLineDash(dash); ctx.stroke(); ctx.setLineDash([]);
}
function niceStep(size) {
  const power = 10 ** Math.floor(Math.log10(Math.max(size, 1e-6)));
  const n = size / power;
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * power;
}
function drawGrid() {
  const step = niceStep(state.extent / 8);
  const center = state.center.map(v => Math.round(v / step) * step);
  const axes = state.view === "xz" ? [0, 2] : state.view === "yz" ? [1, 2] : [0, 1];
  const plane = state.view === "3d" || state.view === "xy" ? 2 : state.view === "xz" ? 1 : 0;
  center[plane] = state.view === "3d" ? state.bounds.min[2] : state.center[plane];
  for (let i = -7; i <= 7; i++) {
    for (const [a, b] of [axes, [axes[1], axes[0]]]) {
      const p = [...center], q = [...center]; p[a] += i * step; q[a] += i * step;
      p[b] -= 7 * step; q[b] += 7 * step;
      line(p, q, i === 0 ? "#35454d88" : "#30424c45", i === 0 ? 0.9 : 0.65);
    }
  }
  ctx.fillStyle = "#526c78"; ctx.font = '8px Consolas, monospace'; ctx.textAlign = "right";
  ctx.fillText(`GRID ${Number(step.toPrecision(3))} u`, state.canvasWidth - 20, state.canvasHeight - 35);
}
function rotate(q, v) {
  // pose.py convention: local +X right, +Y up, -Z forward, quaternion wxyz.
  const [w, x, y, z] = q, [vx, vy, vz] = v;
  const tx = 2 * (y * vz - z * vy), ty = 2 * (z * vx - x * vz), tz = 2 * (x * vy - y * vx);
  return [vx + w * tx + y * tz - z * ty, vy + w * ty + z * tx - x * tz, vz + w * tz + x * ty - y * tx];
}
function add(a, b, scale = 1) { return a.map((v, i) => v + b[i] * scale); }
function drawCamera(sample) {
  const p = sample.position;
  const forward = rotate(sample.quaternion, [0, 0, -1]);
  const right = rotate(sample.quaternion, [1, 0, 0]);
  const up = rotate(sample.quaternion, [0, 1, 0]);
  const length = Math.max(state.extent * 0.13, 0.4);
  const width = Math.tan(sample.horizontal_fov_deg * Math.PI / 360) * length;
  const end = add(p, forward, length);
  const corners = [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([x, y]) => add(add(end, right, x * width), up, y * width * 9 / 16));
  const point = project(p);
  const left = project(add(end, right, -width)), rightEdge = project(add(end, right, width));
  ctx.beginPath(); ctx.moveTo(...point); ctx.lineTo(...left); ctx.lineTo(...rightEdge); ctx.closePath();
  ctx.fillStyle = "#80ccd015"; ctx.fill();
  corners.forEach((corner, i) => { line(p, corner, "#84d5d174", 0.8); line(corner, corners[(i + 1) % 4], "#84d5d1aa", 0.85); });
  line(p, end, "#8dddd5", 1.2, [4, 3]);
  line(p, add(p, up, length * 0.42), "#bedb87", 1.5);
  ctx.beginPath(); ctx.arc(...point, 5, 0, Math.PI * 2); ctx.fillStyle = "#b3f1e4"; ctx.shadowColor = "#86d5cc"; ctx.shadowBlur = 13; ctx.fill(); ctx.shadowBlur = 0;
  ctx.beginPath(); ctx.arc(...point, 10, 0, Math.PI * 2); ctx.strokeStyle = "#8bded754"; ctx.lineWidth = 1; ctx.stroke();
  ctx.textAlign = "left"; ctx.font = '9px Consolas, monospace'; ctx.fillStyle = "#a2c4c5";
  ctx.fillText(`${sample.horizontal_fov_deg.toFixed(1)}°`, point[0] + 14, point[1] - 10);
}
function drawAxes() {
  const origin = [state.canvasWidth - 46, 57];
  const axes = [[[1, 0, 0], "#d7a08e", "X"], [[0, 1, 0], "#b1c781", "Y"], [[0, 0, 1], "#8aaecf", "Z"]];
  ctx.font = '9px Consolas, monospace'; ctx.textAlign = "center";
  axes.forEach(([axis, color, name]) => {
    const p = basisProject(axis); const end = [origin[0] + p[0] * 21, origin[1] + p[1] * 21];
    if (Math.hypot(...p) < 0.1) return;
    ctx.beginPath(); ctx.moveTo(...origin); ctx.lineTo(...end); ctx.strokeStyle = color; ctx.lineWidth = 1; ctx.stroke();
    ctx.fillStyle = color; ctx.fillText(name, end[0] + p[0] * 7, end[1] + p[1] * 7 + 3);
  });
}
function drawCanvas() {
  syncReplayPreview();
  if (!ctx) return;
  ctx.clearRect(0, 0, state.canvasWidth, state.canvasHeight);
  drawGrid();
  drawAxes();
  if (!state.samples.length) return;
  const current = nearestSample(state.previewTime);
  function drawPath(samples, color, width) {
    if (samples.length < 2) return;
    ctx.beginPath(); samples.forEach((s, i) => { const p = project(s.position); if (!i) ctx.moveTo(...p); else ctx.lineTo(...p); });
    ctx.lineJoin = "round"; ctx.lineCap = "round";
    ctx.strokeStyle = color; ctx.lineWidth = width; ctx.stroke();
  }
  drawPath(state.samples, "#98ae6a75", 1.6);
  drawPath(state.samples.slice(0, current.index + 1), "#d0ec88", 2.1);
  drawCamera(current.sample);
}

$("connectButton").addEventListener("click", () => action(async () => {
  $("connectionLabel").textContent = "正在连接"; $("connectionDot").className = "status-dot connecting";
  await api("/api/connect", {}); await refreshState();
  if (state.connection.state === "connected") notify("已连接客户端，只读采样已开启。");
}));
$("disconnectButton").addEventListener("click", () => action(async () => {
  await api("/api/disconnect", {}); await refreshState(); notify("已断开客户端，离线轨迹仍可编辑。");
}));
$("captureTime").addEventListener("input", () => { state.captureTimeEdited = true; });
$("newPathButton").addEventListener("click", () => action(async () => {
  if (state.dirty && state.controls.length) await saveProject();
  await api("/api/project/new",{expected_revision:state.serverRevision});await refreshState(true);
  notify("已用当前七项属性新建动画；原项目已存入 project-history。");
}));
async function startLive(reverse,mode=isCameraOnly()?'current':'auto') {
  if(state.pendingProject&&state.dirty)throw new Error("请先处理服务端项目更新，再播放。");
  if(state.dirty||state.project?.shooting_mode!==state.shootingMode)await saveProject();
  stopPlayback();await api("/api/playback/start",{reverse,mode,orientation_enabled:true,fov_enabled:true,expected_revision:state.serverRevision});await refreshState();
}
$("liveForward").addEventListener("click",()=>action(()=>startLive(false)));
$("liveSeekStart").addEventListener("click",()=>action(()=>startLive(false,'locate')));
$("liveReverse").addEventListener("click",()=>action(()=>startLive(true)));
async function stopLive() {
  try {await api("/api/playback/stop",{});await refreshState();}
  catch(error){notify(error.message,true);}
}
$("livePause").addEventListener("click",()=>action(async()=>{await api("/api/playback/pause",{paused:state.playback.state!=="paused"});await refreshState();}));
$("liveStop").addEventListener("click",stopLive);
document.addEventListener("keydown",event=>{if(event.key==="Escape"&&state.playback.active){event.preventDefault();stopLive();}});
$("captureButton").addEventListener("click", () => action(async () => {
  const raw = $("captureTime").value.trim(), time = Number(raw);
  if (!raw || !finite(time)) throw new Error("请输入有效的关键帧时间。");
  if (state.pendingProject && state.dirty) throw new Error("服务端项目已更新。请先载入服务端项目，或明确保存当前草稿，再记录属性关键帧。");
  if (state.dirty||state.project?.shooting_mode!==state.shootingMode) await saveProject();
  await api("/api/capture", {time_sec: time, replace_existing: $("replaceExisting").checked, expected_revision: state.serverRevision});
  $("replaceExisting").checked = false;
  state.savingTimeline=true;
  try{await refreshState(true);}finally{state.savingTimeline=false;}
  seek(isCameraOnly()?time:state.sample?.replay?.time??time);updateKeyframeCount(); notify(`已记录全部七项属性关键帧，${isCameraOnly()?"镜头":"对局"}时间 ${numberText(isCameraOnly()?time:state.sample?.replay?.time??time)} 秒。`);
}));
$("saveButton").addEventListener("click", () => action(async () => { await saveProject(true); notify("关键帧已保存，正在更新离线预演。"); }));
for (const id of ["timingSelect", "easingSelect", "interpolationSelect"]) $(id).addEventListener("change", () => { stopPlayback();setDirty(true);updateTimingExplanation();queueDraftPreview(); });
$("reloadProjectButton").addEventListener("click", () => action(async () => { await refreshState(true); notify("已载入服务端项目。"); }));
async function guardDirty(next) {
  await persistEditorSession();
  if(autoSavePromise)await autoSavePromise;
  if (!state.dirty) return next();
  const modal = $("draftGuard"); modal.hidden = false;
  const choice = await new Promise(resolve => {
    const done = v => { modal.hidden = true; $("draftSave").onclick = $("draftDiscard").onclick = $("draftCancel").onclick = null; resolve(v); };
    $("draftSave").onclick = () => done('save');
    $("draftDiscard").onclick = () => done('discard');
    $("draftCancel").onclick = () => done('cancel');
  });
  if (choice === 'cancel') return;
  if (choice === 'save') await saveProject(true);
  else clearTimeout(autoSaveTimer);
  return next();
}
function openProjectFlow(path) {
  return action(async () => {
    const result = await api("/api/projects/open", path ? {path} : {}, {timeout: 0});
    if (result.cancelled) return;
    await refreshState(true); showHome(false); notify("已打开项目。");
  });
}
$("importButton").addEventListener("click", () => guardDirty(() => openProjectFlow()));
$("exportButton").addEventListener("click", () => guardDirty(() => action(async () => {
  const result = await api("/api/projects/save_as", {}, {timeout: 0});
  if (result.cancelled) return;
  await refreshState(true); notify("项目已另存为。");
})));
$("playButton").addEventListener("click", play);
$("timelineSlider").addEventListener("input", event => seek(Number(event.target.value)));
$("previewSpeed").addEventListener("change", () => { if (state.playing) { state.playbackStart = state.previewTime; state.playbackAnchor = performance.now(); } });
$("loopButton").addEventListener("click", () => { state.loop = !state.loop; $("loopButton").setAttribute("aria-pressed", String(state.loop)); });
$("fitButton").addEventListener("click", () => fitView());
document.querySelectorAll(".view-button[data-view]").forEach(button => button.addEventListener("click", () => {
  state.view = button.dataset.view;
  document.querySelectorAll(".view-button[data-view]").forEach(b => { b.classList.toggle("active", b === button); b.setAttribute("aria-pressed", String(b === button)); });
  fitView();
}));
let drag = null;
canvas.addEventListener("pointerdown", event => {
  if (event.button !== 0) return;
  canvas.setPointerCapture(event.pointerId); drag = {x: event.clientX, y: event.clientY};
});
canvas.addEventListener("pointermove", event => {
  if (!drag) return;
  const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
  drag = {x: event.clientX, y: event.clientY};
  if (state.view === "3d") { state.yaw += dx * 0.007; state.elevation = Math.max(-1.4, Math.min(1.4, state.elevation + dy * 0.006)); }
  else { state.pan[0] += dx; state.pan[1] += dy; }
  drawCanvas();
});
canvas.addEventListener("pointerup", () => { drag = null; });
canvas.addEventListener("pointercancel", () => { drag = null; });
canvas.addEventListener("lostpointercapture", () => { drag = null; });
canvas.addEventListener("wheel", event => { event.preventDefault(); state.zoom = Math.max(0.08, Math.min(40, state.zoom * Math.exp(-event.deltaY * 0.001))); drawCanvas(); }, {passive: false});
document.addEventListener("keydown", event => {
  if(window.BlitzStartup?.active)return;
  if(state.settingsOpen){
    if(event.key==='Escape'&&!state.busy){event.preventDefault();closeSettings();}
    if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){event.preventDefault();if(!$('settingsSave').disabled)$('settingsForm').requestSubmit();}
    return;
  }
  if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){
    event.preventDefault();window.BlitzNumbers?.finish();finishEaseDrag?.(false);if(state.dirty&&!state.busy&&!state.playback.active)action(async()=>{await saveProject(true);notify('时间轴已保存。');});return;
  }
  const k=event.key.toLowerCase();
  const textEntry=event.target.closest('input,textarea,[contenteditable=true]');
  if((event.ctrlKey||event.metaKey)&&['z','y'].includes(k)&&(!textEntry||event.target.closest('#paneSpeed,#keyInspector,.ce-grid2,#easeContinuous'))){
    event.preventDefault();
    if(k==='z'&&!event.shiftKey&&window.BlitzNumbers?.active){BlitzNumbers.finish(true,true);return;}
    window.BlitzNumbers?.finish();finishEaseDrag?.(false);if(textEntry)event.target.blur();stopPlayback();sequenceEditor?.action(k==='y'||event.shiftKey?'redo':'undo');return;
  }
  if (event.target.closest('input,select,textarea,button,[contenteditable=true]')) return;
  if(!event.ctrlKey&&!event.metaKey&&!event.altKey&&k==='s'&&!event.repeat){event.preventDefault();sequenceEditor?.action('snap');return;}
  if(!event.ctrlKey&&!event.metaKey&&!event.altKey&&(k==='i'||k==='o')&&!isCameraOnly()){
    const t=sequenceEditor?.doc?.timeline;if(!t)return;
    if(event.shiftKey){if(!event.repeat)seek(k==='i'?t.work_start_sec:t.work_end_sec);return;}
    if(event.repeat)return;
    event.preventDefault();
    sequenceEditor.edit(()=>{
      const h=Math.max(0,Math.min(t.duration_sec,sequenceEditor.playhead));
      if(k==='i'){t.work_start_sec=h;if(t.work_start_sec>=t.work_end_sec)t.work_end_sec=Math.min(t.duration_sec,t.work_start_sec+0.001);}
      else{t.work_end_sec=h;if(t.work_end_sec<=t.work_start_sec)t.work_start_sec=Math.max(0,t.work_end_sec-0.001);}
    });return;
  }
  if (event.code === "Space") { event.preventDefault(); play(); }
  if (event.code === "ArrowLeft" || event.code === "ArrowRight") { event.preventDefault(); seek(state.previewTime + (event.code === "ArrowRight" ? 1 : -1) / state.previewRate); }
});
window.addEventListener("beforeunload", event => {persistEditorSession(true,true);if(state.dirty){event.preventDefault();event.returnValue="";} });
window.addEventListener('pagehide',()=>persistEditorSession(true,true));
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden'){autoSaveDraft();persistEditorSession(true,true);}});
new ResizeObserver(resizeCanvas).observe($("canvasWrap"));
const EASE_BUILTINS=[
  ["线性",[0,0,1,1]],["缓入缓出",[.42,0,.58,1]],["缓入",[.42,0,1,1]],["缓出",[0,0,.58,1]],
  ["正弦入",[.12,0,.39,0]],["正弦出",[.61,1,.88,1]],["正弦",[.37,0,.63,1]],
  ["二次入",[.11,0,.5,0]],["二次出",[.5,1,.89,1]],["二次",[.45,0,.55,1]],
  ["三次入",[.32,0,.67,0]],["三次出",[.33,1,.68,1]],["三次",[.65,0,.35,1]],
  ["四次入",[.5,0,.75,0]],["四次出",[.25,1,.5,1]],["四次",[.76,0,.24,1]],
  ["五次入",[.64,0,.78,0]],["五次出",[.22,1,.36,1]],["五次",[.83,0,.17,1]],
  ["指数入",[.7,0,.84,0]],["指数出",[.16,1,.3,1]],["指数",[.87,0,.13,1]],
  ["圆入",[.55,0,1,.55]],["圆出",[0,.55,.45,1]],["圆",[.85,0,.15,1]],
];
const easeState={ctrl:[.42,0,.58,1],mixed:false,automatic:false};
let curveMath=null;import("/curve-core.js").then(m=>{curveMath=m;drawEaseGraph();renderPresetGrid();});
function easeTargets(){
  if(!sequenceEditor?.doc)return [];
  const out=[];
  for(const keys of Object.values(sequenceEditor.doc.tracks)){
    const selCount=keys.filter(k=>sequenceEditor.selected.has(k._id)).length;
    keys.forEach((k,i)=>{
      const next=keys[i+1];if(!next)return;
      if((sequenceEditor.selected.has(k._id)&&sequenceEditor.selected.has(next._id))||(selCount===1&&sequenceEditor.selected.has(k._id)))out.push(k);
    });
  }
  return out;
}
function syncEaseInputs(){for(const [id,i]of[["easeX1",0],["easeY1",1],["easeX2",2],["easeY2",3]])if(document.activeElement!==$(id))$(id).value=Number(easeState.ctrl[i].toFixed(4));}
function easePreviewSegment(){
  const targets=new Set(easeTargets()),choices=[];
  if(!sequenceEditor?.doc)return null;
  for(const [name,rows]of Object.entries(sequenceEditor.doc.tracks))rows.forEach((key,i)=>{if(targets.has(key)&&rows[i+1])choices.push({name,rows,i});});
  return choices.find(c=>c.rows[c.i].value!==c.rows[c.i+1].value)||choices[0];
}
function refreshEaseUI(){
  if(!sequenceEditor?.doc)return;
  const targets=easeTargets(),eases=[...new Set(targets.map(k=>JSON.stringify([k.ease||null,k.curve||null])))];
  $("curveEditor").classList.toggle('disabled',!targets.length);
  for(const id of ['easeX1','easeY1','easeX2','easeY2'])$(id).disabled=!targets.length||!!sequenceEditor.locked;
  $("curveSegmentInfo").textContent=!targets.length?'选择相邻关键帧':`${targets.every(k=>k.curve==='auto')?'连续通过':targets.some(k=>k.curve==='auto')?'混合衔接':'逐段缓动'} · ${targets.length} 段${eases.length>1?' · 多种模板':''}`;
  const shown=easePreviewSegment(),key=shown?.rows[shown.i];
  if(key){easeState.automatic=key.curve==='auto'&&!key.ease;easeState.ctrl=key.ease?[...key.ease]:easeState.automatic?[1/3,0,2/3,1]:[0,0,1,1];}
  easeState.mixed=eases.length>1;
  syncEaseInputs();drawEaseGraph();
}
function drawEaseGraph(){
  const svg=$("easeGraph"),[x1,y1,x2,y2]=easeState.ctrl;
  const X=v=>(v*120).toFixed(2),Y=v=>(120-v*120).toFixed(2);
  let d='M 0 120';
  if(curveMath)for(let i=1;i<=40;i++){const [bx,by]=curveMath.bezierXY(i/40,easeState.ctrl);d+=` L ${X(bx)} ${Y(by)}`;}
  let actual='',label='实线：选中分段 · 虚线：模板';
  if(curveMath){
    const choice=easePreviewSegment();
    if(choice){
      const {name,rows,i}=choice,a=rows[i],b=rows[i+1],delta=b.value-a.value;
      const f=curveMath.scalarTrack(rows,['x','y','z'].includes(name)&&$('interpolationSelect').value==='smooth',$('easingSelect').value);
      for(let j=0;j<=80;j++){const u=j/80,v=delta?(f(a.time_sec+(b.time_sec-a.time_sec)*u)-a.value)/delta:0;actual+=`${j?' L':'M'} ${X(u)} ${Y(v)}`;}
      const channel={x:'X',y:'Y',z:'Z',yaw:'水平角度',pitch:'俯仰',roll:'横滚',zoom:'缩放'}[name];
      label=`实线：${channel} ${a.time_sec.toFixed(2)}–${b.time_sec.toFixed(2)} s · 虚线：模板`;
    }
  }
  $('easeCurveInfo').textContent=label;
  svg.innerHTML=[30,60,90].map(g=>`<line x1="${g}" y1="0" x2="${g}" y2="120" class="ez-grid"/><line x1="0" y1="${g}" x2="120" y2="${g}" class="ez-grid"/>`).join('')
    +`<line x1="0" y1="120" x2="120" y2="0" class="ez-ref"/>`
    +`<line x1="0" y1="120" x2="${X(x1)}" y2="${Y(y1)}" class="ez-tan"/><line x1="120" y1="0" x2="${X(x2)}" y2="${Y(y2)}" class="ez-tan"/>`
    +`<path d="${d}" class="${actual?'ez-template':'ez-curve'}"/>${actual?`<path d="${actual}" class="ez-curve"/>`:''}`
    +`<circle class="ez-h" data-h="0" cx="${X(x1)}" cy="${Y(y1)}" r="5"/><circle class="ez-h" data-h="1" cx="${X(x2)}" cy="${Y(y2)}" r="5"/>`;
  for(const button of $('easePresets').querySelectorAll('button[data-curve]'))button.setAttribute('aria-pressed',String(!easeState.mixed&&button.dataset.curve===JSON.stringify(easeState.automatic?null:easeState.ctrl)));
}
const loadEasePresets=()=>{try{return JSON.parse(localStorage.getItem('blitz-curve-presets'))||[];}catch{return[];}};
const saveEasePresets=list=>localStorage.setItem('blitz-curve-presets',JSON.stringify(list));
function miniCurvePath(ease,size=30){
  if(!curveMath)return '';
  let d=`M 0 ${size}`;
  for(let i=1;i<=16;i++){const [bx,by]=curveMath.bezierXY(i/16,ease);d+=` L ${(bx*size).toFixed(1)} ${(size-by*size).toFixed(1)}`;}
  return `<path d="${d}"/>`;
}
function renderPresetGrid(){
  const grid=$("easePresets");grid.replaceChildren();
  const item=(name,ease,user)=>{
    const b=document.createElement('button');b.type='button';b.className='ez-preset';b.title=`${name} · 单击应用到选中分段 · Ctrl+Z 撤销`;b.dataset.curve=JSON.stringify(ease);
    b.innerHTML=`<svg viewBox="0 0 30 30">${miniCurvePath(ease||[1/3,0,2/3,1])}</svg><span>${name}</span>`;
    b.addEventListener('click',()=>{if(!easeTargets().length)return notify('先选择一个分段的起点，或框选相邻关键帧。');easeState.automatic=!ease;easeState.ctrl=[...(ease||[1/3,0,2/3,1])];if(!ease)$('easeContinuous').checked=true;applyEaseValues();});
    if(user){
      const rn=document.createElement('i');rn.className='ez-edit';rn.textContent='✎';rn.title='改名并重存';rn.addEventListener('click',e=>{e.stopPropagation();$("presetName").value=name;easeState.automatic=false;easeState.ctrl=[...ease];syncEaseInputs();drawEaseGraph();});b.append(rn);
      const del=document.createElement('i');del.className='ez-del';del.textContent='×';del.title='删除预设';del.addEventListener('click',e=>{e.stopPropagation();saveEasePresets(loadEasePresets().filter(p=>p.name!==name));renderPresetGrid();});b.append(del);
    }
    return b;
  };
  grid.append(item('自动衔接',null,false));
  for(const [name,ease]of EASE_BUILTINS)grid.append(item(name,ease,false));
  for(const p of loadEasePresets())grid.append(item(p.name,p.ease,true));
  drawEaseGraph();
}
function applyEaseValues(){
  const targets=easeTargets();if(!targets.length||!curveMath)return;
  const ctrl=easeState.automatic?null:[...easeState.ctrl],continuous=$('easeContinuous').checked;
  return sequenceEditor.edit(()=>curveMath.applyCurveTemplate(targets,ctrl,continuous));
}
$("easeContinuous").addEventListener("change",()=>{
  const targets=easeTargets(),continuous=$('easeContinuous').checked;
  if(targets.length)sequenceEditor.edit(()=>{for(const k of targets){if(continuous)k.curve='auto';else delete k.curve;}});
});
$("easeClear").addEventListener("click",()=>{
  const targets=easeTargets();if(!targets.length)return;
  sequenceEditor.edit(()=>{for(const k of targets){delete k.ease;delete k.curve;}});
});
for(const id of ['easingSelect','interpolationSelect'])$(id).addEventListener('change',drawEaseGraph);
for(const [id,i]of[["easeX1",0],["easeY1",1],["easeX2",2],["easeY2",3]])
  BlitzNumbers.configure($(id),{get:()=>easeState.ctrl[i],set:value=>{easeState.automatic=false;easeState.ctrl[i]=value;drawEaseGraph();return applyEaseValues();}});
$("presetSave").addEventListener("click",()=>{
  const name=$("presetName").value.trim();if(!name)return;
  saveEasePresets([...loadEasePresets().filter(p=>p.name!==name),{name,ease:[...easeState.ctrl]}]);
  $("presetName").value='';renderPresetGrid();
});
{
  const svg=$("easeGraph");let dragging=null,pointerId=null;
  const toCoord=e=>{const r=svg.getBoundingClientRect();
    return [Math.min(1,Math.max(0,((e.clientX-r.left)/r.width*132-6)/120)),
            Math.min(1,Math.max(0,1-((e.clientY-r.top)/r.height*132-6)/120))];};
  svg.addEventListener('pointerdown',e=>{const h=e.target.closest?.('.ez-h');if(e.button!==0||!h||!easeTargets().length||sequenceEditor.locked)return;dragging=Number(h.dataset.h);pointerId=e.pointerId;sequenceEditor.beginNumberEdit();svg.setPointerCapture(e.pointerId);e.preventDefault();});
  svg.addEventListener('pointermove',e=>{if(dragging==null)return;const [x,y]=toCoord(e);easeState.automatic=false;easeState.ctrl[dragging*2]=x;easeState.ctrl[dragging*2+1]=y;syncEaseInputs();drawEaseGraph();applyEaseValues();});
  const finish=cancelled=>{if(dragging==null)return;dragging=null;if(svg.hasPointerCapture(pointerId))svg.releasePointerCapture(pointerId);pointerId=null;sequenceEditor.endNumberEdit(cancelled);refreshEaseUI();};
  finishEaseDrag=finish;
  svg.addEventListener('pointerup',()=>finish(false));svg.addEventListener('pointercancel',()=>finish(true));
  svg.addEventListener('lostpointercapture',()=>finish(true));
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&dragging!==null){e.preventDefault();finish(true);}},true);
  window.addEventListener('blur',()=>finish(false));
}
sequenceEditor=new BlitzTimeline.Editor($("sequenceEditor"),{
  change:applyTimelineChange, seek:time=>seek(time), error:message=>notify(message,true),
  onWorkRangeDragStart:()=>stopPlayback(),
  clipboardScope:target=>!!target.closest('#paneSpeed,#paneCurve'),
  clipboardBusy:()=>!!(speedCurveEditor?.drag||state.settingsOpen||window.BlitzStartup?.active),
  keyframeGuard:keyframeGuardFor,
  inspector:$("keyInspector"), onSelection:()=>showTab([...sequenceEditor.selected].some(id=>sequenceEditor.locate(id)?.row.name==='rate')?'Speed':'Curve'), onInspect:()=>{refreshEaseUI();speedCurveEditor?.refresh();},
  currentTime:()=>state.sample?.replay?.paused?state.sample.replay.time:null,
  evaluate:async time=>(await api('/api/evaluate',{...editPayload(),time_sec:time})).values,
});
speedCurveEditor=new BlitzSpeedEditor($("paneSpeed"),sequenceEditor,{
  pause:stopPlayback,draw:drawSpeedGraph,seek,locked:()=>state.busy||state.playback.active||!state.serviceReady,error:message=>notify(message,true),
});
const projectNumber=input=>input.closest('#keyInspector,#paneSpeed,.ce-grid2,#speedRows');
document.addEventListener('number-start',event=>{if(projectNumber(event.target)){stopPlayback();sequenceEditor.beginNumberEdit();}});
document.addEventListener('number-end',event=>{if(projectNumber(event.target)){sequenceEditor.endNumberEdit(event.detail.cancelled);renderSpeedRows();}});
$("readReplayFile").onclick=async()=>{let info;await action(async()=>{info=await api('/api/replay/timeline',{path:$("replayFilePath").value.trim()});});if(info)applyReplayInfo(info);};
$("openReplayButton").onclick=()=>action(async()=>{await api('/api/replay/open',{});await refreshState();});
$("playProjectReplay").onclick=()=>action(async()=>{
  const path=state.timeline?.replay_file;
  if(!path)throw new Error('当前项目尚未绑定回放，请先载入回放。');
  await api('/api/replay/open_project',{});await refreshState();
});
$("useCurrentReplay").onclick=()=>{if(!state.replayInfo)return notify('未取得启动回放文件，请填写回放文件路径读取长度。',true);applyReplayInfo(state.replayInfo);};
function applyReplayInfo(info){
  if(isCameraOnly())return false;
  const previous=sequenceEditor.doc.timeline,fit=previous.replay_file!==info.replay_file||previous.duration_sec!==info.duration_sec;
  const bound=sequenceEditor.edit(()=>{
    const t=sequenceEditor.doc.timeline;t.duration_sec=info.duration_sec;t.replay_file=info.replay_file;
    const digest=info.replay_sha256||info.sha256;if(digest)t.replay_sha256=digest;else delete t.replay_sha256;
    for(const name of ['battle_start_sec','battle_start_raw_sec','replay_origin_sec','battle_start_status','battle_start_reason']){delete t[name];if(name in info)t[name]=info[name];}
    if(t.work_end_sec>t.duration_sec){t.work_start_sec=0;t.work_end_sec=Math.min(8,t.duration_sec);}
    const minimum=finite(state.replayKeyframeStartSeconds)?state.replayKeyframeStartSeconds:info.battle_start_status==='identified'?info.battle_start_sec:null;
    if(t.starter_keyframes_pending&&finite(minimum)&&minimum<t.duration_sec){
      const keys=Object.values(sequenceEditor.doc.tracks).flat(),first=Math.min(...keys.map(k=>k.time_sec)),last=Math.max(...keys.map(k=>k.time_sec));
      const scale=last>first?Math.min(1,(t.duration_sec-minimum)/(last-first)):1;
      const aligned=time=>Math.min(t.duration_sec,minimum+(time-first)*scale);
      for(const key of keys)key.time_sec=aligned(key.time_sec);
      if(sequenceEditor.doc.speed.time_range)sequenceEditor.doc.speed.time_range={start_sec:minimum,end_sec:aligned(last)};
      t.work_start_sec=minimum;t.work_end_sec=aligned(last);delete t.starter_keyframes_pending;
    }
    if(finite(minimum)&&t.work_start_sec<minimum&&minimum<t.duration_sec){
      const length=t.work_end_sec-t.work_start_sec;t.work_start_sec=minimum;
      if(t.work_end_sec<=minimum)t.work_end_sec=Math.min(t.duration_sec,minimum+length);
    }
  });
  if(!bound)return false;
  if(fit)sequenceEditor.fit();
  $("replayFilePath").value=info.replay_file;
  if(state.timeline?.replay_file===info.replay_file&&state.timeline.duration_sec===info.duration_sec){
    const src=$("sequenceEditor").querySelector('[data-source]');
    src.textContent=src.title=info.verification==='runtime_replay'?`游戏当前回放：${info.name} · ${info.duration_sec.toFixed(3)} 秒`:info.source==='blitz_camera'?`本次从 Blitz Camera 打开：${info.name} · ${info.duration_sec.toFixed(3)} 秒`:`长度来源：${info.name} · 请确认与当前回放一致。`;
  }
  return true;
}
updateButtons(); updateTimingExplanation(); poll(); setInterval(poll, 500);

function speedSettings(){
  return {mode:isCameraOnly()?"paused":state.rateMode,rate:Number($("replayFixedRate").value),camera_clock:isCameraOnly()?"shooting":"replay",
    interpolation:$("speedInterpolation").value,keyframes:copy(state.speedFrames),...(state.rateMode==='curve'&&state.speedRange?{time_range:copy(state.speedRange)}:{})};
}
function updateSpeedExplanation(){
  const mode=state.rateMode,clock="replay";
  $("speedCurveEditor").hidden=true;$("fixedRateLabel").hidden=false;
  document.querySelector(".seq-speed-curve-options").hidden=false;
  $("fixedRateLabel").title='选择固定倍率会替换当前速度曲线；Ctrl+Z 可撤销。';
  $("speedGraph").title='横轴为原曲线的拍摄进度，纵轴为回放倍率。Ctrl+左键添加速度点；选中点后可拖动青色手柄。修改工作区仅裁切播放范围。';
  updateButtons();drawSpeedGraph();
}
function renderSpeedRows(){
 if(sequenceEditor?.numberEdit)return;
 if(BlitzNumbers.active?.closest('#speedRows'))return;
 const body=$("speedRows");body.replaceChildren();
 state.speedFrames.forEach((f,i)=>{
  const tr=document.createElement("tr");
  for(const [key,scale,step,min,max]of [["progress",100,.1,0,100],["rate",1,.0625,.0625,1]]){
   const td=document.createElement("td"),input=document.createElement("input");input.type="number";input.step=step;input.min=min;input.max=max;input.value=Number((f[key]*scale).toFixed(6));
   input.setAttribute("aria-label",`速度关键帧 ${i+1} ${key==="progress"?"拍摄进度百分比":"倍率"}`);
   td.append(input);tr.append(td);BlitzNumbers.configure(input,{step:key==='rate'?.01:.1,get:()=>sequenceEditor.doc.speed.keyframes[i][key]*scale,set:value=>{stopPlayback();return sequenceEditor.edit(()=>{sequenceEditor.doc.speed.keyframes[i][key]=value/scale;});}});
  }
  const td=document.createElement("td"),b=document.createElement("button");b.className="text-button";b.textContent="删除";b.addEventListener("click",()=>{stopPlayback();sequenceEditor.edit(()=>sequenceEditor.doc.speed.keyframes.splice(i,1));});td.append(b);tr.append(td);body.append(tr);
 });drawSpeedGraph();
}
function drawSpeedGraph(){
 const svg=$("speedGraph");if(!svg)return;
 const speed=speedCurveEditor?.drag?speedCurveEditor.speed():speedSettings(),first=state.timeline?.work_start_sec??state.samples[0]?.time_sec??0,duration=state.timeline?state.timeline.work_end_sec-first:(state.samples.at(-1)?.time_sec||0)-first;
 if(!BlitzPreviewTime.valid(speed)){BlitzPreviewTime.draw(svg,speed,0);$("speedPreviewReadout").textContent="请修正速度关键帧后预览。";return;}
 const t=BlitzPreviewTime.atWindowCamera(first,first+duration,speed,state.previewTime),live=state.playback;
 const active=live.active&&["playing","paused"].includes(live.state);
 const clock=offlinePreviewClock(speed),outside=state.previewTime<clock.workStart||state.previewTime>clock.workEnd;
 const shooting=active?live.shooting_elapsed||0:clock.atTime(state.previewTime);
 const schedule=live.schedule_seconds??t.shootingDuration,offset=live.schedule_offset||0;
 const work=speed.mode==='curve'&&speed.time_range?(()=>{const r=speed.time_range;return [first,first+duration].map(v=>BlitzPreviewTime.atCamera(r.end_sec-r.start_sec,speed,(v-r.start_sec)/(r.end_sec-r.start_sec)).shootingProgress);})():null;
 BlitzPreviewTime.draw(svg,speed,active?(shooting+offset)/Math.max(.001,schedule):t.shootingProgress,{editable:true,selected:speedCurveEditor?.index()??-1,work});
 $("speedPreviewReadout").textContent=`${active?"游戏内":"离线预演"} · ${numberText(active?live.current_rate:outside?1:t.rate,3)}× · 拍摄 ${numberText(shooting,2)} / ${numberText(active?live.shooting_duration??schedule-offset:clock.seconds,2)} s · 战斗 +${numberText(active?live.replay_elapsed:isCameraOnly()?0:state.previewTime-clock.start,2)} s`;
}
$("replayFixedRate").addEventListener("change",()=>{stopPlayback();state.rateMode="fixed";state.speedFrames=[{progress:0,rate:Number($("replayFixedRate").value)},{progress:1,rate:Number($("replayFixedRate").value)}];sequenceEditor.changeSpeed(speedSettings());});
function changeSpeedInterpolation(value){const s=speedSettings();s.interpolation=value;s.keyframes.forEach(k=>delete k.ease);stopPlayback();sequenceEditor.changeSpeed(s);}
$("speedInterpolation").addEventListener("change",()=>changeSpeedInterpolation($("speedInterpolation").value));
$("timelineRateInterpolation").addEventListener('change',()=>changeSpeedInterpolation($("timelineRateInterpolation").value));
$("timelineSpeedPreset").onclick=()=>$("speedPreset").click();
$("resetReplaySpeed").onclick=()=>sequenceEditor.action('reset-speed');
$("speedPreset").addEventListener("click",()=>{state.rateMode="curve";state.speedRange=null;state.speedFrames=[{progress:0,rate:1},{progress:.25,rate:.25},{progress:.75,rate:.25},{progress:1,rate:1}];sequenceEditor.changeSpeed(speedSettings());});
$("addSpeedFrame").addEventListener("click",()=>sequenceEditor.add('rate'));

function isCameraOnly(){return state.shootingMode==='camera_only';}
const TAB_PANES={Camera:"paneCamera",Speed:"paneSpeed",Curve:"paneCurve"};
function showTab(name){
  for(const [n,pane] of Object.entries(TAB_PANES)){
    const on=n===name;
    $("tab"+n).classList.toggle("active",on);
    $("tab"+n).setAttribute("aria-selected",String(on));
    $(pane).hidden=!on;
  }
  if(name==='Curve')refreshEaseUI();
  if(name==='Speed')speedCurveEditor?.refresh();
}
for(const name of Object.keys(TAB_PANES))$("tab"+name).addEventListener("click",()=>showTab(name));
function updateModeUI(){
  const free=isCameraOnly();document.body.classList.toggle('camera-only',free);
  document.querySelectorAll('[name=shootingMode]').forEach(e=>e.checked=e.value===state.shootingMode);
  $("tabSpeed").hidden=free;if(free)showTab('Camera');
  $("replaySourceSettings").hidden=free;
  $("shootingModeBadge").textContent=free?'独立镜头时间':'对局时间绑定';
  $("modeSwitch").title=free?'回放保持暂停。仅七条镜头属性轨道，向右无限延伸。':'七条独立属性轨道，共用对局绝对时间；速率轨道控制对局推进。';
  $("captureTime").readOnly=!free;
  $("captureTime").title=free?'指定镜头时间 / 秒':'当前对局绝对时间 / 秒';
  $("liveSeekStart").hidden=free;
  syncReplayPreview();
  drawCanvas();
}
document.querySelectorAll('[name=shootingMode]').forEach(input=>input.addEventListener('change',()=>{
  if(state.busy||state.playback.active)return;stopPlayback();
  sequenceEditor.setMode(input.value,state.timeline);updateModeUI();seek(0);
}));
mountReplayPreview();

const hostBridge=window.chrome?.webview;
if(hostBridge){
  $("windowControls").hidden=false;
  const postWindow=action=>hostBridge.postMessage({command:"window",action});
  $("winMin").addEventListener("click",()=>postWindow("minimize"));
  $("winMax").addEventListener("click",()=>postWindow("maximize"));
  $("winClose").addEventListener("click",()=>postWindow("close"));
  hostBridge.addEventListener("message",e=>{
    if(e?.data?.type==='flush-editor'){
      const id=e.data.id;window.BlitzFlushEditorSession().then(()=>hostBridge.postMessage({command:'editor-flushed',id,success:true})).catch(error=>hostBridge.postMessage({command:'editor-flushed',id,success:false,error:error.message}));return;
    }
    if(e?.data?.type==='host-state'){nativeHostState=e.data;renderGlobalKeys();return;}
    if(e?.data?.type==='host-error'){notify(e.data.message,true);$('globalKeyStatus').textContent=e.data.message;return;}
    if(e?.data?.type==='host-action'&&e.data.action==='capture'){
      refreshState().then(()=>notify('已通过全局快捷键记录全部七项属性关键帧。')).catch(error=>notify(error.message,true));return;
    }
    if(e?.data?.type!=="window-state")return;
    const maximized=!!e.data.maximized;
    setIcon($("winMax"),maximized?"i-restore":"i-max");
    $("winMax").title=maximized?"还原":"最大化";
    $("winMax").setAttribute("aria-label",$("winMax").title);
  });
  hostBridge.postMessage({command:'ready'});
  const titlebar=$("titlebar");
  let lastMaxToggle=0;
  titlebar.addEventListener("mousedown",e=>{
    if(e.button!==0||e.target.closest("button,input,select,label,details,a"))return;
    if(e.detail>=2){const now=Date.now();if(now-lastMaxToggle>600){lastMaxToggle=now;postWindow("maximize");}return;}
    postWindow("drag");
  });
}

const splitDefaults={v:.25,h:.5};
let splitV=splitDefaults.v,splitH=splitDefaults.h;
const wb=$("wb");
function applySplits(){wb.style.setProperty("--v",splitV);wb.style.setProperty("--h",splitH);}
try{
  const sv=+localStorage.getItem("wb-split-v"),sh=+localStorage.getItem("wb-split-h");
  if(sv>0&&sv<1)splitV=sv;if(sh>0&&sh<1)splitH=sh;
}catch{}
applySplits();
function persistSplits(){try{localStorage.setItem("wb-split-v",splitV);localStorage.setItem("wb-split-h",splitH);}catch{}}
document.querySelectorAll(".vsplit,.hsplit").forEach(el=>{
  el.addEventListener("pointerdown",e=>{
    if(e.button!==0)return;
    e.preventDefault();el.setPointerCapture(e.pointerId);el.classList.add("drag");
    const move=ev=>{
      if(el.dataset.split==="v"){
        const r=el.parentElement.getBoundingClientRect();
        splitV=Math.min(Math.max(ev.clientX-r.left,200),Math.max(200,r.width-360))/r.width;
      }else{
        const r=wb.getBoundingClientRect();
        splitH=Math.min(Math.max(ev.clientY-r.top,160),Math.max(160,r.height-140))/r.height;
      }
      applySplits();
    };
    const up=()=>{el.classList.remove("drag");el.removeEventListener("pointermove",move);el.removeEventListener("pointerup",up);el.removeEventListener("pointercancel",up);persistSplits();};
    el.addEventListener("pointermove",move);el.addEventListener("pointerup",up);el.addEventListener("pointercancel",up);
  });
  el.addEventListener("dblclick",()=>{splitV=splitDefaults.v;splitH=splitDefaults.h;applySplits();persistSplits();});
});

function relTime(iso) {
  const d = (Date.now() - Date.parse(iso)) / 1000;
  if (!Number.isFinite(d)) return '—';
  if (d < 90) return '刚刚';
  if (d < 3600) return `${Math.max(1, Math.floor(d / 60))} 分钟前`;
  if (d < 86400) return `${Math.floor(d / 3600)} 小时前`;
  return `${Math.floor(d / 86400)} 天前`;
}
function sizeText(n) {
  if (!Number.isFinite(n)) return '—';
  if (n < 1024) return n + ' B';
  if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
  return (n / 1048576).toFixed(1) + ' MB';
}
function showHome(on) {
  closeHomeMenu();
  if(state.settingsOpen)closeSettings();
  state.home = on;
  $("homeView").hidden = !on; $("wb").hidden = on;
  document.body.classList.toggle('home-open', on);
  if (on) renderHome();
  else requestAnimationFrame(()=>restoreEditorSession());
}
async function renderHome() {
  const request=++homeRequest;
  homeLoading=true;homeError='';
  paintHome();
  try {
    const result=await api('/api/projects/recent');
    if(request===homeRequest)homeItems=result.projects||[];
  } catch(error) { if(request===homeRequest)homeError=error.message; }
  finally{if(request===homeRequest){homeLoading=false;paintHome();}}
}
function homeNode(tag,className,text) {
  const node=document.createElement(tag);node.className=className;
  if(text!==undefined)node.textContent=text;
  return node;
}
function homeIcon(name) {
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
  svg.setAttribute('class','ic');svg.setAttribute('aria-hidden','true');
  const use=document.createElementNS(svg.namespaceURI,'use');use.setAttribute('href','#'+name);svg.append(use);
  return svg;
}
function homeReplaySummary(filename) {
  if(!filename)return {label:'未关联回放',context:''};
  const name=filename.split(/[\\/]/).at(-1),stem=name.replace(/\.wotbreplay$/i,'');
  const standard=stem.match(/^(\d{4})(\d{2})(\d{2})_\d{4}__(.+)_\d{10,}$/);
  // Only shorten the game's standard file names. Renamed replays keep their name.
  if(!standard)return {label:stem,context:''};
  const date=`${standard[2]}.${standard[3]}`,body=standard[4];
  const vehicle=body.match(/^(.*?)_((?:[A-Z][a-z]?\d+|Oth\d+)_.+)$/);
  return vehicle?{label:vehicle[2].replace(/^[^_]+_/,'').replace(/_/g,' '),context:`${date} · ${vehicle[1]}`}:
    {label:body.replace(/_/g,' '),context:date};
}
function homeMode(item){return item.shooting_mode==='camera_only'?'仅镜头':item.shooting_mode==='replay'?'随对局':'—';}
function updateHomeControls() {
  const locked=state.busy||homeOpening||!state.serviceReady||state.playback.active;
  for(const id of ['homeNew','homeNewName','homeOpen'])$(id).disabled=locked;
  document.querySelectorAll('.home-project-open').forEach(button=>{button.disabled=locked||button.dataset.exists!=='true';});
  document.querySelectorAll('#homeProjectMenu [data-home-action]').forEach(button=>{button.disabled=locked&&button.dataset.homeAction!=='info';});
}
async function switchHomeProject(next) {
  if(state.busy||homeOpening||!state.serviceReady||state.playback.active)return;
  closeHomeMenu();homeOpening=true;updateHomeControls();
  try{await guardDirty(next);}catch(error){notify(error.message||'项目未能打开，请重试。',true);}
  finally{homeOpening=false;updateHomeControls();}
}
function paintHome() {
  closeHomeMenu();
  const q=$('homeFilter').value.trim().toLowerCase(),sort=$('homeSort').value;
  const rows=homeItems.filter(item=>!q||[item.name,item.replay,homeReplaySummary(item.replay).label].join(' ').toLowerCase().includes(q));
  const byName=(a,b)=>a.name.localeCompare(b.name,'zh',{numeric:true})||a.path.localeCompare(b.path);
  const opened=item=>Date.parse(item.last_opened)||0;
  rows.sort((a,b)=>sort==='name-asc'?byName(a,b):sort==='name-desc'?-byName(a,b):
    sort==='size'?((b.size_bytes??-1)-(a.size_bytes??-1)||byName(a,b)):(opened(b)-opened(a)||byName(a,b)));
  const list=$('homeRows');list.replaceChildren();list.setAttribute('aria-busy',String(homeLoading));
  $('homeNavCount').textContent=homeItems.length||'';
  $('homeCount').textContent=homeLoading?'正在读取…':homeError?'读取失败':`${rows.length} 个项目`;
  $('homeEmpty').hidden=!homeLoading&&!homeError&&rows.length>0;
  $('homeEmpty').textContent=homeLoading?'正在读取最近项目…':homeError?`读取失败：${homeError}`:
    q?'没有找到匹配的项目':'暂无最近项目，新建或打开一个项目开始创作。';
  $('homeRetry').hidden=!homeError||homeLoading;
  if(homeLoading||homeError){updateHomeControls();return;}
  const today=new Date();today.setHours(0,0,0,0);
  const groups=sort==='recent'&&!q?
    [['今天',rows.filter(item=>opened(item)>=today.getTime())],['更早',rows.filter(item=>opened(item)<today.getTime())]]:
    [[q?'搜索结果':'全部项目',rows]];
  for(const [label,items] of groups){
    if(!items.length)continue;
    const section=homeNode('section','home-group');section.setAttribute('aria-label',label);
    section.append(homeNode('h2','home-group-title',label));
    for(const item of items){
      const row=homeNode('article','home-project'+(item.exists?'':' missing'));row.dataset.path=item.path;
      const button=homeNode('button','home-project-open');button.type='button';button.dataset.exists=String(item.exists);
      button.setAttribute('aria-label',`打开项目 ${item.name}`);button.title=item.path;
      const icon=homeNode('span','home-project-icon');icon.append(homeIcon('i-film'));
      const copy=homeNode('span','home-project-copy'),name=homeNode('span','home-project-name',item.name);
      name.title=item.name;
      const replay=homeNode('span','home-project-replay'),summary=homeReplaySummary(item.replay);
      replay.title=item.replay||'未关联回放';replay.append(homeNode('span','home-replay-label',summary.label));
      if(summary.context)replay.append(homeNode('span','home-replay-context',summary.context));
      copy.append(name,replay);
      const meta=homeNode('span','home-project-meta');
      meta.append(homeNode('span','home-project-time',item.exists?relTime(item.last_opened):'文件不存在'),homeNode('span','home-project-mode',homeMode(item)));
      button.append(icon,copy,meta);
      button.addEventListener('click',()=>switchHomeProject(()=>openProjectFlow(item.path)));
      const more=homeNode('button','home-more');more.type='button';more.append(homeIcon('i-more'));
      more.setAttribute('aria-label',`${item.name} 的更多操作`);more.setAttribute('aria-haspopup','menu');
      more.setAttribute('aria-controls','homeProjectMenu');more.setAttribute('aria-expanded','false');
      more.addEventListener('click',()=>showHomeMenu(item,more));
      more.addEventListener('keydown',event=>{if(event.key==='ArrowDown'){event.preventDefault();showHomeMenu(item,more,true);}});
      row.append(button,more);section.append(row);
    }
    list.append(section);
  }
  updateHomeControls();
}
function closeHomeMenu(restoreFocus=false) {
  $('homeProjectMenu').hidden=true;
  homeMenuTrigger?.setAttribute('aria-expanded','false');
  if(restoreFocus&&homeMenuTrigger?.isConnected)homeMenuTrigger.focus();
  homeMenuItem=null;homeMenuTrigger=null;
}
function showHomeMenu(item,trigger,keyboard=false) {
  if(homeMenuTrigger===trigger&&!keyboard){closeHomeMenu();return;}
  closeHomeMenu();homeMenuItem=item;homeMenuTrigger=trigger;
  const menu=$('homeProjectMenu');menu.querySelector('.home-delete').hidden=!item.exists;
  menu.setAttribute('aria-label',`${item.name} 的项目操作`);menu.hidden=false;
  trigger.setAttribute('aria-expanded','true');updateHomeControls();
  const rect=trigger.getBoundingClientRect(),gap=8;
  menu.style.left=Math.max(gap,Math.min(rect.right-menu.offsetWidth,innerWidth-menu.offsetWidth-gap))+'px';
  menu.style.top=Math.max(gap,rect.bottom+menu.offsetHeight+gap<=innerHeight?rect.bottom+4:rect.top-menu.offsetHeight-4)+'px';
  menu.querySelector('button').focus();
}
function showHomeInfo(item) {
  $('homeInfoName').textContent=item.name;
  $('homeInfoPath').textContent=item.path;
  $('homeInfoReplay').textContent=item.replay||'未关联回放';
  $('homeInfoMode').textContent=homeMode(item);
  const time=new Date(Date.parse(item.last_opened));
  $('homeInfoTime').textContent=Number.isFinite(time.getTime())?`${time.toLocaleString('zh-CN',{hour12:false})}（${relTime(item.last_opened)}）`:'—';
  $('homeInfoSize').textContent=item.exists?sizeText(item.size_bytes):'—';
  $('homeInfoStatus').textContent=item.exists?'可打开':'文件不存在';
  $('homeInfoDialog').showModal();
}
async function deleteProjectFlow(item) {
  if(state.busy)return;
  if(state.playback.active)return notify('请先停止运镜，再删除项目。',true);
  const dialog=$('projectDeleteDialog');if(dialog.open)return;
  $('projectDeleteName').textContent=item.name;
  $('projectDeletePath').textContent=item.path;
  $('projectDeleteDraft').hidden=state.projectPath!==item.path||!state.dirty;
  dialog.returnValue='';dialog.showModal();
  const choice=await new Promise(resolve=>dialog.addEventListener('close',()=>resolve(dialog.returnValue),{once:true}));
  if(choice!=='delete')return;
  await action(async()=>{
    const current=state.projectPath===item.path;
    if(current){stopPlayback();clearTimeout(autoSaveTimer);}
    let deleted=false;
    try{
      if(autoSavePromise)await autoSavePromise;
      if(editorSavePromise)await editorSavePromise;
      const result=await api('/api/projects/delete',{path:item.path,expected_revision:state.serverRevision},{timeout:0});
      if(result.cancelled)return notify('已取消删除。');
      deleted=true;
      try{localStorage.removeItem('blitz-editor-session:'+item.path);}catch{}
      await refreshState(current);await renderHome();
      notify(`已删除项目 ${item.name}。`);
    }finally{if(!deleted&&current&&state.projectPath===item.path&&state.dirty)queueAutoSave();}
  });
}
$("homeButton").addEventListener('click', () => showHome(true));
$("homeNavHome").addEventListener('click', e => { e.preventDefault(); showHome(true); });
$("homeNew").addEventListener('click', () => { $("homeNewRow").hidden = false; $("homeNewName").focus(); });
$("homeNewName").addEventListener('keydown', e => {
  if (e.key === 'Escape') { e.preventDefault(); $("homeNewRow").hidden = true; $("homeNewName").value = ''; }
  if (e.key === 'Enter') {
    e.preventDefault();
    const name = $("homeNewName").value.trim(); if (!name) return;
    switchHomeProject(() => action(async () => {
      const result = await api("/api/projects/new", {name});
      $("homeNewRow").hidden = true; $("homeNewName").value = '';
      await refreshState(true); showHome(false); notify(`已创建项目 ${name}。`);
    }));
  }
});
$("homeOpen").addEventListener('click', () => switchHomeProject(() => openProjectFlow()));
$("homeFilter").addEventListener('input', paintHome);
$("homeSort").addEventListener('change', paintHome);
$('homeRetry').addEventListener('click',renderHome);
$('homeProjectMenu').addEventListener('click',event=>{
  const button=event.target.closest('[data-home-action]'),item=homeMenuItem;
  if(!button||button.disabled||!item)return;
  closeHomeMenu(true);
  if(button.dataset.homeAction==='info')showHomeInfo(item);
  if(button.dataset.homeAction==='delete')deleteProjectFlow(item);
  if(button.dataset.homeAction==='forget')action(async()=>{
    await api('/api/projects/forget',{path:item.path});await renderHome();
    $('homeFilter').focus();notify(`已将 ${item.name} 移出最近列表，项目文件已保留。`);
  });
});
$('homeProjectMenu').addEventListener('keydown',event=>{
  const buttons=[...event.currentTarget.querySelectorAll('button:not([hidden]):not(:disabled)')];
  const index=buttons.indexOf(document.activeElement);
  if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){
    event.preventDefault();
    const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length;
    buttons[next]?.focus();
  }
  if(event.key==='Tab')closeHomeMenu(true);
});
document.addEventListener('pointerdown',event=>{if(homeMenuItem&&!event.target.closest('#homeProjectMenu,.home-more'))closeHomeMenu();});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&homeMenuItem){event.preventDefault();closeHomeMenu(true);}});
$('homeListWrap').addEventListener('scroll',()=>closeHomeMenu());
window.addEventListener('resize',()=>closeHomeMenu());
window.addEventListener('blur',()=>closeHomeMenu());

function settingsMessage(text,error=false){$('settingsResult').textContent=text;$('settingsResult').classList.toggle('error',error);}
function settingsBattleStart(){return $('battleStartMode').value==='auto'?null:Number($('battleStartSeconds').value);}
function renderBattleStartStatus(){
  const guard=keyframeGuardFor();
  $('battleStartStatus').textContent=guard.enabled?guard.message:'载入模式二回放后显示比赛开始时间。';
}
function renderGlobalKeys(){
  const h=nativeHostState,available=!!hostBridge&&!!h;
  for(const id of ['globalCaptureKey','globalHideKey','applyGlobalKeys'])$(id).disabled=!available;
  if(!available)return;
  if(!globalKeysEdited){$('globalCaptureKey').value=h.captureKey||'F8';$('globalHideKey').value=h.hideKey||'F9';}
  $('globalKeyStatus').textContent=h.warnings?.length?h.warnings.join('；'):
    h.captureHotkeyRegistered&&h.hideHotkeyRegistered?'快捷键已生效。游戏最小化时悬浮窗会自动隐藏，恢复游戏后还原。':'快捷键尚未注册，请选择其他按键后应用。';
}
function updateSettingsControls(){
  const locked=state.busy||settingsLoading||!state.serviceReady;
  $('settingsButton').disabled=state.busy;
  $('projectDirectory').disabled=locked||!applicationSettings;
  $('settingsBrowse').disabled=locked;
  $('settingsDefault').disabled=locked||!applicationSettings;
  const manual=$('battleStartMode').value==='manual',seconds=settingsBattleStart();
  $('battleStartMode').disabled=locked||!applicationSettings;
  $('battleStartManual').hidden=!manual;$('battleStartSeconds').disabled=locked||!applicationSettings||!manual;
  const valid=!manual||$('battleStartSeconds').value.trim()!==''&&finite(seconds)&&seconds>=0&&seconds<=3600;
  const changed=applicationSettings&&($('projectDirectory').value.trim()!==applicationSettings.project_directory||seconds!==applicationSettings.replay_keyframe_start_seconds);
  $('settingsSave').disabled=locked||!applicationSettings||!$('projectDirectory').value.trim()||!valid||!changed;
  $('settingsBack').disabled=state.busy;
}
async function openSettings(){
  closeHomeMenu();
  stopPlayback();replayPreviewPane?.stopFlight();
  state.settingsOpen=true;document.body.classList.add('settings-open');$('settingsView').hidden=false;
  $('settingsButton').setAttribute('aria-pressed','true');$('settingsBack').textContent=state.home?'返回主页':'返回工作台';
  settingsLoading=true;settingsMessage('正在读取设置…');updateSettingsControls();
  try{
    applicationSettings=await api('/api/settings');$('projectDirectory').value=applicationSettings.project_directory;
    $('battleStartMode').value=applicationSettings.replay_keyframe_start_seconds===null?'auto':'manual';
    $('battleStartSeconds').value=applicationSettings.replay_keyframe_start_seconds??keyframeGuardFor().start_sec??0;
    settingsMessage('');renderBattleStartStatus();renderGlobalKeys();
  }catch(error){settingsMessage(error.message,true);}
  finally{settingsLoading=false;updateSettingsControls();if(state.settingsOpen)$('projectDirectory').focus();}
}
function closeSettings(){
  state.settingsOpen=false;document.body.classList.remove('settings-open');$('settingsView').hidden=true;
  $('settingsButton').setAttribute('aria-pressed','false');$('settingsButton').focus();
  requestAnimationFrame(()=>{restoreEditorSession();replayPreviewPane?.render();});
}
$('settingsButton').addEventListener('click',()=>state.settingsOpen?closeSettings():openSettings());
$('settingsBack').addEventListener('click',closeSettings);
$('projectDirectory').addEventListener('input',()=>{settingsMessage('');updateSettingsControls();});
for(const id of ['battleStartMode','battleStartSeconds'])$(id).addEventListener('input',()=>{settingsMessage('');updateSettingsControls();});
for(const id of ['globalCaptureKey','globalHideKey'])$(id).addEventListener('change',()=>{globalKeysEdited=true;});
$('applyGlobalKeys').addEventListener('click',()=>{
  const keys={captureKey:$('globalCaptureKey').value,hideKey:$('globalHideKey').value};
  globalKeysEdited=false;hostBridge?.postMessage({command:'settings',...keys});
});
renderGlobalKeys();
$('settingsDefault').addEventListener('click',()=>{$('projectDirectory').value=applicationSettings.default_project_directory;settingsMessage('点击“保存设置”应用默认位置。');updateSettingsControls();});
$('settingsBrowse').addEventListener('click',()=>action(async()=>{
  const result=await api('/api/settings/directory',{initial:$('projectDirectory').value},{timeout:0});
  if(result.cancelled)return;
  $('projectDirectory').value=result.path;settingsMessage('点击“保存设置”应用此位置。');
}));
$('settingsForm').addEventListener('submit',event=>{
  event.preventDefault();if($('settingsSave').disabled)return;
  action(async()=>{
    try{applicationSettings=await api('/api/settings',{project_directory:$('projectDirectory').value,replay_keyframe_start_seconds:settingsBattleStart()});$('projectDirectory').value=applicationSettings.project_directory;await refreshState();settingsMessage('设置已保存。');renderBattleStartStatus();}
    catch(error){settingsMessage(error.message,true);}
  });
});
{
  const params = new URLSearchParams(location.search);
  if (params.has('home') || (window.chrome?.webview && !params.has('workbench'))) showHome(true);
}
setInterval(()=>{restoreEditorSession();if(!state.busy)persistEditorSession().catch(()=>{});},750);
window.BlitzStartup?.watch(()=>{
  if(startupServiceError)return {error:startupServiceError,canEnter:state.loaded};
  if(!state.loaded)return {message:'正在读取项目…'};
  if(state.home){
    if(homeError)return {error:'最近项目读取失败：'+homeError,canEnter:true};
    return homeLoading?{message:'正在读取最近项目…'}:{ready:true};
  }
  if(startupSamples.error)return {error:'轨迹预演未能载入：'+startupSamples.error,canEnter:true};
  if(!startupSamples.ready)return {message:'正在计算镜头轨迹…'};
  restoreEditorSession();
  if(!isCameraOnly()&&state.timeline?.replay_file){
    if(replayPreviewPane?.status==='error')return {error:$('previewStatus').textContent||'回放预览未能载入。',canEnter:true};
    if(replayPreviewPane?.status!=='ready')return {message:$('previewStatus').textContent||'正在准备回放场景…'};
  }
  return {ready:true};
});
