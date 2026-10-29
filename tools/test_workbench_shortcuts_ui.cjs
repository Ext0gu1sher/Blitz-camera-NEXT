// Real keyboard events against an isolated workbench; no game access.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {enterFixture,setSpeedCurveFixture}=require('./ui_fixture.cjs');

(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const context=await browser.newContext({viewport:{width:1550,height:1150},permissions:['clipboard-read','clipboard-write']});
 const page=await context.newPage(),errors=[],gameRequests=[],checks=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(/\/api\/(connect|playback\/start|replay\/open)$/.test(r.url()))gameRequests.push(r.url());});
 const read=()=>page.evaluate(()=>({data:sequenceEditor.data(),playing:state.playing,undo:sequenceEditor.undoStack.length}));
 const selectX=()=>page.evaluate(()=>{const e=sequenceEditor;e.selected=new Set([e.doc.tracks.x.find(k=>k.time_sec===10)._id]);e.render();});
 const stop=async()=>{if((await read()).playing){await page.keyboard.press('Space');await page.waitForFunction(()=>!state.playing);}};
 try{
  await page.goto(process.argv[2]);await enterFixture(page);await page.waitForFunction(()=>state.loaded&&sequenceEditor?.doc&&state.samples.length>1);
  if(process.env.SHORTCUT_SCENARIO!=='space'){
   for(const [name,time] of [['tab',40],['button',45],['range',50],['body',55]]){
    await selectX();
    if(name==='tab')await page.locator('#tabCamera').click();
    if(name==='button')await page.locator('#loopButton').focus();
    if(name==='range')await page.locator('#timelineSlider').focus();
    if(name==='body')await page.evaluate(()=>document.activeElement.blur());
    await page.keyboard.press('Control+c');
    assert.match(await page.evaluate(()=>navigator.clipboard.readText()),/^BlitzCamera keyframes\n/,`copy with ${name} focused`);
    await page.evaluate(time=>seek(time),time);
    await page.keyboard.press('Control+v');
    await page.waitForFunction(time=>sequenceEditor.data().tracks.x.some(k=>Math.abs(k.time_sec-time)<1e-7),time,{timeout:1500});
    assert.equal((await read()).data.tracks.x.find(k=>k.time_sec===time).value,10,`paste with ${name} focused`);
   }
   checks.push('keyframe clipboard works with workbench tab, button, range and body focus');
   await selectX();await page.locator('#tabCamera').focus();const beforeCut=(await read()).data;
   await page.keyboard.press('Control+x');assert.deepEqual((await read()).data,beforeCut);
   checks.push('cut remains scoped to the keyframe editor');
   await page.evaluate(()=>{const e=sequenceEditor;e.selected=new Set([e.doc.tracks.x.find(k=>k.time_sec===10)._id]);e.render();showTab('Curve');});
   const field=page.locator('#presetName');await field.fill('ordinary text');await field.press('Control+a');await field.press('Control+c');
   assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),'ordinary text');await field.fill('');await field.press('Control+v');assert.equal(await field.inputValue(),'ordinary text');
   checks.push('text input retains native clipboard');
   await selectX();await page.locator('#tabCamera').focus();
   await page.evaluate(()=>{const range=document.createRange();range.selectNodeContents(document.getElementById('tabCamera'));const selection=getSelection();selection.removeAllRanges();selection.addRange(range);});
   await page.keyboard.press('Control+c');assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),'镜头');
   await page.evaluate(()=>getSelection().removeAllRanges());checks.push('selected page text retains native copy');
   // A hidden workbench must not receive a keyframe paste through stale focus.
   const before=await read();
   for(const guard of ['home','settings','draft','dialog']){
    await page.evaluate(guard=>{
     const e=sequenceEditor,old={home:state.home,settings:state.settingsOpen};
     if(guard==='home')state.home=true;
     if(guard==='settings')state.settingsOpen=true;
     if(guard==='draft')document.getElementById('draftGuard').hidden=false;
     if(guard==='dialog')document.getElementById('cameraDeleteDialog').showModal();
     const data=new DataTransfer();data.setData('text/plain','BlitzCamera keyframes\n'+JSON.stringify(e.clipboard));
     e.scroll.dispatchEvent(new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:data}));
     state.home=old.home;state.settingsOpen=old.settings;document.getElementById('draftGuard').hidden=true;
     if(guard==='dialog')document.getElementById('cameraDeleteDialog').close();
    },guard);
    assert.deepEqual((await read()).data,before.data,`keyframes changed while ${guard} was open`);
   }
   checks.push('home, settings and dialogs block stale keyframe paste');
  }
  if(process.env.SHORTCUT_SCENARIO!=='clipboard'){
   await page.locator('#tabSpeed').click();await setSpeedCurveFixture(page);
   await page.evaluate(()=>seek(sequenceEditor.map().rateTime(.13)));
   await page.locator('#sequenceEditor [data-add=rate]').click();
   let before=await read();assert.equal(before.data.speed.keyframes.length,5);
   // Reproduce the old focus state: a button focused by keyboard still has its
   // normal Space activation, including the duplicate-speed-key warning.
   await page.locator('#sequenceEditor [data-add=rate]').focus();await page.keyboard.press('Space');
   assert.match(await page.locator('#toast').textContent(),/当前时刻已有速率关键帧/);assert.equal((await read()).playing,false);
   // A mouse click now returns focus to the timeline before the next Space.
   await page.locator('#sequenceEditor [data-add=rate]').click();await page.evaluate(()=>{document.getElementById('toast').textContent='';});
   await page.keyboard.press('Space');await page.waitForFunction(()=>state.playing,null,{timeout:1500});
   assert.deepEqual((await read()).data,before.data);assert.doesNotMatch(await page.locator('#toast').textContent(),/已有.*关键帧/);
   await stop();checks.push('Space after timeline speed add does not show a duplicate-keyframe error');
   await setSpeedCurveFixture(page);
   await page.evaluate(()=>seek(sequenceEditor.map().rateTime(.13)));
   await page.locator('[data-speed-action=add]').click();
   before=await read();assert.equal(before.data.speed.keyframes.length,5);
   await page.keyboard.press('Space');await page.waitForFunction(()=>state.playing,null,{timeout:1500});
   assert.deepEqual((await read()).data,before.data);assert.doesNotMatch(await page.locator('#toast').textContent(),/已有.*关键帧/);
   await stop();checks.push('Space after mouse-adding speed key plays without adding again');
   // Keyboard focus retains normal button activation and its accessible Space action.
   await page.evaluate(()=>seek(sequenceEditor.map().rateTime(.18)));
   await page.locator('[data-speed-action=add]').focus();await page.keyboard.press('Space');
   assert.equal((await read()).data.speed.keyframes.length,6);assert.equal((await read()).playing,false);
   checks.push('keyboard-focused keyframe button still responds to Space');
   await page.evaluate(()=>seek(32));await page.locator('#addKeyframeButton').click();
   await page.waitForFunction(()=>state.tracks.x.some(k=>Math.abs(k.time_sec-32)<1e-7));before=await read();
   await page.keyboard.press('Space');await page.waitForFunction(()=>state.playing,null,{timeout:1500});
   assert.deepEqual((await read()).data,before.data);await stop();
   checks.push('Space after mouse-adding camera keys plays without adding again');
   // Use a mocked endpoint to exercise the record button without a game session.
   let captureRequests=0;
   await page.route('**/api/capture',route=>{captureRequests++;return route.fulfill({status:400,json:{error:'该时刻已有属性关键帧。'}});});
   await page.locator('#tabCamera').click();await page.evaluate(()=>{state.dirty=false;document.getElementById('captureButton').disabled=false;});
   await page.locator('#captureButton').click();await page.waitForFunction(()=>!state.busy);assert.equal(captureRequests,1);
   await page.keyboard.press('Space');await page.waitForFunction(()=>state.playing,null,{timeout:1500});
   assert.equal(captureRequests,1);await stop();checks.push('Space after record does not send a second capture request');
   // Preview record is stubbed so the focus behavior can be checked without a 3D replay.
   await page.evaluate(()=>{window.previewRecordClicks=0;replayPreviewPane.record=()=>{previewRecordClicks++;};document.getElementById('replayPreviewControls').hidden=false;document.getElementById('previewRecord').disabled=false;});
   await page.locator('#previewRecord').click();assert.equal(await page.evaluate(()=>previewRecordClicks),1);
   await page.keyboard.press('Space');await page.waitForFunction(()=>state.playing,null,{timeout:1500});
   assert.equal(await page.evaluate(()=>previewRecordClicks),1);await stop();checks.push('Space after preview record does not record again');
  }
  assert.deepEqual(errors,[]);assert.deepEqual(gameRequests,[]);
  const result={passed:true,checks,errors,gameRequests};
  if(!process.env.SHORTCUT_SCENARIO){const out=path.resolve('output/workbench-shortcuts-acceptance');fs.mkdirSync(out,{recursive:true});fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));}
  console.log(JSON.stringify(result));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
