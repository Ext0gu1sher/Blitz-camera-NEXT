const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {enterFixture}=require('./ui_fixture.cjs'),T=require('../blitzcam/web/preview-time.js');
const out=path.resolve('output/timeline-rate-drag-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const page=await browser.newPage({viewport:{width:1550,height:1150}}),errors=[],gameRequests=[],checks=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(/\/api\/(connect|playback\/start|replay\/open)$/.test(r.url()))gameRequests.push(r.url());});
 const read=()=>page.evaluate(()=>({data:sequenceEditor.data(),undo:sequenceEditor.undoStack.length,playhead:sequenceEditor.playhead,
  rates:sequenceEditor.doc.speed.keyframes.map(k=>({id:k._id,time:sequenceEditor.map().rateTime(k.progress),rate:k.rate}))}));
 const stable=(before,after,moving)=>{
  for(const key of before.rates)if(!moving.includes(key.id)){
   const actual=after.rates.find(k=>k.id===key.id);
   assert.ok(Math.abs(actual.time-key.time)<1e-7,`unselected rate ${key.id} moved from ${key.time} to ${actual.time}`);
   assert.equal(actual.rate,key.rate,'unselected rate changed');
  }
 };
 const center=async id=>{const b=await page.locator(`.seq-key[data-key="${id}"]`).boundingBox();return {x:b.x+b.width/2,y:b.y+b.height/2};};
 const setup=async({axis='replay',snap=true,trim=false,custom=false,group=false,dense=false}={})=>{
  const id=await page.evaluate(({axis,snap,trim,custom,group,dense})=>{
   const e=sequenceEditor;e.edit(()=>{
    e.doc.timeline.work_start_sec=10;e.doc.timeline.work_end_sec=trim?24:30;
    e.doc.speed={mode:'curve',rate:1,camera_clock:'replay',interpolation:'smooth',time_range:{start_sec:10,end_sec:30},
     keyframes:[{progress:0,rate:1},{progress:.25,rate:.25},{progress:.7,rate:.6},{progress:1,rate:.8}].map(k=>({...k,_id:++e.ids}))};
    if(custom){e.doc.speed.keyframes[0].ease=[.2,.1,.8,.9];e.doc.speed.keyframes[1].ease=[.15,.2,.7,.85];}
    if(dense){
     e.doc.timeline.work_start_sec=69.75;e.doc.timeline.work_end_sec=73.84;
     e.doc.speed.time_range={start_sec:0,end_sec:73.84};
     e.doc.speed.keyframes=[1,1,1,.0625,.0625,1,1].map((rate,i)=>({rate,progress:i/6,_id:++e.ids}));
     e.setRateTimes([0,8.13,71.067,71.212,71.254,71.748,73.84]);
    }
   });
   e.axis=axis;e.root.querySelector('[data-option=axis]').value=axis;if(e.snap!==snap)e.action('snap');
   e.selected=new Set(group?e.doc.speed.keyframes.slice(1,-1).map(k=>k._id):[]);
   e.action('workfit');e.scroll.scrollTop=e.scroll.scrollHeight;seek(12.3);e.render();
   if(dense){e.scale=1200;e.render();e.scroll.scrollLeft=e.x(70.95);}
   return e.doc.speed.keyframes[dense?3:1]._id;
  },{axis,snap,trim,custom,group,dense});
  await page.locator('.seq-scroll').scrollIntoViewIfNeeded();return id;
 };
 const move=async(id,dx,dy)=>{
  const before=await read(),a=await center(id);await page.mouse.move(a.x,a.y);await page.mouse.down();
  const moving=await page.evaluate(()=>[...sequenceEditor.selected]);
  for(let i=1;i<=6;i++){
   const target={x:a.x+dx*i/6,y:a.y+dy*i/6};await page.mouse.move(target.x,target.y);
   if((Math.abs(dx)+Math.abs(dy))*i/6<3)continue;
   const actual=await center(id);assert.ok(Math.abs(actual.x-target.x)<.3,`during drag x ${actual.x} != ${target.x}`);
   assert.ok(Math.abs(actual.y-target.y)<.3,`during drag y ${actual.y} != ${target.y}`);
   stable(before,await read(),moving);
  }
  const held=await center(id);await page.mouse.up();const released=await center(id);
  assert.ok(Math.abs(released.x-held.x)<.3,`release jumped ${released.x-held.x}px`);
  assert.ok(Math.abs(released.y-held.y)<.3,'release changed rate');return released;
 };
 try{
  await page.goto(process.argv[2]);await enterFixture(page);await page.waitForFunction(()=>state.samples.length>1);await page.locator('#tabSpeed').click();
  for(const config of [{name:'vertical',dx:0,dy:-14},{name:'horizontal',dx:37,dy:0},
   {name:'diagonal without snap',snap:false,dx:29,dy:-12},{name:'custom handles',custom:true,dx:24,dy:-10},
   {name:'trimmed work area',trim:true,dx:26,dy:-12},{name:'shooting ruler',axis:'shooting',dx:24,dy:-10},
   {name:'trimmed shooting ruler',axis:'shooting',trim:true,custom:true,dx:18,dy:-10},
   {name:'selected group',group:true,dx:18,dy:-8},
   {name:'dense 1/16x points vertical',dense:true,dx:0,dy:-12},
   {name:'dense 1/16x points diagonal',dense:true,dx:18,dy:-8}]){
   const id=await setup(config),before=await read();await move(id,config.dx,config.dy);const after=await read();
   stable(before,after,config.group?before.rates.slice(1,-1).map(k=>k.id):[id]);
   assert.ok(T.valid(after.data.speed));assert.equal(after.undo,before.undo+1);assert.equal(after.playhead,before.playhead);
   assert.deepEqual(after.data.tracks,before.data.tracks);assert.deepEqual(after.data.timeline,before.data.timeline);
   await page.keyboard.press('Control+z');assert.deepEqual((await read()).data,before.data);
   await page.keyboard.press('Control+Shift+z');assert.deepEqual((await read()).data,after.data);checks.push(config.name);
  }
  // A rate point stays at the exact cursor time even inside a camera key's snap radius.
  let id=await setup(),start=await center(id);
  const targetX=await page.evaluate(()=>{const e=sequenceEditor,r=e.scroll.getBoundingClientRect();return r.left+e.x(20)-e.scroll.scrollLeft+4;});
  await move(id,targetX-start.x,-4);checks.push('no camera-key magnet');
  // Crossing a neighbour clamps continuously instead of rejecting and restoring the whole drag.
  id=await setup();start=await center(id);const beforeCross=await read();
  await page.mouse.move(start.x,start.y);await page.mouse.down();await page.mouse.move(start.x+500,start.y-8,{steps:6});await page.mouse.up();
  const crossed=await read();assert.ok(T.valid(crossed.data.speed));assert.ok(crossed.data.speed.keyframes[1].progress>.25);
  assert.ok(crossed.data.speed.keyframes[1].progress<crossed.data.speed.keyframes[2].progress);assert.equal(crossed.undo,beforeCross.undo+1);checks.push('neighbour bound');
  // Escape restores an uncommitted drag exactly, including custom handles.
  id=await setup({custom:true});const beforeCancel=await read();start=await center(id);
  await page.mouse.move(start.x,start.y);await page.mouse.down();await page.mouse.move(start.x+20,start.y-10,{steps:4});
  await page.keyboard.press('Escape');await page.mouse.up();assert.deepEqual(await read(),beforeCancel);checks.push('escape cancel');
  // Endpoint times remain anchored to the authored range; their rates remain editable.
  const beforeEndpoint=await read(),endpoint=await page.evaluate(()=>sequenceEditor.doc.speed.keyframes[0]._id);start=await center(endpoint);
  await page.mouse.move(start.x,start.y);await page.mouse.down();await page.mouse.move(start.x+25,start.y+12,{steps:4});await page.mouse.up();
  const afterEndpoint=await read(),endSpeed=afterEndpoint.data.speed;stable(beforeEndpoint,afterEndpoint,[endpoint]);assert.equal(endSpeed.keyframes[0].progress,0);assert.ok(endSpeed.keyframes[0].rate<1);assert.ok(T.valid(endSpeed));checks.push('anchored endpoint');
  id=await setup({dense:true});await page.locator(`.seq-key[data-key="${id}"]`).click();await page.locator('#tabCurve').click();
  for(const [field,value]of [['value',.3],['time',71.222]]){
   const before=await read(),input=page.locator(`#keyInspector [data-field=${field}]`);
   await input.locator('..').locator('.number-value').dblclick();await input.fill(String(value));await input.press('Enter');
   const after=await read();stable(before,after,[id]);
   assert.ok(Math.abs(after.rates.find(k=>k.id===id)[field==='time'?'time':'rate']-value)<1e-7);
   checks.push('precise '+field+' entry preserves neighbours');
  }
  await page.evaluate(()=>refreshDraftPreview());
  assert.ok(!(await page.locator('#toast').textContent()).includes('草稿预演：'));
  const saved=(await read()).data.speed;await page.locator('#saveButton').click();await page.waitForFunction(()=>document.querySelector('#savedLabel').textContent==='已保存');
  await page.reload();await enterFixture(page);assert.deepEqual((await read()).data.speed,saved);checks.push('draft and save reload');
  await page.locator('.sequence-panel').screenshot({path:path.join(out,'timeline-rate.png')});
  assert.deepEqual(errors,[]);assert.deepEqual(gameRequests,[]);
  const result={passed:true,checks,errors,gameRequests};fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }catch(e){console.error({errors});await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});throw e;}
 finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
