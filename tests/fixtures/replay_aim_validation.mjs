import assert from 'node:assert/strict';
import * as THREE from '../../blitzcam/web/vendor/three/build/three.module.js';
globalThis.window={dispatchEvent(){}};
const {ReplayPreviewPane}=await import('../../blitzcam/web/replay-preview.js');
const root=new THREE.Group();
for(const name of ['turret_1','turret_2','gun_1','gun_2','gun_2_mask']){
  const node=new THREE.Group();node.name=name;root.add(node);
  if(name==='gun_2'){const child=new THREE.Group();child.name='gun_2_nc';node.add(child);}
}
const parts=ReplayPreviewPane.prototype.rig(root,{model_origins:{track:[0,0,0],turret:[0,1,2]},
  configs:[{turret_local:7,gun_local:8,turret_node:2,gun_node:2,gun_origin:[0,2,.5]}]},
  {turret_local:7,gun_local:8});
assert.equal(root.getObjectByName('turret_1').visible,false);
assert.equal(root.getObjectByName('gun_1').visible,false);
assert.deepEqual(parts.entries.map(e=>e.node.name),['turret_2','gun_2','gun_2_mask']);
const gun=root.getObjectByName('gun_2_nc'),base={x:10,y:20,z:30,yaw:0,pitch:0,roll:0,turretRel:0,gunPitch:0};
const third=Math.PI/6,half=Math.PI/2,h=Math.sqrt(3)/2;
// Explicit geometric expectations in the mirrored Y-up scene (not another
// copy of the rig's matrix formula). Include hull slope and independent aim.
const cases=[
  [{},[0,0,1]], [{yaw:half},[-1,0,0]],
  [{yaw:half,turretRel:-half},[0,0,1]],
  [{turretRel:half,gunPitch:third},[-h,.5,0]],
  [{pitch:third},[0,-.5,h]],
  [{pitch:third,gunPitch:third},[0,0,1]],
  [{roll:third,turretRel:half},[-h,.5,0]],
];
const sample=pose=>{
  ReplayPreviewPane.prototype.poseModel({root,parts},{...base,...pose});root.updateMatrixWorld(true);
  return new THREE.Vector3(0,1,0).transformDirection(gun.matrixWorld).toArray();
};
for(let cycle=0;cycle<3;cycle++)for(const [pose,expected] of [...cases,...cases.toReversed()]){
  sample({yaw:2,gunPitch:-.1,turretRel:3});
  const actual=sample(pose);actual.forEach((v,i)=>assert.ok(Math.abs(v-expected[i])<1e-10,`${JSON.stringify(pose)}: ${actual}`));
  assert.deepEqual(sample(pose),actual);
}
console.log(JSON.stringify({passed:true,directionCases:cases.length,backwardSeekDeterministic:true}));
