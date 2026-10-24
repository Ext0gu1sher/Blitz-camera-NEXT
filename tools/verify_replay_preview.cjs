const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const out=path.resolve('output/replay-preview-091-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',args:['--enable-webgl','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const errors=[],shaderErrors=[],requests=[];
 const page=await browser.newPage({viewport:{width:1440,height:1100}});
 page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')shaderErrors.push(m.text());});
 page.on('request',r=>{if(r.url().includes('/api/'))requests.push({url:r.url(),method:r.method()});});
 try{
  await page.goto(process.argv[2]);await page.waitForFunction(()=>window.BlitzReplayPreview&&typeof state!=='undefined'&&state.loaded);
  await page.waitForFunction(()=>replayPreviewPane?.status==='ready'||replayPreviewPane?.status==='error',{},{timeout:240000});
  assert.equal(await page.evaluate(()=>replayPreviewPane.status),'ready',await page.locator('#previewStatus').innerText());
  await page.waitForFunction(()=>document.body.dataset.appReady==='true');
  assert.deepEqual(errors,[]);
  const readings=await page.evaluate(()=>{let values=[];for(const t of [40,60,75,60]){seek(t);values.push(window.BlitzReplayPreviewDiagnostics());}return values;});
  const source=await page.evaluate(async()=>(await (await fetch('/api/preview/state')).json()).source);
  for(const reading of readings){assert.equal(reading.replayOrigin,source.replay_origin_sec);assert.equal(reading.rawTime,reading.time+source.replay_origin_sec+reading.offset);}
  assert.equal(readings[0].map,'canal');assert.ok(readings[1].visible.length>0);assert.ok(readings[1].triangles>0);
  assert.deepEqual(readings[1].visible,readings[3].visible);
  await page.locator('#replayScene').screenshot({path:path.join(out,'observer-0.9.1.png')});
  const battleEffects=await page.evaluate(()=>{
    const pane=replayPreviewPane,fx=pane.effects,origin=pane.sampler.origin+pane.offset;
    const seekRaw=t=>seek(t-origin);
    const snapshot=()=>JSON.stringify(fx.root.children.filter(o=>o.visible).map(o=>{
      const g=o.geometry;
      if(g.isInstancedBufferGeometry)return [o.name,...['iA','iB','iC'].map(k=>Array.from(g.attributes[k].array.slice(0,g.instanceCount*4)))];
      if(o.isLineSegments)return [o.name,...['position','color'].map(k=>Array.from(g.attributes[k].array.slice(0,g.drawRange.count*3)))];
      return [o.material.name,Object.fromEntries(Object.entries(o.material.uniforms).map(([k,u])=>[k,u.value?.toArray?.()??u.value]))];
    }));
    const entry=fx.timeline.shots.find(e=>pane.models.get(e.shot.shooter_eid)?.parts&&pane.sampler.poseAtRaw(e.shot.shooter_eid,e.start));
    seekRaw(entry.start+.05);const fire=structuredClone(fx.diagnostics()),data=fx.shotDataFor(entry),first=snapshot();
    const before=JSON.stringify([...pane.models].map(([id,v])=>[id,v.root.position.toArray(),v.root.quaternion.toArray(),v.parts?.entries.map(e=>e.node.matrix.toArray())]));
    pane.muzzleAt(entry.shot.shooter_eid,entry.start,data.from,data.dir);
    const after=JSON.stringify([...pane.models].map(([id,v])=>[id,v.root.position.toArray(),v.root.quaternion.toArray(),v.parts?.entries.map(e=>e.node.matrix.toArray())]));
    seekRaw(entry.start+10);seekRaw(entry.start+.05);const backward=first===snapshot();pane.render();const paused=first===snapshot();
    const impact=fx.timeline.events.find(e=>e.type==='impact');seekRaw(impact.time+.05);const hit=structuredClone(fx.diagnostics());
    const death=fx.timeline.deaths.find(e=>pane.sampler.poseAtRaw(e.eid,e.time,{lastKnown:true}));
    seekRaw(death.time+.6);const burst=structuredClone(fx.diagnostics()),wreck=pane.models.get(death.eid),wreckAmount=wreck.destroyedVisual.amount;
    const deathPose=wreck.root.position.toArray();seekRaw(death.time+10);
    const current=pane.sampler.poseAtRaw(death.eid,death.time+10,{lastKnown:true})?.pose;
    const wreckFollowsCurrent=current&&wreck.root.position.distanceTo({x:-current.x,y:current.y,z:current.z})<1e-8;
    seekRaw(death.time+.6);const wreckSeekStable=JSON.stringify(deathPose)===JSON.stringify(wreck.root.position.toArray());
    seekRaw(death.time-.2);const aliveAmount=wreck.destroyedVisual.amount;
    seekRaw(entry.start+.05);pane.setView('observer');pane.orbit.target.copy(data.tip);pane.observer.position.copy(data.tip).add({x:18,y:9,z:18});pane.orbit.update();pane.render();
    return {shots:fx.timeline.shots.length,invalid:fx.timeline.invalidShots,fire,hit,burst,paused,backward,muzzlePreservesPose:before===after,
      barrelReach:data.tip.distanceTo(data.from),wreckAmount,aliveAmount,wreckFollowsCurrent,wreckSeekStable,deathTime:death.time,deathEid:death.eid};
  });
  assert.equal(battleEffects.shots,80);assert.equal(battleEffects.invalid,0);assert.ok(battleEffects.fire.muzzles>0&&battleEffects.fire.tracers>0);
  assert.ok(battleEffects.hit.impacts>0&&battleEffects.hit.sparks>0);assert.ok(battleEffects.burst.bursts>0&&battleEffects.burst.wrecks>0);
  assert.ok(battleEffects.paused&&battleEffects.backward&&battleEffects.muzzlePreservesPose&&battleEffects.wreckFollowsCurrent&&battleEffects.wreckSeekStable);
  assert.ok(battleEffects.barrelReach>=.3&&battleEffects.barrelReach<=15);assert.ok(battleEffects.wreckAmount>0);assert.equal(battleEffects.aliveAmount,0);
  await page.locator('#replayScene').screenshot({path:path.join(out,'muzzle-fire.png')});
  await page.evaluate(({deathTime,deathEid})=>{const p=replayPreviewPane;seek(deathTime+.4-p.sampler.origin-p.offset);const model=p.models.get(deathEid);p.orbit.target.copy(model.root.position);p.observer.position.copy(model.root.position).add({x:18,y:10,z:18});p.orbit.update();p.render();},battleEffects);
  await page.locator('#replayScene').screenshot({path:path.join(out,'destruction-burst.png')});
  await page.evaluate(()=>{seek(60);replayPreviewPane.fit();});
  const clocks=await page.evaluate(()=>{
    const saved={mode:state.rateMode,frames:structuredClone(state.speedFrames),fixed:document.getElementById('replayFixedRate').value,speed:document.getElementById('previewSpeed').value};
    const advance=(start,seconds)=>{seek(start);state.playing=true;state.playbackStart=start;state.playbackAnchor=performance.now();animate(state.playbackAnchor+seconds*1000);stopPlayback();return {editor:state.previewTime,scene:BlitzReplayPreviewDiagnostics().time};};
    document.getElementById('previewSpeed').value='1';state.rateMode='fixed';document.getElementById('replayFixedRate').value='0.25';const fixed=advance(60,8);
    state.rateMode='curve';state.speedFrames=[{progress:0,rate:1},{progress:.25,rate:.25},{progress:.75,rate:.25},{progress:1,rate:1}];
    const settings=speedSettings(),duration=BlitzPreviewTime.duration(40,settings),expected=40+40*BlitzPreviewTime.atShooting(40,settings,8/duration).cameraProgress,curve=advance(40,8);
    state.rateMode=saved.mode;state.speedFrames=saved.frames;document.getElementById('replayFixedRate').value=saved.fixed;document.getElementById('previewSpeed').value=saved.speed;seek(60);
    return {fixed,curve,expected};
  });
  assert.ok(Math.abs(clocks.fixed.editor-62)<1e-8);assert.equal(clocks.fixed.scene,clocks.fixed.editor);
  assert.ok(Math.abs(clocks.curve.editor-clocks.expected)<1e-8);assert.equal(clocks.curve.scene,clocks.curve.editor);
  await page.locator('#previewCamera').click();
  const expected=await page.evaluate(async()=>{const response=await fetch('/api/evaluate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...editPayload(),time_sec:state.previewTime})});const v=await response.json();return {v,diag:window.BlitzReplayPreviewDiagnostics()};});
  assert.equal(expected.diag.view,'camera');
  const p=expected.v.pose.position;for(const [a,b] of expected.diag.camera.map((v,i)=>[v,[-p[0],p[2],p[1]][i]]))assert.ok(Math.abs(a-b)<1e-8);
  const q=expected.v.pose.quaternion;
  const cameraAgreement=await page.evaluate(async({q,diag})=>{const THREE=await import('/vendor/three/build/three.module.js');const frame=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0),Math.PI).multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1,0,0),-Math.PI/2));const target=frame.multiply(new THREE.Quaternion(q[1],q[2],q[3],q[0]));return 1-Math.abs(target.dot(new THREE.Quaternion(...diag.quaternion)));},{q,diag:expected.diag});
  assert.ok(cameraAgreement<1e-10);
  const zoom=expected.v.pose.horizontal_fov_deg,vertical=2*Math.atan(Math.tan(zoom*Math.PI/360)/(16/9))*180/Math.PI;
  assert.ok(Math.abs(vertical-expected.diag.angle)<1e-9);
  await page.locator('#previewObserver').click();await page.evaluate(()=>seek(66.123));await page.locator('#previewRecord').click();
  const recorded=await page.evaluate(()=>({counts:Object.values(state.tracks).map(a=>a.filter(k=>Math.abs(k.time_sec-66.123)<1e-5).length),dirty:state.dirty,time:state.previewTime}));
  assert.deepEqual(recorded.counts,[1,1,1,1,1,1,1]);assert.equal(recorded.dirty,true);assert.equal(recorded.time,66.123);
  const angles=await page.evaluate(async()=>{const {nearestAngle}=await import('/replay-preview-core.js');return [nearestAngle(-179,179),nearestAngle(179,-179),nearestAngle(10,730)];});
  assert.deepEqual(angles,[181,-181,730]);
  const savedView=await page.evaluate(async()=>{
    await window.BlitzFlushEditorSession();seek(64.125);const p=replayPreviewPane;
    p.observer.position.set(87,56,145);p.orbit.target.set(5,30,18);p.orbit.update();
    p.override={position:[101,71,42],yaw:26,pitch:-18,roll:2,zoom:67};p.setView('camera');p.render();
    await window.BlitzFlushEditorSession();return BlitzEditorSession.capturePreview(p);
  });
  const restoredPage=await browser.newPage({viewport:{width:1440,height:1100}});
  restoredPage.on('pageerror',e=>errors.push(e.message));restoredPage.on('console',m=>{if(m.type()==='error')shaderErrors.push(m.text());});
  await restoredPage.goto(process.argv[2]);await restoredPage.waitForFunction(()=>state.loaded&&replayPreviewPane?.status==='ready'&&!pendingEditorRestore&&!pendingPreviewRestore,{},{timeout:240000});
  const restoredView=await restoredPage.evaluate(()=>({time:state.previewTime,preview:BlitzEditorSession.capturePreview(replayPreviewPane)}));
  assert.equal(restoredView.time,64.125);assert.equal(restoredView.preview.view,'camera');assert.deepEqual(restoredView.preview.override,savedView.override);
  for(const key of ['position','target'])for(let i=0;i<3;i++)assert.ok(Math.abs(restoredView.preview.observer[key][i]-savedView.observer[key][i])<1e-9);
  await restoredPage.close();
  let secondMap=null;
  if(process.argv[3]){
    await page.evaluate(file=>replayPreviewPane.select(file),process.argv[3]);
    await page.waitForFunction(()=>replayPreviewPane.status==='ready'||replayPreviewPane.status==='error',{},{timeout:240000});
    assert.equal(await page.evaluate(()=>replayPreviewPane.status),'ready',await page.locator('#previewStatus').innerText());
    const changed=await page.evaluate(()=>{seek(60);return BlitzReplayPreviewDiagnostics();});
    const changedSource=await page.evaluate(async()=>(await (await fetch('/api/preview/state')).json()).source);
    assert.equal(changed.replayOrigin,changedSource.replay_origin_sec);assert.equal(changed.rawTime,60+changedSource.replay_origin_sec+changed.offset);
    secondMap=changed.map;assert.equal(secondMap,'plant');assert.notEqual(changed.source,readings[0].source);assert.ok(changed.triangles>0);assert.ok(changed.visible.length>0);
  }
  await page.locator('[name=shootingMode][value=camera_only]').check();
  assert.equal(await page.locator('#replayScene').isVisible(),false);assert.equal(await page.locator('#pathCanvas').isVisible(),true);assert.equal(await page.locator('.replay-speed-panel').isVisible(),false);
  assert.ok(!requests.some(r=>/\/api\/(connect|playback\/start|replay\/open)$/.test(r.url)));
  assert.deepEqual(errors,[]);assert.deepEqual(shaderErrors,[]);
  const result={ok:true,map:readings[0].map,secondMap,replayOrigin:source.replay_origin_sec,automaticReplayClockAlignment:true,vehicleRecords:readings[1].visible.length,triangles:readings[1].triangles,backwardSeekDeterministic:true,speedLinkedSceneClock:true,exactCameraEvaluatorAgreement:true,cameraQuaternionError:cameraAgreement,offlineSevenTrackRecord:true,realSceneCameraRestored:true,battleEffects,modeOneIsolated:true,gameRequests:0,errors,shaderErrors};
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }catch(e){console.error('preview diagnostics',await page.locator('#previewStatus').innerText().catch(()=>''),errors,shaderErrors);throw e;}
 finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
