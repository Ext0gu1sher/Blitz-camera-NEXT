// Isolated application acceptance. Never starts or connects to the game.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {enterFixture}=require('./ui_fixture.cjs');
const out=path.resolve('output/work-range-drag-app-acceptance');fs.mkdirSync(out,{recursive:true});
// Native pointer coordinates can be rounded to float32 in Chromium.
const near=(actual,expected,label)=>assert.ok(Math.abs(actual-expected)<1e-5,`${label}: ${actual} != ${expected}`);
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const page=await browser.newPage({viewport:{width:1550,height:1150}}),errors=[],gameRequests=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(/\/api\/(connect|playback\/start|replay\/open)$/.test(r.url()))gameRequests.push(r.url());});
 const read=()=>page.evaluate(()=>({data:sequenceEditor.data(),timeline:structuredClone(state.timeline),playhead:sequenceEditor.playhead,previewTime:state.previewTime,playing:state.playing,undo:sequenceEditor.undoStack.length,redo:sequenceEditor.redoStack.length,changes:window.rangeDragChanges,drag:sequenceEditor.drag?.kind,snap:sequenceEditor.snap,pointerAlt:window.rangePointerAlt,status:document.querySelector('[data-status]').textContent}));
 const fit=async(axis='replay')=>{await page.locator('[data-option=axis]').selectOption(axis);await page.evaluate(()=>{sequenceEditor.scale=24;sequenceEditor.render();sequenceEditor.scroll.scrollLeft=100;});await page.locator('.seq-scroll').scrollIntoViewIfNeeded();};
 const anchor=async(part,target)=>{
  const grip=page.locator(part==='range'?'[data-work=range]':`[data-work=${part}] .seq-work-grip`);await grip.scrollIntoViewIfNeeded();const r=await grip.boundingBox();assert.ok(r,`${part} handle visible`);
  const delta=await page.evaluate(({part,target})=>{const e=sequenceEditor,map=e.map(),before=e.doc.timeline,at=part==='end'?before.work_end_sec:before.work_start_sec;return e.x(target,map)-e.x(at,map);},{part,target});
  return {x:r.x+r.width/2,y:r.y+r.height/2,delta};
 };
 const start=async(part,target,{alt=false}={})=>{const p=await anchor(part,target);if(alt)await page.keyboard.down('Alt');await page.mouse.move(p.x,p.y);await page.mouse.down();assert.equal(await page.evaluate(()=>sequenceEditor.drag?.kind),'work','pointer hit draggable range');await page.mouse.move(p.x+p.delta,p.y,{steps:8});return p;};
 const finish=async({alt=false}={})=>{await page.mouse.up();if(alt)await page.keyboard.up('Alt');};
 const drag=async(part,target,options={})=>{await start(part,target,options);await finish(options);return read();};
 const undo=async()=>{await page.locator('[data-action=undo]').click();return read();};
 const redo=async()=>{await page.locator('[data-action=redo]').click();return read();};
 const save=async()=>{await page.locator('#saveButton').click();await page.waitForFunction(()=>document.querySelector('#savedLabel').textContent==='已保存');};
 try{
  await page.goto(process.argv[2]);await enterFixture(page);await page.waitForFunction(()=>state.loaded&&sequenceEditor?.doc&&state.samples.length>1);
  await page.evaluate(()=>{window.rangeDragChanges=0;const change=sequenceEditor.adapter.change;sequenceEditor.adapter.change=data=>{window.rangeDragChanges++;return change(data);};sequenceEditor.root.addEventListener('pointermove',event=>{window.rangePointerAlt=event.altKey;},{capture:true});seek(42);});
  await fit();const original=await read();assert.equal(original.data.timeline.work_start_sec,10);assert.equal(original.data.timeline.work_end_sec,30);
  const invariant=actual=>{assert.deepEqual(actual.data.tracks,original.data.tracks,'range dragging preserves camera keys');assert.deepEqual(actual.data.speed,original.data.speed,'range dragging preserves authored speed curve');near(actual.previewTime,42,'preview time retained');near(actual.playhead,42,'timeline playhead retained');};
  // Active preview pauses without scrubbing; interim values stay local until release.
  await page.evaluate(async()=>{await play();cancelAnimationFrame(state.animationRequest);state.animationRequest=0;});assert.equal((await read()).playing,true);
  await start('start',12.123,{alt:true});const live=await read();assert.equal(live.playing,false);near(live.data.timeline.work_start_sec,12.123,'live in point');assert.equal(live.timeline.work_start_sec,10);assert.equal(live.changes,0);assert.equal(live.undo,0);assert.match(live.status,/入 12\.123 s.*长 17\.877 s/);invariant(live);
  await finish({alt:true});const first=await read();near(first.timeline.work_start_sec,12.123,'committed application range');assert.equal(first.changes,1);assert.equal(first.undo,1);invariant(first);
  const undone=await undo();assert.deepEqual(undone.data.timeline,original.data.timeline);assert.equal(undone.undo,0);assert.equal(undone.redo,1);
  const redone=await redo();assert.deepEqual(redone.data.timeline,first.data.timeline);assert.equal(redone.undo,1);await undo();
  const outPoint=await drag('end',34.567,{alt:true});near(outPoint.timeline.work_end_sec,34.567,'out point drag');invariant(outPoint);await undo();
  const moved=await drag('range',14.125,{alt:true});near(moved.timeline.work_start_sec,14.125,'whole range start');near(moved.timeline.work_end_sec,34.125,'whole range end');invariant(moved);await undo();
  // Both cancellation paths discard the transaction and retain app/undo state.
  for(const cancellation of ['escape','pointercancel','lostpointercapture','blur']){
   const before=await read();await start('end',36,{alt:true});assert.notDeepEqual((await read()).data.timeline,before.data.timeline);
   if(cancellation==='escape')await page.keyboard.press('Escape');
   else if(cancellation==='pointercancel')await page.locator('#sequenceEditor').dispatchEvent('pointercancel',{pointerId:1,pointerType:'mouse'});
   else if(cancellation==='lostpointercapture'){await page.evaluate(()=>sequenceEditor.root.releasePointerCapture(sequenceEditor.drag.pointerId));await page.waitForFunction(()=>!sequenceEditor.drag);}
   else await page.evaluate(()=>window.dispatchEvent(new Event('blur')));
   await finish({alt:true});const cancelled=await read();assert.deepEqual(cancelled.data,before.data);assert.deepEqual(cancelled.timeline,before.timeline);assert.equal(cancelled.undo,before.undo);assert.equal(cancelled.changes,before.changes);assert.equal(cancelled.drag,undefined);invariant(cancelled);
  }
  // Starting a drag also invalidates preview play waiting for a draft response.
  let releaseDraft,holdDraft;const heldDraft=new Promise(resolve=>holdDraft=resolve),draftRelease=new Promise(resolve=>releaseDraft=resolve);
  await page.route('**/api/sample/draft',async route=>{const response=await route.fetch();holdDraft();await draftRelease;await route.fulfill({response});});
  await page.evaluate(()=>{clearTimeout(draftTimer);setDirty(true);window.delayedRangePlay=play();});await heldDraft;
  const pendingPlayBefore=await read(),pauseAnchor=await anchor('start',13);await page.mouse.move(pauseAnchor.x,pauseAnchor.y);await page.mouse.down();releaseDraft();await page.evaluate(()=>window.delayedRangePlay);
  const pendingPlayAfter=await read();assert.equal(pendingPlayAfter.playing,false);near(pendingPlayAfter.previewTime,pendingPlayBefore.previewTime,'pending preview play stays paused at original time');
  await page.keyboard.press('Escape');await page.mouse.up();await page.unroute('**/api/sample/draft');
  // A nearby camera key attracts an edge; Alt gives subframe positioning.
  const snapped=await drag('start',20.12);near(snapped.timeline.work_start_sec,20,'keyframe snap');await undo();
  const unsnapped=await drag('start',20.123,{alt:true});near(unsnapped.timeline.work_start_sec,20.123,'Alt bypasses frame/key snap');await undo();
  // Handles clamp at the replay boundary and cannot cross each other.
  const clampStart=await drag('start',-5,{alt:true});near(clampStart.timeline.work_start_sec,0,'left replay boundary');await undo();
  const crossed=await drag('start',40,{alt:true});near(crossed.timeline.work_start_sec,29.999,'start cannot cross end');near(crossed.timeline.work_end_sec,30,'out point remains fixed');await undo();
  const reversed=await drag('end',5,{alt:true});near(reversed.timeline.work_end_sec,10.001,'end cannot cross start');near(reversed.timeline.work_start_sec,10,'in point remains fixed');await undo();
  // Keyboard operations cannot mutate the document or resume preview mid-drag.
  const beforeKeys=await read();await start('start',14.125,{alt:true});const liveKeys=await read();
  for(const key of ['i','o','Space','Control+z','Control+Shift+z'])await page.keyboard.press(key);
  const afterKeys=await read();assert.deepEqual(afterKeys.data,liveKeys.data);assert.deepEqual(afterKeys.timeline,beforeKeys.timeline);assert.equal(afterKeys.undo,beforeKeys.undo);assert.equal(afterKeys.playing,false);assert.equal(afterKeys.changes,beforeKeys.changes);await page.keyboard.press('Escape');await finish({alt:true});
  // Shooting ruler uses the map captured at drag start through successive moves.
  await fit('shooting');const p=await anchor('start',16.789);await page.keyboard.down('Alt');await page.mouse.move(p.x,p.y);await page.mouse.down();
  const dx=await page.evaluate(()=>{const e=sequenceEditor,m=e.drag.map;return e.x(13.456,m)-e.x(10,m);});
  await page.mouse.move(p.x+dx,p.y,{steps:4});near((await read()).data.timeline.work_start_sec,13.456,'shooting drag first point');
  await page.mouse.move(p.x+p.delta,p.y,{steps:5});near((await read()).data.timeline.work_start_sec,16.789,'shooting drag uses frozen map');await finish({alt:true});invariant(await read());await undo();
  // A fixed-rate out point remains under the pointer when the new clock applies.
  await page.locator('#tabSpeed').click();await page.locator('#replayFixedRate').selectOption('0.25');await fit('shooting');
  await start('end',34,{alt:true});const beforeRelease=await page.locator('[data-work=end] .seq-work-grip').boundingBox();await finish({alt:true});
  const afterRelease=await page.locator('[data-work=end] .seq-work-grip').boundingBox();assert.ok(Math.abs(beforeRelease.x-afterRelease.x)<1,'shooting-ruler edge stays under pointer after release');await undo();await undo();assert.deepEqual((await read()).data.speed,original.data.speed);
  // Polling another window's update must not load through an active transaction.
  await fit();await save();assert.equal(await page.evaluate(()=>state.dirty),false);
  const external=await (await page.request.get(process.argv[2]+'/api/state')).json();external.project.replay_timeline.work_start_sec=11;external.project_revision++;
  external.replay_launch={id:'range-drag-external-launch',state:'launched',info:{name:'external.wotbreplay',replay_file:'D:/external.wotbreplay',duration_sec:100}};
  await page.route('**/api/state',route=>route.fulfill({json:external}));
  await start('start',14.125,{alt:true});const liveExternal=await read();await page.evaluate(()=>refreshState());
  assert.deepEqual((await read()).data,liveExternal.data);assert.equal((await read()).undo,liveExternal.undo);assert.equal(await page.evaluate(()=>!!state.pendingProject),true);assert.equal(await page.locator('#externalChange').isVisible(),true);
  external.replay_launch={state:'idle'};
  await page.keyboard.press('Escape');await finish({alt:true});near((await read()).data.timeline.work_start_sec,10,'external poll cancellation baseline');
  await page.evaluate(()=>refreshState());near((await read()).data.timeline.work_start_sec,11,'external update loads after cancellation');assert.equal(await page.evaluate(()=>!!state.pendingProject),false);
  await page.unroute('**/api/state');await page.evaluate(async()=>{await refreshState();seek(42);});near((await read()).data.timeline.work_start_sec,10,'real project restored after external fixture');
  // Changes persist through the normal save/reload path.
  await fit();await drag('start',12.123,{alt:true});await drag('end',35.678,{alt:true});await save();await page.reload();await enterFixture(page);await page.waitForFunction(()=>state.loaded&&sequenceEditor?.doc);
  const loaded=await read();near(loaded.timeline.work_start_sec,12.123,'saved in point');near(loaded.timeline.work_end_sec,35.678,'saved out point');assert.deepEqual(loaded.data.tracks,original.data.tracks);assert.deepEqual(loaded.data.speed,original.data.speed);
  await page.locator('.sequence-panel').screenshot({path:path.join(out,'draggable-in-out.png')});
  await page.locator('[name=shootingMode][value=camera_only]').check();await page.waitForFunction(()=>sequenceEditor.free());assert.equal(await page.locator('[data-work]').count(),0);
  assert.deepEqual(errors,[]);assert.deepEqual(gameRequests,[]);
  const result={passed:true,inOutDraggable:true,wholeRangeDraggable:true,pauseWithoutSeek:true,pendingPlayCancelled:true,liveReadout:true,oneCommitPerDrag:true,cameraKeysAndSpeedUnchanged:true,undoRedo:true,escapeRollback:true,pointerCancelRollback:true,lostCaptureRollback:true,blurRollback:true,snapAndAlt:true,clampedBoundaries:true,noCrossing:true,keyboardBlockedDuringDrag:true,frozenShootingRuler:true,shootingReleaseAnchored:true,externalUpdateProtected:true,replayAutoBindDeferred:true,saveReload:true,noRangeInCameraOnly:true,errors,gameRequests};
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }catch(error){await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});console.error(errors,await read().catch(()=>({})));throw error;}
 finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
