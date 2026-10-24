// Offline acceptance for the supplied Faust/Rhm replay and live camera snapshot.
// Uses a temporary service/project; never connects to or changes the game.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const snapshot=JSON.parse(fs.readFileSync(process.argv[3],'utf8').replace(/^\uFEFF/,'')),out=process.argv[4];
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',args:['--enable-webgl','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1868,height:1280}}),errors=[],shaderErrors=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('console',m=>{if(m.type()==='error'&&/shader|WebGLProgram/i.test(m.text()))shaderErrors.push(m.text());});
 try{
  await page.goto(process.argv[2]);
  await page.waitForFunction(()=>typeof replayPreviewPane!=='undefined'&&['ready','error'].includes(replayPreviewPane?.status),{},{timeout:240000});
  assert.equal(await page.evaluate(()=>replayPreviewPane.status),'ready',await page.locator('#previewStatus').innerText());
  await page.waitForFunction(()=>document.body.dataset.appReady==='true');
  const report=await page.evaluate(async snapshot=>{
   const pane=replayPreviewPane,THREE=await import('/vendor/three/build/three.module.js');
   seek(snapshot.editor_state.timeline.playhead);pane.setView('camera');pane.render();
   const live=snapshot.sample,pose=pane.evaluated,camera=pane.shot;
   const delta={position:pose.position.map((v,i)=>v-live.camera.position[i]),yaw:pose.yaw-live.camera.yaw_deg,pitch:pose.pitch-live.camera.pitch_deg,roll:pose.roll-live.camera.roll_deg,zoom:pose.zoom-live.camera.horizontal_fov_deg};
   const ray=new THREE.Raycaster();ray.setFromCamera(new THREE.Vector2(0,0),camera);
   const hits=ray.intersectObject(pane.assetsGroup,true).filter(hit=>{let n=hit.object;while(n){if(!n.visible)return false;n=n.parent;}return true;});
   const hit=hits[0],normal=hit.face.normal.clone(),matrix=hit.object.matrixWorld.clone();
   if(hit.instanceId!==undefined){const inst=new THREE.Matrix4();hit.object.getMatrixAt(hit.instanceId,inst);matrix.multiply(inst);}
   normal.applyNormalMatrix(new THREE.Matrix3().getNormalMatrix(matrix));
   const culling={};pane.assetsGroup.traverse(o=>{for(const m of [o.material].flat())if(m?.userData.clientCullMode!==undefined)culling[m.userData.clientCullMode]=(culling[m.userData.clientCullMode]||0)+1;});
   return {editorTime:pane.time,gameTime:live.replay.time,delta,near:camera.near,gameNear:live.raw_camera.projection[14],gameAspect:live.raw_camera.aspect,previewAspect:camera.aspect,
    center:{distance:hit.distance,facing:normal.dot(ray.ray.direction),material:hit.object.material.name},culling,engine:pane.data.engine};
  },snapshot);
  assert.deepEqual(report.delta.position,[0,0,0]);
  for(const key of ['yaw','pitch','roll','zoom'])assert.ok(Math.abs(report.delta[key])<1e-5,key);
  assert.equal(report.near,report.gameNear);
  assert.ok(report.culling[0]>0&&report.culling[2]>0,'retain both explicitly two-sided and back-culled materials');
  assert.ok(report.center.distance>10&&report.center.distance<20,'center ray must reach the tank, not the near wall back face');
  assert.equal(report.center.material,'RhB_Waffentrager_mtr');assert.ok(report.center.facing<0);
  await page.locator('#replayScene').screenshot({path:path.join(out,'camera-corrected.png')});
  report.wreck=await page.evaluate(async()=>{
   const p=replayPreviewPane,origin=p.sampler.origin+p.offset;
   const {buildPoseFacet,sampleVehiclePoseGame}=await import('/vendor/wotbtools/vehiclePose.js');
   const facet=buildPoseFacet(p.data.playback),def=facet.vehicles.find(v=>v.eid===6883665),rawDef=p.data.playback.vehicles.find(v=>v.eid===def.eid),death=rawDef.death_t??rawDef.death_times[0];
   const at=raw=>{
    seek(raw-origin);const model=p.models.get(def.eid),frame=p.sampler.at(raw-origin,p.offset).find(f=>f.eid===def.eid);
    const expected=sampleVehiclePoseGame(def,facet,raw,undefined,def.visibility);
    return {raw,visible:model.root.visible,life:frame?.life.lifeState,position:model.root.position.toArray(),rotation:model.root.quaternion.toArray(),expected:[-expected.x,expected.y,expected.z]};
   };
   const samples=[death,death+.6,death+2,death+5,death+10,death+.6].map(at);
   const before=samples.at(-1);p.render();const stable=JSON.stringify(before.position)===JSON.stringify(p.models.get(def.eid).root.position.toArray());
   // Use the user's authored camera inside the hall; an orbit camera above it
   // sees the catwalk ceiling instead of the moving wreck below.
   seek(death+.6-origin);p.setView('camera');p.render();
   return {eid:def.eid,death,samples,stable};
  });
  for(const s of report.wreck.samples){assert.equal(s.visible,true);assert.equal(s.life,'DESTROYED');for(let i=0;i<3;i++)assert.ok(Math.abs(s.position[i]-s.expected[i])<1e-8);}
  assert.deepEqual(report.wreck.samples[1],report.wreck.samples.at(-1));assert.ok(report.wreck.stable);
  report.wreck.distance=Math.hypot(...report.wreck.samples[4].position.map((v,i)=>v-report.wreck.samples[0].position[i]));
  assert.ok(report.wreck.distance>17&&report.wreck.distance<18,'real replay has post-destruction motion');
  await page.locator('#replayScene').screenshot({path:path.join(out,'wreck-moving.png')});
  report.errors=errors;report.shaderErrors=shaderErrors;
  fs.writeFileSync(path.join(out,'alignment.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
  assert.deepEqual(errors,[]);assert.deepEqual(shaderErrors,[]);
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
