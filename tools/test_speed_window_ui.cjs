const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const T=require('../blitzcam/web/preview-time.js');
const {enterFixture}=require('./ui_fixture.cjs');
const out=path.resolve('output/speed-window-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const page=await browser.newPage({viewport:{width:1550,height:1150}}),errors=[],gameRequests=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(/\/api\/(connect|playback\/start|replay\/open)$/.test(r.url()))gameRequests.push(r.url());});
 const read=()=>page.evaluate(()=>({data:sequenceEditor.data(),times:sequenceEditor.doc.speed.keyframes.map(k=>sequenceEditor.map().rateTime(k.progress)),curve:document.querySelector('.seq-rate-curve').getAttribute('points')}));
 const save=async()=>{await page.locator('#saveButton').click();await page.waitForFunction(()=>document.querySelector('#savedLabel').textContent==='已保存');};
 const range=async(start,end)=>{
  for(const [field,time,key] of [['work_end_sec',end,'o'],['work_start_sec',start,'i']]){
   if(await page.evaluate(field=>sequenceEditor.doc.timeline[field],field)===time)continue;
   await page.evaluate(time=>seek(time),time);await page.locator('.seq-scroll').focus();await page.keyboard.press(key);
  }
 };
 try{
  await page.goto(process.argv[2]);await enterFixture(page);await page.waitForFunction(()=>state.loaded&&sequenceEditor?.doc&&state.samples.length>1);
  const original=await read();assert.equal(original.times.length,4);
  await range(10,18);const trimmed=await read();assert.equal(trimmed.data.timeline.work_end_sec,18,JSON.stringify(await page.evaluate(()=>({toast:document.getElementById('toast').textContent,dirty:state.dirty,undo:sequenceEditor.undoStack.length,timeline:sequenceEditor.doc.timeline}))));
  assert.deepEqual(trimmed.data.speed,original.data.speed);assert.deepEqual(trimmed.data.tracks,original.data.tracks);
  assert.deepEqual(trimmed.times,original.times);assert.equal(trimmed.curve,original.curve);
  assert.ok(trimmed.times[2]>18);assert.equal(await page.locator('.seq-key[data-channel=rate]').count(),4);
  await page.locator('[data-action=undo]').click();assert.equal((await read()).data.timeline.work_end_sec,30);
  await page.locator('[data-action=redo]').click();assert.deepEqual((await read()).times,original.times);
  await page.evaluate(()=>refreshDraftPreview());await page.waitForFunction(()=>state.samples.length>1);
  // A delayed draft recalculation must not restore an older playhead used by I/O.
  let releaseDraft,heldDraft;const held=new Promise(resolve=>heldDraft=resolve),release=new Promise(resolve=>releaseDraft=resolve);
  await page.route('**/api/sample/draft',async route=>{const response=await route.fetch();heldDraft();await release;await route.fulfill({response});});
  const pendingDraft=page.evaluate(()=>refreshDraftPreview());await held;
  await page.evaluate(()=>seek(13));releaseDraft();await pendingDraft;
  assert.equal(await page.evaluate(()=>state.previewTime),13);
  await page.unroute('**/api/sample/draft');
  // Shortening the out point must not change rate or travel at a given elapsed time.
  for(const from of [10,14]){
   const initial=T.atCamera(20,original.data.speed,(from-10)/20),seconds=initial.shootingElapsed+2;
   const expected=10+20*T.atShooting(20,original.data.speed,seconds/initial.shootingDuration).cameraProgress;
   const actual=await page.evaluate(from=>{seek(from);document.getElementById('previewSpeed').value='1';state.playing=true;state.playbackStart=from;state.playbackAnchor=performance.now();animate(state.playbackAnchor+2000);stopPlayback();return state.previewTime;},from);
   assert.ok(Math.abs(actual-expected)<1e-8,JSON.stringify({from,expected,actual}));
  }
  // Editor preview covers the full replay; I/O only bounds in-game playback.
  const advance=async(from,seconds,loop=false)=>page.evaluate(async({from,seconds,loop})=>{
   seek(from);state.loop=loop;document.getElementById('previewSpeed').value='1';await play();
   const started=state.previewTime;cancelAnimationFrame(state.animationRequest);state.animationRequest=0;
   animate(state.playbackAnchor+seconds*1000);
   const result={started,time:state.previewTime,playing:state.playing,readout:document.getElementById('speedPreviewReadout').textContent};
   stopPlayback();state.loop=false;return result;
  },{from,seconds,loop});
  for(const from of [5,25]){
   const result=await advance(from,1);assert.equal(result.started,from);assert.equal(result.time,from+1);assert.equal(result.playing,true);
   assert.match(result.readout,/1\.000×/);
  }
  const crossed=await advance(17,T.windowDuration(17,18,trimmed.data.speed)+2);
  assert.ok(Math.abs(crossed.time-20)<1e-8);assert.equal(crossed.playing,true);
  const ended=await advance(99,2);assert.equal(ended.time,100);assert.equal(ended.playing,false);
  const looped=await advance(99,2,true);assert.ok(Math.abs(looped.time-1)<1e-8);assert.equal(looped.playing,true);
  assert.equal((await advance(100,1)).started,0);
  await page.evaluate(()=>seek(16));assert.equal(await page.evaluate(()=>sequenceEditor.playhead),16);await page.locator('.seq-scroll').focus();await page.keyboard.press('o');
  assert.equal((await read()).data.timeline.work_end_sec,16);assert.deepEqual((await read()).times,original.times);
  await page.evaluate(()=>seek(12));await page.locator('.seq-scroll').focus();await page.keyboard.press('i');
  assert.equal((await read()).data.timeline.work_start_sec,12);assert.deepEqual((await read()).times,original.times);
  await page.locator('[data-action=undo]').click();await page.locator('[data-action=undo]').click();
  await save();await page.reload();await enterFixture(page);await page.waitForFunction(()=>state.loaded&&sequenceEditor?.doc);
  const loaded=await read();assert.deepEqual(loaded.times,original.times);assert.deepEqual(loaded.data.speed,original.data.speed);
  assert.equal(loaded.data.timeline.work_end_sec,18);
  for(const end of [26,35,15,30,12,18]){await range(10,end);const changed=await read();assert.deepEqual(changed.times,original.times);assert.deepEqual(changed.data.speed,original.data.speed);}
  await range(2,38);const extended=await read();assert.deepEqual(extended.times,original.times);
  const holds=await page.evaluate(()=>[3,35].map(t=>BlitzPreviewTime.atWindowCamera(2,38,speedSettings(),t).rate));assert.deepEqual(holds,[1,1]);
  await range(32,38);await page.locator('#tabSpeed').click();
  assert.equal(await page.locator('#speedWindowNotice').isVisible(),true);
  assert.match(await page.locator('#speedWindowNotice').textContent(),/全程保持末尾 1×/);
  assert.match(await page.locator('#speedWindowNotice').textContent(),/实际拍摄 6\.000 秒/);
  await page.locator('#paneSpeed').screenshot({path:path.join(out,'curve-tail-notice.png')});
  await range(2,7);assert.match(await page.locator('#speedWindowNotice').textContent(),/全程保持起始 1×/);
  await range(2,38);assert.equal(await page.locator('#speedWindowNotice').isVisible(),false);
  // Adding a key after the authored curve may extend it without moving old knots.
  await page.evaluate(()=>sequenceEditor.add('rate',36));const added=await read();assert.equal(added.times.length,5);
  for(let i=0;i<4;i++)assert.ok(Math.abs(added.times[i]-original.times[i])<1e-8);assert.equal(added.times[4],36);
  await page.locator('[data-action=undo]').click();assert.deepEqual((await read()).times,original.times);
  await range(10,18);await page.evaluate(()=>{const e=sequenceEditor;e.scale=(e.scroll.clientWidth-32)/32;e.render();e.scroll.scrollLeft=0;});
  await page.locator('.sequence-panel').screenshot({path:path.join(out,'trimmed-speed-curve.png')});
  await save();assert.deepEqual(errors,[]);assert.deepEqual(gameRequests,[]);
  const result={passed:true,outPointOnlyTrims:true,outsideKeysPreserved:true,sameOfflineRateAndTravel:true,previewBeforeInPoint:true,previewAfterOutPoint:true,previewCrossesOutPoint:true,previewStopsAtReplayEnd:true,previewLoopsWholeReplay:true,draftPreservesCurrentPlayhead:true,keyboardInOut:true,undoRedo:true,saveReload:true,endpointHolds:true,addOutsideCurvePreservesOldKnots:true,errors,gameRequests};
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }catch(e){await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});console.error(errors,await page.evaluate(()=>({toast:document.getElementById('toast').textContent,timeline:sequenceEditor.doc.timeline,undo:sequenceEditor.undoStack.length,dirty:state.dirty})));throw e;}
 finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
