// Isolated application fixture; never connects to or starts the game.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {enterFixture}=require('./ui_fixture.cjs');
const out=path.resolve('output/playhead-follow-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const page=await browser.newPage({viewport:{width:1550,height:1150}}),errors=[],checks=[];
 page.on('pageerror',e=>errors.push(e.message));
 const read=()=>page.evaluate(()=>({scroll:sequenceEditor.scroll.scrollLeft,width:sequenceEditor.scroll.clientWidth,
  max:sequenceEditor.scroll.scrollWidth-sequenceEditor.scroll.clientWidth,playhead:sequenceEditor.playhead,time:state.previewTime,
  drag:sequenceEditor.drag?.kind,auto:sequenceEditor.autoFrame,data:sequenceEditor.data(),undo:sequenceEditor.undoStack.length}));
 const setup=async(axis='replay',edge=null)=>{
  await page.evaluate(({axis,edge})=>{const e=sequenceEditor;e.cancel();e.axis=axis;e.scale=60;e.snap=false;e.render();
   e.scroll.scrollLeft=edge==='left'?0:edge==='right'?e.scroll.scrollWidth-e.scroll.clientWidth-80:300;
   seek(e.fromDisplay((e.scroll.scrollLeft+e.scroll.clientWidth/2-14)/e.scale));},{axis,edge});
  await page.locator('.seq-scroll').scrollIntoViewIfNeeded();
 };
 const start=async()=>{
  const r=await page.locator('.seq-scroll').boundingBox();
  await page.mouse.move(r.x+r.width/2,r.y+6);await page.mouse.down();
  assert.equal((await read()).drag,'seek');return r;
 };
 const stop=async()=>{await page.mouse.up();const held=await read();await page.waitForTimeout(420);assert.equal((await read()).scroll,held.scroll);assert.equal((await read()).time,held.time);};
 try{
  await page.goto(process.argv[2]);await enterFixture(page);await page.waitForFunction(()=>state.samples.length>1);
  const original=await read();
  for(const axis of ['replay','shooting']){
   await setup(axis);let r=await start(),before=await read();
   await page.evaluate(()=>{window.followFrames=[];window.followRecording=true;const record=()=>{followFrames.push(sequenceEditor.scroll.scrollLeft);if(followRecording)requestAnimationFrame(record);};requestAnimationFrame(record);});
   await page.mouse.move(r.x+r.width-8,r.y+6);await page.waitForTimeout(260);let after=await read();
   const initial=after.scroll-before.scroll;assert.ok(initial>0&&initial<40,'gentle start without a page jump');
   assert.ok(after.time>before.time);assert.equal(after.time,after.playhead);
   await page.waitForTimeout(370);assert.ok((await read()).scroll-after.scroll>initial,'speed eases up while holding');
   const frames=await page.evaluate(()=>{followRecording=false;return followFrames;});
   const deltas=frames.slice(1).map((v,i)=>v-frames[i]);assert.ok(deltas.filter(v=>v>0).length>=5,'continuous frame movement');
   assert.ok(deltas.every(v=>v>=0&&v<=12),'no large scroll steps');
   await page.mouse.move(r.x+r.width/2,r.y+6);before=await read();await page.waitForTimeout(420);assert.equal((await read()).scroll,before.scroll);
   await page.mouse.move(r.x+8,r.y+6);await page.waitForTimeout(260);after=await read();assert.ok(after.scroll<before.scroll);assert.ok(after.time<before.time);
   await stop();checks.push(axis+' ruler eases into continuous left/right follow and stops');
  }
  await setup();let r=await start(),before=await read();await page.mouse.move(r.x+r.width-32,r.y+6);await page.waitForTimeout(650);
  const shallow=(await read()).scroll-before.scroll;assert.ok(shallow>0&&shallow<15,'slow at the start of the edge zone');
  before=await read();await page.mouse.move(r.x+r.width-4,r.y+6);await page.waitForTimeout(650);
  assert.ok((await read()).scroll-before.scroll>shallow*3,'faster nearer the outer edge');await stop();checks.push('speed follows edge proximity');
  for(const event of ['Escape','pointercancel','lostpointercapture','blur']){
   await setup();const r=await start();await page.mouse.move(r.x+r.width-8,r.y+6);
   const before=await read();await page.waitForFunction(n=>sequenceEditor.scroll.scrollLeft>n,before.scroll);
   if(event==='Escape')await page.keyboard.press('Escape');
   else await page.evaluate(event=>{if(event==='blur')window.dispatchEvent(new Event('blur'));else sequenceEditor.root.dispatchEvent(new PointerEvent(event,{bubbles:true,pointerId:sequenceEditor.drag.pointerId}));},event);
   assert.equal((await read()).drag,undefined);await stop();checks.push(event+' stops follow');
  }
  for(const edge of ['left','right']){
   await setup('replay',edge);const r=await start();await page.mouse.move(edge==='left'?r.x-12:r.x+r.width+12,r.y+6);
   await page.waitForFunction(edge=>{const s=sequenceEditor.scroll;return edge==='left'?s.scrollLeft===0:s.scrollLeft===s.scrollWidth-s.clientWidth;},edge);
   const held=await read();assert.equal(held.scroll,edge==='left'?0:held.max);assert.equal(held.time,edge==='left'?0:100);await stop();checks.push(edge+' replay boundary');
  }
  await setup();r=await page.locator('.seq-scroll').boundingBox();const clicked=await read();await page.mouse.click(r.x+r.width-8,r.y+6);await page.waitForTimeout(420);
  assert.equal((await read()).scroll,clicked.scroll);checks.push('ordinary edge click does not scroll');
  assert.deepEqual((await read()).data,original.data);assert.equal((await read()).undo,original.undo);checks.push('keys, rates, work range and history unchanged');
  await page.locator('[name=shootingMode][value=camera_only]').check();await page.waitForFunction(()=>isCameraOnly());await setup('shooting');
  const horizon=await page.evaluate(()=>{const e=sequenceEditor,end=e.map().end;e.scroll.scrollLeft=e.x(end)-e.scroll.clientWidth-40;seek(e.fromDisplay((e.scroll.scrollLeft+e.scroll.clientWidth/2-14)/e.scale));return end;});
  r=await start();await page.mouse.move(r.x+r.width-8,r.y+6);
  await page.waitForFunction(end=>state.previewTime>end,horizon,{timeout:6000});await stop();checks.push('camera-only follow extends past original horizon');
  await page.locator('.sequence-panel').screenshot({path:path.join(out,'follow.png')});
  assert.deepEqual(errors,[]);const result={passed:true,checks,errors};fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
