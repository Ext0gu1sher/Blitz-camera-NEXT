// Deterministic event/particle acceptance; no browser or game connection.
import assert from 'node:assert/strict';
import * as THREE from '../blitzcam/web/vendor/three/build/three.module.js';
import {createBattleTimeline,teamShotColor} from '../blitzcam/web/replay-effects-core.js';
import {ReplayBattleEffects,muzzleTipOf} from '../blitzcam/web/replay-effects.js';
import {defLifeAt} from '../blitzcam/web/vendor/wotbtools/battlePlaybackV2.js';
import {destroyedVisualAmount,prepareTankDestroyedVisual,applyTankDestroyedVisual} from '../blitzcam/web/vendor/wotbtools/tankDestroyedVisual.js';

const vehicle={eid:1,team:1,death_t:12,death_times:[12,20],resurrection_times:[16]};
const shot={t_fire:10,shooter_eid:1,from:[10,2,0],to:[110,2,0],flight_secs:1,target_eid:2,is_author:true,hit_flags:0x10};
const ricochet={...shot,t_fire:11,via:[[60,2,0]],to:[80,25,0],leg_secs:[.25,.75],hit_flags:8};
const playback={meta:{friendly_team:1},vehicles:[vehicle,{eid:2,team:2}],shots:[shot,ricochet,{...shot,t_fire:13,target_eid:null},
  {...shot,t_fire:14,is_author:false,game_hit_result:255},{...shot,from:[NaN,0,0]}]};
const original=structuredClone(playback),timeline=createBattleTimeline(playback);
assert.deepEqual(playback,original);assert.equal(timeline.invalidShots,1);
assert.equal(timeline.shots.length,4);assert.deepEqual(timeline.shots[0].points,[[-10,2,0],[-110,2,0]]);
assert.equal(timeline.shots[0].color,0x3ee08a);assert.equal(teamShotColor(2,1),0xff5a45);assert.equal(teamShotColor(null,1),0xf5f5f5);
assert.equal(timeline.at(9.99).events.length,0);assert.equal(timeline.at(10.1).events[0].type,'muzzle');
assert.equal(timeline.events.find(e=>e.entry?.id===1&&e.type==='impact').time,11.25);
assert.equal(timeline.events.find(e=>e.entry?.id===1&&e.type==='impact').kind,'ricochet');
assert.equal(timeline.events.filter(e=>e.type==='impact').length,2); // No invented misses or unknown impacts.
assert.deepEqual(timeline.deaths.map(e=>e.time),[12,20]);
assert.equal(defLifeAt(vehicle,17).lifeState,'ALIVE');assert.equal(defLifeAt(vehicle,20).lifeState,'DESTROYED');
assert.ok(!timeline.at(15).paths.some(e=>e.id===0));assert.deepEqual(timeline.at(NaN),{events:[],paths:[]});

const camera=new THREE.PerspectiveCamera(55,16/9,.1,2000);camera.position.set(0,15,30);camera.lookAt(-25,2,0);
const pose={x:25,y:2,z:0,yaw:0,pitch:0,roll:0};let measurements=0;
const sampler={poseAtRaw:(eid,t)=>eid===1&&t>=0?{eid,pose}:null};
const effects=new ReplayBattleEffects(playback,sampler,{muzzleAt:(eid,t,from,dir)=>{measurements++;assert.equal(eid,1);return from.clone().addScaledVector(dir,3);}});
const snapshot=()=>effects.root.children.filter(o=>o.visible).map(o=>{
  const g=o.geometry,result={name:o.name,material:o.material.name};
  if(g.isInstancedBufferGeometry)result.particles=['iA','iB','iC'].map(k=>Array.from(g.attributes[k].array.slice(0,g.instanceCount*4)));
  else if(o.isLineSegments)result.lines=['position','color'].map(k=>Array.from(g.attributes[k].array.slice(0,g.drawRange.count*3)));
  else result.ribbon=Object.fromEntries(Object.entries(o.material.uniforms).map(([k,u])=>[k,u.value?.toArray?.()??u.value]));
  return result;
});
const at=t=>{effects.update(t,camera,720,[{eid:1,pose,life:defLifeAt(vehicle,t)}]);return structuredClone(snapshot());};
const fire=at(10.1);assert.equal(effects.diagnostics().muzzles,1);assert.equal(effects.diagnostics().tracers,1);
assert.ok(effects.diagnostics().glow>0&&effects.diagnostics().smoke>0);assert.equal(measurements,1);
assert.deepEqual(at(10.1),fire);at(30);assert.deepEqual(at(10.1),fire);assert.equal(measurements,1);
const hit=at(11.3);assert.equal(effects.diagnostics().impacts,2);assert.ok(effects.diagnostics().sparks>0);
at(9);assert.deepEqual(at(11.3),hit);
const burst=at(12.6);assert.equal(effects.diagnostics().bursts,1);assert.equal(effects.diagnostics().wrecks,1);
at(17);assert.equal(effects.diagnostics().wrecks,0);at(21);assert.equal(effects.diagnostics().bursts,1);
assert.deepEqual(at(12.6),burst);for(let i=0;i<20;i++){at(9);at(21);at(12.6);}assert.deepEqual(snapshot(),burst);
assert.ok(effects.diagnostics().ribbons<=6);assert.equal(measurements,4);
at(30);assert.equal(effects.diagnostics().glow,0);assert.ok(effects.diagnostics().smoke>0); // Persistent wreck smoke.
assert.equal(destroyedVisualAmount(defLifeAt(vehicle,12),12),0);assert.equal(destroyedVisualAmount(defLifeAt(vehicle,13),13),1);
assert.equal(destroyedVisualAmount(defLifeAt(vehicle,17),17),0);

// The mounted barrel bounds, rather than the vehicle origin, determine the muzzle.
const barrel=new THREE.Mesh(new THREE.BoxGeometry(1,1,8),new THREE.MeshStandardMaterial());barrel.position.set(-15,2,0);barrel.rotation.y=Math.PI/2;barrel.updateMatrixWorld();
assert.deepEqual(muzzleTipOf([barrel],new THREE.Vector3(-10,2,0),new THREE.Vector3(-1,0,0)).toArray(),[-19,2,0]);
const sourceMaterial=barrel.material,visual=prepareTankDestroyedVisual(barrel);assert.notEqual(barrel.material,sourceMaterial);
applyTankDestroyedVisual(visual,1);assert.equal(visual.amount,1);applyTankDestroyedVisual(visual,0);assert.equal(barrel.material.roughness,sourceMaterial.roughness);
let disposed=0;effects.root.traverse(o=>{o.geometry?.addEventListener('dispose',()=>disposed++);});effects.dispose();assert.ok(disposed>=3);
barrel.geometry.dispose();barrel.material.dispose();sourceMaterial.dispose();
console.log(JSON.stringify({ok:true,recordedEventClassification:true,rawClockAndMirroring:true,ricochetSegments:true,deathAndResurrection:true,barrelBounds:true,deterministicPausedAndBackwardParticles:true,boundedRibbonPool:true,resourceDisposal:true}));
