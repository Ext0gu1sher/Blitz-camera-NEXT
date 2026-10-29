const {chromium}=require('playwright');
const {enterFixture}=require('./ui_fixture.cjs');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const out=path.resolve('output/preview-details-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],requests=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push(r.url()));
  await page.route('**/api/preview/select',r=>r.fulfill({status:400,json:{error:'合成测试场景'}}));
  const value=fn=>page.evaluate(fn),wait=fn=>page.waitForFunction(fn);
  const speed=()=>value(()=>Number(document.getElementById('previewCameraSpeed').textContent.match(/[\d.]+/)[0]));
  const pose=()=>value(()=>structuredClone(replayPreviewPane.override));
  try{
    await page.goto(process.argv[2]);await enterFixture(page);
    await value(async()=>{
      const p=replayPreviewPane,T=await import('/vendor/three/build/three.module.js');
      p.initRenderer();p.scene.add(new T.GridHelper(100,20));p.status='ready';document.getElementById('previewEmpty').hidden=true;p.render();
      window.originalTracks=structuredClone(state.tracks);window.originalDirty=state.dirty;
    });
    // Real focused buttons must route Space to transport and suppress the
    // button's default keyup click, including a held Space key.
    for(const [id,view] of [['previewCamera','camera'],['previewObserver','observer']]){
      await value(()=>seek(0));await page.locator('#'+id).click();
      assert.equal(await value(()=>document.activeElement.id),id);
      await page.keyboard.down('Space');await wait(()=>state.playing&&state.previewTime>.3);
      await page.keyboard.down('Space');assert.equal(await value(()=>state.playing),true);
      await page.keyboard.up('Space');assert.equal(await value(()=>replayPreviewPane.view),view);
      await wait(()=>replayPreviewPane.motionMeter.speed>.65&&replayPreviewPane.motionMeter.speed<1.35);
      assert.match(await page.locator('#previewCameraFov').textContent(),/60\.0°/);
      await page.keyboard.press('Space');assert.equal(await value(()=>state.playing),false);assert.equal(await speed(),0);
      await page.waitForTimeout(150);assert.equal(await value(()=>state.playing),false);
    }
    // Meter follows wall-clock playback speed, not just timeline distance.
    await value(()=>{seek(1);document.getElementById('previewSpeed').value='2';});
    await page.keyboard.press('Space');await wait(()=>state.playing&&replayPreviewPane.motionMeter.speed>1.6&&replayPreviewPane.motionMeter.speed<2.4);
    await page.keyboard.press('Space');await value(()=>{seek(40);document.getElementById('previewSpeed').value='1';});
    assert.equal(await speed(),0,'seeking must not produce a speed spike');
    await page.locator('.preview-alignment summary').click();await page.locator('#previewOffset').locator('..').locator('.number-value').dblclick();
    assert.equal(await value(()=>document.activeElement.id),'previewOffset');
    await page.keyboard.press('Space');assert.equal(await value(()=>state.playing),false,'text/number input must retain its keyboard behavior');
    await page.keyboard.press('Escape');await page.locator('.preview-alignment summary').click();
    await value(()=>{
      const p=replayPreviewPane;seek(.2);p.setView('camera');
      p.sampler={at:()=>[],rawTime:t=>t,recorderAt:(t,offset)=>window.missingRecorder?null:{pose:{x:50+(t+offset)*10,y:7,z:80,yaw:Math.PI/2+t*.1}}};p.offset=.25;
    });
    const enter=async()=>{await page.locator('#previewFly').click();await wait(()=>replayPreviewPane.flying&&document.pointerLockElement);};
    await enter();await page.keyboard.press('Space');await page.keyboard.down('x');
    await wait(()=>state.playing&&state.previewTime>.6&&replayPreviewPane.followingRear());
    const checkRear=async()=>{
      await wait(()=>{
        const p=replayPreviewPane,t=Number(document.getElementById('previewSceneTime').textContent.match(/[\d.]+/)[0]),angle=Math.PI/2+t*.1,expected=[50+(t+p.offset)*10-Math.sin(angle)*15,80-Math.cos(angle)*15,13];
        return p.override.position.every((v,i)=>Math.abs(v-expected[i])<.01)&&Math.abs(p.override.yaw-(-t*.1*180/Math.PI))<.01;
      });
    };
    await checkRear();await wait(()=>replayPreviewPane.motionMeter.speed>5);
    assert.match(await page.locator('#previewCameraFov').textContent(),/54\.0°/);
    assert.match(await page.locator('#previewFlightSpeed').textContent(),/车后跟随/);
    await page.keyboard.down('w');await page.mouse.move(720,430);await page.mouse.wheel(0,-100);
    await checkRear();await page.keyboard.up('w');
    assert.deepEqual(await value(()=>replayPreviewPane.flightVelocity),[0,0,0]);
    await page.keyboard.press('Space');assert.equal(await value(()=>state.playing),false);
    await page.waitForTimeout(150);const paused=await pose();assert.equal(await speed(),0);
    await page.waitForTimeout(150);assert.deepEqual(await pose(),paused);
    await page.keyboard.press('Space');await checkRear();await page.keyboard.up('x');
    const released=await pose();await page.waitForTimeout(220);assert.deepEqual(await pose(),released,'release keeps the camera while the tank continues playing');
    assert.equal(await value(()=>state.playing),true);assert.equal(await speed(),0);
    await page.mouse.wheel(0,-150);await wait(()=>replayPreviewPane.override.zoom<54);
    assert.match(await page.locator('#previewCameraFov').textContent(),new RegExp((await pose()).zoom.toFixed(1).replace('.','\\.')));
    await page.keyboard.press('Space');
    // Custom reset bindings, including release of the modifier, use the same
    // held-key lifecycle. Losing focus must not leave a hidden follow active.
    await value(async()=>{
      replayPreviewPane.stopFlight();const settings=await api('/api/settings');
      await api('/api/settings',{project_directory:settings.project_directory,input_controls:{...BlitzControls.config,bindings:{...BlitzControls.config.bindings,rear:'Shift+KeyH'}}});
      await refreshState();seek(.2);
    });
    await enter();await page.keyboard.press('Space');await page.keyboard.down('Shift');await page.keyboard.down('h');
    await wait(()=>replayPreviewPane.followingRear());await checkRear();
    await page.keyboard.up('Shift');await page.keyboard.up('h');assert.equal(await value(()=>replayPreviewPane.followingRear()),false);
    const modifierReleased=await pose();await page.waitForTimeout(150);assert.deepEqual(await pose(),modifierReleased);
    await page.keyboard.down('Shift');await page.keyboard.down('h');await checkRear();
    await value(()=>{window.missingRecorder=true;});await wait(()=>replayPreviewPane.rearUnavailable);
    const missing=await pose();await page.waitForTimeout(150);assert.deepEqual(await pose(),missing);
    await value(()=>{window.missingRecorder=false;});await wait(()=>!replayPreviewPane.rearUnavailable);await checkRear();
    await value(()=>window.dispatchEvent(new Event('blur')));await wait(()=>!replayPreviewPane.flying&&!document.pointerLockElement);
    assert.equal(await value(()=>state.playing),false);assert.equal(await value(()=>replayPreviewPane.flightKeys.size),0);
    await page.keyboard.up('h');await page.keyboard.up('Shift');
    // Narrow preview, long map name: metrics must remain inside the preview.
    await page.setViewportSize({width:1000,height:760});
    await value(()=>{document.getElementById('previewMap').textContent='测试地图 · Test map';replayPreviewPane.render();});
    const fits=await value(()=>{
      const scene=document.getElementById('replayScene').getBoundingClientRect(),hud=document.querySelector('.preview-camera-hud').getBoundingClientRect();
      return hud.left>=scene.left&&hud.right<=scene.right&&hud.top>=scene.top;
    });assert.equal(fits,true);
    await page.locator('#replayScene').screenshot({path:path.join(out,'preview-metrics.png')});
    assert.deepEqual(await value(()=>state.tracks),await value(()=>window.originalTracks));assert.equal(await value(()=>state.dirty),await value(()=>window.originalDirty));
    assert.ok(!requests.some(u=>/\/api\/(connect|playback\/start)$/.test(u)));assert.deepEqual(errors,[]);
    const result={passed:true,spaceAfterViewSwitch:true,telemetry:true,playbackSpeed:true,seekAndPauseReset:true,heldRearFollow:true,releasePreservesPose:true,customChord:true,missingPoseRecovery:true,blurCleanup:true,errors};
    fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
  }catch(error){await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});console.error(errors);throw error;}
  finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
