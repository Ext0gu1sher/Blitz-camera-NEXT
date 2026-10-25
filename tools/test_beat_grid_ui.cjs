const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const out=path.resolve('output/beat-grid-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const page=await browser.newPage({viewport:{width:1500,height:1000}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 const view=id=>page.locator('#'+id).locator('..').locator('.number-value');
 const read=()=>page.evaluate(()=>({settings:state.beatGrid,first:sequenceEditor.beatGrid()?.first,time:sequenceEditor.beatGrid()?.count?BlitzBeatGrid.timeAt(sequenceEditor.beatGrid(),sequenceEditor.beatGrid().first):null,height:sequenceEditor.height(),row:sequenceEditor.rows()[0].y,revision:state.serverRevision,undo:state.cameraUndo.length}));
 const type=async(id,value)=>{await view(id).dblclick();await page.keyboard.type(value);await page.keyboard.press('Enter');};
 const saved=()=>page.waitForFunction(()=>!state.dirty&&!autoSavePromise&&!state.pendingProject);
 try{
  await page.goto(process.argv[2]);await page.waitForFunction(()=>document.body.dataset.appReady==='true'&&state.loaded&&sequenceEditor?.doc&&state.samples.length>1&&!pendingEditorRestore);
  await page.locator('#tabBeat').click();const before=await read();assert.equal(before.height,310);assert.equal(before.settings.enabled,false);
  await page.locator('#beatEnabled').check();assert.equal((await read()).height,334);assert.equal((await read()).row,64);assert.equal((await read()).time,10);
  await page.evaluate(()=>sequenceEditor.action('workfit'));assert.ok(await page.locator('[data-beat]').count()>0);
  await type('beatBpm','137.125');assert.equal((await read()).settings.bpm,137.125);
  await type('beatOffset','-0.123456');assert.equal((await read()).settings.offset_sec,-.123456);
  await page.locator('#beatBpm').locator('..').locator('[data-direction="1"]').click();assert.equal((await read()).settings.bpm,138.125);
  await saved();let snapshot=await read();
  const rect=await view('beatBpm').boundingBox(),x=rect.x+rect.width/2,y=rect.y+rect.height/2;
  await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x+12,y,{steps:4});
  assert.equal((await read()).settings.bpm,150.125);await page.waitForTimeout(1650);assert.equal((await read()).revision,snapshot.revision);
  await page.mouse.up();assert.equal((await read()).undo,snapshot.undo+1);await saved();
  await page.keyboard.press('Control+z');assert.equal((await read()).settings.bpm,138.125);await page.keyboard.press('Control+Shift+z');assert.equal((await read()).settings.bpm,150.125);
  await view('beatBpm').dblclick();await page.keyboard.type('301');await page.keyboard.press('Enter');assert.equal((await read()).settings.bpm,150.125);
  await view('beatOffset').dblclick();await page.keyboard.type('1.5');await page.keyboard.press('Escape');assert.equal((await read()).settings.offset_sec,-.123456);
  await type('beatOffset','0');await page.evaluate(()=>seek(16));await page.locator('[data-beat-origin="playhead"]').click();assert.ok(Math.abs((await read()).time-16)<1e-6);
  await page.evaluate(()=>seek(22));assert.ok(Math.abs((await read()).time-16)<1e-6);
  await page.locator('[data-beat-origin="inpoint"]').click();await page.locator('#beatDivision').selectOption('2');
  await page.evaluate(()=>sequenceEditor.edit(()=>{sequenceEditor.doc.timeline.work_start_sec=12;}));assert.equal((await read()).time,12);
  // A visible beat is seekable; snapping also retains beats hidden by display thinning.
  const beat=page.locator('[data-beat]').nth(2),time=Number(await beat.getAttribute('data-beat'));await beat.click();assert.ok(Math.abs(await page.evaluate(()=>state.previewTime)-time)<1e-6);
  assert.ok(await page.evaluate(()=>{const e=sequenceEditor,g=e.beatGrid(),t=BlitzBeatGrid.timeAt(g,g.first+3),d=e.displayTime(t),hit=e.snapTo(d+.1/e.scale,e.snapTargets(null,e.map(),false));return Math.abs(hit.time-d)<1e-6;}));
  // Move an actual camera key to a beat, on both ruler types.
  for(const axis of ['replay','shooting']){
   const target=await page.evaluate(axis=>{const e=sequenceEditor;e.axis=axis;e.action('workfit');const g=e.beatGrid(),t=BlitzBeatGrid.nearest(g,18);const r=e.scroll.getBoundingClientRect();return {time:t,x:r.left+e.x(t)-e.scroll.scrollLeft+1};},axis);
   const key=await page.locator('.seq-key[data-channel=x]').nth(1).boundingBox();
   await page.mouse.move(key.x+key.width/2,key.y+key.height/2);await page.mouse.down();await page.mouse.move(target.x,key.y+key.height/2,{steps:6});await page.mouse.up();
   assert.ok(Math.abs(await page.evaluate(()=>sequenceEditor.doc.tracks.x[1].time_sec)-target.time)<1e-5);
   await page.keyboard.press('Control+z');
  }
  await page.locator('#tabBeat').click();
  await page.screenshot({path:path.join(out,'enabled.png')});
  const retained=(await read()).settings;await page.locator('#beatEnabled').uncheck();assert.equal((await read()).height,310);assert.equal((await read()).row,40);
  assert.equal(await page.locator('[data-beat]').count(),0);assert.ok(await page.locator('.seq-beat-label').isHidden());assert.ok(await view('beatBpm').isDisabled());
  await saved();await page.screenshot({path:path.join(out,'disabled.png')});await page.reload();await page.waitForFunction(()=>document.body.dataset.appReady==='true'&&!pendingEditorRestore);
  assert.deepEqual((await read()).settings,{...retained,enabled:false});assert.equal((await read()).height,310);
  await page.locator('#tabBeat').click();await page.locator('#beatEnabled').check();assert.deepEqual((await read()).settings,retained);
  await saved();await page.evaluate(()=>newCamera());assert.deepEqual((await read()).settings,retained);await saved();
  const persisted=await page.evaluate(async()=>{const response=await fetch('/api/state');return (await response.json()).project.beat_grid;});assert.deepEqual(persisted,retained);
  await page.evaluate(()=>sequenceEditor.setMode('camera_only',state.timeline));await page.locator('#tabBeat').click();assert.equal((await read()).height,232);assert.equal((await read()).time,0);
  await page.locator('#beatEnabled').uncheck();assert.equal((await read()).height,208);
  assert.deepEqual(errors,[]);console.log('PASS real app: number drag/steps/text/cancel/undo, autosave, origins, trim, snapping, collapse/restore, reload and camera switch');
 }catch(error){await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});console.error(await read().catch(()=>({errors})));throw error;}
 finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
