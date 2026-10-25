import * as THREE from './vendor/three/build/three.module.js';
import {GLTFLoader} from './vendor/three/examples/jsm/loaders/GLTFLoader.js';
import {OrbitControls} from './vendor/three/examples/jsm/controls/OrbitControls.js';
import {PreviewGuides} from './preview-guides.js';
import {createReplaySampler,cameraEvaluator,cameraBasis,cameraBehindVehicle,flightSeekSeconds,worldToScene,sceneToWorld,verticalAngle,nearestAngle} from './replay-preview-core.js';
import {loadTerrain,buildGroundGeometry,makeGroundMaterial,groundLayerKeys,setupGroundTextures} from './vendor/wotbtools/groundPass.js';
import {poseFromYPR,dropDuplicateGunMasks,neutralizeDefaultMetalness} from './vendor/wotbtools/glbRig.js';
import {pruneForeignVariantsDetailed} from './vendor/wotbtools/variantFilter.js';
import {resolveSceneryExtras,makeTexResolvers,assembleSceneryMaterials} from './vendor/wotbtools/sceneryAssembly.js';
import {strictSurfacesOf,isWaterNode,isNonIntactStateName} from './vendor/wotbtools/sceneryAssemblyRules.js';
import {clearSceneryMatCache,applyMaterialTextureAnisotropy} from './vendor/wotbtools/sceneryMaterials.js';
import {collectInstanceEntries,groupInstanceBatches,buildInstancedMesh,buildStandaloneLightmappedMeshes,hasTransparentMaterial} from './vendor/wotbtools/sceneryInstancing.js';
import {ReplayBattleEffects,muzzleTipOf} from './replay-effects.js';
import {prepareTankDestroyedVisual,applyTankDestroyedVisual,destroyedVisualAmount} from './vendor/wotbtools/tankDestroyedVisual.js';

const QFRAME=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0),Math.PI).multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1,0,0),-Math.PI/2));
const FLIGHT_SPEEDS=[1,2,4,8,16,32,64,128,256];
const controls=()=>window.BlitzControls;
const $=id=>document.getElementById(id);
const post=async(path,data)=>{const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});const v=await r.json();if(!r.ok)throw Error(v.error||'操作失败');return v;};
const json=async url=>{const r=await fetch(url);if(!r.ok)throw Error(`资源读取失败 (${r.status})`);return r.json();};
const texture=async url=>new THREE.TextureLoader().loadAsync(url);
const gltf=async url=>(await new GLTFLoader().loadAsync(url)).scene;
const vector=p=>new THREE.Vector3(...p);
function dispose(root){const seen=new Set(),release=v=>{if(v?.isTexture&&!seen.has(v)){seen.add(v);v.dispose();}};root?.traverse(n=>{if(n.geometry&&!seen.has(n.geometry)){seen.add(n.geometry);n.geometry.dispose();}for(const m of [n.material].flat()){if(!m||seen.has(m))continue;seen.add(m);Object.values(m).forEach(release);for(const u of Object.values(m.uniforms||{}))for(const v of [u.value].flat())release(v);m.dispose();}});}

export class ReplayPreviewPane {
  constructor(adapter){
    this.adapter=adapter;this.generation=0;this.source=null;this.data=null;this.sampler=null;this.active=false;this.view='observer';this.offset=0;this.time=0;this.models=new Map();this.templates=new Map();this.status='empty';this.lastTracks=null;this.pathSamples=null;this.mode='camera_only';
    this.flying=false;this.flightPending=false;this.flightKeys=new Set();this.flightVelocity=[0,0,0];this.flightSeek=null;this.flightSpeed=4;this.flightRequest=0;
    this.flightHost=window.chrome?.webview;
    $('retryPreview').onclick=()=>this.reload();
    $('previewEmpty').addEventListener('click',()=>this.activateEmpty());
    $('previewEmpty').addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();if(!e.repeat)this.activateEmpty();}});
    $('previewObserver').onclick=()=>this.setView('observer');$('previewCamera').onclick=()=>this.setView('camera');
    $('previewFit').onclick=()=>this.fit();$('previewRecord').onclick=()=>this.record();
    $('previewFly').onclick=()=>this.flying?this.stopFlight():this.startFlight();
    $('previewOffset').onchange=()=>{const n=Number($('previewOffset').value);if(!Number.isFinite(n)||Math.abs(n)>600){$('previewOffset').value=this.offset;return;}this.offset=n;this.storeOffset();this.render();};
    this.resizeObserver=new ResizeObserver(()=>this.render());this.resizeObserver.observe($('replayScene'));
    window.addEventListener('pagehide',()=>{this.stopFlight();this.worker?.terminate();});
    window.addEventListener('blitz-controls-changed',()=>this.stopFlight());
  }
  message(text,error=false){$('previewStatus').textContent=text;$('previewStatus').classList.toggle('error',error);}
  empty(label,{progress=null,msg='',error=false}={}){
    const el=$('previewEmpty');el.hidden=false;
    el.querySelector('[data-label]').textContent=label;
    const bar=el.querySelector('[data-progress]');bar.hidden=progress==null;
    if(progress!=null)bar.firstElementChild.style.width=Math.min(100,Math.max(0,progress*100)).toFixed(1)+'%';
    const m=el.querySelector('[data-msg]');m.textContent=msg;m.classList.toggle('pe-error',!!error);
  }
  clear(){
    ++this.generation;this.cancelParse?.();this.worker?.terminate();this.worker=null;this.cancelParse=null;
    this.source=null;this.data=null;this.requestedPath=null;this.offset=0;
    this.resetScene();
    $('previewFile').textContent='未选择回放';$('previewFile').title='';
    $('previewSourceFile').textContent='—';$('previewSourceFile').title='';
    $('previewMap').textContent='';$('previewStatus').title='';$('previewOffset').value=0;
    this.syncReloadUI();this.message('点击“载入回放”或顶部按钮选择当前项目的回放。');this.empty('载入回放');
  }
  update({mode,time,tracks,smooth,easing,samples,replayFile,projectPath}){
    if(this.projectPath!==projectPath){this.projectPath=projectPath;this.clear();}
    if(this.boundReplayFile!==replayFile){this.boundReplayFile=replayFile;if(!replayFile)this.clear();}
    const cameraChanged=this.mode!==mode||this.lastTracks!==tracks||this.lastSmooth!==smooth||this.lastEasing!==easing;
    // Playback and seeking advance the scene while the pilot keeps the camera.
    if(cameraChanged||(this.time!==time&&!this.flying)){this.stopFlight();this.override=null;}
    this.mode=mode;this.active=mode==='replay';this.time=time;
    document.querySelector('.preview-panel').classList.toggle('preview3d-active',this.active);
    $('replayPreviewControls').hidden=!this.active;$('replayScene').hidden=!this.active;
    this.syncReloadUI();
    if(!this.active){this.syncFlightUI();return;}
    if(tracks!==this.lastTracks||smooth!==this.lastSmooth||easing!==this.lastEasing){this.lastTracks=tracks;this.lastSmooth=smooth;this.lastEasing=easing;this.evaluate=cameraEvaluator(tracks,smooth,easing);}
    if(samples!==this.pathSamples){this.pathSamples=samples;this.updatePath();}
    if(replayFile&&replayFile!==this.requestedPath)this.select(replayFile);
    // The flight loop renders the new scene time once per frame while moving.
    if(!this.flying)this.render();
  }
  storeOffset(){try{localStorage.setItem('blitz-preview-residual-offset:'+this.source.sha256,String(this.offset));}catch{}}
  syncReloadUI(){
    const disabled=this.status==='loading'||this.adapter.locked();
    $('retryPreview').disabled=!this.boundReplayFile||disabled;
    $('previewEmpty').setAttribute('aria-disabled',String(disabled));$('previewEmpty').tabIndex=disabled?-1:0;
    $('previewEmpty').title=this.boundReplayFile?'重新加载预览':'选择回放文件';
  }
  activateEmpty(){
    this.syncReloadUI();if($('previewEmpty').getAttribute('aria-disabled')==='true')return;
    return this.boundReplayFile?this.reload():this.adapter.selectReplay();
  }
  reload(){
    this.syncReloadUI();if($('retryPreview').disabled)return;
    this.adapter.pause();return this.select(this.boundReplayFile);
  }
  async select(path){
    if(!path)return;
    this.requestedPath=path;
    const gen=++this.generation;this.cancelParse?.();this.worker?.terminate();this.worker=null;this.resetScene();this.source=null;this.data=null;this.status='loading';this.message('正在读取本地回放…');this.empty('正在载入回放…',{progress:.02,msg:'正在读取本地回放…'});
    $('previewFile').textContent=path.split(/[\\/]/).at(-1);$('previewFile').title=path;
    $('previewSourceFile').textContent=$('previewFile').textContent;$('previewSourceFile').title=path;
    this.syncReloadUI();
    try{
      const result=await post('/api/preview/select',{path});
      if(gen!==this.generation)return;
      if(result.cancelled){this.status='empty';this.message('已取消载入。');this.empty('重新加载预览');return;}
      this.source=result.source;this.requestedPath=this.source.replay_file;
      $('previewFile').textContent=this.source.name;$('previewFile').title=this.source.replay_file;
      $('previewSourceFile').textContent=this.source.name;$('previewSourceFile').title=this.source.replay_file;
      // Old manual offsets could compensate for the missing origin. Keep them
      // separate so an existing compensation is not added a second time.
      try{this.offset=Number(localStorage.getItem('blitz-preview-residual-offset:'+this.source.sha256))||0;}catch{this.offset=0;}
      $('previewOffset').value=this.offset;
      this.message('正在本机解析车辆运动和战斗时钟…');this.empty('正在载入回放…',{progress:.06,msg:'正在本机解析车辆运动和战斗时钟…'});
      const response=await fetch('/api/preview/replay/'+this.source.id);if(!response.ok)throw Error((await response.json()).error);
      const bytes=await response.arrayBuffer();if(gen!==this.generation)return;
      const data=await this.parse(bytes,gen);if(gen!==this.generation)return;this.data=data;
      this.sampler=createReplaySampler(this.data,this.source.replay_origin_sec);this.empty('正在载入回放…',{progress:.15,msg:'解析完成'});
      $('previewOffset').title='回放时钟已自动对齐；微调仅影响车辆预览，不移动镜头关键帧。';
      await post('/api/preview/prepare',{source_id:this.source.id,map_id:this.data.playback.meta.map_id,tank_ids:[...new Set(this.data.playback.vehicles.map(v=>v.tank_id))]});
      await this.waitForAssets(gen);
    }catch(error){if(gen===this.generation){this.status='error';this.message(error.message,true);this.empty('重新加载预览',{msg:error.message,error:true});}}
    finally{if(gen===this.generation)this.syncReloadUI();}
  }
  parse(bytes,id){
    return new Promise((resolve,reject)=>{
      const worker=this.worker=new Worker('/replay-preview-worker.js',{type:'module'});
      const finish=(error,bundle)=>{clearTimeout(timer);worker.terminate();if(this.worker===worker){this.worker=null;this.cancelParse=null;}error?reject(error):resolve(bundle);};
      const timer=setTimeout(()=>finish(Error('回放解析超时，请重试。')),120000);
      this.cancelParse=()=>finish(new DOMException('已更换回放','AbortError'));
      worker.onmessage=({data})=>{if(data.id===id)finish(data.error?Error(data.error):null,data.bundle);};
      worker.onerror=e=>finish(Error(e.message||'回放解析线程失败。'));
      worker.postMessage({id,bytes},[bytes]);
    });
  }
  async waitForAssets(gen){
    while(gen===this.generation){
      const s=await json('/api/preview/state');if(gen!==this.generation)return;
      if(s.source?.id!==this.source.id)throw Error('预览来源已由另一个窗口更换，请重新载入。');
      this.message(s.message);this.empty('正在载入回放…',{progress:.15+(s.progress||0)*.7,msg:s.message});
      if(s.state==='error')throw Error(s.message);
      if(s.state==='ready'){this.message('正在装配 3D 场景…');this.empty('正在载入回放…',{progress:.85,msg:'正在装配 3D 场景…'});await this.loadScene(s.manifest,gen);return;}
      await new Promise(r=>setTimeout(r,650));
    }
  }
  initRenderer(){
    if(this.renderer)return;
    this.renderer=new THREE.WebGLRenderer({antialias:true,alpha:false,powerPreference:'high-performance'});
    this.renderer.setPixelRatio(Math.min(devicePixelRatio||1,2));this.renderer.outputColorSpace=THREE.SRGBColorSpace;
    this.renderer.setClearColor(0x18242c);this.renderer.domElement.setAttribute('aria-label','离线回放三维预览');
    $('replayScene').prepend(this.renderer.domElement);
    this.renderer.domElement.addEventListener('webglcontextlost',e=>{e.preventDefault();this.stopFlight();this.status='error';this.syncFlightUI();this.message('3D 预览暂时失去显卡上下文，请重新载入。',true);});
    this.scene=new THREE.Scene();this.scene.add(new THREE.HemisphereLight(0xdcecff,0x766548,2.2));
    const light=new THREE.DirectionalLight(0xffefd7,2);light.position.set(-150,300,100);this.scene.add(light);
    this.observer=new THREE.PerspectiveCamera(50,16/9,.1,3000);this.observer.position.set(350,280,350);
    // Steam 11.21 replay FreeCamera uses a 1 m near plane (live reversed-Z
    // projection[14] = 1). Keep the observer's close inspection plane separate.
    this.shot=new THREE.PerspectiveCamera(50,16/9,1,3000);
    this.orbit=new OrbitControls(this.observer,this.renderer.domElement);this.orbit.target.set(0,20,0);this.orbit.enableDamping=false;this.orbit.maxDistance=1800;this.orbit.minDistance=.3;
    this.orbit.addEventListener('change',()=>this.render());
    this.guides=new PreviewGuides();this.pathGroup=this.guides.root;this.scene.add(this.pathGroup);this.assetsGroup=new THREE.Group();this.scene.add(this.assetsGroup);
    this.glyphLabel=document.createElement('span');this.glyphLabel.className='preview-camera-label';this.glyphLabel.hidden=true;$('replayScene').append(this.glyphLabel);
    $('previewOverrideReset').addEventListener('click',()=>{this.override=null;this.render();});
    this.bindPilot();
    this.bindFlight();
  }
  inViewport(e){
    const r=this.renderer.domElement.getBoundingClientRect(),vw=Math.min(r.width,r.height*16/9),vh=vw*9/16,x=r.left+(r.width-vw)/2,y=r.top+(r.height-vh)/2;
    return e.clientX>=x&&e.clientX<=x+vw&&e.clientY>=y&&e.clientY<=y+vh;
  }
  ensureOverride(){if(!this.override){const base=this.evaluated||this.evaluate?.(this.time);if(base)this.override={position:[...base.position],yaw:base.yaw,pitch:base.pitch,roll:base.roll,zoom:base.zoom};}}
  bindPilot(){
    const el=this.renderer.domElement;
    el.addEventListener('contextmenu',e=>{if(this.view==='camera')e.preventDefault();});
    el.addEventListener('pointerdown',e=>{
      if(this.view!=='camera'||this.status!=='ready'||this.adapter.locked()||!this.inViewport(e))return;
      el.setPointerCapture(e.pointerId);this.pilot={button:e.button,shift:e.shiftKey,x:e.clientX,y:e.clientY};
      e.preventDefault();e.stopPropagation();
    });
    el.addEventListener('pointermove',e=>{
      if(!this.pilot)return;
      const dx=e.clientX-this.pilot.x,dy=e.clientY-this.pilot.y;this.pilot.x=e.clientX;this.pilot.y=e.clientY;
      this.pilotMove(dx,dy);
    });
    const end=()=>{this.pilot=null;};
    el.addEventListener('pointerup',end);el.addEventListener('pointercancel',end);
    el.addEventListener('wheel',e=>{
      if(this.view!=='camera'||this.status!=='ready'||this.adapter.locked()||!this.inViewport(e))return;
      e.preventDefault();e.stopPropagation();
      this.ensureOverride();const o=this.override;if(!o)return;
      if(e.ctrlKey||e.metaKey)o.zoom=Math.min(90,Math.max(5,o.zoom*(e.deltaY<0?1.09:0.92)));
      else{const span=Math.max(1,(this.heightMeta?.span||400)/1000),b=cameraBasis(o.yaw,o.pitch,o.roll);o.position=o.position.map((v,i)=>v-b.forward[i]*e.deltaY*span);}
      this.render();
    },{passive:false});
  }
  syncFlightUI(){
    const available=this.active&&this.view==='camera'&&this.status==='ready'&&!this.adapter.locked()&&!!(this.override||this.evaluate?.(this.time));
    if((this.flying||this.flightPending)&&!available)this.stopFlight();
    const button=$('previewFly');button.hidden=this.view!=='camera';button.disabled=!available||this.flightPending;
    button.setAttribute('aria-pressed',String(this.flying));
    $('previewFlightHud').hidden=!this.flying;
    $('previewFlightSpeed').textContent=`${this.flightSpeed} 档`;
  }
  async startFlight(){
    if(this.flying||this.flightPending||!this.active||this.view!=='camera'||this.status!=='ready'||this.adapter.locked())return;
    const el=this.renderer?.domElement;
    if(!el||(!this.flightHost&&!el.requestPointerLock)){this.message('当前窗口不支持自由飞行的鼠标锁定。',true);return;}
    this.adapter.pause?.();this.ensureOverride();if(!this.override)return;
    this.pilot=null;this.flightPending=true;this.flightKeys.clear();this.flightVelocity=[0,0,0];this.flightSeek=null;
    el.tabIndex=-1;el.focus({preventScroll:true});this.syncFlightUI();
    try{
      if(this.flightHost){
        const rect=el.getBoundingClientRect(),id=++this.flightRequest;
        this.flightHost.postMessage({command:'flight',action:'start',id,x:rect.x+rect.width/2,y:rect.y+rect.height/2,exitKey:controls().key('exitFlight'),exitMouse:controls().key('exitFlightMouse')});
        this.flightTimeout=setTimeout(()=>{if(this.flightPending&&id===this.flightRequest){this.stopFlight();this.message('未能捕获鼠标，请重新点击自由飞行。',true);}},2000);
      }else await el.requestPointerLock();
    }
    catch(error){if(this.flightPending){this.stopFlight();this.message('未能锁定鼠标，请重新点击自由飞行。',true);}}
  }
  stopFlight(){
    const hadCapture=this.flying||this.flightPending;
    // Freeze time before releasing the camera: the next playback update would
    // otherwise discard its override and restore the keyframed pose.
    if(hadCapture)this.adapter.pause?.();
    this.flying=false;this.flightPending=false;this.flightKeys.clear();this.flightVelocity=[0,0,0];this.flightSeek=null;
    clearTimeout(this.flightTimeout);
    if(hadCapture&&this.flightHost)this.flightHost.postMessage({command:'flight',action:'stop',id:this.flightRequest});
    cancelAnimationFrame(this.flightFrame);this.flightFrame=0;
    if(this.renderer&&document.pointerLockElement===this.renderer.domElement)document.exitPointerLock();
    this.syncFlightUI();
  }
  enterFlight(){
    if(!this.flightPending)return;
    clearTimeout(this.flightTimeout);this.flightPending=false;this.flying=true;this.flightLast=performance.now();this.syncFlightUI();
    if(this.flying)this.flightFrame=requestAnimationFrame(now=>this.advanceFlight(now));
  }
  bindFlight(){
    const el=this.renderer.domElement;
    this.flightHost?.addEventListener('message',e=>{
      const m=e.data;if(!m||m.id!==this.flightRequest)return;
      if(m.type==='flight-state'){
        if(m.active){
          if(this.flightPending)this.enterFlight();
          else if(!this.flying)this.flightHost.postMessage({command:'flight',action:'stop',id:m.id});
        }else{
          const failed=this.flightPending;this.stopFlight();
          if(failed)this.message('未能捕获鼠标，请重新点击自由飞行。',true);
        }
      }else if(m.type==='flight-motion'&&this.flying){this.lookFlight(m.dx,m.dy);this.render();}
      else if(m.type==='flight-wheel'&&this.flying)this.zoomFlight(m.delta);
    });
    document.addEventListener('pointerlockchange',()=>{
      if(document.pointerLockElement!==el){if(this.flying||this.flightPending)this.stopFlight();return;}
      if(!this.flightPending){document.exitPointerLock();return;}
      this.enterFlight();
    });
    document.addEventListener('pointerlockerror',()=>{
      if(this.flightPending){this.stopFlight();this.message('未能锁定鼠标，请重新点击自由飞行。',true);}
    });
    document.addEventListener('pointerdown',e=>{
      if(!this.flying){this.flightMouseConsumed=null;return;}
      this.flightMouseConsumed={button:e.button,until:performance.now()+1000};
      if('Mouse'+e.button!==controls().key('exitFlightMouse')){e.preventDefault();e.stopImmediatePropagation();return;}
      e.preventDefault();e.stopImmediatePropagation();this.stopFlight();
    },true);
    // Pointer lock restores the cursor over its old UI target on release.
    // Consume the remainder of that click, including a right-click menu.
    for(const name of ['pointerup','click','auxclick','contextmenu'])document.addEventListener(name,e=>{
      const consumed=this.flightMouseConsumed;
      if(this.flying||consumed&&e.button===consumed.button&&performance.now()<consumed.until){e.preventDefault();e.stopImmediatePropagation();}
    },true);
    document.addEventListener('keydown',e=>{
      if(!this.flying)return;
      e.preventDefault();e.stopImmediatePropagation();
      const c=controls(),chord=c.chord(e);
      if(e.code==='Escape'||c.matches('exitFlight',e)){this.stopFlight();return;}
      const modified=e.ctrlKey||e.metaKey||e.altKey||e.shiftKey;
      if(e.code==='Space'){
        if(!e.repeat&&!modified&&!this.adapter.locked()){
          this.flightSeek=null;this.flightKeys.delete(c.key('seekBack'));this.flightKeys.delete(c.key('seekForward'));
          this.adapter.togglePlayback?.();
        }
        return;
      }
      if(c.matches('seekBack',e)||c.matches('seekForward',e)){
        if(!e.repeat&&!this.adapter.locked()&&!this.flightKeys.has(chord)){
          this.flightKeys.add(chord);this.syncFlightSeek(performance.now(),true);
        }
        return;
      }
      if(c.matches('rear',e)){
        if(!e.repeat)this.resetFlightBehindPlayer();
        return;
      }
      if(c.matches('recordPreview',e)){if(!e.repeat){this.stopFlight();this.record();}return;}
      const speed=Array.from({length:9},(_,i)=>i+1).find(i=>c.matches('speed'+i,e));
      if(speed){this.flightSpeed=speed;this.syncFlightUI();return;}
      if(c.schema.actions.some(a=>a.scopes.includes('flight')&&c.matches(a.id,e)))this.flightKeys.add(chord);
    },true);
    document.addEventListener('keyup',e=>{
      if(!this.flying)return;e.preventDefault();e.stopImmediatePropagation();
      const before=this.seekDirection();controls().release(this.flightKeys,e.code);
      if(before!==this.seekDirection())this.syncFlightSeek(performance.now());
    },true);
    document.addEventListener('mousemove',e=>{
      if(this.flightHost||!this.flying||document.pointerLockElement!==el)return;
      this.lookFlight(e.movementX,e.movementY);this.render();
    });
    // Capture before the existing drag/wheel pilot; its controls stay unchanged outside flight.
    el.addEventListener('wheel',e=>{
      if(!this.flying)return;e.preventDefault();e.stopImmediatePropagation();
      this.zoomFlight(e.deltaY);
    },{passive:false,capture:true});
    window.addEventListener('blur',()=>this.stopFlight());
    document.addEventListener('visibilitychange',()=>{if(document.hidden)this.stopFlight();});
  }
  syncFlightSeek(now,step=false){
    const direction=this.seekDirection();
    this.flightSeek=direction?{direction,started:now,travel:0}:null;
    if(direction&&step)this.adapter.stepTime?.(direction);
  }
  seekDirection(){const c=controls();return Number(c.held('seekForward',this.flightKeys))-Number(c.held('seekBack',this.flightKeys));}
  advanceFlightSeek(now){
    const held=this.flightSeek;if(!held)return;
    const travel=flightSeekSeconds(Math.max(0,(now-held.started)/1000),controls().config.tuning),seconds=(travel-held.travel)*held.direction;
    held.travel=travel;
    if(!seconds)return;
    const moved=this.adapter.seekTimeBy?.(seconds);
    // Reaching either end stops seeking until a fresh direction is pressed.
    if(Number.isFinite(moved)&&Math.abs(moved)+1e-9<Math.abs(seconds))this.flightSeek=null;
  }
  resetFlightBehindPlayer(){
    if(!this.flying||!this.active||this.view!=='camera'||this.status!=='ready'||this.adapter.locked())return;
    const frame=this.sampler?.recorderAt(this.time,this.offset),pose=cameraBehindVehicle(frame?.pose);
    if(!pose){this.message('当前时刻没有主角的可用位置，暂时无法回到车后视角。',true);return;}
    this.override=pose;this.flightKeys.clear();this.flightVelocity=[0,0,0];this.flightSeek=null;this.flightLast=performance.now();
    this.message('已回到主角后方 · 可继续自由飞行');this.render();
  }
  zoomFlight(delta){
    this.override.zoom=Math.min(90,Math.max(5,this.override.zoom*Math.exp(delta*.001)));this.render();
  }
  lookFlight(dx,dy){
    const o=this.override;if(!o)return;
    // Degrees per relative mouse count: independent of preview size, gentler on pitch.
    const gain=.055*controls().value('mouseSensitivity',1)*Math.tan(o.zoom*Math.PI/360)/Math.tan(Math.PI/6);
    // Positive yaw points left in the game's world-coordinate camera basis.
    o.yaw-=dx*gain;
    o.pitch=Math.max(-80,Math.min(80,o.pitch-dy*gain*.65));
  }
  advanceFlight(now){
    this.flightFrame=0;if(!this.flying)return;
    if(!this.active||this.view!=='camera'||this.status!=='ready'||this.adapter.locked()){this.stopFlight();return;}
    const dt=Math.max(0,Math.min(.05,(now-this.flightLast)/1000));this.flightLast=now;
    const c=controls(),held=id=>c.held(id,this.flightKeys)?1:0,o=this.override,b=cameraBasis(o.yaw,o.pitch,o.roll);
    const forward=held('forward')-held('backward'),right=held('right')-held('left'),up=held('up')-held('down');
    const direction=b.forward.map((v,i)=>v*forward+b.right[i]*right+(i===2?up:0));
    const length=Math.hypot(...direction),speed=FLIGHT_SPEEDS[this.flightSpeed-1]*c.value('flightSpeedScale',1);
    // Integrate exponential acceleration exactly, independently of display refresh rate.
    const k=length>0?14:22,decay=Math.exp(-k*dt);
    for(let i=0;i<3;i++){
      const target=length>0?direction[i]/length*speed:0,old=this.flightVelocity[i];
      o.position[i]+=target*dt+(old-target)*(1-decay)/k;
      this.flightVelocity[i]=target+(old-target)*decay;
    }
    o.yaw-=(held('yawRight')-held('yawLeft'))*30*dt;
    o.pitch=Math.max(-80,Math.min(80,o.pitch+(held('pitchUp')-held('pitchDown'))*20*dt));
    // Positive roll banks the camera clockwise: its up axis tilts to the right.
    o.roll+=(held('rollRight')-held('rollLeft'))*c.value('rollSpeed',45)*dt;
    this.advanceFlightSeek(now);
    this.render();this.flightFrame=requestAnimationFrame(t=>this.advanceFlight(t));
  }
  pilotMove(dx,dy){
    this.ensureOverride();const o=this.override;if(!o)return;
    if(this.pilot.button===1||this.pilot.button===2){
      const b=cameraBasis(o.yaw,o.pitch,o.roll),span=(this.heightMeta?.span||400)/500;
      o.position=o.position.map((v,i)=>v-b.right[i]*dx*span+b.up[i]*dy*span);
    }else if(this.pilot.shift)o.roll+=dx*.2;
    else{
      const vw=Math.max(1,Math.min(this.renderWidth||300,(this.renderHeight||300)*16/9)),vh=vw*9/16;
      o.yaw+=dx*o.zoom/vw;o.pitch=Math.max(-80,Math.min(80,o.pitch-dy*verticalAngle(o.zoom,16/9)/vh));
    }
    this.render();
  }
  resetScene(){
    this.stopFlight();
    this.effects?.dispose();this.effects=null;
    this.manifest=null;this.status='empty';this.sampler=null;this.models.clear();this.override=null;this.pilot=null;this.evaluated=null;
    for(const t of this.templates.values())dispose(t.model);this.templates.clear();this.terrain=null;this.terrainLod=null;this.animMaterials=[];
    clearSceneryMatCache();
    if(this.assetsGroup){dispose(this.assetsGroup);this.assetsGroup.clear();}
    this.render();
  }
  async loadScene(manifest,gen){
    this.initRenderer();this.manifest=manifest;const urls=manifest.urls;
    const doc=await new GLTFLoader().loadAsync(urls.scenery),scenery=doc.scene;
    if(gen!==this.generation){dispose(scenery);return;}
    const prune=pruneForeignVariantsDetailed(scenery,this.data.playback.meta.map_id);
    if(prune.failClosed)throw Error('地图变体映射不完整，已停止场景装配。');
    const terrain=await loadTerrain({binUrl:urls.terrain,metaUrl:urls.terrainMeta,fetchFn:fetch,stale:()=>gen!==this.generation});
    if(gen!==this.generation)return;if(!terrain.field)throw Error('地图高度场缺失或校验失败，未使用猜测地形。');
    const [layers,mapTexture]=await Promise.all([urls.groundLayers?json(urls.groundLayers):null,texture(urls.ground)]);
    if(gen!==this.generation){mapTexture.dispose();return;}
    let texs=null;
    if(layers){texs={};await Promise.all(groundLayerKeys(layers).map(async k=>{if(!urls['ground/'+k])throw Error('地表贴图缺失：'+k);texs[k]=await texture(urls['ground/'+k]);}));setupGroundTextures(texs,Math.min(8,this.renderer.capabilities.getMaxAnisotropy()));mapTexture.dispose();}
    else mapTexture.colorSpace=THREE.SRGBColorSpace;
    if(gen!==this.generation)return;
    this.field=terrain.field;this.heightMeta=terrain.meta;
    this.terrain=new THREE.Mesh(new THREE.BufferGeometry(),makeGroundMaterial({layers,texs,size:terrain.meta.span,mapTexture:layers?null:mapTexture}));this.assetsGroup.add(this.terrain);
    this.rebuildTerrain(true);
    const extras=await resolveSceneryExtras(doc);if(gen!==this.generation){dispose(scenery);return;}
    const strictSurfaces=strictSurfacesOf(scenery);
    this.animMaterials=assembleSceneryMaterials(doc,{strictSurfaces,masks:makeTexResolvers(doc,extras),groundLayers:layers?{layers,texs}:null}).animLayerMats;
    scenery.traverse(n=>{if(isNonIntactStateName(n.name))n.visible=false;});
    const entries=collectInstanceEntries(scenery).filter(e=>{for(let n=e.node;n;n=n.parent)if(!n.visible)return false;return true;});
    const batchable=e=>!e.node.userData?.isSky&&!isWaterNode(e.name,e.material,{strictSurfaces})&&!hasTransparentMaterial(e.material);
    const batched=entries.filter(batchable);
    buildStandaloneLightmappedMeshes(entries.filter(e=>!batchable(e)&&hasTransparentMaterial(e.material)&&!e.node.userData?.isSky&&!isWaterNode(e.name,e.material,{strictSurfaces})),scenery);
    for(const b of groupInstanceBatches(batched,Math.max(75,terrain.meta.span/8)))scenery.add(buildInstancedMesh(b));
    for(const e of batched)e.node.removeFromParent();
    applyMaterialTextureAnisotropy(scenery,Math.min(8,this.renderer.capabilities.getMaxAnisotropy()));
    scenery.quaternion.copy(QFRAME);this.assetsGroup.add(scenery);
    const errors=[...manifest.missing];
    const ids=Object.keys(manifest.vehicles);let loaded=0;
    for(const tid of ids){
      const [model,rig]=await Promise.all([gltf(urls['vehicle/'+tid]),json(urls['rig/'+tid])]);
      if(gen!==this.generation){dispose(model);return;}
      neutralizeDefaultMetalness(model);dropDuplicateGunMasks(model);this.templates.set(Number(tid),{model,rig});
      this.empty('正在载入回放…',{progress:.85+.15*++loaded/Math.max(1,ids.length),msg:`装配车辆 ${loaded}/${ids.length}`});
    }
    for(const def of this.data.playback.vehicles){
      const template=this.templates.get(def.tank_id);
      let root,parts;
      if(template){root=template.model.clone(true);parts=this.rig(root,template.rig,def);}
      if(!template||!parts){
        if(template)errors.push({tank_id:def.tank_id,reason:'未核对到当前搭载模型配置'});
        root=new THREE.Group();const box=new THREE.Mesh(new THREE.BoxGeometry(3,1.5,6),new THREE.MeshStandardMaterial({color:def.team===this.data.playback.meta.friendly_team?0x85ad74:0xbb6b66}));root.add(box);root.userData.proxy=true;
      }
      const destroyedVisual=prepareTankDestroyedVisual(root);
      root.visible=false;this.assetsGroup.add(root);this.models.set(def.eid,{root,parts,def,destroyedVisual});
    }
    this.effects=new ReplayBattleEffects(this.data.playback,this.sampler,{muzzleAt:(...args)=>this.muzzleAt(...args)});
    this.scene.add(this.effects.root);
    this.status='ready';$('previewEmpty').hidden=true;
    $('previewMap').textContent=`${manifest.map.display} · ${this.models.size} 辆车`;
    $('previewStatus').title=manifest.limitations.join(' ')+(errors.length?` ${errors.length} 辆缺少模型，用方块标记。`:'');
    const missingAim=this.data.aim?.missing.length||0;
    this.updatePath();this.fit();this.message('离线场景已载入 · 可前后拖动时间轴'+(missingAim?` · ${missingAim} 辆车缺少炮管俯仰参数`:''));this.render();
    this.adapter.ready?.();
    // Deterministic diagnostics, consumed by automated acceptance. No game API.
    window.BlitzReplayPreviewDiagnostics=()=>({state:this.status,time:this.time,offset:this.offset,replayOrigin:this.sampler?.origin,rawTime:this.sampler?.rawTime(this.time,this.offset),engine:this.data?.engine,source:this.source?.sha256,map:this.manifest?.map.key,visible:[...this.models].filter(([,v])=>v.root.visible).map(([eid,v])=>({eid,p:v.root.position.toArray()})),camera:this.shot?.position.toArray(),quaternion:this.shot?.quaternion.toArray(),angle:this.shot?.fov,triangles:this.renderer.info.render.triangles,geometryCount:this.renderer.info.memory.geometries,view:this.view,guides:this.guides?.diagnostics(),effects:this.effects?.diagnostics()});
  }
  rig(root,metadata,def){
    if(!metadata?.model_origins?.track||!metadata?.model_origins?.turret)return null;
    const configs=metadata.configs||[],matches=configs.filter(c=>c.turret_local===def.turret_local&&c.gun_local===def.gun_local);
    const cfg=matches.at(-1)||(configs.length===1?configs[0]:null);
    if(!cfg)return null; // Unknown mounted variant is not inferred from HP/shells.
    const turrets=[],guns=[];
    root.traverse(n=>{let m=n.name.match(/^turret_(\d+)$/);if(m){n.visible=Number(m[1])===cfg.turret_node;if(n.visible)turrets.push(n);}m=n.name.match(/^gun_(\d+)/);if(m)n.visible=Number(m[1])===cfg.gun_node;if(n.visible&&/^gun_\d+(?:_mask)?$/.test(n.name))guns.push(n);});
    if(!turrets.length&&!guns.length)return null;
    const a=metadata.model_origins,tP=a.track.map((v,i)=>v+a.turret[i]),gP=tP.map((v,i)=>v+(cfg.gun_origin?.[i]||0));
    const entries=[...turrets,...guns].map(n=>{n.updateMatrix();n.matrixAutoUpdate=false;return {node:n,bake:n.matrix.clone(),gun:guns.includes(n)};});
    return {entries,tP,gP,gunNodes:guns,itr:metadata.initial_turret_rotation};
  }
  muzzleAt(eid,raw,from,dir){
    const item=this.models.get(eid),frame=this.sampler.poseAtRaw(eid,raw);
    if(!item?.parts||!frame)return from.clone();
    // Measure the actual mounted barrel at the recorded fire pose, then restore
    // the current frame. Frame rate and playback speed cannot shift the muzzle.
    const position=item.root.position.clone(),rotation=item.root.quaternion.clone(),matrices=item.parts.entries.map(e=>e.node.matrix.clone());
    try{
      this.poseModel(item,frame.pose);item.root.updateMatrixWorld(true);
      return muzzleTipOf(item.parts.gunNodes,from,dir);
    }finally{
      item.root.position.copy(position);item.root.quaternion.copy(rotation);
      item.parts.entries.forEach((e,i)=>e.node.matrix.copy(matrices[i]));item.root.updateMatrixWorld(true);
    }
  }
  poseModel(item,pose){
    const {root,parts}=item;root.position.set(-pose.x,pose.y,pose.z);
    if(root.userData.proxy){root.rotation.set(pose.pitch,-pose.yaw,-pose.roll,'YXZ');return;}
    poseFromYPR(-pose.yaw,pose.pitch,-pose.roll,root.quaternion);
    if(!parts)return;
    const {tP,gP,itr}=parts,tr=-pose.turretRel;
    const rot=new THREE.Matrix4();if(itr)rot.makeRotationFromEuler(new THREE.Euler(-(itr.pitch||0)*Math.PI/180,-(itr.roll||0)*Math.PI/180,tr-(itr.yaw||0)*Math.PI/180,'ZYX'));else rot.makeRotationZ(tr);
    const mt=new THREE.Matrix4().makeTranslation(...tP).multiply(rot).multiply(new THREE.Matrix4().makeTranslation(...tP.map(v=>-v)));
    const mg=mt.clone().multiply(new THREE.Matrix4().makeTranslation(...gP)).multiply(new THREE.Matrix4().makeRotationX(pose.gunPitch)).multiply(new THREE.Matrix4().makeTranslation(...gP.map(v=>-v)));
    for(const e of parts.entries)e.node.matrix.copy(e.gun?mg:mt).multiply(e.bake);
  }
  updatePath(){
    this.guides?.setPath(this.pathSamples);
  }
  setView(view){if(view!==this.view)this.stopFlight();this.view=view;$('previewObserver').setAttribute('aria-pressed',String(view==='observer'));$('previewCamera').setAttribute('aria-pressed',String(view==='camera'));this.render();}
  fit(){
    if(!this.observer)return;
    let points=(this.pathSamples||[]).map(s=>vector(worldToScene(s.position)));
    if(!points.length)points=[new THREE.Vector3(-200,0,-200),new THREE.Vector3(200,70,200)];
    const box=new THREE.Box3().setFromPoints(points),center=box.getCenter(new THREE.Vector3()),size=Math.max(15,box.getSize(new THREE.Vector3()).length());
    this.orbit.target.copy(center);this.observer.position.copy(center).add(new THREE.Vector3(.7,.7,.85).multiplyScalar(size));this.orbit.update();this.render();
  }
  rebuildTerrain(force=false){
    if(!this.terrain)return;
    const c=this.view==='camera'?this.shot:this.observer,now=performance.now();
    if(!force&&this.terrainLod&&now-this.terrainLod.time<180)return;
    if(!force&&this.terrainLod&&c.position.distanceTo(this.terrainLod.pos)<1&&Math.abs(c.fov-this.terrainLod.fov)<.5)return;
    this.terrainLod={time:now,pos:c.position.clone(),fov:c.fov};
    const geo=buildGroundGeometry({field:this.field,n:this.heightMeta.size,span:this.heightMeta.span,cam:{x:c.position.x,y:c.position.y,z:c.position.z},fovY:c.fov*Math.PI/180,aspect:c.aspect});
    this.terrain.geometry.dispose();this.terrain.geometry=geo;
  }
  render(){
    this.syncFlightUI();
    if(!this.active||!this.renderer)return;
    const rect=$('replayScene').getBoundingClientRect();if(rect.width<1||rect.height<1)return;
    const w=rect.width,h=rect.height;
    if(this.renderWidth!==w||this.renderHeight!==h){this.renderer.setSize(w,h,false);this.renderWidth=w;this.renderHeight=h;}
    const base=this.evaluate?.(this.time);this.evaluated=base;
    const pose=this.override||base;
    if(!pose&&this.view==='camera'){this.stopFlight();this.view='observer';$('previewCamera').setAttribute('aria-pressed','false');$('previewObserver').setAttribute('aria-pressed','true');}
    if(pose){const b=cameraBasis(pose.yaw,pose.pitch,pose.roll);this.shot.position.copy(vector(worldToScene(pose.position)));const matrix=new THREE.Matrix4().makeBasis(vector(worldToScene(b.right)),vector(worldToScene(b.up)),vector(worldToScene(b.forward)).negate());this.shot.quaternion.setFromRotationMatrix(matrix);this.shot.aspect=16/9;this.shot.fov=verticalAngle(pose.zoom,16/9);this.shot.updateProjectionMatrix();this.shot.updateMatrixWorld();}
    this.orbit.enabled=this.view==='observer';this.pathGroup.visible=this.view==='observer';
    const frames=this.sampler?.at(this.time,this.offset)||[],raw=this.sampler?.rawTime(this.time,this.offset);
    if(this.sampler){for(const item of this.models.values())item.root.visible=false;for(const frame of frames){const item=this.models.get(frame.eid);if(item){item.root.visible=true;this.poseModel(item,frame.pose);applyTankDestroyedVisual(item.destroyedVisual,destroyedVisualAmount(frame.life,raw));}}}
    for(const mat of this.animMaterials||[])mat.uniforms.uTime.value=this.time+this.offset;
    const camera=this.view==='camera'?this.shot:this.observer;this.observer.aspect=w/h;this.observer.updateProjectionMatrix();this.rebuildTerrain();
    this.effects?.update(raw,camera,this.view==='camera'?Math.min(h,w*9/16):h,frames);
    this.glyphLabel.hidden=true;this.guides.glyph.visible=!!pose;
    if(pose&&this.view==='observer'){const label=this.guides.update(this.shot,this.observer,w,h,this.time,pose.zoom),scale=window.BlitzUIScale||1;this.glyphLabel.hidden=!label.visible;this.glyphLabel.style.left=label.x/scale+'px';this.glyphLabel.style.top=label.y/scale+'px';this.glyphLabel.textContent=`${pose.zoom.toFixed(1)}°`;}
    this.renderer.setScissorTest(false);this.renderer.setViewport(0,0,w,h);this.renderer.clear();
    if(this.view==='camera'){
      const vw=Math.min(w,h*16/9),vh=vw*9/16,x=(w-vw)/2,y=(h-vh)/2;
      this.renderer.setViewport(x,y,vw,vh);this.renderer.setScissor(x,y,vw,vh);this.renderer.setScissorTest(true);
    }
    this.renderer.render(this.scene,camera);this.renderer.setScissorTest(false);
    $('previewRecord').disabled=this.status!=='ready'||this.adapter.locked();
    $('previewCamera').disabled=!pose;
    $('previewOverride').hidden=!this.override;
    $('previewSceneTime').textContent=`对局 ${this.time.toFixed(3)} s · ${this.view==='camera'?'实机':'场景观察'}`;
  }
  record(){
    if(this.status!=='ready'||this.adapter.locked())return;
    const reference=this.evaluated||this.evaluate?.(this.time),degrees=180/Math.PI;let pose;
    if(this.view==='camera'){
      const src=this.override||reference;if(!src)return;
      pose={position:[...src.position],yaw:nearestAngle(src.yaw,reference?.yaw??src.yaw),pitch:src.pitch,roll:nearestAngle(src.roll,reference?.roll??src.roll),zoom:src.zoom};
    }else{
      const q=QFRAME.clone().invert().multiply(this.observer.quaternion),u=vector([0,1,0]).applyQuaternion(q),f=vector([0,0,-1]).applyQuaternion(q);
      const yaw=Math.atan2(f.y,f.x),pitch=Math.atan2(f.z,Math.hypot(f.x,f.y)),right0=new THREE.Vector3(Math.sin(yaw),-Math.cos(yaw),0),up0=right0.clone().cross(f);
      const roll=Math.atan2(u.dot(right0),u.dot(up0));
      pose={position:sceneToWorld(this.observer.position.toArray()),yaw:nearestAngle(yaw*degrees,reference?.yaw??yaw*degrees),pitch:pitch*degrees,roll:nearestAngle(roll*degrees,reference?.roll??roll*degrees),zoom:2*Math.atan(Math.tan(this.observer.fov*Math.PI/360)*this.observer.aspect)*degrees};
    }
    this.adapter.record(pose,this.time);
    this.override=null;this.render();
  }
}
window.BlitzReplayPreview={mount:adapter=>new ReplayPreviewPane(adapter)};
window.dispatchEvent(new Event('blitz-replay-preview-ready'));
