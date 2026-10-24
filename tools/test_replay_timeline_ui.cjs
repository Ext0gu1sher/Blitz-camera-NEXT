// Isolated synthetic replay only. No desktop control, game input or Hook.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {ClockMap}=require('../blitzcam/web/timeline.js');
const {enterFixture}=require('./ui_fixture.cjs');
const meta={time_basis:'replay',duration_sec:305.66,work_start_sec:12,work_end_sec:24};
const map=new ClockMap({x:[{time_sec:12,value:0},{time_sec:24,value:1}]},{mode:'fixed',rate:.25,camera_clock:'replay'},meta);
assert.equal(map.duration,305.66);assert.equal(map.atTime(12),12);assert.equal(map.atTime(24),60);assert.equal(map.atTime(25),61);
for(const t of [0,10,12,15,24,25,305.66])assert.ok(Math.abs(map.atSeconds(map.atTime(t))-t)<1e-9);
const base=process.argv[2],chosen=process.argv[3],out=path.resolve('output/timeline-070-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const errors=[];
 try{
  const page=await browser.newPage({viewport:{width:1550,height:1150}});page.on('pageerror',e=>errors.push(e.message));
  const server=async()=>(await page.request.get(base+'/api/state')).json();
  await page.goto(base+'/');await page.waitForSelector('.seq-key[data-channel=x]');await enterFixture(page);await page.waitForFunction(()=>Number(document.querySelector('#timelineSlider').max)===305.66);
  assert.equal(await page.locator('[data-option=axis]').inputValue(),'replay');
  assert.equal(Number(await page.locator('#timelineSlider').getAttribute('max')),305.66);
  assert.equal(await page.locator('#captureTime').getAttribute('readonly'),'');
  assert.equal(Number(await page.locator('#captureTime').inputValue()),12);
  const original=(await server()).project,revision=(await server()).project_revision;
  // Scrubbing the full ruler must reach empty areas without seeking the game.
  const scroll=page.locator('.seq-scroll');await scroll.scrollIntoViewIfNeeded();
  const keyCenter=async(channel,index)=>page.locator(`.seq-key[data-channel=${channel}]`).nth(index).evaluate(e=>{const r=e.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2};});
  const scale=async()=>{const a=await keyCenter('x',0),b=await keyCenter('x',3);return(b.x-a.x)/12;};
  let rect=await scroll.boundingBox(),s=await scale();
  await page.mouse.click(rect.x+14+90*s,rect.y+20);
  assert.ok(Math.abs(Number(await page.locator('#timelineSlider').inputValue())-90)<.02);
  assert.equal((await server()).sample.replay.time,12);
  assert.deepEqual((await server()).project,original);
  // Alt-wheel zoom keeps the time under the pointer in place, including when scrolled.
  const anchor=Math.round(rect.x+rect.width*.53)-rect.x;
  const timeUnderPointer=async()=>{const r=await scroll.boundingBox(),k=await keyCenter('x',0);return 12+(r.x+anchor-k.x)/await scale();};
  const before=await timeUnderPointer(),beforeScale=await scale();
  await page.mouse.move(rect.x+anchor,rect.y+160);await page.keyboard.down('Alt');
  for(let i=0;i<5;i++)await page.mouse.wheel(0,-120);
  await page.keyboard.up('Alt');await page.waitForTimeout(100);
  const after=await timeUnderPointer(),afterScale=await scale();assert.ok(afterScale>beforeScale);assert.ok(Math.abs(after-before)*afterScale<1.5,JSON.stringify({before,after,beforeScale,afterScale}));
  assert.equal((await server()).project_revision,revision);
  // Fit the selected interval, then marquee six keys across X/Y/Z without Shift.
  await page.locator('[data-action=workfit]').click();await page.waitForTimeout(100);
  let a=await keyCenter('x',1),b=await keyCenter('z',2);
  const marquee=async(reverse=false,shift=false)=>{a=await keyCenter('x',1);b=await keyCenter('z',2);const from={x:a.x-12,y:a.y-12},to={x:b.x+12,y:b.y+12};if(shift)await page.keyboard.down('Shift');await page.mouse.move(reverse?to.x:from.x,reverse?to.y:from.y);await page.mouse.down();await page.mouse.move(reverse?from.x:to.x,reverse?from.y:to.y,{steps:5});await page.mouse.up();if(shift)await page.keyboard.up('Shift');};
  await marquee();assert.equal(await page.locator('.seq-key.selected').count(),6);
  assert.match(await page.locator('[data-selection]').textContent(),/6/);
  await page.locator('.sequence-panel').screenshot({path:path.join(out,'six-keys-selected.png')});
  await marquee(true);assert.equal(await page.locator('.seq-key.selected').count(),6);
  // Shift-marquee adds to a selected key on a different channel.
  await page.locator('.seq-key[data-channel=yaw]').first().click();await marquee(false,true);
  assert.equal(await page.locator('.seq-key.selected').count(),7);
  await marquee();
  // Drag the selected group, preserving spacing and untouched channels.
  a=await keyCenter('x',1);await page.mouse.move(a.x,a.y);await page.mouse.down();await page.mouse.move(a.x+36,a.y,{steps:5});await page.mouse.up();
  await page.locator('#saveButton').click();await page.waitForFunction(()=>document.querySelector('#savedLabel').textContent==='已保存');
  const changed=(await server()).project;
  const delta=changed.camera_tracks.x[1].time_sec-16.8;assert.ok(delta>0);
  for(const name of ['x','y','z']){assert.ok(Math.abs(changed.camera_tracks[name][1].time_sec-16.8-delta)<1e-6);assert.ok(Math.abs(changed.camera_tracks[name][2].time_sec-20.4-delta)<1e-6);assert.equal(changed.camera_tracks[name][0].time_sec,12);assert.equal(changed.camera_tracks[name][3].time_sec,24);}
  for(const name of ['yaw','pitch','roll','zoom'])assert.deepEqual(changed.camera_tracks[name].map(k=>k.time_sec),[12,16.8,20.4,24]);
  assert.equal(changed.replay_timeline.duration_sec,305.66);
  // A rate change cannot move absolute camera keys on the replay ruler.
  const keyX=async()=>page.locator('.seq-key[data-channel=x]').nth(1).evaluate(e=>e.querySelector('rect').getAttribute('x'));
  const normal=await keyX();await page.locator('#tabSpeed').click();await page.locator('#replayFixedRate').selectOption('0.25');assert.equal(await keyX(),normal);
  await page.locator('#saveButton').click();await page.waitForFunction(()=>document.querySelector('#savedLabel').textContent==='已保存');
  // Read a selected replay file's metadata and retain authored timestamps.
  await page.getByText('回放来源与全片长度',{exact:true}).click();await page.locator('#replayFilePath').fill(chosen);await page.locator('#readReplayFile').click();
  await page.waitForFunction(()=>Number(document.querySelector('#timelineSlider').max)===306.125);
  await page.locator('#saveButton').click();await page.waitForFunction(()=>document.querySelector('#savedLabel').textContent==='已保存');
  assert.deepEqual((await server()).project.camera_tracks,changed.camera_tracks);
  await page.reload();await page.waitForSelector('.seq-key[data-channel=x]');await enterFixture(page);
  assert.equal(Number(await page.locator('#timelineSlider').getAttribute('max')),306.125);
  await page.locator('[data-action=fit]').click();
  await page.locator('.sequence-panel').screenshot({path:path.join(out,'whole-replay.png')});
  // Play uses the work interval and reference replay timestamp, without retiming the project.
  const finalProject=(await server()).project;
  await page.locator('#liveForward').click();await page.waitForFunction(()=>!document.querySelector('#liveStop').disabled);
  assert.equal((await server()).playback.timeline_start,12);
  assert.equal((await server()).playback.timeline_end,24);
  assert.deepEqual((await server()).project,finalProject);
  await page.locator('#liveStop').click();
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({passed:true,checks:['full replay extent','absolute replay keys','scrub without game seek','mouse-anchored Alt-wheel zoom','left-drag marquee in both directions','Shift additive marquee','group movement with spacing','rate change leaves camera timestamps fixed','metadata read and persistence','work-area playback without project retiming'],errors},null,2));
  console.log('PASS: full replay timeline, Alt-wheel zoom, marquee, group movement, absolute timestamps and bounded playback (synthetic).');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
