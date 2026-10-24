import assert from 'node:assert/strict';
import {createReplaySampler,validatePlayback} from '../../blitzcam/web/replay-preview-core.js';

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
console.log(JSON.stringify({passed:true}));
