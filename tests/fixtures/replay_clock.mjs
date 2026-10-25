import assert from 'node:assert/strict';
import {createReplaySampler,cameraEvaluator} from '../../blitzcam/web/replay-preview-core.js';

const samples=31,zero=()=>Array(samples).fill(0);
const bundle={
  playback:{meta:{samples,t_start:40,duration:43,map_id:21},vehicles:[{
    eid:7,account_id:1,tank_id:6929,
    pos:Array.from({length:samples},(_,i)=>[100+i,7,200]).flat(),
    hull_yaw:zero(),hull_pitch:zero(),turret_yaw:zero(),gun_pitch:zero(),coverage:[40,43]
  }],visibility:[{eid:7,t_in:40,t_out:43}]},
  result:{players:[{account_id:1,team:1,tank_id:6929}],result_duration_secs:10,author_account_id:1},
  ai:{battle:{periods:[{period:3,clock:33}],winner:1},rosters:[{eid:7,account_id:1,team:1,tank_id:6929}],events:[],poses:[],turrets:[]}
};
for(const origin of [0,1.8336540460586548,4.18244743347168,15.758445739746094]){
  const sampler=createReplaySampler(bundle,origin);
  for(const raw of [40,40.5,41,42.8]){
    const client=raw-origin,frame=sampler.at(client);
    assert.equal(sampler.rawTime(client),raw);assert.equal(frame.length,1);
    assert.ok(Math.abs(frame[0].pose.x-(100+10*(raw-40)))<1e-8);
    assert.equal(sampler.at(client-10).length,0);
    if(raw<42.8)assert.ok(Math.abs(sampler.at(client,.1)[0].pose.x-sampler.at(client+.1)[0].pose.x)<1e-8);
  }
}
assert.throws(()=>createReplaySampler(bundle));assert.throws(()=>createReplaySampler(bundle,NaN));
const tracks=Object.fromEntries(['x','y','z','yaw','pitch','roll','zoom'].map(name=>[name,[{time_sec:38.262415,value:name==='zoom'?60:10}]]));
const saved=structuredClone(tracks),camera=cameraEvaluator(tracks,false,'linear');
assert.deepEqual(camera(38.262415).position,[10,10,10]);assert.deepEqual(tracks,saved);
const empty=Object.fromEntries(Object.keys(tracks).map(name=>[name,[]]));
assert.equal(cameraEvaluator(empty,true,'linear')(0),null);
empty.x=[{time_sec:20,value:45}];
assert.deepEqual(cameraEvaluator(empty,true,'linear')(22),{position:[45,0,0],yaw:0,pitch:0,roll:0,zoom:60});
assert.equal(empty.zoom.length,0);
console.log(JSON.stringify({passed:true}));
