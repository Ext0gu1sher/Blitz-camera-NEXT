const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const out=path.resolve('output/number-fields-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const page=await browser.newPage({viewport:{width:1500,height:1100}}),errors=[],gameRequests=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/\/api\/(connect|playback\/start|replay\/open)$/.test(r.url()))gameRequests.push(r.url());});
 const view=selector=>page.locator(selector).locator('..').locator('.number-value');
 const read=()=>page.evaluate(()=>({doc:sequenceEditor.data(),undo:sequenceEditor.undoStack.length,revision:state.serverRevision,dirty:state.dirty}));
 const select=async(name,index)=>page.evaluate(([name,index])=>{sequenceEditor.selected=new Set([sequenceEditor.doc.tracks[name][index]._id]);sequenceEditor.hadSelection=false;sequenceEditor.render();},[name,index]);
 const startDrag=async(selector,dx,modifier,dy=0)=>{const box=await view(selector).boundingBox(),x=box.x+box.width/2,y=box.y+box.height/2;if(modifier)await page.keyboard.down(modifier);await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x+dx,y+dy,{steps:5});return {x,y};};
 const endDrag=async modifier=>{await page.mouse.up();if(modifier)await page.keyboard.up(modifier);};
 const type=async(selector,value,finish=true)=>{await view(selector).dblclick();await page.locator(selector).fill(String(value));if(finish)await page.locator(selector).press('Enter');};
 const near=(actual,expected)=>assert.ok(Math.abs(actual-expected)<1e-5,`${actual} != ${expected}`);
 try{
  await page.goto(process.argv[2]);await page.waitForFunction(()=>document.body.dataset.appReady==='true'&&state.loaded&&sequenceEditor?.doc&&state.samples.length>1&&!pendingEditorRestore);
  await select('x',1);await page.waitForFunction(()=>!!curveMath);
  const value='#keyInspector [data-field=value]',time='#keyInspector [data-field=time]';
  assert.equal(await page.locator(value).isVisible(),false);assert.equal(await view(value).isVisible(),true);
  assert.equal(await page.locator('#keyInspector [data-action],#easeApply').count(),0);
  assert.equal(await page.locator('input[type=number]:not(.number-input)').count(),0);
  let before=await read();await startDrag(value,20);let live=await read();near(live.doc.tracks.x[1].value,22);assert.equal(live.undo,before.undo);
  // The model changes before pointer release, but the disk snapshot waits for the whole gesture.
  await page.waitForTimeout(1750);assert.equal((await read()).revision,before.revision);await endDrag();assert.equal((await read()).undo,before.undo+1);
  await page.keyboard.press('Control+z');near((await read()).doc.tracks.x[1].value,20);await page.keyboard.press('Control+Shift+z');near((await read()).doc.tracks.x[1].value,22);
  // Vertical scrubbing uses the same live edit/commit. The initial dominant axis stays stable during diagonal drift.
  before=await read();const vertical=await startDrag(value,10,undefined,-20);near((await read()).doc.tracks.x[1].value,24);assert.equal((await read()).undo,before.undo);
  assert.equal(await view(value).evaluate(el=>getComputedStyle(el).cursor),'ns-resize');await page.mouse.move(vertical.x+60,vertical.y-20,{steps:5});near((await read()).doc.tracks.x[1].value,24);
  await page.mouse.move(vertical.x+60,vertical.y-10,{steps:5});near((await read()).doc.tracks.x[1].value,23);await endDrag();assert.equal((await read()).undo,before.undo+1);assert.equal(await view(value).evaluate(el=>el.parentElement.dataset.scrubAxis),undefined);await page.keyboard.press('Control+z');near((await read()).doc.tracks.x[1].value,22);
  const horizontal=await startDrag(value,20,undefined,-10);near((await read()).doc.tracks.x[1].value,24);assert.equal(await view(value).evaluate(el=>getComputedStyle(el).cursor),'ew-resize');await page.mouse.move(horizontal.x+20,horizontal.y+60,{steps:5});near((await read()).doc.tracks.x[1].value,24);await endDrag();await page.keyboard.press('Control+z');
  await startDrag(value,0,undefined,20);near((await read()).doc.tracks.x[1].value,20);await endDrag();await page.keyboard.press('Control+z');
  await startDrag(value,0,'Shift',-20);await endDrag('Shift');near((await read()).doc.tracks.x[1].value,22.2);await page.keyboard.press('Control+z');
  await startDrag(value,0,'Control',-5);await endDrag('Control');near((await read()).doc.tracks.x[1].value,27);await page.keyboard.press('Control+z');
  before=await read();await startDrag(value,0,undefined,-30);await page.keyboard.press('Escape');await endDrag();near((await read()).doc.tracks.x[1].value,22);assert.equal((await read()).undo,before.undo);
  before=await read();await type(value,31.123456,false);near((await read()).doc.tracks.x[1].value,31.123456);assert.equal((await read()).undo,before.undo);
  await page.locator(value).press('Enter');assert.equal(await page.locator(value).isVisible(),false);assert.equal((await read()).undo,before.undo+1);
  // Ctrl-Z from the active text editor undoes the entire edit, and Escape leaves no undo entry.
  before=await read();await type(value,39,false);await page.keyboard.press('Control+z');near((await read()).doc.tracks.x[1].value,31.123456);assert.equal((await read()).undo,before.undo);
  await type(value,45,false);await page.keyboard.press('Escape');near((await read()).doc.tracks.x[1].value,31.123456);assert.equal((await read()).undo,before.undo);
  await startDrag(value,20,'Shift');await endDrag('Shift');near((await read()).doc.tracks.x[1].value,31.323456);await page.keyboard.press('Control+z');
  before=await read();await startDrag(value,30);await page.keyboard.press('Escape');await endDrag();near((await read()).doc.tracks.x[1].value,31.123456);assert.equal((await read()).undo,before.undo);
  await startDrag(time,30);await endDrag();near((await read()).doc.tracks.x[1].time_sec,20.5);await page.keyboard.press('Control+z');
  await startDrag(time,0,undefined,-30);await endDrag();near((await read()).doc.tracks.x[1].time_sec,20.5);await page.keyboard.press('Control+z');
  before=await read();await type(time,10,false);near((await read()).doc.tracks.x[1].time_sec,20);await page.locator(time).press('Enter');assert.equal((await read()).undo,before.undo);
  await type(value,'',false);near((await read()).doc.tracks.x[1].value,31.123456);await page.keyboard.press('Escape');
  await type(value,32.5,false);await page.keyboard.press('Control+s');await page.waitForFunction(()=>!state.dirty&&!state.busy);near((await read()).doc.tracks.x[1].value,32.5);assert.equal(await page.evaluate(()=>!!sequenceEditor.numberEdit),false);
  before=await read();await type(value,33.25,false);await page.evaluate(()=>BlitzFlushEditorSession());near((await read()).doc.tracks.x[1].value,33.25);assert.equal((await read()).undo,before.undo+1);assert.equal(await page.evaluate(()=>BlitzNumbers.active),null);
  // Camera easing numbers and graph handles apply directly and use the same transaction history.
  before=await read();await startDrag('#easeX1',20);near((await read()).doc.tracks.x[1].ease[0],.2);await endDrag();assert.equal((await read()).undo,before.undo+1);await page.keyboard.press('Control+z');assert.equal((await read()).doc.tracks.x[1].ease,undefined);
  await startDrag('#easeX1',0,undefined,-20);near((await read()).doc.tracks.x[1].ease[0],.2);await endDrag();await page.keyboard.press('Control+z');assert.equal((await read()).doc.tracks.x[1].ease,undefined);
  const handle=page.locator('#easeGraph [data-h="0"]'),hb=await handle.boundingBox();before=await read();await page.mouse.move(hb.x+hb.width/2,hb.y+hb.height/2);await page.mouse.down();await page.mouse.move(hb.x+24,hb.y-18,{steps:5});assert.ok((await read()).doc.tracks.x[1].ease[0]>0);await page.mouse.up();assert.equal((await read()).undo,before.undo+1);await page.keyboard.press('Control+z');assert.equal((await read()).doc.tracks.x[1].ease,undefined);
  before=await read();await page.mouse.move(hb.x+hb.width/2,hb.y+hb.height/2);await page.mouse.down();await page.mouse.move(hb.x+18,hb.y-12,{steps:4});await page.evaluate(()=>BlitzFlushEditorSession());await page.mouse.up();assert.equal((await read()).undo,before.undo+1);assert.equal(await page.evaluate(()=>!!sequenceEditor.numberEdit),false);await page.keyboard.press('Control+z');assert.equal((await read()).doc.tracks.x[1].ease,undefined);
  // Speed fields remain live, bounded, and undoable while the precise editor has focus.
  await page.evaluate(()=>{sequenceEditor.selected=new Set([sequenceEditor.doc.speed.keyframes[1]._id]);sequenceEditor.hadSelection=false;sequenceEditor.render();});
  const rate='[data-speed-field=rate]',progress='[data-speed-field=progress]';before=await read();await startDrag(rate,15);near((await read()).doc.speed.keyframes[1].rate,.4);await endDrag();assert.equal((await read()).undo,before.undo+1);await page.keyboard.press('Control+z');
  await startDrag(rate,0,undefined,-100);near((await read()).doc.speed.keyframes[1].rate,1);await endDrag();await page.keyboard.press('Control+z');await startDrag(rate,0,undefined,30);near((await read()).doc.speed.keyframes[1].rate,.0625);await endDrag();await page.keyboard.press('Control+z');
  await type(rate,.6,false);near((await read()).doc.speed.keyframes[1].rate,.6);await page.keyboard.press('Control+z');near((await read()).doc.speed.keyframes[1].rate,.25);
  await startDrag(progress,20);near((await read()).doc.speed.keyframes[1].progress,.27);await endDrag();await page.keyboard.press('Control+z');
  await startDrag(progress,0,undefined,-20);near((await read()).doc.speed.keyframes[1].progress,.27);await endDrag();await page.keyboard.press('Control+z');
  await type(rate,2,false);near((await read()).doc.speed.keyframes[1].rate,.25);await page.keyboard.press('Escape');
  await page.evaluate(()=>{sequenceEditor.selected=new Set([sequenceEditor.doc.speed.keyframes[0]._id]);sequenceEditor.render();});assert.equal(await view(progress).isDisabled(),true);assert.equal(await view(time).isDisabled(),true);
  await select('pitch',1);await type(value,90,false);near((await read()).doc.tracks.pitch[1].value,0);await page.keyboard.press('Escape');await type(value,-22);near((await read()).doc.tracks.pitch[1].value,-22);
  // Capture time uses the shared interaction and keeps its existing mode-dependent read-only behavior.
  assert.equal(await view('#captureTime').isDisabled(),true);await page.locator('[name=shootingMode][value=camera_only]').check();await page.waitForFunction(()=>sequenceEditor.free());
  assert.equal(await view('#captureTime').isDisabled(),false);await type('#captureTime',3.25);near(Number(await page.locator('#captureTime').inputValue()),3.25);
  await startDrag('#captureTime',0,undefined,-30);await endDrag();near(Number(await page.locator('#captureTime').inputValue()),3.75001);
  // Preview alignment is a local preference and also uses the common number control.
  await page.locator('[name=shootingMode][value=replay]').check();await page.waitForFunction(()=>!sequenceEditor.free());await page.locator('.preview-alignment summary').click();
  await type('#previewOffset',1.25,false);assert.equal(await page.evaluate(()=>replayPreviewPane.offset),1.25);await page.keyboard.press('Escape');assert.equal(await page.evaluate(()=>replayPreviewPane.offset),0);
  await startDrag('#previewOffset',0,undefined,-20);near(await page.evaluate(()=>replayPreviewPane.offset),.2);await page.keyboard.press('Escape');await endDrag();near(await page.evaluate(()=>replayPreviewPane.offset),0);
  await select('x',1);await page.locator('#paneCurve').screenshot({path:path.join(out,'numbers-default.png')});await view(value).dblclick();await page.locator('#keyInspector').screenshot({path:path.join(out,'numbers-precise.png')});await page.keyboard.press('Escape');
  await page.waitForFunction(()=>!state.dirty);await page.evaluate(()=>BlitzFlushEditorSession());const persisted=await read();await page.reload();await page.waitForFunction(()=>document.body.dataset.appReady==='true'&&state.loaded&&state.samples.length>1&&!pendingEditorRestore);assert.deepEqual((await read()).doc,persisted.doc);
  const overlay=await browser.newPage();overlay.on('pageerror',e=>errors.push(e.message));overlay.on('request',r=>{if(/\/api\/(connect|playback\/start|replay\/open)$/.test(r.url()))gameRequests.push(r.url());});await overlay.goto(process.argv[2]+'/overlay?panel=capture');await overlay.waitForFunction(()=>model.ready);assert.equal(await overlay.locator('#captureTime').isVisible(),false);const overlayNumber=overlay.locator('#captureTime').locator('..').locator('.number-value');assert.equal(await overlayNumber.isDisabled(),true);
  await page.locator('[name=shootingMode][value=camera_only]').check();await page.waitForFunction(()=>!state.dirty);await overlay.waitForFunction(()=>!document.getElementById('captureTime').readOnly);const ob=await overlayNumber.boundingBox(),ox=ob.x+ob.width/2,oy=ob.y+ob.height/2,original=Number(await overlay.locator('#captureTime').inputValue());await overlay.mouse.move(ox,oy);await overlay.mouse.down();await overlay.mouse.move(ox,oy-30,{steps:5});await overlay.mouse.up();near(Number(await overlay.locator('#captureTime').inputValue()),original+.50001);await overlay.mouse.move(ox,oy);await overlay.mouse.down();await overlay.mouse.move(ox,oy+30,{steps:5});await overlay.mouse.up();near(Number(await overlay.locator('#captureTime').inputValue()),original);await overlay.close();
  assert.deepEqual(errors,[]);assert.deepEqual(gameRequests,[]);const result={passed:true,allNumbersScrubbable:true,verticalUpAndDown:true,diagonalAxisStable:true,verticalModifiers:true,liveBeforeRelease:true,oneUndoPerGesture:true,textEntryOnDoubleClick:true,undoWhileTyping:true,escapeRestores:true,fineAdjustment:true,boundsAndInvalidInput:true,easingNumbersAndHandles:true,speedFields:true,captureAndAlignment:true,autoSaveReload:true,overlayNumbers:true,overlayVerticalScrubbing:true,errors,gameRequests};fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }catch(e){await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});console.error(errors,await page.evaluate(()=>({toast:document.getElementById('toast')?.textContent,number:BlitzNumbers.active?.outerHTML,editing:!!sequenceEditor?.numberEdit})));throw e;}
 finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
