import assert from 'node:assert/strict';
import {createReplaySampler,validatePlayback,cameraBehindVehicle,cameraBasis} from '../../blitzcam/web/replay-preview-core.js';

const samples=31,zero=()=>Array(samples).fill(0);
const vehicle=(eid,account)=>({eid,account_id:account,tank_id:6929,
  pos:Array.from({length:samples},(_,i)=>[100+i,7,200]).flat(),
  hull_yaw:zero(),hull_pitch:zero(),turret_yaw:zero(),gun_pitch:zero(),coverage:[40,43],
  pose_kf:{t:[40,41,42.8],pos:[300,7,200,310,7,200,328,7,200],yaw:[0,0,0],pitch:[0,0,0]}});
const base={
  playback:{meta:{samples,t_start:40,duration:43,map_id:21},vehicles:[vehicle(7,1),vehicle(8,2)],
    visibility:[{eid:7,t_in:40,t_out:43},{eid:8,t_in:40,t_out:43}]},
  result:{players:[{account_id:1,team:1,tank_id:6929},{account_id:2,team:2,tank_id:6929}],result_duration_secs:10,author_account_id:1},
  ai:{battle:{periods:[{period:3,clock:33}],winner:1},rosters:[{eid:7,account_id:1,team:1,tank_id:6929},{eid:8,account_id:2,team:2,tank_id:6929}],events:[],poses:[],turrets:[]}
};
const origin=4.25;
assert.equal(validatePlayback(base.playback),base.playback);
for(const hasCurve of [true,false]){
  const bundle=structuredClone(base);
  if(!hasCurve)delete bundle.playback.vehicles[0].pose_kf;
  const saved=structuredClone(bundle),sampler=createReplaySampler(bundle,origin);
  for(const raw of [40,40.5,41,42.8]){
    const frames=sampler.at(raw-origin);
    assert.equal(frames.length,2);
    assert.ok(Math.abs(frames[0].pose.x-((hasCurve?300:100)+10*(raw-40)))<1e-8);
    assert.ok(Math.abs(frames[1].pose.x-(300+10*(raw-40)))<1e-8);
    assert.equal(frames[0].def,bundle.playback.vehicles[0]);
    assert.deepEqual(sampler.at(raw-origin),frames);
  }
  assert.deepEqual(sampler.at(39-origin),[]);
  assert.deepEqual(sampler.at(44-origin),[]);
  assert.deepEqual(bundle,saved);
  // Neither the curve nor the legacy grid may leak an invisible pose.
  for(const field of ['visibility','coverage']){
    const hidden=structuredClone(bundle);
    if(field==='visibility')hidden.playback.visibility[0].t_out=40.5;
    else hidden.playback.vehicles[0].coverage=[40,40.5];
    assert.deepEqual(createReplaySampler(hidden,origin).at(41-origin).map(f=>f.eid),[8]);
  }
}

for(const times of [[40,42,41.8127],[40,41,41]]){
  const bundle=structuredClone(base);bundle.playback.vehicles[0].pose_kf.t=times;
  assert.throws(()=>validatePlayback(bundle.playback),/时间顺序异常/);
  assert.throws(()=>createReplaySampler(bundle,origin),/时间顺序异常/);
}

// Destruction changes the material/life state, not the recorded motion clock.
// Follow WotbTools' current-time pose sampling while holding the last observed
// position through coverage/visibility gaps and after the final record.
for(const hasCurve of [true,false]){
  const bundle=structuredClone(base),v=bundle.playback.vehicles[0];v.death_t=40.5;
  if(!hasCurve)delete v.pose_kf;
  const saved=structuredClone(bundle),sampler=createReplaySampler(bundle,origin),first=hasCurve?300:100;
  for(const raw of [40.25,40.5,41,42.5,41,40.25]){
    const frame=sampler.at(raw-origin).find(f=>f.eid===7);
    assert.ok(Math.abs(frame.pose.x-(first+10*(raw-40)))<1e-8,'wreck must follow recorded displacement');
    assert.equal(frame.life.lifeState,raw>=40.5?'DESTROYED':'ALIVE');
  }
  assert.deepEqual(sampler.at(45-origin).find(f=>f.eid===7).pose,sampler.at(44-origin).find(f=>f.eid===7).pose,'no extrapolation after final pose');
  assert.deepEqual(bundle,saved);
  for(const field of ['coverage','visibility']){
    const hidden=structuredClone(bundle);
    if(field==='coverage')hidden.playback.vehicles[0].coverage=[40,41,42,43];
    else hidden.playback.visibility.splice(0,1,{eid:7,t_in:40,t_out:41},{eid:7,t_in:42,t_out:43});
    const sample=createReplaySampler(hidden,origin),at=raw=>sample.at(raw-origin).find(f=>f.eid===7);
    assert.equal(at(41.5).pose.x,first+10,'hidden wreck holds the last observation');
    assert.ok(Math.abs(at(42.5).pose.x-(first+25))<1e-8,'new observations resume wreck motion');
    hidden.playback.vehicles[0].resurrection_times=[41.2];hidden.playback.vehicles[0].death_times=[40.5,42.2];
    const resurrected=createReplaySampler(hidden,origin);
    assert.equal(resurrected.at(41.5-origin).find(f=>f.eid===7),undefined,'resurrected hidden vehicle is not a persistent wreck');
    assert.equal(resurrected.at(42.5-origin).find(f=>f.eid===7).life.lifeState,'DESTROYED');
  }
  v.death_t=39;const early=createReplaySampler(bundle,origin);
  assert.equal(early.at(39.5-origin).find(f=>f.eid===7),undefined,'destruction cannot reveal a future first position');
}

// Incomplete/nonfinite curves and invalid base grids still fail closed.
for(const corrupt of [
  v=>v.pose_kf.t[1]=NaN,
  v=>v.pose_kf.pos.pop(),
  v=>v.pose_kf.yaw[0]=Infinity,
  v=>v.pose_kf.pitch.pop(),
  v=>v.pos.pop(),
  v=>v.hull_yaw[0]=NaN,
  v=>v.coverage.push(44)
]){
  const bundle=structuredClone(base);
  corrupt(bundle.playback.vehicles[0]);
  assert.throws(()=>createReplaySampler(bundle,origin));
}
// X returns to the recorder at the displayed clock, never the first/nearest tank.
const rearBundle=structuredClone(base);rearBundle.result.author_account_id=2;
const rearSampler=createReplaySampler(rearBundle,origin),beforeRear=structuredClone(rearBundle);
for(const raw of [40,41.2,42.8,40.5]){
  const frame=rearSampler.recorderAt(raw-origin-.2,.2);
  assert.equal(frame.eid,8);
  assert.deepEqual(frame,rearSampler.at(raw-origin).find(f=>f.eid===8));
}
assert.equal(rearSampler.recorderAt(39-origin),null);
assert.equal(rearSampler.recorderAt(44-origin),null);
assert.deepEqual(rearBundle,beforeRear);
delete rearBundle.result.author_account_id;
assert.equal(createReplaySampler(rearBundle,origin).recorderAt(41-origin),null);
rearBundle.result.author_account_id=2;rearBundle.playback.vehicles[1].death_t=40.5;
assert.equal(createReplaySampler(rearBundle,origin).recorderAt(44-origin).eid,8,'destroyed recorder uses the displayed wreck');
rearBundle.ai.rosters[1].team=1;
assert.equal(createReplaySampler(rearBundle,origin).recorderAt(41-origin),null,'conflicting identity cannot select another tank');
for(const yaw of [0,Math.PI/2,Math.PI,-Math.PI/2,Math.PI*5.7]){
  const vehiclePose={x:100,y:7,z:200,yaw},saved={...vehiclePose},camera=cameraBehindVehicle(vehiclePose);
  const heading=[Math.sin(yaw),Math.cos(yaw)],delta=[camera.position[0]-100,camera.position[1]-200];
  assert.ok(delta[0]*heading[0]+delta[1]*heading[1]<0,'camera must be behind the hull');
  assert.ok(Math.abs(delta[0]*heading[1]-delta[1]*heading[0])<1e-9,'camera must be centered behind the hull');
  assert.ok(camera.position[2]>vehiclePose.y);
  const f=cameraBasis(camera.yaw,camera.pitch,camera.roll).forward;
  assert.ok(f[0]*heading[0]+f[1]*heading[1]>.9,'camera must face along the hull');
  assert.ok(f[2]<0);assert.equal(camera.roll,0);assert.equal(camera.zoom,54);
  assert.deepEqual(vehiclePose,saved);
}
for(const pose of [null,{}, {x:0,y:NaN,z:0,yaw:0}])assert.equal(cameraBehindVehicle(pose),null);
console.log(JSON.stringify({passed:true}));
