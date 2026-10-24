// Isolated editor component acceptance. No service, replay, or game access.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const out=path.resolve('output/keyframe-guard-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const page=await browser.newPage({viewport:{width:1400,height:650}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.setContent('<style>body{background:#191919;color:#ddd;font:12px sans-serif}#editor{display:flex;flex-direction:column;width:1250px;height:400px}#inspector{padding:20px}button,select{color:inherit;background:#252525;border:1px solid #444}.ic{width:12px;height:12px}input{width:100px}</style><div id="editor"></div><div id="inspector"><span data-selection></span><label><span data-time-label></span><input type="number" data-field="time"></label><label><span data-value-label></span><input type="number" data-field="value"></label></div>');
  for(const file of ['timeline.css','number-field.css'])await page.addStyleTag({path:path.resolve('blitzcam/web',file)});
  for(const file of ['preview-time.js','number-field.js','timeline.js'])await page.addScriptTag({path:path.resolve('blitzcam/web',file)});
  await page.evaluate(()=>{
   window.guard={enabled:true,start_sec:15,source:'automatic',status:'ready'};window.notices=[];window.changes=[];
   const tracks=Object.fromEntries(BlitzTimeline.CHANNELS.map(([name])=>[name,[10,20,30].map(time_sec=>({time_sec,value:name==='zoom'?60:0}))]));
   window.editor=new BlitzTimeline.Editor(document.getElementById('editor'),{inspector:document.getElementById('inspector'),
    keyframeGuard:()=>guard,error:m=>notices.push(m),change:data=>changes.push(data),seek:t=>editor.updatePlayhead(t),
    evaluate:async()=>Object.fromEntries(BlitzTimeline.CHANNELS.map(([name])=>[name,name==='zoom'?60:0]))});
   editor.load(tracks,{mode:'fixed',rate:1,camera_clock:'replay',interpolation:'linear',keyframes:[{progress:0,rate:1},{progress:1,rate:1}]},false,
    {duration_sec:100,work_start_sec:10,work_end_sec:30});
   window.reset=()=>{editor.load(tracks,{mode:'fixed',rate:1,camera_clock:'replay',interpolation:'linear',keyframes:[{progress:0,rate:1},{progress:1,rate:1}]},false,{duration_sec:100,work_start_sec:10,work_end_sec:30});notices.length=0;};
   document.addEventListener('number-start',()=>editor.beginNumberEdit());document.addEventListener('number-end',e=>editor.endNumberEdit(e.detail.cancelled));
  });
  assert.equal(await page.locator('.seq-keyframe-blocked').count(),7);assert.equal(await page.locator('.seq-keyframe-boundary').count(),1);
  assert.match(await page.locator('[data-keyframe-guard]').textContent(),/15\.000/);
  const original=await page.evaluate(()=>editor.data().tracks);
  for(const channel of ['all','x']){await page.evaluate(channel=>editor.add(channel,12),channel);assert.deepEqual(await page.evaluate(()=>editor.data().tracks),original);}
  assert.equal(await page.evaluate(()=>editor.undoStack.length),0);
  await page.evaluate(()=>editor.add('x',15));assert.equal(await page.evaluate(()=>editor.doc.tracks.x.some(k=>k.time_sec===15)),true);
  await page.evaluate(()=>{editor.action('undo');editor.action('redo');});assert.equal(await page.evaluate(()=>editor.doc.tracks.x.some(k=>k.time_sec===15)),true);
  // Editing a grandfathered key's value is permitted; changing its time is rejected.
  assert.equal(await page.evaluate(()=>editor.edit(()=>editor.doc.tracks.x[0].value=7)),true);
  assert.equal(await page.evaluate(()=>editor.edit(()=>editor.doc.tracks.x[0].time_sec=11)),false);
  assert.equal(await page.evaluate(()=>editor.doc.tracks.x[0].time_sec),10);
  // Deletion is permitted. Another track's old early timestamp cannot authorize a new key.
  assert.equal(await page.evaluate(()=>editor.edit(()=>editor.doc.tracks.x.shift())),true);
  assert.equal(await page.evaluate(()=>editor.edit(()=>editor.doc.tracks.x.push({time_sec:10,value:0,_id:++editor.ids}))),false);
  await page.evaluate(()=>{reset();editor.selected=new Set([editor.doc.tracks.x[1]._id]);editor.render();});
  const timeInput=page.locator('[data-field=time]');await timeInput.locator('..').locator('.number-value').dblclick();await timeInput.fill('12');await timeInput.press('Enter');
  assert.equal(await page.evaluate(()=>editor.doc.tracks.x[1].time_sec),20);assert.equal(await timeInput.inputValue(),'20');
  // A real pointer drag into the shaded region rolls back on release.
  await page.evaluate(()=>{editor.snap=false;editor.scale=12;editor.render();});
  const key=page.locator('.seq-key[data-channel=x]').nth(1),r=await key.boundingBox();
  await page.mouse.move(r.x+r.width/2,r.y+r.height/2);await page.mouse.down();await page.mouse.move(r.x+r.width/2-96,r.y+r.height/2,{steps:5});await page.mouse.up();
  assert.equal(await page.evaluate(()=>editor.doc.tracks.x[1].time_sec),20);assert.equal(await page.evaluate(()=>editor.undoStack.length),0);
  // Current settings also apply to undo/redo, including a guard changed mid-session.
  await page.evaluate(()=>{guard.start_sec=5;editor.edit(()=>editor.doc.tracks.x[1].time_sec=12);editor.action('undo');guard.start_sec=15;editor.action('redo');});
  assert.equal(await page.evaluate(()=>editor.doc.tracks.x[1].time_sec),20);assert.equal(await page.evaluate(()=>editor.redoStack.length),1);
  // The in-point and whole work area stop at the boundary on both clocks.
  for(const axis of ['replay','shooting'])for(const part of ['start','range']){
   await page.evaluate(axis=>{reset();guard.start_sec=15.123456;editor.doc.timeline.work_start_sec=20;editor.doc.timeline.work_end_sec=40;editor.axis=axis;editor.doc.speed.mode='fixed';editor.doc.speed.rate=.25;editor.scale=8;editor.snap=true;editor.scroll.scrollLeft=0;editor.render();},axis);
   const before=await page.evaluate(()=>({tracks:editor.data().tracks,speed:editor.data().speed,head:editor.playhead}));
   const at=await page.locator(`[data-work=${part}]`).evaluate(el=>{const r=el.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};});
   const dx=await page.evaluate(part=>editor.x(12)-editor.x(part==='range'?30:20),part);
   await page.keyboard.down('Alt');await page.mouse.move(at.x,at.y);await page.mouse.down();await page.mouse.move(at.x+dx,at.y,{steps:5});await page.mouse.up();await page.keyboard.up('Alt');
   const after=await page.evaluate(()=>({tracks:editor.data().tracks,speed:editor.data().speed,head:editor.playhead,t:editor.doc.timeline,undo:editor.undoStack.length}));
   assert.equal(after.t.work_start_sec,15.123456);assert.equal(after.t.work_end_sec,part==='range'?35.123456:40);assert.equal(after.undo,1);
   assert.deepEqual(after.tracks,before.tracks);assert.deepEqual(after.speed,before.speed);assert.equal(after.head,before.head);
   await page.evaluate(()=>editor.action('undo'));assert.equal(await page.evaluate(()=>editor.doc.timeline.work_start_sec),20);
   await page.evaluate(()=>editor.action('redo'));assert.equal(await page.evaluate(()=>editor.doc.timeline.work_start_sec),15.123456);
  }
  await page.evaluate(()=>{reset();guard.start_sec=15;editor.adapter.currentTime=()=>12;});
  assert.equal(await page.evaluate(()=>editor.action('inpoint')),false);assert.equal(await page.evaluate(()=>editor.doc.timeline.work_start_sec),10);
  await page.evaluate(()=>{editor.adapter.currentTime=()=>15;editor.action('inpoint');});assert.equal(await page.evaluate(()=>editor.doc.timeline.work_start_sec),15);
  await page.evaluate(()=>{guard.start_sec=16;editor.action('undo');});assert.equal(await page.evaluate(()=>editor.doc.timeline.work_start_sec),15);assert.equal(await page.evaluate(()=>editor.undoStack.length),1);
  // Both information areas share a single row at wide and narrow widths.
  for(const width of [1250,650]){
   await page.evaluate(width=>{editor.root.style.width=width+'px';editor.render();},width);
   const layout=await page.evaluate(()=>{const note=editor.root.querySelector('[data-keyframe-guard]'),status=editor.root.querySelector('[data-status]'),bar=note.parentElement,n=note.getBoundingClientRect(),s=status.getBoundingClientRect(),b=bar.getBoundingClientRect();return {sameParent:status.parentElement===bar,dy:Math.abs(n.y+n.height/2-s.y-s.height/2),height:b.height,overflow:bar.scrollWidth>bar.clientWidth};});
   assert.equal(layout.sameParent,true);assert.ok(layout.dy<1);assert.ok(layout.height<=26);assert.equal(layout.overflow,false);
  }
  await page.evaluate(()=>editor.root.style.width='1250px');
  await page.evaluate(()=>{reset();guard.start_sec=null;editor.render();});
  await page.evaluate(()=>{editor.selected=new Set([editor.doc.tracks.x[1]._id]);editor.render();});
  assert.equal(await page.locator('[data-field=time]').isDisabled(),true);assert.equal(await page.locator('[data-field=value]').isDisabled(),false);
  assert.equal(await page.evaluate(()=>editor.edit(()=>editor.doc.timeline.work_start_sec=25)),false);
  const range=await page.locator('[data-work=range]').boundingBox();await page.mouse.move(range.x+range.width/2,range.y+range.height/2);await page.mouse.down();assert.equal(await page.evaluate(()=>editor.drag),null);await page.mouse.up();
  await page.evaluate(()=>editor.add('x',25));assert.equal(await page.evaluate(()=>editor.doc.tracks.x.length),3);
  assert.equal(await page.evaluate(()=>editor.edit(()=>editor.doc.tracks.x[0].value=3)),true);
  assert.match(await page.locator('[data-keyframe-guard]').textContent(),/尚未解析/);
  // Existing close-key warnings and the pre-battle explanation remain independent.
  await page.evaluate(()=>{guard.start_sec=15;editor.doc.tracks.x.push({time_sec:20.01,value:0,_id:++editor.ids});editor.doc.tracks.x.sort((a,b)=>a.time_sec-b.time_sec);editor.render();});
  assert.equal(await page.locator('[data-key-warning]').isVisible(),true);assert.equal(await page.locator('[data-keyframe-guard]').isVisible(),true);
  await page.locator('#editor').screenshot({path:path.join(out,'pre-battle-boundary.png')});
  await page.evaluate(()=>{editor.doc.mode='camera_only';editor.render();});await page.evaluate(()=>editor.add('x',12));
  assert.equal(await page.evaluate(()=>editor.doc.tracks.x.some(k=>k.time_sec===12)),true);assert.equal(await page.locator('[data-keyframe-guard]').isVisible(),false);
  assert.equal(await page.locator('[data-field=time]').isDisabled(),false);
  assert.deepEqual(errors,[]);
  const result={passed:true,addAll:true,singleTrack:true,boundaryAllowed:true,legacyValueEdit:true,numberRollback:true,pointerDragRollback:true,currentGuardForHistory:true,inpointAndRangeClampBothClocks:true,altKeepsBoundary:true,gameTimeInpointGuard:true,inpointHistoryGuard:true,singleLineFooter:true,unknownRangeBlocked:true,unknownStartBlocked:true,separateWarnings:true,cameraOnlyUnrestricted:true,errors};
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }catch(error){await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});console.error(errors);throw error;}
 finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
