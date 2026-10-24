import * as THREE from './vendor/three/build/three.module.js';
import {FX_BUDGETS,TRACER_STREAK_M,createBattleFx,muzzleTipOf,trailOpacityAt} from './vendor/wotbtools/battleFx.js';
import {pointAtInto,pointAtArcInto,arcAtTime} from './vendor/wotbtools/shotPath.js';
import {createBattleTimeline} from './replay-effects-core.js';

const v=p=>new THREE.Vector3(...p);
export class ReplayBattleEffects {
  constructor(playback,sampler,{muzzleAt}={}){
    this.timeline=createBattleTimeline(playback);this.sampler=sampler;this.muzzleAt=muzzleAt;
    this.fx=createBattleFx(FX_BUDGETS.high);this.root=this.fx.root;this.root.name='replay-battle-effects';
    this.shotData=new Map();this.activePaths=new Map();this.burstPositions=new Map();this.last={};
  }
  shotDataFor(entry){
    if(this.shotData.has(entry.id))return this.shotData.get(entry.id);
    const from=v(entry.points[0]),impact=v(entry.points[1]),dir=impact.clone().sub(from).normalize();
    if(dir.lengthSq()<1e-8)dir.set(0,0,1);
    const tip=this.muzzleAt?.(entry.shot.shooter_eid,entry.start,from,dir)||from.clone();
    const data={from,impact,dir,tip,s0:Math.min(tip.distanceTo(from),entry.arc[0]),
                out:entry.points.length>2?v(entry.points[2]).sub(impact):null};
    this.shotData.set(entry.id,data);return data;
  }
  burstPosition(event){
    const key=event.eid+':'+event.time;
    if(!this.burstPositions.has(key)){
      const frame=this.sampler.poseAtRaw(event.eid,event.time,{lastKnown:true});
      this.burstPositions.set(key,frame?v([-frame.pose.x,frame.pose.y,frame.pose.z]):null);
    }
    return this.burstPositions.get(key);
  }
  update(raw,camera,height,vehicles){
    const fx=this.fx,frame=this.timeline.at(raw),glows=[];fx.clearTransients();
    const ids=new Set(frame.paths.map(s=>s.id));
    for(const [id,path] of this.activePaths)if(!ids.has(id)){
      fx.giveRibbon(path.tracer);for(const mesh of path.trails)fx.giveRibbon(mesh);this.activePaths.delete(id);
    }
    let muzzleCount=0,impactCount=0,burstCount=0,tracerCount=0,trailCount=0,wreckCount=0;
    for(const event of frame.events){
      if(event.type==='burst'){
        const pos=this.burstPosition(event);if(!pos)continue;
        fx.spawnBurst(pos,event.time*1000,event.seed);burstCount++;continue;
      }
      const data=this.shotDataFor(event.entry);
      if(event.type==='muzzle'){fx.spawnMuzzle(data.tip,data.dir,event.time*1000,event.entry.seed);muzzleCount++;}
      else {fx.spawnImpact(event.kind,data.impact,data.dir,data.out,event.time*1000,event.entry.seed);impactCount++;}
    }
    const head=new THREE.Vector3(),tail=new THREE.Vector3();
    for(const entry of frame.paths){
      let path=this.activePaths.get(entry.id);
      if(!path){path={tracer:fx.takeRibbon('tracer'),trails:entry.ends.map(()=>fx.takeRibbon('trail'))};this.activePaths.set(entry.id,path);}
      const data=this.shotDataFor(entry),sHead=arcAtTime(entry.points,entry.ends,entry.arc,raw,entry.start);
      path.tracer.visible=raw<entry.end&&sHead>data.s0;
      if(path.tracer.visible){
        pointAtInto(entry.points,entry.ends,raw,entry.start,head);
        pointAtArcInto(entry.points,entry.arc,Math.max(data.s0,sHead-TRACER_STREAK_M),tail);
        fx.setTracer(path.tracer,tail,head,entry.color);glows.push({head:head.clone(),color:entry.color});tracerCount++;
      }
      const opacity=trailOpacityAt(raw-entry.end);
      for(let k=0;k<path.trails.length;k++){
        const mesh=path.trails[k],start=k?entry.ends[k-1]:entry.start,len=entry.arc[k]-(k?entry.arc[k-1]:0);
        const fraction=Math.min(1,Math.max(0,(raw-start)/(entry.ends[k]-start))),f0=k?0:Math.min(1,data.s0/Math.max(len,1e-8));
        mesh.visible=len>1e-4&&opacity>0&&fraction>f0;
        if(mesh.visible){
          const a=v(entry.points[k]),b=v(entry.points[k+1]);
          fx.setTrail(mesh,tail.copy(a).lerp(b,f0),head.copy(a).lerp(b,fraction),entry.color,opacity);trailCount++;
        }
      }
    }
    fx.frame(raw*1000,camera,height,emit=>{
      for(const g of glows)emit.headGlow(g.head,g.color);
      for(const vehicle of vehicles||[]){
        if(vehicle.life?.lifeState!=='DESTROYED')continue;
        const p=vehicle.pose,since=raw-vehicle.life.destroyedKnownAtSec;
        emit.wreck(-p.x,p.y,p.z,-p.yaw,since,raw,vehicle.eid);wreckCount++;
      }
    });
    this.last={rawTime:raw,muzzles:muzzleCount,impacts:impactCount,bursts:burstCount,tracers:tracerCount,trails:trailCount,wrecks:wreckCount,...fx.stats(),
               invalidShots:this.timeline.invalidShots,totalShots:this.timeline.shots.length,
               activeShotIds:frame.paths.map(s=>s.id)};
  }
  diagnostics(){return this.last;}
  dispose(){this.fx.dispose();this.shotData.clear();this.activePaths.clear();this.burstPositions.clear();}
}
export {muzzleTipOf};
