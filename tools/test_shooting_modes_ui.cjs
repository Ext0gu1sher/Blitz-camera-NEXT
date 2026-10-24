// Isolated synthetic replay. No desktop automation, game, injection or memory access.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {enterFixture}=require('./ui_fixture.cjs');
const base=process.argv[2],out=path.resolve('output/shooting-modes-080-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'}),errors=[];
 const timeout=setTimeout(()=>browser.close(),60000);
 try{
  const page=await browser.newPage({viewport:{width:1550,height:1150}});page.on('pageerror',e=>errors.push(e.message));
  const server=async()=>(await page.request.get(base+'/api/state')).json();
  const save=async()=>{await page.locator('#saveButton').click();await page.waitForFunction(()=>document.querySelector('#savedLabel').textContent==='已保存');};
  await page.goto(base+'/');await page.waitForSelector('.seq-key[data-channel=x]');await enterFixture(page);
  assert.equal(await page.locator('#replaySpeedMode,#replayOnly').count(),0);
  assert.equal(await page.locator('.seq-range').isVisible(),true);
  const original=(await server()).project;
  await page.locator('[name=shootingMode][value=camera_only]').check();
  assert.equal(await page.locator('.seq-range').isVisible(),false);
  assert.equal(await page.locator('.seq-rate-label').isVisible(),false);
  assert.equal(await page.locator('.replay-speed-panel').isVisible(),false);
  assert.equal(await page.locator('#replaySourceSettings').isVisible(),false);
  assert.equal(await page.locator('.seq-key[data-channel=rate]').count(),0);
  assert.equal(await page.locator('.seq-label').count(),7);
  assert.equal(await page.locator('#captureTime').getAttribute('readonly'),null);
  await save();
  let p=(await server()).project;
  assert.equal(p.shooting_mode,'camera_only');assert.equal(p.replay_speed.mode,'paused');
  assert.equal(JSON.stringify(p.camera_tracks),JSON.stringify(original.camera_tracks),'switching never shifts key timestamps');
  // Recording uses the independently chosen time, never the paused replay's 12s.
  await page.locator('#captureTime').locator('..').locator('.number-value').dblclick();await page.locator('#captureTime').fill('3.25');await page.locator('#captureTime').press('Enter');await page.waitForTimeout(650);
  assert.equal(await page.locator('#captureTime').inputValue(),'3.25');
  await page.locator('#captureButton').click();
  await page.waitForFunction(()=>document.querySelectorAll('.seq-key[data-channel=x]').length===5);
  p=(await server()).project;
  for(const rows of Object.values(p.camera_tracks))assert.ok(rows.some(k=>k.time_sec===3.25));
  // Author beyond both the replay's duration and the old one-hour edit limit.
  await page.locator('.seq-key[data-channel=x]').last().click();
  await page.locator('[data-field=time]').locator('..').locator('.number-value').dblclick();await page.locator('[data-field=time]').fill('7200');await page.locator('[data-field=time]').press('Enter');await save();
  p=(await server()).project;assert.equal(p.camera_tracks.x.at(-1).time_sec,7200);
  const sample=await (await page.request.post(base+'/api/sample',{data:{rate_hz:60}})).json();
  assert.ok(sample.samples.length<=6201);assert.equal(sample.samples[0].time_sec,0);assert.equal(sample.samples.at(-1).time_sec,7200);
  await page.locator('[data-action=fit]').click();
  await page.locator('.seq-scroll').scrollIntoViewIfNeeded();
  const beforeDrag=Number(await page.locator('[data-field=time]').inputValue());
  const key=await page.locator('.seq-key[data-channel=x]').last().boundingBox();
  console.log('Checking independent key drag and edge scrolling');
  await page.mouse.move(key.x+key.width/2,key.y+key.height/2);await page.mouse.down();
  await page.mouse.move(key.x+key.width/2+100,key.y+key.height/2,{steps:6});await page.waitForTimeout(200);await page.mouse.up();
  assert.ok(Number(await page.locator('[data-field=time]').inputValue())>beforeDrag,'drag past the former right boundary');
  assert.equal(Number(await page.locator('#timelineSlider').inputValue()),3.25,'key dragging never moves playhead');
  await save();p=(await server()).project;
  const end=p.camera_tracks.x.at(-1).time_sec;
  for(let i=0;i<3;i++){
    const width=await page.locator('.seq-content').evaluate(e=>e.clientWidth);
    await page.locator('.seq-scroll').evaluate(e=>e.scrollLeft=e.scrollWidth);
    await page.waitForFunction(width=>document.querySelector('.seq-content').clientWidth>width,width);
  }
  // No replay-time/range check should reject either direction at replay time 12.
  for(const [id,reverse]of [['liveForward',false],['liveReverse',true]]){
    await page.locator('#'+id).click();await page.waitForFunction(()=>!document.querySelector('#liveStop').disabled);
    const live=(await server()).playback;
    assert.equal(live.reverse,reverse);assert.equal(live.timeline_start,0);assert.equal(live.timeline_end,end);assert.equal(live.duration,end);
    await page.locator('#liveStop').click();await page.waitForFunction(()=>!document.querySelector('#liveForward').disabled);
  }
  await page.reload();await page.waitForSelector('.seq-key[data-channel=x]');await enterFixture(page);
  assert.equal(await page.locator('[name=shootingMode][value=camera_only]').isChecked(),true);
  assert.equal(await page.locator('.seq-range').isVisible(),false);
  await page.locator('[data-action=fit]').click();
  await page.locator('.sequence-panel').screenshot({path:path.join(out,'camera-only.png')});
  const overlay=await browser.newPage({viewport:{width:328,height:640}});overlay.on('pageerror',e=>errors.push(e.message));
  await overlay.goto(base+'/overlay?panel=keyframes');await overlay.waitForFunction(()=>!document.querySelector('#liveReverse').disabled);
  assert.equal(await overlay.locator('#miniSpeedGraph').isVisible(),false);
  assert.equal(await overlay.locator('#applyDuration').isVisible(),false);
  await overlay.waitForFunction(()=>!document.querySelector('#miniPreview').disabled);
  await overlay.screenshot({path:path.join(out,'overlay-camera-only.png')});
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({passed:true,scope:'synthetic replay only',duration:end,checks:['exactly two shooting modes','playback-way selector removed','independent mode hides replay bounds and rate track','record at chosen camera time','keys beyond replay duration and one hour','drag beyond previous end and edge autoscroll','indefinite rightward scrolling','playhead stays put','forward and reverse independent playback use 0..last key','mode persistence','overlay hides speed graph and retiming'],errors},null,2));
  console.log('PASS: independent shooting mode, unbounded timeline editing and isolated playback validation (synthetic).');
 }finally{clearTimeout(timeout);await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
