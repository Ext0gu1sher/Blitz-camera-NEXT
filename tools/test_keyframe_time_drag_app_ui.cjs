// Real input gestures against an isolated replay fixture; never uses the game.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {enterFixture}=require('./ui_fixture.cjs');
const out=path.resolve('output/keyframe-time-drag-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const page=await browser.newPage({viewport:{width:1550,height:1150}}),errors=[],gameRequests=[],checks=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/\/api\/(connect|playback\/start|replay\/open)$/.test(r.url()))gameRequests.push(r.url());});
 const saved=()=>page.waitForFunction(()=>!state.dirty&&!state.busy&&!autoSavePromise);
 const input=page.locator('#keyInspector [data-field=time]'),view=input.locator('..').locator('.number-value');
 const selected=()=>page.evaluate(()=>({key:structuredClone(sequenceEditor.singleSelection()?.key),undo:sequenceEditor.undoStack.length,head:state.previewTime,drag:!!sequenceEditor.numberEdit}));
 const drag=async(dx,modifier)=>{const r=await view.boundingBox();assert.ok(r);if(modifier)await page.keyboard.down(modifier);await page.mouse.move(r.x+r.width/2,r.y+r.height/2);await page.mouse.down();await page.mouse.move(r.x+r.width/2+dx,r.y+r.height/2,{steps:8});};
 const release=async modifier=>{await page.mouse.up();if(modifier)await page.keyboard.up(modifier);};
 const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-5,`${a} != ${b}`);
 try{
  await page.goto(process.argv[2]);await enterFixture(page);await page.waitForFunction(()=>state.samples.length>1);
  await page.evaluate(async()=>{await api('/api/projects/new',{name:'默认项目时间拖动验收'});await refreshState(true);showHome(false);});
  await page.waitForFunction(()=>state.samples.length>1&&!state.busy);
  await page.evaluate(async replay=>{const info=await api('/api/replay/timeline',{path:replay});applyReplayInfo(info);},process.argv[3]);await saved();
  await page.evaluate(()=>{const e=sequenceEditor;e.selected=new Set([e.doc.tracks.x[0]._id]);e.hadSelection=false;e.render();seek(42);});
  const before=await selected();assert.equal(before.key.time_sec,0);
  await drag(48);const live=await selected();assert.ok(live.key.time_sec>=15,'a legacy early key must be movable out of the pre-battle interval');assert.equal(live.undo,before.undo);
  await release();const after=await selected();assert.ok(after.key.time_sec>=15);assert.equal(after.undo,before.undo+1);near(after.head,42);checks.push('default pre-battle key time scrub reaches legal boundary');
  await saved();await page.evaluate(()=>refreshState());near((await selected()).key.time_sec,after.key.time_sec);checks.push('poll and autosave preserve key time');
  await page.keyboard.press('Control+z');assert.equal((await selected()).key.time_sec,after.key.time_sec,'undo cannot restore an early key under the current boundary');
  await view.dblclick();await input.fill('17.25');await input.press('Enter');near((await selected()).key.time_sec,17.25);
  await drag(24);await release();near((await selected()).key.time_sec,17.65);checks.push('legal numeric scrubbing and precise entry');
  await drag(-600,'Control');await release('Control');near((await selected()).key.time_sec,15);checks.push('numeric time scrub clamps at current battle boundary');
  const final=await selected();await saved();await page.reload();await enterFixture(page);await page.waitForFunction(()=>state.samples.length>1);
  assert.ok(await page.evaluate(t=>state.tracks.x.some(k=>Math.abs(k.time_sec-t)<1e-6),final.key.time_sec));checks.push('save reload retains edited time');
  assert.deepEqual(errors,[]);assert.deepEqual(gameRequests,[]);
  const result={passed:true,checks,errors,gameRequests};fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }catch(error){console.error(error);await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});console.error(await page.evaluate(()=>({toast:document.getElementById('toast')?.textContent,selected:sequenceEditor?.singleSelection(),number:!!sequenceEditor?.numberEdit})).catch(()=>({errors})));throw error;}
 finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
