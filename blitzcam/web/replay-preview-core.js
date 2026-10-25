// Offline preview math. Scalar evaluation mirrors channels.ScalarTrack exactly;
// vehicle sampling/identity use the pinned WotbTools implementation (MIT).
import {buildCanonicalReplayFacts, entityFirstSeenByAccount, resolveReplayClock} from './vendor/wotbtools/facts.js';
import {buildPoseFacet, selectActiveDef, sampleVehiclePoseGame, poseCoveredAt} from './vendor/wotbtools/vehiclePose.js';
import {scalarTrack} from './curve-core.js';
import {defLifeAt} from './vendor/wotbtools/battlePlaybackV2.js';

export {scalarTrack};

const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
export function validatePlayback(p){
  if(!p?.meta || !Number.isInteger(p.meta.samples)||p.meta.samples<1||p.meta.samples>36001||!Number.isFinite(p.meta.t_start)||!Number.isFinite(p.meta.duration)||!Number.isInteger(p.meta.map_id)||!Array.isArray(p.vehicles)||p.vehicles.length>64)throw Error('回放运动数据契约不匹配。');
  const finiteArray=(a,n)=>Array.isArray(a)&&a.length===n&&a.every(Number.isFinite);
  for(const v of p.vehicles){
    if(!Number.isInteger(v.eid)||!Number.isInteger(v.tank_id)||!finiteArray(v.pos,p.meta.samples*3)||!['hull_yaw','hull_pitch','turret_yaw','gun_pitch'].every(k=>finiteArray(v[k],p.meta.samples)))throw Error('车辆运动数据不完整。');
    if(!Array.isArray(v.coverage)||v.coverage.length%2||!v.coverage.every(Number.isFinite))throw Error('车辆可用区间无效。');
    const k=v.pose_kf;
    if(k&&(!Array.isArray(k.t)||!k.t.every(Number.isFinite)||!finiteArray(k.pos,k.t.length*3)||!finiteArray(k.yaw,k.t.length)||!finiteArray(k.pitch,k.t.length)))throw Error('车辆重建关键点不完整。');
    if(k&&!k.t.every((t,i)=>!i||t>k.t[i-1]))throw Error(`车辆 ${v.eid} 的重建关键点时间顺序异常。`);
  }
  return p;
}

export function createReplaySampler(bundle,replayOrigin){
  if(!Number.isFinite(replayOrigin)||replayOrigin<0||replayOrigin>3600)throw Error('回放时间原点缺失或无效，请重启工作台并重新载入回放。');
  const {playback:p,result,ai}=bundle;validatePlayback(p);
  const clock=resolveReplayClock(ai?.battle?.periods||[],result,p.meta.duration);
  if(!clock)throw Error('未读到可靠的战斗阶段时钟，无法建立预览时间。');
  const facts=buildCanonicalReplayFacts({result,aiReview:ai,streamEndRaw:p.meta.duration});
  if(!facts)throw Error('回放实体身份数据不完整。');
  const starts=entityFirstSeenByAccount(facts),facet=buildPoseFacet(p,starts);
  const groups=new Map(), originals=new Map(p.vehicles.map(v=>[v.eid,v]));
  for(const v of facet.vehicles){if(!groups.has(v.account_id))groups.set(v.account_id,[]);groups.get(v.account_id).push(v);}
  const definitions=new Map(facet.vehicles.map(v=>[v.eid,v]));
  const rawTime=(replayTime,offset=0)=>replayTime+replayOrigin+offset;
  const poseAtRaw=(eid,raw,{lastKnown=false}={})=>{
    const def=definitions.get(eid);if(!def||!Number.isFinite(raw))return null;
    const active=selectActiveDef(groups.get(def.account_id)||[],starts.get(def.account_id),raw-clock.startRaw);
    if(active?.eid!==eid)return null;
    let sample=raw;
    if(lastKnown){
      // Only positions observed at/before the requested frame; never pull a
      // hidden vehicle's future first sample backwards into an explosion.
      sample=-Infinity;
      for(let i=0;i+1<def.coverage.length;i+=2)for(let j=0;j+1<(def.visibility?.length||0);j+=2){
        const begin=Math.max(def.coverage[i],def.visibility[j]),end=Math.min(raw,def.coverage[i+1],def.visibility[j+1]);
        if(begin<=end)sample=Math.max(sample,end);
      }
      if(!Number.isFinite(sample))return null;
    }else if(!poseCoveredAt(def,raw)||!def.visibility?.some((v,i,a)=>i%2===0&&raw>=v&&raw<a[i+1]))return null;
    const pose=sampleVehiclePoseGame(def,facet,sample,undefined,def.visibility);
    if(![pose.x,pose.y,pose.z,pose.yaw,pose.pitch,pose.roll].every(Number.isFinite))return null;
    return {eid,def:originals.get(eid),pose,life:defLifeAt(originals.get(eid),raw)};
  };
  const at=(replayTime,offset=0)=>{
    // The editor uses ReplayPlayer's raw - origin getter. Facets retain raw
    // packet clocks; period-3 startRaw is a separate battle/countdown origin.
    const raw=rawTime(replayTime,offset), frames=[];
    for(const [account,defs] of groups){
      const def=selectActiveDef(defs,starts.get(account),raw-clock.startRaw);
      if(!def)continue;
      const life=defLifeAt(originals.get(def.eid),raw),dead=life?.lifeState==='DESTROYED';
      // Like WotbTools applyPose, wrecks keep following the recorded pose at
      // the current clock. Only missing observations hold the last known pose;
      // death itself must not freeze sliding, falling or subsequent impacts.
      const frame=poseAtRaw(def.eid,raw,{lastKnown:dead});
      if(frame)frames.push({...frame,life});
    }
    return frames;
  };
  return {clock,origin:replayOrigin,rawTime,poseAtRaw,meta:p.meta,at,recorderAt(replayTime,offset=0){
    const frames=at(replayTime,offset).filter(frame=>facts.entities.get(frame.eid)?.recorder&&frame.def.account_id===facts.recorderAccountId);
    return frames.length===1?frames[0]:null;
  }};
}

// A stable rear-view preset for the offline preview. 54 degrees is the desktop
// client's default horizontal FOV; distance/elevation are preview framing, not
// a reconstruction of the game's unrecorded orbit input or camera collisions.
export function cameraBehindVehicle(pose){
  if(!pose||![pose.x,pose.y,pose.z,pose.yaw].every(Number.isFinite))return null;
  const back=15,height=6;
  // Replay vehicle coordinates are y-up, yaw 0 = +z. Camera tracks are z-up,
  // yaw 0 = +x, so heading becomes 90 degrees minus the hull's yaw.
  return {position:[pose.x-Math.sin(pose.yaw)*back,pose.z-Math.cos(pose.yaw)*back,pose.y+height],
    yaw:90-pose.yaw*180/Math.PI,pitch:-10,roll:0,zoom:54};
}

// Integrated replay seconds for a held arrow key. The initial single-frame tap
// is separate. After a short tap window, ramp smoothly from 1x to 64x in 3 s.
// Integrating the curve makes travel independent of key-repeat/display rates.
export function flightSeekSeconds(heldSeconds,{seekDelay=.25,seekRamp=3,seekMax=64}={}){
  const elapsed=Math.max(0,heldSeconds-seekDelay),ramp=Math.min(elapsed,seekRamp);
  return ramp+(seekMax-1)*ramp**3/(3*seekRamp**2)+Math.max(0,elapsed-seekRamp)*seekMax;
}

export function cameraEvaluator(tracks,smooth,easing){
  const names=['x','y','z','yaw','pitch','roll','zoom'];
  if(!names.some(n=>tracks?.[n]?.length))return ()=>null;
  const samplers=names.map((n,i)=>tracks?.[n]?.length?scalarTrack(tracks[n],smooth&&i<3,easing):()=>n==='zoom'?60:0);
  return time=>{const v=samplers.map(f=>f(time));return v.every(Number.isFinite)?{position:v.slice(0,3),yaw:v[3],pitch:v[4],roll:v[5],zoom:v[6]}:null;};
}
export function cameraBasis(yaw,pitch,roll){
  const [y,p,r]=[yaw,pitch,roll].map(a=>a*Math.PI/180),f=[Math.cos(p)*Math.cos(y),Math.cos(p)*Math.sin(y),Math.sin(p)];
  const right=[Math.sin(y),-Math.cos(y),0],up=[right[1]*f[2],-right[0]*f[2],right[0]*f[1]-right[1]*f[0]];
  return {right:right.map((v,i)=>v*Math.cos(r)-up[i]*Math.sin(r)),up:up.map((v,i)=>v*Math.cos(r)+right[i]*Math.sin(r)),forward:f};
}
export const worldToScene=p=>[-p[0],p[2],p[1]];
export const sceneToWorld=p=>[-p[0],p[2],p[1]];
export const verticalAngle=(horizontal,aspect)=>2*Math.atan(Math.tan(horizontal*Math.PI/360)/aspect)*180/Math.PI;
export const nearestAngle=(angle,reference)=>angle+360*Math.round((reference-angle)/360);
