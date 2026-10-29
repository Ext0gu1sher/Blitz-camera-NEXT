// Real application acceptance in the isolated speed-window fixture; no game access.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {enterFixture}=require('./ui_fixture.cjs');
const out=path.resolve('output/keyframe-clipboard-app-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const context=await browser.newContext({viewport:{width:1550,height:1150},permissions:['clipboard-read','clipboard-write']}),page=await context.newPage(),errors=[],gameRequests=[],checks=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/\/api\/(connect|playback\/start|replay\/open)$/.test(r.url()))gameRequests.push(r.url());});
 const read=()=>page.evaluate(()=>({data:sequenceEditor.data(),tracks:structuredClone(state.tracks),undo:sequenceEditor.undoStack.length,selected:[...sequenceEditor.selected].map(id=>{const v=sequenceEditor.locate(id);return v?{channel:v.row.name,time:v.row.name==='rate'?sequenceEditor.map().rateTime(v.key.progress):v.key.time_sec}:null;}),previewTime:state.previewTime,playhead:sequenceEditor.playhead,playing:state.playing,clipboard:JSON.stringify(sequenceEditor.clipboard)}));
 const selected=async points=>page.evaluate(points=>{const e=sequenceEditor;e.selected=new Set(points.map(([name,time])=>e.doc.tracks[name].find(k=>k.time_sec===time)._id));e.render();},points);
 const save=async()=>{await page.evaluate(()=>saveProject(true));await page.waitForFunction(()=>!state.dirty&&!state.busy&&!autoSavePromise);};
 const at=(data,channel,time)=>data.tracks[channel].find(k=>Math.abs(k.time_sec-time)<1e-7);
 try{
  await page.goto(process.argv[2]);await enterFixture(page);await page.waitForFunction(()=>state.loaded&&sequenceEditor?.doc&&state.samples.length>1);
  const initial=await read(),sourcePath=await page.evaluate(()=>state.projectPath);
  await page.evaluate(()=>sequenceEditor.edit(()=>sequenceEditor.doc.tracks.x[0].ease=[.2,.1,.8,.9]));
  await selected([['x',10],['x',20],['y',20]]);await page.locator('.seq-scroll').focus();await page.keyboard.press('Control+c');
  await page.waitForFunction(()=>!!sequenceEditor.clipboard);const source=await read();assert.match(await page.evaluate(()=>navigator.clipboard.readText()),/^BlitzCamera keyframes\n/);
  await page.evaluate(()=>seek(40));await page.keyboard.press('Control+v');await page.waitForFunction(()=>state.tracks.x.some(k=>k.time_sec===40));
  const pasted=await read();assert.equal(pasted.undo,source.undo+1);assert.equal(pasted.selected.length,3);assert.equal(pasted.playhead,40);assert.equal(pasted.previewTime,40);assert.deepEqual(pasted.tracks,pasted.data.tracks);
  for(const [name,from,to]of [['x',10,40],['x',20,50],['y',20,50]])assert.deepEqual(at(pasted.data,name,to),{...at(source.data,name,from),time_sec:to});
  assert.deepEqual(pasted.data.speed,source.data.speed);assert.deepEqual(pasted.data.timeline,source.data.timeline);
  await page.keyboard.press('Control+z');assert.deepEqual((await read()).data,source.data);await page.keyboard.press('Control+Shift+z');assert.deepEqual((await read()).data,pasted.data);checks.push('native Ctrl+C/V, source ease and offsets, one undo/redo, application synchronization');
  // Browser text copy/paste in the editor inspector is preserved and does not replace keyframe memory.
  await page.evaluate(()=>{const input=document.createElement('textarea');input.id='clipboardTextProbe';document.getElementById('paneCurve').append(input);showTab('Curve');});
  const input=page.locator('#clipboardTextProbe');await input.fill('ordinary editor text');await input.press('Control+a');await input.press('Control+c');assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),'ordinary editor text');
  await input.fill('');await input.press('Control+v');assert.equal(await input.inputValue(),'ordinary editor text');assert.equal((await read()).clipboard,source.clipboard);assert.deepEqual((await read()).data,pasted.data);
  await page.locator('.seq-scroll').focus();await page.keyboard.press('Control+v');assert.deepEqual((await read()).data,pasted.data);await page.evaluate(()=>document.getElementById('clipboardTextProbe').remove());checks.push('ordinary inspector text copy/paste and foreign clipboard preservation');
  // Toolbar paste uses the keyframe memory even after the operating system clipboard contains text.
  await page.evaluate(async()=>{seek(65);await play();cancelAnimationFrame(state.animationRequest);state.animationRequest=0;});assert.equal((await read()).playing,true);
  await page.locator('[data-action=paste]').click();const viaButton=await read();assert.equal(viaButton.playing,false);assert.equal(viaButton.previewTime,65);assert.equal(viaButton.playhead,65);assert.ok(at(viaButton.data,'x',65));assert.ok(at(viaButton.data,'x',75));assert.ok(at(viaButton.data,'y',75));assert.equal(viaButton.selected.length,3);checks.push('toolbar paste cache and preview pause without seek');
  await save();await page.reload();await enterFixture(page);await page.waitForFunction(()=>state.loaded&&sequenceEditor?.doc&&state.samples.length>1);assert.deepEqual((await read()).data,viaButton.data);checks.push('pasted keys and easing persist through save/reload');
  // Mixed camera/rate copy through the speed pane preserves all absolute replay times.
  const rateBefore=await page.evaluate(()=>{const e=sequenceEditor,m=e.map();window.rateTimes=e.doc.speed.keyframes.map(k=>m.rateTime(k.progress));e.selected=new Set([e.doc.tracks.x.find(k=>k.time_sec===10)._id,e.doc.speed.keyframes[1]._id,e.doc.speed.keyframes[2]._id]);e.render();showTab('Speed');return {data:e.data(),undo:e.undoStack.length,knots:e.doc.speed.keyframes.map((k,i)=>({time:rateTimes[i],rate:k.rate,ease:k.ease}))};});
  await page.locator('#speedGraph').focus();await page.keyboard.press('Control+c');await page.evaluate(()=>seek(15));await page.keyboard.press('Control+v');await page.waitForFunction(()=>sequenceEditor.doc.speed.keyframes.length===6);
  const rateAfter=await page.evaluate(()=>{const e=sequenceEditor;return {data:e.data(),undo:e.undoStack.length,selected:[...e.selected].length,knots:e.doc.speed.keyframes.map(k=>({time:e.map().rateTime(k.progress),rate:k.rate,ease:k.ease}))};});
  assert.equal(rateAfter.undo,rateBefore.undo+1);assert.equal(rateAfter.selected,3);assert.ok(at(rateAfter.data,'x',15));
  for(const expected of [...rateBefore.knots,...[rateBefore.knots[1],rateBefore.knots[2]].map(k=>({...k,time:k.time+5,ease:k.ease??[1/3,0,2/3,1]}))]){
   const actual=rateAfter.knots.find(k=>Math.abs(k.time-expected.time)<1e-6);assert.ok(actual,`preserved replay time ${expected.time}`);assert.equal(actual.rate,expected.rate);assert.deepEqual(actual.ease,expected.ease);
  }
  await page.keyboard.press('Control+z');assert.deepEqual((await read()).data,rateBefore.data);checks.push('speed-pane clipboard scope and mixed rate/camera replay times');
  // Copy a camera point, switch to a real second project, and paste from the retained memory.
  await selected([['x',10]]);await page.locator('[data-action=copy]').click();const onePoint=(await read()).clipboard;await save();
  const targetDirectory=(await page.evaluate(()=>api('/api/settings'))).project_directory;
  assert.equal(path.dirname(path.resolve(targetDirectory)),path.dirname(path.resolve(sourcePath)),'new project directory must be isolated beside the source fixture');
  const target=await page.evaluate(async()=>{const result=await api('/api/projects/new',{name:'Clipboard target'});await refreshState(true);return result.path;});assert.notEqual(target,sourcePath);assert.equal((await read()).clipboard,onePoint);
  await page.evaluate(()=>seek(2));await page.locator('[data-action=paste]').click();const targetData=await read();assert.equal(at(targetData.data,'x',2).value,at(source.data,'x',10).value);assert.deepEqual(at(targetData.data,'x',2).ease,[.2,.1,.8,.9]);assert.equal(targetData.selected.length,1);await save();
  await page.evaluate(async sourcePath=>{await api('/api/projects/open',{path:sourcePath});await refreshState(true);},sourcePath);assert.equal((await read()).clipboard,onePoint);checks.push('toolbar copy and paste across real projects');
  await page.locator('.sequence-panel').screenshot({path:path.join(out,'copied-pasted-timeline.png')});
  assert.deepEqual(errors,[]);assert.deepEqual(gameRequests,[]);assert.deepEqual((await read()).data.timeline,initial.data.timeline);
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({passed:true,checks,errors,gameRequests},null,2));console.log(JSON.stringify({passed:true,checks,errors,gameRequests}));
 }catch(error){console.error(errors,await read().catch(()=>({})),await page.locator('#toast').textContent().catch(()=>''));await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});throw error;}
 finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
