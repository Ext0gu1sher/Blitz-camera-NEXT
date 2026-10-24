// Isolated timeline acceptance. No service, game access, or desktop input.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const out=path.resolve('output/keyframe-clipboard-acceptance');fs.mkdirSync(out,{recursive:true});
const near=(a,b,label)=>assert.ok(Math.abs(a-b)<1e-7,`${label}: ${a} != ${b}`);
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const page=await browser.newPage({viewport:{width:1400,height:750}}),errors=[],checks=[];page.on('pageerror',e=>errors.push(e.message));
 const read=()=>page.evaluate(()=>({data:editor.data(),undo:editor.undoStack.length,redo:editor.redoStack.length,playhead:editor.playhead,changes:changes.length,selected:[...editor.selected].map(id=>{const v=editor.locate(id);return v?{channel:v.row.name,time:v.row.name==='rate'?editor.map().rateTime(v.key.progress):v.key.time_sec,value:v.row.name==='rate'?v.key.rate:v.key.value,ease:v.key.ease}:null;}),clipboard:JSON.stringify(editor.clipboard)}));
 const setup=async(options={})=>page.evaluate(options=>reset(options),options);
 const select=async(points)=>page.evaluate(points=>{editor.selected=new Set(points.map(([name,time])=>{const row=name==='rate'?editor.doc.speed.keyframes:editor.doc.tracks[name];return row.find(k=>Math.abs((name==='rate'?editor.map().rateTime(k.progress):k.time_sec)-time)<1e-7)._id;}));editor.render();},points);
 const copy=async()=>page.evaluate(()=>{window.payload=editor.copyKeyframes();return !!payload;});
 const paste=async time=>page.evaluate(time=>editor.pasteKeyframes(payload,time),time);
 const at=(data,channel,time)=>data.tracks[channel].find(k=>Math.abs(k.time_sec-time)<1e-7);
 try{
  await page.setContent('<style>body{background:#191919;color:#ddd;font:12px sans-serif}#editor{display:flex;flex-direction:column;width:1250px;height:420px}button,select{color:inherit;background:#252525;border:1px solid #444}.ic{width:12px;height:12px}input{width:100px}</style><div id="editor"></div><div id="inspector"><span data-selection></span><span data-time-label></span><input data-field="time"><span data-value-label></span><input data-field="value"></div><p id="pageText">Example selected page text</p>');
  await page.addStyleTag({path:path.resolve('blitzcam/web/timeline.css')});
  for(const file of ['preview-time.js','keyframe-clipboard.js','timeline.js'])await page.addScriptTag({path:path.resolve('blitzcam/web',file)});
  await page.evaluate(()=>{
   window.changes=[];window.notices=[];window.guard={enabled:false};
   window.editor=new BlitzTimeline.Editor(document.getElementById('editor'),{inspector:document.getElementById('inspector'),change:data=>changes.push(data),error:m=>notices.push(m),seek:t=>editor.updatePlayhead(t),keyframeGuard:()=>guard,evaluate:async()=>({})});
   window.reset=({mode='replay',axis='replay'}={})=>{
    guard={enabled:false};const tracks=Object.fromEntries(BlitzTimeline.CHANNELS.map(([name],i)=>[name,[0,10,20,30,60,100].map(time_sec=>({time_sec,value:name==='zoom'?60:name==='pitch'?time_sec/10:i*10+time_sec,...(time_sec===10?{ease:[.2,.1,.8,.9]}:{})}))]));
    editor.load(tracks,{mode:'curve',rate:1,camera_clock:'replay',interpolation:'smooth',time_range:{start_sec:10,end_sec:60},keyframes:[{progress:0,rate:1},{progress:.3,rate:.4,ease:[.2,.1,.8,.9]},{progress:.7,rate:.4},{progress:1,rate:1}]},false,{duration_sec:100,work_start_sec:10,work_end_sec:60},mode);
    editor.axis=axis;editor.scale=10;editor.snap=false;editor.scroll.scrollLeft=0;editor.updatePlayhead(30);editor.render();changes.length=0;notices.length=0;
   };
  });
  // Earliest selected point aligns to the playhead; every channel keeps its values/ease and relative time.
  await setup();await select([['x',10],['x',20],['y',20]]);assert.equal(await copy(),true);const before=await read();
  assert.equal(await paste(30),true);const after=await read();assert.equal(after.undo,1);assert.equal(after.changes,1);assert.equal(after.selected.length,3);
  for(const [name,from,to]of [['x',10,30],['x',20,40],['y',20,40]])assert.deepEqual(at(after.data,name,to),{...at(before.data,name,from),time_sec:to});
  assert.equal(after.data.tracks.x.filter(k=>k.time_sec===30).length,1);assert.deepEqual(after.data.tracks.z,before.data.tracks.z);assert.deepEqual(after.data.speed,before.data.speed);assert.deepEqual(after.data.timeline,before.data.timeline);assert.equal(after.playhead,before.playhead);assert.equal(after.clipboard,before.clipboard);
  await page.locator('.seq-scroll').focus();await page.keyboard.press('Control+z');assert.deepEqual((await read()).data,before.data);await page.keyboard.press('Control+Shift+z');assert.deepEqual((await read()).data,after.data);checks.push('multi-channel offsets, ease, overwrite, selection and one undo');
  // The copied data remains a snapshot through later document edits and repeated pastes.
  await page.evaluate(()=>{editor.doc.tracks.x.find(k=>k.time_sec===10).value=999;editor.doc.tracks.x.find(k=>k.time_sec===10).ease[0]=.4;});
  assert.equal(await paste(50),true);let repeated=await read();assert.equal(at(repeated.data,'x',50).value,10);assert.deepEqual(at(repeated.data,'x',50).ease,[.2,.1,.8,.9]);checks.push('clipboard snapshot survives source changes');
  // The native ClipboardEvent path carries a typed payload plus a recognizable text fallback.
  await setup();await select([['x',10],['y',20]]);await page.locator('.seq-scroll').focus();
  const copied=await page.evaluate(()=>{const data=new DataTransfer(),event=new ClipboardEvent('copy',{bubbles:true,cancelable:true,clipboardData:data});editor.scroll.dispatchEvent(event);window.clipboardText=data.getData('text/plain');window.clipboardTyped=data.getData('application/x-blitzcam-keyframes');return {prevented:event.defaultPrevented,text:clipboardText,typed:clipboardTyped};});
  assert.equal(copied.prevented,true);assert.match(copied.text,/^BlitzCamera keyframes\n/);assert.ok(copied.typed.length>20);
  await page.evaluate(()=>editor.updatePlayhead(40));
  const pasted=await page.evaluate(()=>{const data=new DataTransfer();data.setData('text/plain',clipboardText);const event=new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:data});editor.scroll.dispatchEvent(event);return event.defaultPrevented;});
  assert.equal(pasted,true);assert.equal((await read()).selected.length,2);assert.ok(at((await read()).data,'x',40));assert.ok(at((await read()).data,'y',50));checks.push('native copy and plain-text clipboard paste');
  // Normal text controls and page text selection keep browser copy/paste behavior.
  const textBefore=await read();
  for(const kind of ['input','textarea','contenteditable']){
   const blocked=await page.evaluate(kind=>{const host=editor.root.querySelector('.seq-inspector');let target;if(kind==='input')target=document.createElement('input');else if(kind==='textarea')target=document.createElement('textarea');else{target=document.createElement('div');target.contentEditable='true';}host.append(target);target.focus();const data=new DataTransfer();data.setData('text/plain','ordinary text');const copy=new ClipboardEvent('copy',{bubbles:true,cancelable:true,clipboardData:data}),paste=new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:data});target.dispatchEvent(copy);target.dispatchEvent(paste);target.remove();return {copy:copy.defaultPrevented,paste:paste.defaultPrevented};},kind);
   assert.deepEqual(blocked,{copy:false,paste:false});
  }
  const selectedText=await page.evaluate(()=>{editor.scroll.focus();const range=document.createRange();range.selectNodeContents(document.getElementById('pageText'));const selection=getSelection();selection.removeAllRanges();selection.addRange(range);const event=new ClipboardEvent('copy',{bubbles:true,cancelable:true,clipboardData:new DataTransfer()});editor.scroll.dispatchEvent(event);const prevented=event.defaultPrevented;selection.removeAllRanges();return prevented;});
  assert.equal(selectedText,false);assert.deepEqual((await read()).data,textBefore.data);assert.equal((await read()).clipboard,textBefore.clipboard);checks.push('text inputs, editable content and page selection are not intercepted');
  // Foreign clipboard text is ignored, including when there is a valid internal cache.
  const foreign=await page.evaluate(()=>{editor.scroll.focus();const data=new DataTransfer();data.setData('text/plain','not a keyframe payload');const event=new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:data});editor.scroll.dispatchEvent(event);return event.defaultPrevented;});
  assert.equal(foreign,false);assert.deepEqual((await read()).data,textBefore.data);checks.push('foreign clipboard text is ignored');
  // WebView2 may target BODY for clipboard commands. Resolve the focused editor,
  // while preserving normal text behavior when an editable field owns focus.
  await setup();await select([['x',10],['y',20]]);await page.locator('.seq-scroll').focus();
  const bodyCopy=await page.evaluate(()=>{const data=new DataTransfer(),event=new ClipboardEvent('copy',{bubbles:true,cancelable:true,clipboardData:data});document.body.dispatchEvent(event);window.bodyClipboard=data.getData('application/x-blitzcam-keyframes');return {prevented:event.defaultPrevented,typed:bodyClipboard};});
  assert.equal(bodyCopy.prevented,true);assert.ok(bodyCopy.typed.length>20);await page.evaluate(()=>editor.updatePlayhead(55));
  const bodyPaste=await page.evaluate(()=>{const data=new DataTransfer();data.setData('application/x-blitzcam-keyframes',bodyClipboard);const event=new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:data});document.body.dispatchEvent(event);return event.defaultPrevented;});
  assert.equal(bodyPaste,true);const bodyResult=await read();assert.ok(at(bodyResult.data,'x',55));assert.ok(at(bodyResult.data,'y',65));assert.equal(bodyResult.selected.length,2);assert.equal(bodyResult.undo,1);
  const bodyInput=await page.evaluate(()=>{const input=document.createElement('input');editor.root.querySelector('.seq-inspector').append(input);input.focus();const data=new DataTransfer();data.setData('application/x-blitzcam-keyframes',bodyClipboard);const copy=new ClipboardEvent('copy',{bubbles:true,cancelable:true,clipboardData:data}),paste=new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:data});document.body.dispatchEvent(copy);document.body.dispatchEvent(paste);input.remove();return {copy:copy.defaultPrevented,paste:paste.defaultPrevented};});
  assert.deepEqual(bodyInput,{copy:false,paste:false});assert.deepEqual(await read(),bodyResult);checks.push('BODY-target clipboard commands follow editor focus and respect text-field focus');
  // Loading another project retains the clipboard and creates one independent transaction there.
  await setup();await select([['x',10],['x',20]]);await copy();const retained=(await read()).clipboard;
  await setup();assert.equal((await read()).clipboard,retained);assert.equal(await page.evaluate(()=>editor.pasteKeyframes(undefined,45)),true);assert.ok(at((await read()).data,'x',45));assert.ok(at((await read()).data,'x',55));assert.equal((await read()).undo,1);checks.push('clipboard survives project load');
  // Rate knots use replay-time offsets even though their stored progress is a shooting clock.
  for(const axis of ['replay','shooting']){
   await setup({axis});const oldRates=await page.evaluate(()=>{const e=editor;window.oldRateTimes=e.doc.speed.keyframes.map(k=>e.map().rateTime(k.progress));e.selected=new Set([e.doc.tracks.x[1]._id,e.doc.speed.keyframes[1]._id,e.doc.speed.keyframes[2]._id]);e.render();return e.doc.speed.keyframes.map((k,i)=>({time:oldRateTimes[i],rate:k.rate,ease:k.ease}));});
   await copy();const rateBefore=await read();assert.equal(await paste(15),true);const newRates=await page.evaluate(()=>editor.doc.speed.keyframes.map(k=>({time:editor.map().rateTime(k.progress),rate:k.rate,ease:k.ease})));assert.equal(newRates.length,6);
   for(const expected of [...oldRates,...[oldRates[1],oldRates[2]].map(k=>({...k,time:k.time+5,ease:k.ease??[1/3,0,2/3,1]}))]){
    const found=newRates.find(k=>Math.abs(k.time-expected.time)<1e-6);assert.ok(found,`${axis}: ${JSON.stringify(expected)}`);near(found.time,expected.time,'rate replay time');assert.equal(found.rate,expected.rate);assert.deepEqual(found.ease,expected.ease);
   }
   const mixed=await read();assert.ok(at(mixed.data,'x',15));assert.equal(mixed.selected.length,3);assert.equal(mixed.undo,1);assert.equal(mixed.playhead,rateBefore.playhead);
   await page.locator('.seq-scroll').focus();await page.keyboard.press('Control+z');assert.deepEqual((await read()).data,rateBefore.data);
  }
  checks.push('mixed camera/rate time offsets, preserved old knots and shooting-ruler paste');
  await setup();await page.evaluate(()=>{editor.selected=new Set([editor.doc.speed.keyframes[1]._id]);editor.render();});await copy();await setup({mode:'camera_only'});const mixedModeBefore=await read();assert.equal(await paste(25),false);assert.deepEqual(await read(),mixedModeBefore);checks.push('rate batches rejected atomically in camera-only mode');
  // Guard/bounds failures reject the entire batch and preserve history, selection and clipboard.
  for(const scenario of ['beforeStart','beyondEnd','unknownStart']){
   await setup();await select([['x',10],['y',20]]);await copy();await page.evaluate(scenario=>{guard=scenario==='beforeStart'?{enabled:true,start_sec:15}:scenario==='unknownStart'?{enabled:true,start_sec:null}:{enabled:false};},scenario);const baseline=await read();
   assert.equal(await paste(scenario==='beyondEnd'?95:5),false);const rejected=await read();assert.deepEqual(rejected,baseline);assert.equal(await page.evaluate(()=>notices.length),1);
  }
  checks.push('prebattle, unresolved start and duration failures are atomic');
  // Pointer transactions and locked editor cannot copy transient data or create a paste undo entry.
  await setup();await select([['x',10],['y',20]]);await copy();const point=await page.locator('[data-work=start] .seq-work-grip').boundingBox();await page.mouse.move(point.x+point.width/2,point.y+point.height/2);await page.mouse.down();await page.mouse.move(point.x+point.width/2+40,point.y+point.height/2,{steps:4});
  const held=await read();assert.equal(await paste(50),false);await page.evaluate(()=>editor.copyKeyframes());assert.deepEqual(await read(),held);await page.keyboard.press('Escape');await page.mouse.up();assert.equal((await read()).undo,0);assert.equal((await read()).data.timeline.work_start_sec,10);
  await page.evaluate(()=>editor.lock(true));const locked=await read();assert.equal(await paste(50),false);assert.deepEqual(await read(),locked);await page.evaluate(()=>editor.lock(false));checks.push('drag and lock preserve clipboard and history');
  // Mode one can paste beyond the visible horizon and uses camera time directly.
  await setup({mode:'camera_only',axis:'shooting'});await select([['x',10],['y',20]]);await copy();assert.equal(await paste(150),true);assert.ok(at((await read()).data,'x',150));assert.ok(at((await read()).data,'y',160));checks.push('camera-only paste grows time range');
  await setup();await select([['x',10],['x',20],['y',20]]);await copy();await paste(40);await page.locator('#editor').screenshot({path:path.join(out,'pasted-keyframes.png')});
  assert.deepEqual(errors,[]);fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({passed:true,checks,errors},null,2));console.log(JSON.stringify({passed:true,checks,errors}));
 }catch(error){console.error(errors,await read().catch(()=>({})),await page.evaluate(()=>window.notices).catch(()=>[]));await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});throw error;}
 finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
