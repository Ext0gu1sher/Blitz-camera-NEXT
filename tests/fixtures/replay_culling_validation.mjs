import assert from 'node:assert/strict';
import * as THREE from '../../blitzcam/web/vendor/three/build/three.module.js';
import {assembleSceneryMaterials} from '../../blitzcam/web/vendor/wotbtools/sceneryAssembly.js';
import {clearSceneryMatCache} from '../../blitzcam/web/vendor/wotbtools/sceneryMaterials.js';
import {collectInstanceEntries,groupInstanceBatches,buildInstancedMesh} from '../../blitzcam/web/vendor/wotbtools/sceneryInstancing.js';

const scene=new THREE.Group(),maps={};
for(const name of ['maskTexOf','lmTexOf','detailTexOf','envTexOf','waterTexOf','decalTexOf'])maps[name]=()=>null;
maps.lmTexOf=()=>new THREE.Texture();maps.maskTexOf=()=>new THREE.Texture();
const cases=[];
for(const kind of ['wall','lightmap','foliage','sky','blend','decal','water']){
 for(const mode of [0,1,2]){
  const m=new THREE.MeshStandardMaterial({name:kind,side:THREE.DoubleSide});m.userData.clientCullMode=mode;
  if(kind==='lightmap')m.userData.lightmap=0;
  if(kind==='foliage')m.name='ST|same-leaf';
  if(kind==='sky')m.userData.sky=true;
  if(kind==='blend')m.userData.blendLayer=true;
  if(kind==='decal')m.userData.decal=true;
  if(kind==='water'){m.userData.water=true;m.transparent=true;m.opacity=.7;}
  const geo=new THREE.PlaneGeometry(2,2);geo.setAttribute('uv1',geo.attributes.uv.clone());
  const mesh=new THREE.Mesh(geo,m);mesh.name=kind;scene.add(mesh);cases.push({mesh,mode,kind});
 }
}
assembleSceneryMaterials({scene},{strictSurfaces:true,masks:maps,groundLayers:{layers:{},texs:{cm:new THREE.Texture()}}});
for(const {mesh,mode,kind} of cases){
 assert.equal(mesh.material.side,[THREE.DoubleSide,THREE.BackSide,THREE.FrontSide][mode],`${kind} culling ${mode}`);
 assert.equal(mesh.material.userData.clientCullMode,mode);
}
// Identical textures/names with different culling must not share a material.
assert.notEqual(cases[0].mesh.material,cases[2].mesh.material);
const wall=cases.find(c=>c.kind==='wall'&&c.mode===2).mesh;
scene.updateMatrixWorld(true);
const batches=groupInstanceBatches(collectInstanceEntries(wall),100);
assert.equal(batches.length,1);
const instanced=buildInstancedMesh(batches[0]);instanced.updateMatrixWorld(true);
const ray=new THREE.Raycaster(new THREE.Vector3(0,0,-2),new THREE.Vector3(0,0,1));
assert.equal(ray.intersectObject(instanced).length,0,'wall back face cannot block the shot after instancing');
ray.set(new THREE.Vector3(0,0,2),new THREE.Vector3(0,0,-1));
assert.ok(ray.intersectObject(instanced).length>0,'wall front face remains visible');
clearSceneryMatCache();
console.log(JSON.stringify({passed:true,cases:cases.length}));
