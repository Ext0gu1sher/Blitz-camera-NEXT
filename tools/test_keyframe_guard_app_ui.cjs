const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {enterFixture}=require('./ui_fixture.cjs');
const out=path.resolve('output/keyframe-guard-app-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const page=await browser.newPage({viewport:{width:1550,height:1150}}),errors=[],gameRequests=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/\/api\/(connect|playback\/start|replay\/open)$/.test(r.url()))gameRequests.push(r.url());});
 const base=process.argv[2],replay=process.argv[3];
 const saved=()=>page.waitForFunction(()=>!state.dirty&&!state.busy&&!autoSavePromise);
 try{
  await page.goto(base);await enterFixture(page);await page.waitForFunction(()=>state.samples.length>1);
  const original=await page.evaluate(()=>sequenceEditor.data().tracks);
  const info=await page.evaluate(async file=>{const info=await api('/api/replay/timeline',{path:file});applyReplayInfo(info);return info;},replay);
  assert.equal(info.battle_start_sec,15);assert.equal(info.battle_start_status,'identified');
  assert.deepEqual(await page.evaluate(()=>sequenceEditor.data().tracks),original);await saved();
  await page.waitForFunction(()=>state.keyframeGuard?.start_sec===15);
  assert.equal(await page.locator('.seq-keyframe-boundary').count(),1);assert.equal(await page.locator('[data-keyframe-guard]').isVisible(),true);
  assert.equal(await page.evaluate(()=>state.timeline.work_start_sec),15);
  // Real global I/O shortcuts cannot author an early in-point, including O's
  // implicit movement of the in-point when the playhead precedes the range.
  await page.locator('.seq-scroll').focus();await page.evaluate(()=>seek(12));
  const beforeRange=await page.evaluate(()=>({timeline:sequenceEditor.data().timeline,undo:sequenceEditor.undoStack.length}));
  for(const key of ['i','o']){
   await page.keyboard.press(key);
   assert.deepEqual(await page.evaluate(()=>({timeline:sequenceEditor.data().timeline,undo:sequenceEditor.undoStack.length})),beforeRange);
  }
  await page.evaluate(()=>seek(20));await page.keyboard.press('i');await saved();assert.equal(await page.evaluate(()=>state.timeline.work_start_sec),20);
  await page.keyboard.press('Control+z');await saved();assert.equal(await page.evaluate(()=>state.timeline.work_start_sec),15);
  assert.deepEqual(await page.evaluate(()=>sequenceEditor.data().tracks),original);
  for(const width of [1550,1000]){
   await page.setViewportSize({width,height:1150});
   const footer=await page.evaluate(()=>{const n=document.querySelector('[data-keyframe-guard]'),s=document.querySelector('[data-status]'),r=n.parentElement.getBoundingClientRect(),a=n.getBoundingClientRect(),b=s.getBoundingClientRect();return {same:n.parentElement===s.parentElement,center:Math.abs(a.y+a.height/2-b.y-b.height/2),height:r.height,overflow:n.parentElement.scrollWidth>n.parentElement.clientWidth};});
   assert.equal(footer.same,true);assert.ok(footer.center<1);assert.ok(footer.height<=26);assert.equal(footer.overflow,false);
  }
  await page.setViewportSize({width:1550,height:1150});
  await page.evaluate(()=>sequenceEditor.add('all',12));assert.deepEqual(await page.evaluate(()=>sequenceEditor.data().tracks),original);
  await page.evaluate(()=>sequenceEditor.add('all',15));assert.equal(await page.evaluate(()=>Object.values(state.tracks).every(rows=>rows.some(k=>k.time_sec===15))),true);await saved();
  // Existing early keys remain editable when metadata is first bound.
  assert.equal(await page.evaluate(()=>sequenceEditor.edit(()=>sequenceEditor.doc.tracks.x[0].value+=1)),true);await saved();
  await page.evaluate(()=>{sequenceEditor.snap=false;sequenceEditor.scale=12;sequenceEditor.scroll.scrollLeft=0;sequenceEditor.render();});
  const key=page.locator('.seq-key[data-channel=x]').filter({has:page.locator('title',{hasText:'20.000s'})});
  const r=await key.boundingBox();assert.ok(r);
  await page.mouse.move(r.x+r.width/2,r.y+r.height/2);await page.mouse.down();await page.mouse.move(r.x+r.width/2-96,r.y+r.height/2,{steps:5});await page.mouse.up();
  assert.equal(await page.evaluate(()=>state.tracks.x.some(k=>k.time_sec===20)),true);assert.equal(await page.evaluate(()=>state.tracks.x.some(k=>k.time_sec===12)),false);
  await page.locator('#toast').waitFor({state:'hidden'});
  await page.locator('.sequence-panel').screenshot({path:path.join(out,'event-bound-timeline.png')});
  await page.locator('#settingsButton').click();await page.waitForFunction(()=>!settingsLoading);
  assert.equal(await page.locator('#battleStartMode').inputValue(),'auto');assert.match(await page.locator('#battleStartStatus').textContent(),/15\.000/);
  await page.locator('#battleStartMode').selectOption('manual');const input=page.locator('#battleStartSeconds');
  await input.locator('..').locator('.number-value').dblclick();await input.fill('0');await input.press('Enter');await page.locator('#settingsSave').click();
  await page.waitForFunction(()=>!state.busy&&state.replayKeyframeStartSeconds===0);await page.locator('#settingsView').screenshot({path:path.join(out,'event-bound-settings.png')});
  await page.locator('#settingsBack').click();await page.evaluate(()=>sequenceEditor.add('x',12));
  assert.equal(await page.evaluate(()=>state.tracks.x.some(k=>k.time_sec===12)),true);await saved();
  await page.locator('.seq-scroll').focus();await page.evaluate(()=>seek(5));await page.keyboard.press('i');await saved();assert.equal(await page.evaluate(()=>state.timeline.work_start_sec),5);
  await page.reload();await enterFixture(page);await page.waitForFunction(()=>sequenceEditor?.doc&&state.keyframeGuard);
  assert.equal(await page.evaluate(()=>keyframeGuardFor(sequenceEditor.data()).start_sec),0);assert.equal(await page.evaluate(()=>state.tracks.x.some(k=>k.time_sec===12)),true);
  assert.equal(await page.evaluate(()=>state.timeline.work_start_sec),5);
  // Create the actual default project from Home, then bind replay metadata.
  // Its original 0..8 range must not remain before the event.
  await page.evaluate(async()=>{const settings=await api('/api/settings');await api('/api/settings',{project_directory:settings.project_directory,replay_keyframe_start_seconds:null});await refreshState();});
  const previousProject=await page.evaluate(()=>state.projectPath);
  await page.locator('#homeButton').click();await page.locator('#homeNew').click();await page.locator('#homeNewName').fill('默认项目回放边界验收');await page.locator('#homeNewName').press('Enter');
  await page.waitForFunction(previous=>state.projectPath!==previous&&!state.busy,previousProject);await saved();
  const defaultTracks=await page.evaluate(()=>sequenceEditor.data().tracks);
  assert.deepEqual(await page.evaluate(()=>[state.timeline.work_start_sec,state.timeline.work_end_sec]),[0,8]);
  await page.evaluate(async path=>applyReplayInfo(await api('/api/replay/timeline',{path})),replay);await saved();
  assert.deepEqual(await page.evaluate(()=>[state.timeline.work_start_sec,state.timeline.work_end_sec]),[15,23]);
  assert.deepEqual(await page.evaluate(()=>sequenceEditor.data().tracks),defaultTracks);
  const dragRange=async(part,target)=>{
   const at=await page.locator(`[data-work=${part}]`).evaluate(el=>{const r=el.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};});
   const dx=await page.evaluate(({part,target})=>{const e=sequenceEditor;return e.x(target)-e.x(part==='end'?e.doc.timeline.work_end_sec:e.doc.timeline.work_start_sec);},{part,target});
   await page.keyboard.down('Alt');await page.mouse.move(at.x,at.y);await page.mouse.down();await page.mouse.move(at.x+dx,at.y,{steps:5});await page.mouse.up();await page.keyboard.up('Alt');await saved();
  };
  const visibleHandles=await page.evaluate(()=>{const scroll=sequenceEditor.scroll.getBoundingClientRect();return [...sequenceEditor.svg.querySelectorAll('[data-work=start],[data-work=end]')].every(el=>{const r=el.getBoundingClientRect();return r.x>=scroll.x&&r.right<=scroll.right;});});assert.equal(visibleHandles,true);
  const nearRange=async expected=>{const actual=await page.evaluate(()=>[state.timeline.work_start_sec,state.timeline.work_end_sec]);assert.ok(actual.every((v,i)=>Math.abs(v-expected[i])<1e-4),JSON.stringify({actual,expected}));};
  await dragRange('end',26);await nearRange([15,26]);
  await dragRange('start',16);await nearRange([16,26]);
  const finalImportedRange=await page.evaluate(()=>[state.timeline.work_start_sec,state.timeline.work_end_sec]);
  await page.reload();await enterFixture(page);await page.waitForFunction(()=>sequenceEditor?.doc&&state.keyframeGuard);
  assert.deepEqual(await page.evaluate(()=>[state.timeline.work_start_sec,state.timeline.work_end_sec]),finalImportedRange);
  assert.deepEqual(await page.evaluate(()=>sequenceEditor.data().tracks),defaultTracks);
  assert.deepEqual(errors,[]);assert.deepEqual(gameRequests,[]);
  const result={passed:true,explicitEventParsed:true,bindPreservesLegacyKeys:true,bindingAlignsInpoint:true,inpointShortcutsGuarded:true,outShortcutCannotBypassGuard:true,inpointUndoAndSaveReload:true,singleLineFooterWideAndNarrow:true,realAppAddGuard:true,eventBoundaryAllowed:true,legacyValueEdit:true,realAppDragRollback:true,manualZeroOverridesEvent:true,bindingAndManualSettingPersist:true,defaultProjectPreviewImportAligned:true,importedHandlesVisibleAndDraggable:true,defaultImportSaveReload:true,errors,gameRequests};
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }catch(error){await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});console.error(errors,await page.evaluate(()=>({toast:document.getElementById('toast').textContent,guard:state.keyframeGuard,timeline:state.timeline})));throw error;}
 finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
