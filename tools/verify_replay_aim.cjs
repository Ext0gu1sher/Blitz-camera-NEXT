const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const output=path.resolve('output/replay-aim-acceptance');fs.mkdirSync(output,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',args:['--enable-webgl','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('console',m=>{if(m.type()==='error')errors.push(m.text());});
 try{
  await page.goto(process.argv[2]);
  await page.waitForFunction(()=>typeof replayPreviewPane!=='undefined'&&['ready','error'].includes(replayPreviewPane?.status),{},{timeout:240000});
  assert.equal(await page.evaluate(()=>replayPreviewPane.status),'ready',await page.locator('#previewStatus').innerText());
  await page.waitForFunction(()=>document.body.dataset.appReady==='true');
  const report=await page.evaluate(async()=>{
   const pane=replayPreviewPane,THREE=await import('/vendor/three/build/three.module.js');
   const wasm=await import('/vendor/agent/wotb_replay_wasm.js');await wasm.default({module_or_path:'/vendor/agent/wotb_replay_wasm_bg.wasm'});
   const bytes=new Uint8Array(await (await fetch('/api/preview/replay/'+pane.source.id)).arrayBuffer());
   const before=JSON.parse(wasm.parsePlayback(bytes));
   const changed=pane.data.playback.vehicles.map(v=>({eid:v.eid,tank:v.tank_id,samples:v.gun_pitch.filter((p,i)=>p!==before.vehicles.find(b=>b.eid===v.eid).gun_pitch[i]).length}));
   const directions=[],snapshots=[];let best=null;
   const author=pane.data.playback.vehicles.find(v=>v.account_id===pane.data.result.author_account_id)?.eid;
   // Use real GLBs in the renderer. Validate turret heading and barrel pitch
   // independently of the rig's pivot matrices, including hull pitch/roll.
   for(let raw=20;raw<pane.data.playback.meta.duration-1;raw+=3.7){
    seek(raw-pane.sampler.origin-pane.offset);
    for(const frame of pane.sampler.at(pane.time,pane.offset)){
     const item=pane.models.get(frame.eid),p=frame.pose,node=item?.parts?.gunNodes.find(n=>/^gun_\d+$/.test(n.name));
     if(!node||frame.life?.lifeState==='DESTROYED')continue;
     const actual=new THREE.Vector3(0,1,0).transformDirection(node.matrixWorld);
     if(!item.parts.itr){
      // Hull-local forward after horizontal aim and barrel elevation.
      const local=new THREE.Vector3(-Math.sin(p.turretRel)*Math.cos(p.gunPitch),Math.sin(p.gunPitch),Math.cos(p.turretRel)*Math.cos(p.gunPitch));
      const expected=local.applyEuler(new THREE.Euler(p.pitch,-p.yaw,-p.roll,'YXZ'));
      directions.push(actual.angleTo(expected)*180/Math.PI);
     }
     const i=Math.max(0,Math.min(before.meta.samples-1,Math.round((raw-before.meta.t_start)/.1))),old=before.vehicles.find(v=>v.eid===frame.eid).gun_pitch[i];
     const difference=Math.abs(p.gunPitch-old);
     if(frame.eid===author&&(!best||difference>best.difference))best={raw,eid:frame.eid,difference};
    }
   }
   const snap=()=>JSON.stringify([...pane.models].filter(([,m])=>m.root.visible).map(([id,m])=>[id,m.root.matrixWorld.toArray(),m.parts?.entries.map(e=>e.node.matrixWorld.toArray())]));
   for(const raw of [best.raw,best.raw+2,best.raw]){seek(raw-pane.sampler.origin-pane.offset);snapshots.push(snap());}
   const selected=pane.models.get(best.eid),gun=selected.parts.gunNodes.find(n=>/^gun_\d+$/.test(n.name));
   const forward=new THREE.Vector3(0,1,0).transformDirection(gun.matrixWorld);
   pane.setView('observer');pane.orbit.target.copy(selected.root.position).add(new THREE.Vector3(0,2,0));
   pane.observer.position.copy(pane.orbit.target).add(new THREE.Vector3(forward.z*12,5,-forward.x*12));pane.orbit.update();pane.render();
   window.aimComparison={before,best,fixedSampler:pane.sampler};
   return {map:pane.manifest.map.key,vehicles:changed.length,anchored:pane.data.aim.anchored.length,missing:pane.data.aim.missing,
    changed,directionSamples:directions.length,maxDirectionErrorDegrees:Math.max(...directions),backwardStable:snapshots[0]===snapshots[2],best};
  });
  assert.equal(report.anchored,report.vehicles);assert.deepEqual(report.missing,[]);
  assert.ok(report.changed.every(v=>v.samples>100));assert.ok(report.directionSamples>50);
  assert.ok(report.maxDirectionErrorDegrees<.00001);assert.ok(report.backwardStable);
  await page.locator('#replayScene').screenshot({path:path.join(output,`${process.argv[3]}-fixed.png`)});
  await page.evaluate(async()=>{
   const {createReplaySampler}=await import('/replay-preview-core.js'),p=replayPreviewPane;
   p.sampler=createReplaySampler({...p.data,playback:aimComparison.before},p.sampler.origin);p.render();
  });
  await page.locator('#replayScene').screenshot({path:path.join(output,`${process.argv[3]}-before.png`)});
  await page.evaluate(()=>{replayPreviewPane.sampler=aimComparison.fixedSampler;replayPreviewPane.render();});
  assert.deepEqual(errors,[]);report.passed=true;
  fs.writeFileSync(path.join(output,`${process.argv[3]}-result.json`),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
