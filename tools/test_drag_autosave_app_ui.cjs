// Exercise release/commit and late save acknowledgements without touching the game.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {enterFixture}=require('./ui_fixture.cjs');
const out=path.resolve('output/drag-autosave-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const page=await browser.newPage({viewport:{width:1550,height:1150}}),errors=[],checks=[];
 page.on('pageerror',e=>errors.push(e.message));
 const read=()=>page.evaluate(()=>({time:sequenceEditor.doc.tracks.x[1].time_sec,undo:sequenceEditor.undoStack.length,dirty:state.dirty,number:!!sequenceEditor.numberEdit,drag:!!sequenceEditor.drag,revision:state.serverRevision}));
 const saved=()=>page.waitForFunction(()=>!state.dirty&&!autoSavePromise&&!state.busy);
 const view=page.locator('#keyInspector [data-field=time]').locator('..').locator('.number-value');
 const numeric=async dx=>{const b=await view.boundingBox();await page.mouse.move(b.x+b.width/2,b.y+b.height/2);await page.mouse.down();await page.mouse.move(b.x+b.width/2+dx,b.y+b.height/2,{steps:5});};
 const select=()=>page.evaluate(()=>{const e=sequenceEditor;e.selected=new Set([e.doc.tracks.x[1]._id]);e.hadSelection=false;e.render();});
 const keyCenter=()=>page.evaluate(()=>{const e=sequenceEditor,key=e.doc.tracks.x[1],r=e.scroll.getBoundingClientRect();return {x:r.left+e.x(key.time_sec)-e.scroll.scrollLeft,y:r.top+e.rows()[0].y+12-e.scroll.scrollTop};});
 let pendingRoute,releaseResponse,savedPayload;
 const holdNextSave=async()=>{
  let ready;const captured=new Promise(resolve=>ready=resolve),gate=new Promise(resolve=>releaseResponse=resolve);
  pendingRoute=async route=>{savedPayload=route.request().postDataJSON();delete savedPayload.expected_revision;const response=await route.fetch();ready();await gate;await route.fulfill({response});};
  await page.route('**/api/project/edit',pendingRoute,{times:1});return {captured};
 };
 try{
  await page.goto(process.argv[2]);await enterFixture(page);await page.waitForFunction(()=>state.samples.length>1);await select();
  // No second click is made after release; both local and disk values must survive polling.
  let before=await read();await numeric(36);await page.waitForTimeout(1800);assert.equal((await read()).revision,before.revision);
  const held=await read();await page.mouse.up();let after=await read();assert.equal(after.number,false);assert.equal(after.undo,before.undo+1);assert.equal(after.time,held.time);
  await saved();await page.evaluate(()=>refreshState());assert.equal((await read()).time,held.time);checks.push('release without another click survives autosave and polling');
  // Hosts can drop capture before the release reaches the original control.
  before=await read();await view.evaluate(el=>el.addEventListener('pointerdown',e=>el.dataset.testPointer=e.pointerId,{once:true}));
  await numeric(24);const moved=await read();await view.evaluate(el=>el.releasePointerCapture(Number(el.dataset.testPointer)));
  await page.mouse.move(20,20);await page.mouse.up();after=await read();assert.equal(after.time,moved.time,'capture loss must not silently restore the previous value');assert.equal(after.number,false);assert.equal(after.undo,before.undo+1);
  await saved();checks.push('number release outside control after capture loss commits once');
  // A key drag must also finish when its capture is lost, rather than lingering until a click.
  await page.evaluate(()=>{sequenceEditor.action('workfit');sequenceEditor.scroll.scrollTop=0;});
  const b=await keyCenter();before=await read();
  await page.locator('#sequenceEditor').evaluate(el=>el.addEventListener('pointerdown',e=>el.dataset.testPointer=e.pointerId,{once:true}));
  await page.mouse.move(b.x,b.y);await page.mouse.down();await page.mouse.move(b.x+25,b.y,{steps:5});const keyMoved=await read();assert.ok(keyMoved.drag&&keyMoved.time!==before.time);
  await page.locator('#sequenceEditor').evaluate(el=>el.releasePointerCapture(Number(el.dataset.testPointer)));await page.mouse.move(20,20);await page.mouse.up();
  after=await read();assert.equal(after.drag,false,'key transaction must end on release even without capture');assert.equal(after.time,keyMoved.time);assert.equal(after.undo,before.undo+1);await saved();checks.push('timeline key release after capture loss commits once');
  // An earlier autosave may finish while a new direct drag still owns a provisional document.
  const heldSave=await holdNextSave();await page.evaluate(async()=>{sequenceEditor.edit(()=>sequenceEditor.doc.tracks.y[1].value+=1);await refreshDraftPreview();autoSaveDraft();});await heldSave.captured;
  const box=await keyCenter();before=await read();await page.mouse.move(box.x,box.y);await page.mouse.down();await page.mouse.move(box.x+24,box.y,{steps:5});const newest=await read();assert.ok(newest.drag&&newest.time!==before.time);
  assert.deepEqual(await page.evaluate(()=>editPayload()),savedPayload,'a live key drag must be distinct from the committed snapshot being saved');
  await page.evaluate(()=>refreshState());assert.equal(await page.evaluate(()=>state.pendingProject),null,'polling an in-flight autosave must not report an external change');assert.equal((await read()).revision,before.revision);
  releaseResponse();await page.waitForFunction(()=>!autoSavePromise);assert.equal((await read()).dirty,true,'an old acknowledgement must not mark a live edit saved');assert.equal((await read()).time,newest.time);
  await page.mouse.up();await saved();after=await read();assert.equal(after.time,newest.time);assert.equal(after.undo,before.undo+1);checks.push('late save acknowledgement preserves newer drag and queues its save');
  // Cancellation remains a rollback, with no extra undo record.
  before=await read();await select();await numeric(24);await page.keyboard.press('Escape');await page.mouse.up();after=await read();assert.equal(after.time,before.time);assert.equal(after.undo,before.undo);await saved();checks.push('Escape still cancels the numeric gesture');
  const expected=(await read()).time;await page.reload();await enterFixture(page);await page.waitForFunction(()=>state.samples.length>1);assert.equal((await read()).time,expected);checks.push('reload retains the final value');
  assert.deepEqual(errors,[]);const result={passed:true,checks,errors};fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }catch(error){await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});console.error(await read().catch(()=>({errors})));throw error;}
 finally{releaseResponse?.();await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
