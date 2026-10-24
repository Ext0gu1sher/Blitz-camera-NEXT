// Headless, isolated fixture only. No desktop UI control or real game calls.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const timing=require('../blitzcam/web/preview-time.js');
const {enterFixture}=require('./ui_fixture.cjs');
const asymmetric={mode:'curve',interpolation:'smooth',camera_clock:'shooting',keyframes:[{progress:0,rate:1},{progress:1,rate:.25}]};
assert.equal(timing.rateAt(asymmetric,.5),.625);assert.equal(timing.integral(asymmetric,.5),.4296875);
assert.equal(timing.atShooting(10,asymmetric,.5).replayElapsed,4.296875);
const replayCurve={...asymmetric,camera_clock:'replay'};
assert.equal(timing.atShooting(10,replayCurve,.5).shootingDuration,16);
assert.equal(timing.atShooting(10,replayCurve,.5).cameraProgress,.6875);
assert.ok(Math.abs(timing.atCamera(10,replayCurve,.6875).shootingProgress-.5)<1e-10);
assert.equal(timing.atShooting(8,{mode:'paused'},.5).replayElapsed,0);
assert.equal(timing.duration(8,{mode:'fixed',rate:.25,camera_clock:'replay'}),32);
const {ClockMap}=require('../blitzcam/web/timeline.js');
const tracks={x:[{time_sec:12,value:0},{time_sec:20,value:8}]};
for(const settings of [{mode:'fixed',rate:.25,camera_clock:'replay'},replayCurve]){
 const map=new ClockMap(tracks,settings);
 for(const t of [12,12.25,15,19.5,20])assert.ok(Math.abs(map.atSeconds(map.atTime(t))-t)<1e-9);
}
assert.equal(new ClockMap(tracks,{mode:'fixed',rate:.25,camera_clock:'replay'}).atTime(16),16);
const base=process.argv[2],out=path.resolve('output/attribute-keyframes-073-acceptance');
fs.mkdirSync(out,{recursive:true});
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  const errors=[],mapRequests=[];
  try{
    const context=await browser.newContext({viewport:{width:328,height:608},deviceScaleFactor:1});
    await context.addInitScript(()=>{
      window.__messages=[];window.__hostListeners=[];
      window.chrome.webview={postMessage:m=>window.__messages.push(m),addEventListener:(type,fn)=>window.__hostListeners.push(fn)};
    });
    context.on('request',r=>{if(/terrain|map-cache/.test(r.url()))mapRequests.push(r.url());});
    const page=await context.newPage();page.on('pageerror',e=>{errors.push(e.message);console.error('UI error:',e.message);});
    await page.goto(base+'/overlay?panel=keyframes');
    await page.waitForFunction(()=>document.querySelector('#attributeSummary').textContent.includes('28 个属性关键帧')&&!document.querySelector('#miniPreview').disabled);
    assert.equal(await page.locator('#frames, #frameDetail, #rename, #captureName').count(),0);
    assert.doesNotMatch(await page.locator('body').innerText(),/机位/);
    assert.equal(await page.locator('#liveOrientation, #liveFov').count(),0);
    assert.equal(await page.locator('#liveForward').isEnabled(),true);
    const within=await page.locator('#liveStop').boundingBox();assert.ok(within.y+within.height<=608,'Playback controls must be visible without scrolling');
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await page.locator('#miniSlider').evaluate(e=>{e.value=.5;e.dispatchEvent(new Event('input'));});
    assert.match(await page.locator('#miniSpeedReadout').textContent(),/0.250×.*5.00 \/ 10.00 s.*\+2.19 s/);
    const graphWidth=(await page.locator('#miniSpeedGraph').boundingBox()).width;
    assert.equal(Number(await page.locator('#miniSpeedGraph [data-speed-cursor]').getAttribute('x1')),32+(graphWidth-42)*.5);
    const cameraBefore=await page.locator('#miniCanvas').evaluate(e=>e.toDataURL());
    const canvas=await page.locator('#miniCanvas').boundingBox();
    await page.mouse.move(canvas.x+100,canvas.y+90);await page.mouse.down();await page.mouse.move(canvas.x+150,canvas.y+110,{steps:4});await page.mouse.up();
    const cameraRotated=await page.locator('#miniCanvas').evaluate(e=>e.toDataURL());assert.notEqual(cameraBefore,cameraRotated);
    await page.mouse.wheel(0,-180);
    assert.notEqual(cameraRotated,await page.locator('#miniCanvas').evaluate(e=>e.toDataURL()));
    await page.locator('#miniFit').click();assert.equal(cameraBefore,await page.locator('#miniCanvas').evaluate(e=>e.toDataURL()));
    await page.screenshot({path:path.join(out,'right-3d.png'),omitBackground:true});
    assert.equal(await page.locator('#terrainMap, #terrainFit, #terrainPath, #terrainStatus, [data-view=map], script[src*=terrain]').count(),0);
    assert.equal((await (await page.request.get(base+'/api/state')).json()).playback.active,false);
    await page.locator('#miniSlider').evaluate(e=>{e.value=.7;e.dispatchEvent(new Event('input'));});
    await page.waitForFunction(()=>document.querySelector('#miniTime').textContent.startsWith('7.00'));
    const selected=await (await page.request.get(base+'/api/state')).json();assert.equal(selected.ui.selected_time,0);
    await page.locator('#miniPreview').click();
    await page.waitForFunction(()=>document.querySelector('#miniSlider').value>.71);
    await page.locator('#miniPreview').click();
    await page.locator('[data-view=xy]').click();assert.equal(await page.locator('[data-view=xy]').getAttribute('aria-pressed'),'true');
    const before=(await (await page.request.get(base+'/api/state')).json()).project;
    await page.locator('#pathDuration').locator('..').locator('.number-value').dblclick();await page.locator('#pathDuration').fill('12');await page.locator('#pathDuration').press('Enter');
    await page.waitForFunction(()=>document.querySelector('#miniTime').textContent.endsWith('/ 12.00 s'));
    const retimed=(await (await page.request.get(base+'/api/state')).json()).project;
    retimed.keyframes.forEach((f,i)=>assert.ok(Math.abs(f.time_sec-[0,4.8,8.4,12][i])<1e-10));
    before.keyframes.forEach((f,i)=>{const {time_sec,...pose}=f;const {time_sec:t,...actual}=retimed.keyframes[i];assert.deepEqual(actual,pose);});
    await page.screenshot({path:path.join(out,'right-panel.png'),omitBackground:true});
    await page.locator('#liveForward').click();
    await page.waitForFunction(()=>!document.querySelector('#liveStop').disabled&&document.querySelector('#pathDuration').disabled);
    let state=await (await page.request.get(base+'/api/state')).json();assert.equal(state.playback.reverse,false);assert.equal(state.playback.orientation_enabled,true);assert.equal(state.playback.fov_enabled,true);
    await page.locator('#liveStop').click();await page.waitForFunction(()=>!document.querySelector('#liveReverse').disabled);
    await page.locator('#liveReverse').click();
    await page.waitForFunction(()=>!document.querySelector('#liveStop').disabled);
    state=await (await page.request.get(base+'/api/state')).json();assert.equal(state.playback.reverse,true);assert.equal(state.playback.orientation_enabled,true);assert.equal(state.playback.fov_enabled,true);
    await page.locator('#liveStop').click();
    await page.waitForFunction(()=>!document.querySelector('#liveForward').disabled);
    const telemetry=await context.newPage();telemetry.on('pageerror',e=>errors.push(e.message));
    await telemetry.setViewportSize({width:272,height:298});await telemetry.goto(base+'/overlay?panel=telemetry');
    await telemetry.waitForFunction(()=>document.querySelector('#yaw').textContent==='0.00°');
    assert.equal(await telemetry.getByText('摄像机水平角度',{exact:true}).count(),1);
    assert.equal(await telemetry.getByText('缩放',{exact:true}).count(),1);
    assert.doesNotMatch(await telemetry.locator('body').innerText(),/FOV|偏航/i);
    assert.equal(await telemetry.evaluate(()=>{const e=document.querySelector('.angles dt');return e.scrollWidth<=e.clientWidth;}),true);
    await telemetry.screenshot({path:path.join(out,'telemetry-panel.png'),omitBackground:true});
    assert.doesNotMatch(await page.locator('body').innerText(),/FOV|偏航/i);
    const top=await context.newPage();top.on('pageerror',e=>errors.push(e.message));
    await top.setViewportSize({width:830,height:102});await top.goto(base+'/overlay?panel=connection');
    await top.locator('#workbench').click();
    assert.ok(await top.evaluate(()=>window.__messages.some(m=>m.command==='workbench')));
    await top.evaluate(()=>window.__hostListeners.forEach(fn=>fn({data:{type:'host-action',action:'workbench',ok:true}})));
    await top.screenshot({path:path.join(out,'top-panel.png'),omitBackground:true});
    // The normal browser preview must navigate directly to the full workbench.
    const browserContext=await browser.newContext({viewport:{width:1250,height:850}});
    browserContext.on('request',r=>{if(/\/api\/preview\/(prepare|asset\/)|map-cache/.test(r.url()))mapRequests.push(r.url());});
    const browserPage=await browserContext.newPage();browserPage.on('pageerror',e=>errors.push(e.message));
    await browserPage.goto(base+'/overlay?panel=connection');await browserPage.locator('#workbench').click();
    await browserPage.waitForURL(base+'/');await browserPage.waitForSelector('.seq-key[data-channel=x]',{state:'attached'});
    const version=await (await browserPage.request.get(base+'/api/state')).json();
    assert.ok((await browserPage.locator('.version-label').textContent()).includes(version.version));
    assert.equal(await browserPage.locator('.seq-key[data-channel=x]').count(),4);
    assert.equal(await browserPage.locator('#keyframeRows, .keyframe-table').count(),0);
    assert.doesNotMatch(await browserPage.locator('body').innerText(),/机位/);
    assert.equal(await browserPage.locator('#liveOrientation, #liveFov').count(),0);
    assert.doesNotMatch(await browserPage.locator('body').innerText(),/FOV|偏航/i);
    assert.equal(await browserPage.locator('#terrainMap, #terrainFit, #terrainPath, #terrainStatus, [data-view=map], script[src*=terrain]').count(),0);
    const beforeView=(await (await browserPage.request.get(base+'/api/state')).json()).project;
    await browserPage.locator('[data-view=xz]').click();
    await browserPage.locator('[data-view="3d"]').click();
    await browserPage.locator('#fitButton').click();
    await browserPage.locator('.preview-panel').screenshot({path:path.join(out,'workbench-grid.png')});
    assert.deepEqual((await (await browserPage.request.get(base+'/api/state')).json()).project,beforeView);
    await browserPage.locator('[name=shootingMode][value=camera_only]').check();
    for(const [id,reverse]of[['liveForward',false],['liveReverse',true]]){
      await browserPage.waitForFunction(()=>!document.querySelector('#liveForward').disabled);
      await browserPage.locator('#'+id).click();
      await browserPage.waitForFunction(()=>!document.querySelector('#liveStop').disabled);
      state=await (await page.request.get(base+'/api/state')).json();
      assert.equal(state.playback.reverse,reverse);assert.equal(state.playback.orientation_enabled,true);assert.equal(state.playback.fov_enabled,true);
      await browserPage.locator('#liveStop').click();
    }
    await browserPage.waitForFunction(()=>!document.querySelector('#liveForward').disabled);
    await browserPage.locator('[name=shootingMode][value=replay]').check();await browserPage.locator('#tabSpeed').click();await browserPage.locator('#replayFixedRate').selectOption('0.25');assert.equal(await browserPage.locator('#cameraClock').inputValue(),'replay');
    await browserPage.waitForTimeout(500);
    await browserPage.locator('#timelineSlider').evaluate(e=>{e.value=6;e.dispatchEvent(new Event('input'));});
    assert.match(await browserPage.locator('#speedPreviewReadout').textContent(),/0.250×.*24.00 \/ 48.00 s.*\+6.00 s/);
    await browserPage.locator('#timelineSpeedPreset').click();assert.equal(await browserPage.locator('#cameraClock option').count(),1);
    await browserPage.locator('#playButton').click();
    await browserPage.waitForFunction(()=>Number(document.querySelector('#timelineSlider').value)>6.05);
    assert.equal(await browserPage.locator('#speedGraph [data-speed-cursor]').count(),1);
    assert.equal(await browserPage.locator('.seq-label').count(),7);
    assert.equal(await browserPage.locator('.seq-rate-label').count(),1);
    await browserPage.locator('#playButton').click();
    await browserPage.locator('.sequence-panel').screenshot({path:path.join(out,'timeline-before-edit.png')});

    // Change only one zoom key. Position and all other parameter keys must stay fixed.
    await browserPage.locator('.seq-key[data-channel=zoom]').nth(1).click();
    for(const [field,value]of [['time','5.25'],['value','79']]){const input=browserPage.locator(`[data-field=${field}]`);await input.locator('..').locator('.number-value').dblclick();await input.fill(value);await input.press('Enter');}
    await browserPage.waitForTimeout(600);
    assert.equal(await browserPage.locator('.seq-key[data-channel=zoom].selected').count(),1);
    await browserPage.locator('#saveButton').click();
    await browserPage.waitForFunction(()=>document.querySelector('#savedLabel').textContent==='已保存');
    let channelState=(await (await browserPage.request.get(base+'/api/state')).json()).project;
    assert.equal(channelState.replay_speed.camera_clock,'replay');
    channelState.camera_tracks.x.forEach((k,i)=>assert.ok(Math.abs(k.time_sec-[0,4.8,8.4,12][i])<1e-10));
    assert.ok(channelState.camera_tracks.zoom.some(k=>k.time_sec===5.25&&k.value===79));
    assert.equal(channelState.camera_tracks.yaw.some(k=>k.time_sec===5.25),false);
    await browserPage.locator('[data-action=undo]').click();await browserPage.locator('[data-action=undo]').click();
    await browserPage.locator('#saveButton').click();
    await browserPage.waitForFunction(()=>document.querySelector('#savedLabel').textContent==='已保存');
    channelState=(await (await browserPage.request.get(base+'/api/state')).json()).project;
    assert.equal(channelState.camera_tracks.zoom.some(k=>k.time_sec===5.25),false);
    await browserPage.locator('[data-action=redo]').click();await browserPage.locator('[data-action=redo]').click();
    await browserPage.locator('#saveButton').click();
    await browserPage.waitForFunction(()=>document.querySelector('#savedLabel').textContent==='已保存');
    const restoredTracks=(await (await browserPage.request.get(base+'/api/state')).json()).project.camera_tracks;
    // On a shooting-time ruler, changing the rate moves camera key positions,
    // without changing any replay-time camera timestamps in persisted data.
    await browserPage.locator('[name=shootingMode][value=replay]').check();await browserPage.locator('#tabSpeed').click();await browserPage.locator('#replayFixedRate').selectOption('0.25');
    await browserPage.locator('#replayFixedRate').selectOption('1');
    const lastX=()=>browserPage.locator('.seq-key[data-channel=x]').last().evaluate(e=>e.querySelector('.seq-key-hit').getAttribute('x'));
    const atNormal=Number(await lastX());
    await browserPage.locator('#replayFixedRate').selectOption('0.25');
    const atSlow=Number(await lastX());assert.equal(atSlow,atNormal);
    await browserPage.locator('#saveButton').click();
    await browserPage.waitForFunction(()=>document.querySelector('#savedLabel').textContent==='已保存');
    const fixedState=(await (await browserPage.request.get(base+'/api/state')).json()).project;
    assert.deepEqual(fixedState.camera_tracks,restoredTracks);
    await browserPage.locator('[data-action=fit]').click();
    await browserPage.locator('.sequence-panel').screenshot({path:path.join(out,'timeline-fixed-quarter.png')});
    // Reopen the main page: independent parameter keys must survive serialization.
    const persisted=JSON.stringify(fixedState.camera_tracks);
    await browserPage.reload();await browserPage.waitForSelector('.seq-key[data-channel=zoom]');await enterFixture(browserPage);
    assert.equal(await browserPage.locator('.seq-key[data-channel=zoom]').count(),4);
    assert.equal(JSON.stringify((await (await browserPage.request.get(base+'/api/state')).json()).project.camera_tracks),persisted);
    await browserPage.locator('#tabSpeed').click();
    await browserPage.locator('#timelineSpeedPreset').click();
    await browserPage.locator('[data-action=fit]').click();
    await browserPage.locator('.sequence-panel').screenshot({path:path.join(out,'timeline-seven-tracks.png')});

    // Exercise actual pointer dragging, then verify only that parameter changed.
    const zoomKey=browserPage.locator('.seq-key[data-channel=zoom]').nth(1);
    await zoomKey.click();const zoomBefore=Number(await browserPage.locator('[data-field=time]').inputValue());
    let box=await zoomKey.boundingBox();
    await browserPage.mouse.move(box.x+box.width/2,box.y+box.height/2);await browserPage.mouse.down();
    await browserPage.mouse.move(box.x+box.width/2+25,box.y+box.height/2,{steps:4});await browserPage.mouse.up();
    assert.notEqual(Number(await browserPage.locator('[data-field=time]').inputValue()),zoomBefore);
    await browserPage.locator('#saveButton').click();
    await browserPage.waitForFunction(()=>document.querySelector('#savedLabel').textContent==='已保存');
    let dragged=(await (await browserPage.request.get(base+'/api/state')).json()).project;
    for(const name of ['x','y','z','yaw','pitch','roll'])assert.deepEqual(dragged.camera_tracks[name],fixedState.camera_tracks[name]);
    // Drag a speed key vertically: camera timestamps must stay unchanged.
    const camerasBeforeRate=dragged.camera_tracks;
    const rateKey=browserPage.locator('.seq-key[data-channel=rate]').first();box=await rateKey.boundingBox();
    await browserPage.mouse.move(box.x+box.width/2,box.y+box.height/2);await browserPage.mouse.down();
    await browserPage.mouse.move(box.x+box.width/2,box.y+box.height/2+8,{steps:4});await browserPage.mouse.up();
    await browserPage.locator('#saveButton').click();
    await browserPage.waitForFunction(()=>document.querySelector('#savedLabel').textContent==='已保存');
    const speedDragged=(await (await browserPage.request.get(base+'/api/state')).json()).project;
    assert.deepEqual(speedDragged.camera_tracks,camerasBeforeRate);
    assert.ok(speedDragged.replay_speed.keyframes[0].rate<1);
    assert.equal(speedDragged.replay_speed.keyframes[0].progress,0);
    // Delete and keyboard undo operate on a single axis, including after saving.
    await browserPage.locator('.seq-key[data-channel=x]').nth(1).click();
    await browserPage.keyboard.press('Delete');
    assert.equal(await browserPage.locator('.seq-key[data-channel=x]').count(),3);
    await browserPage.locator('.seq-scroll').focus();await browserPage.keyboard.press('Control+z');
    assert.equal(await browserPage.locator('.seq-key[data-channel=x]').count(),4);
    await browserPage.locator('[data-option=axis]').selectOption('replay');
    await browserPage.locator('[data-option=axis]').selectOption('shooting');
    await browserPage.locator('#timelineSlider').evaluate(e=>{e.value=3.2;e.dispatchEvent(new Event('input'));});
    const beforeAdd=(await (await browserPage.request.get(base+'/api/state')).json()).project;
    await browserPage.locator('[data-add=zoom]').click();
    await browserPage.waitForFunction(()=>document.querySelectorAll('.seq-key[data-channel=zoom]').length===5);
    assert.equal(await browserPage.locator('.seq-key[data-channel=x]').count(),4);
    assert.deepEqual((await (await browserPage.request.get(base+'/api/state')).json()).project,beforeAdd);
    await browserPage.locator('[data-action=undo]').click();
    assert.equal(await browserPage.locator('.seq-key[data-channel=zoom]').count(),4);
    assert.equal(await browserPage.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    await browserPage.locator('.sequence-panel').screenshot({path:path.join(out,'timeline-verified.png')});
    await browserPage.screenshot({path:path.join(out,'workbench.png')});
    // A single record writes all seven properties at the paused replay time.
    if(await browserPage.locator('#saveButton').isEnabled()){
      await browserPage.locator('#saveButton').click();
      await browserPage.waitForFunction(()=>document.querySelector('#savedLabel').textContent==='已保存');
    }
    const capture=await context.newPage();capture.on('pageerror',e=>errors.push(e.message));
    await capture.setViewportSize({width:272,height:238});await capture.goto(base+'/overlay?panel=capture');
    await capture.waitForFunction(()=>!document.querySelector('#capture').disabled);
    assert.equal(await capture.locator('#captureName, #renameName').count(),0);
    assert.equal(await capture.locator('#captureTime').inputValue(),'12.000000');
    assert.equal(await capture.locator('#captureTime').getAttribute('readonly'),'');
    assert.doesNotMatch(await capture.locator('body').innerText(),/机位|FOV|偏航/i);
    const captureBox=await capture.locator('#capture').boundingBox();assert.ok(captureBox.y+captureBox.height<=238);
    for(const [capturePage,button,replace] of [[capture,'#capture','#replace'],[browserPage,'#captureButton','#replaceExisting']]){
      const currentState=await (await capturePage.request.get(base+'/api/state')).json(),beforeCapture=currentState.project;
      if(capturePage===browserPage){await capturePage.waitForFunction(revision=>state.serverRevision===revision&&!state.dirty,currentState.project_revision);await capturePage.locator('#tabCamera').click();}
      await capturePage.locator(replace).check();
      const [recordResponse]=await Promise.all([capturePage.waitForResponse(r=>r.url()===base+'/api/capture'),capturePage.locator(button).click()]);
      assert.equal(recordResponse.ok(),true,await recordResponse.text());
      await capturePage.waitForFunction(()=>document.querySelector('#toast').textContent.includes('已记录全部七项属性关键帧'));
      const afterCapture=(await (await capturePage.request.get(base+'/api/state')).json()).project;
      for(const [name,value] of Object.entries({x:0,y:0,z:20,yaw:0,pitch:0,roll:0,zoom:60})){
        assert.equal(afterCapture.camera_tracks[name].find(k=>k.time_sec===12).value,value);
        assert.deepEqual(afterCapture.camera_tracks[name].filter(k=>k.time_sec!==12),beforeCapture.camera_tracks[name].filter(k=>k.time_sec!==12));
      }
      assert.deepEqual(afterCapture.replay_timeline,beforeCapture.replay_timeline);
      assert.equal((await (await capturePage.request.get(base+'/api/state')).json()).playback.active,false);
    }
    await capture.screenshot({path:path.join(out,'capture-panel.png'),omitBackground:true});
    assert.deepEqual(errors,[]);
    assert.deepEqual(mapRequests,[]);
    fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({status:'passed',scope:'headless synthetic fixture; no game or desktop automation',checks:['7 independent camera tracks and bottom speed track','replay-bound default clock','fixed-rate keys move on shooting ruler without retiming replay keys','single-parameter inspector edits','pointer camera and speed key drags','delete and keyboard undo','undo redo across saves','independent channels survive reload','grid preview in both UIs','map controls and asset requests removed','full-camera list, details, naming and numbered markers removed','one-click record writes seven independent properties','preview scrubbing does not select a full camera state','offline preview','3D orbit zoom and reset','rate graph playhead and integrated replay time','fixed-rate replay clock preview','visible play controls','retiming preserves full poses','channels always enabled in both UIs and directions','channel switches removed','zoom and horizontal-angle labels','stop remains available','workbench bridge acknowledgement','browser workbench navigation'],errors},null,2));
    console.log('PASS: seven-channel timeline, clock mapping, key editing, pointer drags, undo/redo, persistence and overlay regression (synthetic fixture)');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
