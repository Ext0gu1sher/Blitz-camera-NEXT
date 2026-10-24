// Isolated timeline acceptance. No service, game access, or desktop input.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const out=path.resolve('output/work-range-drag-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const page=await browser.newPage({viewport:{width:1400,height:650}}),errors=[],checks=[];page.on('pageerror',e=>errors.push(e.message));
 const read=()=>page.evaluate(()=>({data:editor.data(),undo:editor.undoStack.length,redo:editor.redoStack.length,playhead:editor.playhead,changes:changes.length,seeks:seeks.length,starts:starts,selected:[...editor.selected]}));
 const setup=async({axis='replay',scale=20,snap=false,start=10,end=30}={})=>page.evaluate(options=>reset(options),{axis,scale,snap,start,end});
 const anchor=async part=>page.locator(`[data-work=${part}]`).evaluate(el=>{const r=el.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};});
 const drag=async(part,dx,{cancel=false,alt=false}={})=>{
  const at=await anchor(part);if(alt)await page.keyboard.down('Alt');
  await page.mouse.move(at.x,at.y);await page.mouse.down();await page.mouse.move(at.x+dx,at.y,{steps:5});
  const during=await read();if(cancel)await page.keyboard.press('Escape');await page.mouse.up();
  if(alt)await page.keyboard.up('Alt');return during;
 };
 const unchanged=(after,before)=>{assert.deepEqual(after.data.tracks,before.data.tracks);assert.deepEqual(after.data.speed,before.data.speed);assert.equal(after.playhead,before.playhead);assert.equal(after.seeks,before.seeks);assert.deepEqual(after.selected,before.selected);};
 try{
  await page.setContent('<style>body{background:#191919;color:#ddd;font:12px sans-serif}#editor{display:flex;flex-direction:column;width:1250px;height:400px}button,select{color:inherit;background:#252525;border:1px solid #444}.ic{width:12px;height:12px}input{width:100px}</style><div id="editor"></div><div id="inspector"><span data-selection></span><span data-time-label></span><input data-field="time"><span data-value-label></span><input data-field="value"></div>');
  await page.addStyleTag({path:path.resolve('blitzcam/web/timeline.css')});
  for(const file of ['preview-time.js','timeline.js'])await page.addScriptTag({path:path.resolve('blitzcam/web',file)});
  await page.evaluate(()=>{
   window.changes=[];window.seeks=[];window.notices=[];window.starts=0;
   const tracks=Object.fromEntries(BlitzTimeline.CHANNELS.map(([name])=>[name,[0,20,50,100].map(time_sec=>({time_sec,value:name==='zoom'?60:0}))]));
   window.editor=new BlitzTimeline.Editor(document.getElementById('editor'),{inspector:document.getElementById('inspector'),
    change:data=>changes.push(data),error:m=>notices.push(m),seek:t=>{seeks.push(t);editor.updatePlayhead(t);},onWorkRangeDragStart:()=>starts++,evaluate:async()=>({})});
   window.reset=({axis='replay',scale=20,snap=false,start=10,end=30}={})=>{
    editor.load(tracks,{mode:'curve',rate:1,camera_clock:'replay',interpolation:'smooth',time_range:{start_sec:5,end_sec:80},
      keyframes:[{progress:0,rate:1,ease:[.2,.1,.8,.9]},{progress:.3,rate:.4,ease:[.15,.2,.7,.85]},{progress:1,rate:.7}]},false,
      {duration_sec:100,work_start_sec:start,work_end_sec:end});
    editor.axis=axis;editor.root.querySelector('[data-option=axis]').value=axis;editor.scale=scale;editor.snap=snap;
    editor.scroll.scrollLeft=0;editor.scroll.scrollTop=0;editor.updatePlayhead(24.25);editor.selected=new Set([editor.doc.tracks.x[1]._id]);editor.render();changes.length=0;seeks.length=0;starts=0;notices.length=0;
   };
  });
  for(const [part,dx,expected] of [['start',60,[13,30]],['end',80,[10,34]],['range',100,[15,35]]]){
   await setup();const before=await read(),during=await drag(part,dx),after=await read();
   assert.equal(during.changes,0);assert.equal(during.undo,0);assert.equal(during.starts,1);assert.equal(after.changes,1);assert.equal(after.undo,1);
   assert.equal(after.data.timeline.work_start_sec,expected[0]);assert.equal(after.data.timeline.work_end_sec,expected[1]);unchanged(after,before);
   assert.match(await page.locator('[data-status]').textContent(),/入 .* · 出 .* · 长 /);
   await page.keyboard.press('Control+z');assert.deepEqual((await read()).data,before.data);
   await page.keyboard.press('Control+Shift+z');assert.deepEqual((await read()).data,after.data);checks.push(part+' drag and history');
  }
  await setup();let before=await read();await drag('end',90,{cancel:true});assert.deepEqual((await read()).data,before.data);assert.equal((await read()).undo,0);assert.equal((await read()).changes,0);unchanged(await read(),before);checks.push('Escape rollback');
  await setup();before=await read();let a=await anchor('start');await page.mouse.move(a.x,a.y);await page.mouse.down();await page.mouse.move(a.x+80,a.y,{steps:4});
  await page.evaluate(()=>editor.root.dispatchEvent(new PointerEvent('pointercancel',{bubbles:true,pointerId:editor.drag.pointerId})));await page.mouse.up();assert.deepEqual((await read()).data,before.data);assert.equal((await read()).undo,0);checks.push('pointercancel rollback');
  for(const event of ['blur','lostpointercapture']){
   await setup();before=await read();a=await anchor('start');await page.mouse.move(a.x,a.y);await page.mouse.down();await page.mouse.move(a.x+70,a.y,{steps:4});
   await page.evaluate(event=>{if(event==='blur')window.dispatchEvent(new Event('blur'));else editor.root.dispatchEvent(new PointerEvent('lostpointercapture',{pointerId:editor.drag.pointerId}));},event);
   await page.mouse.up();assert.deepEqual((await read()).data,before.data);assert.equal((await read()).undo,0);assert.equal((await read()).changes,0);
  }
  checks.push('window blur and lost capture rollback');
  await setup();a=await anchor('start');await page.mouse.click(a.x,a.y);assert.equal((await read()).undo,0);assert.equal((await read()).changes,0);assert.equal((await read()).seeks,0);checks.push('click does not create history or seek');
  await setup();before=await read();a=await anchor('start');await page.mouse.move(a.x,a.y);await page.mouse.down();await page.mouse.move(a.x+80,a.y,{steps:4});const heldRange=(await read()).data;
  for(const shortcut of ['Control+z','Delete','ArrowRight','i','o','Space'])await page.keyboard.press(shortcut);
  assert.deepEqual((await read()).data,heldRange);assert.equal((await read()).undo,0);assert.equal((await read()).changes,0);assert.equal((await read()).seeks,0);await page.keyboard.press('Escape');await page.mouse.up();assert.deepEqual((await read()).data,before.data);checks.push('edit and playback shortcuts blocked during drag');
  await setup();a=await anchor('start');await page.mouse.move(a.x,a.y);await page.mouse.down();await page.mouse.move(a.x+80,a.y,{steps:4});
  await page.evaluate(()=>{const d=editor.data();d.tracks.x[0].value=123;editor.load(d.tracks,d.speed,false,{duration_sec:100,work_start_sec:12,work_end_sec:32});});
  await page.mouse.move(a.x+100,a.y);await page.mouse.up();assert.equal((await read()).data.tracks.x[0].value,123);assert.equal((await read()).data.timeline.work_start_sec,12);assert.equal((await read()).data.timeline.work_end_sec,32);assert.equal((await read()).undo,0);checks.push('external load cancels previous pointer transaction');
  // Boundary movement clamps without crossing or changing camera/rate keys.
  await setup({start:10,end:11});before=await read();await drag('start',240);let after=await read();assert.equal(after.data.timeline.work_start_sec,10.999);assert.equal(after.data.timeline.work_end_sec,11);unchanged(after,before);
  await setup({start:10,end:10.001});await drag('start',-30);assert.ok((await read()).data.timeline.work_start_sec<10);
  await setup({start:10,end:10.001});await drag('end',30);assert.ok((await read()).data.timeline.work_end_sec>10.001);checks.push('both handles usable for a very short interval');
  await setup({start:10,end:30});await drag('range',-600);after=await read();assert.equal(after.data.timeline.work_start_sec,0);assert.equal(after.data.timeline.work_end_sec,20);
  await setup({start:70,end:90,scale:7});await drag('range',500);after=await read();assert.equal(after.data.timeline.work_start_sec,80);assert.equal(after.data.timeline.work_end_sec,100);checks.push('boundary and crossing clamps');
  // Snap exact key, playhead and frame times; Alt temporarily bypasses snapping.
  await setup({snap:true});await drag('start',196);assert.equal((await read()).data.timeline.work_start_sec,20);
  await setup({snap:true});await drag('end',-118);assert.equal((await read()).data.timeline.work_end_sec,24.25);
  await setup({snap:true});await drag('start',45);assert.ok(Math.abs((await read()).data.timeline.work_start_sec*60-Math.round((await read()).data.timeline.work_start_sec*60))<1e-6);
  await setup({snap:true});await drag('start',196,{alt:true});assert.equal((await read()).data.timeline.work_start_sec,19.8);checks.push('key playhead frame snaps and Alt bypass');
  // Nonlinear shooting clock is frozen during either trim and whole-range moves.
  for(const part of ['start','end','range']){
   await setup({axis:'shooting',scale:10});before=await read();a=await anchor(part);await page.mouse.move(a.x,a.y);await page.mouse.down();
   const frozen=await page.evaluate(()=>({keys:[...editor.svg.querySelectorAll('[data-channel=x]')].map(k=>k.querySelector('rect').getAttribute('x')),head:editor.head.style.left,start:editor.drag.map.workStart,end:editor.drag.map.workEnd}));
   for(let i=1;i<=4;i++){
    await page.mouse.move(a.x+i*8,a.y);
    const state=await page.evaluate(()=>({keys:[...editor.svg.querySelectorAll('[data-channel=x]')].map(k=>k.querySelector('rect').getAttribute('x')),head:editor.head.style.left,start:editor.drag.map.workStart,end:editor.drag.map.workEnd}));
    assert.deepEqual(state,frozen);unchanged(await read(),before);
   }
   const held=await page.evaluate(()=>{window.releaseAnchor=editor.drag.anchorTime;return editor.x(releaseAnchor,editor.drag.map)-editor.scroll.scrollLeft;});
   await page.mouse.up();unchanged(await read(),before);assert.equal((await read()).undo,1);
   const released=await page.evaluate(()=>editor.x(releaseAnchor)-editor.scroll.scrollLeft);assert.ok(Math.abs(released-held)<1,'shooting ruler release anchor');
  }
  checks.push('frozen shooting ruler and stationary release anchor');
  // Slow-motion release used to jump 120px as the work-clock was rebuilt.
  await setup({axis:'shooting',scale:10,start:10,end:20});await page.evaluate(()=>{editor.doc.speed.mode='fixed';editor.doc.speed.rate=.25;editor.render();});
  a=await anchor('end');await page.mouse.move(a.x,a.y);await page.mouse.down();await page.keyboard.down('Alt');await page.mouse.move(a.x+40,a.y,{steps:4});const held=await anchor('end');await page.mouse.up();await page.keyboard.up('Alt');const released=await anchor('end');assert.ok(Math.abs(released.x-held.x)<1,JSON.stringify({held,released}));assert.equal((await read()).data.timeline.work_end_sec,24);checks.push('quarter-speed release stays under pointer');
  // Holding near a viewport edge scrolls the timeline and keeps updating the range.
  await setup({start:10,end:30,scale:30});a=await anchor('end');const scroll=await page.locator('.seq-scroll').boundingBox();await page.mouse.move(a.x,a.y);await page.mouse.down();await page.mouse.move(scroll.x+scroll.width-8,a.y,{steps:3});
  const panBefore=await page.evaluate(()=>editor.scroll.scrollLeft);await page.waitForTimeout(180);const panAfter=await page.evaluate(()=>editor.scroll.scrollLeft);assert.ok(panAfter>panBefore);await page.keyboard.press('Escape');await page.mouse.up();assert.equal((await read()).undo,0);checks.push('edge auto scroll');
  await setup();before=await read();await page.evaluate(()=>editor.lock(true));a=await anchor('start');await page.mouse.move(a.x,a.y);await page.mouse.down();await page.mouse.move(a.x+50,a.y);await page.mouse.up();assert.deepEqual((await read()).data,before.data);assert.equal((await read()).starts,0);await page.evaluate(()=>editor.lock(false));checks.push('locked editor');
  await setup();await page.locator('#editor').screenshot({path:path.join(out,'work-range.png')});
  await page.evaluate(()=>{editor.doc.mode='camera_only';editor.render();});assert.equal(await page.locator('[data-work]').count(),0);checks.push('camera-only hides range');
  assert.deepEqual(errors,[]);assert.deepEqual(await page.evaluate(()=>notices),[]);
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({passed:true,checks,errors},null,2));console.log(JSON.stringify({passed:true,checks,errors}));
 }catch(error){console.error(await page.evaluate(()=>({snap:editor.snap,range:editor.data().timeline,notices})));await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});throw error;}
 finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
