// Headless synthetic fixture: no desktop automation or real game access.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {enterFixture}=require('./ui_fixture.cjs');
const base=process.argv[2],out=path.resolve('output/timeline-074-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const errors=[];
 try{
  const page=await browser.newPage({viewport:{width:1550,height:1150}});page.on('pageerror',e=>errors.push(e.message));
  const server=async()=>(await page.request.get(base+'/api/state')).json();
  const save=async()=>{await page.locator('#saveButton').click();await page.waitForFunction(()=>document.querySelector('#savedLabel').textContent==='已保存');};
  await page.goto(base+'/');await page.waitForSelector('.seq-key[data-channel=x]');await enterFixture(page);
  await page.locator('[data-action=workfit]').click();
  await page.locator('#timelineSlider').evaluate(e=>{e.value=14.5;e.dispatchEvent(new Event('input'));});
  const head=await page.locator('.seq-head').getAttribute('style');
  const before=(await server()).project;
  await page.locator('.seq-key[data-channel=zoom]').nth(1).click();
  assert.equal(Number(await page.locator('#timelineSlider').inputValue()),14.5);
  assert.equal(await page.locator('.seq-head').getAttribute('style'),head);
  const box=await page.locator('.seq-key[data-channel=zoom]').nth(1).boundingBox();
  await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();
  await page.mouse.move(box.x+box.width/2+24,box.y+box.height/2,{steps:4});await page.mouse.up();
  await page.waitForTimeout(350);
  assert.equal(Number(await page.locator('#timelineSlider').inputValue()),14.5);
  assert.equal(await page.locator('.seq-head').getAttribute('style'),head);
  const channels=['x','y','z','yaw','pitch','roll','zoom'];
  const clickTrack=async(channel,time)=>{
    await page.locator('.seq-scroll').scrollIntoViewIfNeeded();
    const rect=await page.locator('.seq-scroll').boundingBox();
    const ends=await page.locator('.seq-key[data-channel=x]').evaluateAll(rows=>[rows[0],rows.at(-1)].map(e=>{const r=e.getBoundingClientRect();return r.x+r.width/2;}));
    const x=ends[0]+(time-12)/12*(ends[1]-ends[0]);
    const y=channel==='rate'
      ? await page.locator('.seq-scroll').evaluate(el=>{el.scrollTop=Math.max(0,Math.min(259,el.scrollHeight-el.clientHeight));return el.getBoundingClientRect().y+259-el.scrollTop;})
      : rect.y+40+channels.indexOf(channel)*24+12;
    await page.keyboard.down('Control');await page.mouse.click(x,y);await page.keyboard.up('Control');
  };
  for(const channel of channels){
    const count=await page.locator(`.seq-key[data-channel=${channel}]`).count();
    await clickTrack(channel,18.5);
    await page.waitForFunction(({channel,count})=>document.querySelectorAll(`.seq-key[data-channel=${channel}]`).length===count+1,{channel,count});
    assert.equal(Number(await page.locator('[data-field=time]').inputValue()),18.5);
    assert.equal(Number(await page.locator('#timelineSlider').inputValue()),14.5);
    assert.equal(await page.locator('.seq-head').getAttribute('style'),head);
  }
  assert.deepEqual((await server()).project,before,'Ctrl-click edits a draft only');
  await save();const recorded=(await server()).project;
  for(const channel of channels)assert.ok(recorded.camera_tracks[channel].some(k=>k.time_sec===18.5));
  await page.locator('#tabSpeed').click();await page.locator('#timelineSpeedPreset').click();await save();
  const curved=(await server()).project;
  // Ctrl-click rate also keeps the replay timestamp despite changing its integral.
  await clickTrack('rate',18.5);
  await page.waitForFunction(()=>document.querySelectorAll('.seq-key[data-channel=rate]').length===5);
  assert.ok(Math.abs(Number(await page.locator('[data-field=time]').inputValue())-18.5)<1e-5);
  await page.locator('[data-action=undo]').click();
  assert.equal(await page.locator('.seq-key[data-channel=rate]').count(),4);
  await page.locator('#resetReplaySpeed').click();
  assert.equal(await page.locator('#replayFixedRate').inputValue(),'1');
  await save();let reset=(await server()).project;
  assert.deepEqual(reset.replay_speed,{mode:'fixed',rate:1,camera_clock:'replay',interpolation:'smooth',keyframes:[{progress:0,rate:1},{progress:1,rate:1}]});
  assert.deepEqual(reset.camera_tracks,curved.camera_tracks);assert.deepEqual(reset.replay_timeline,curved.replay_timeline);
  await page.locator('[data-action=undo]').click();await save();assert.deepEqual((await server()).project.replay_speed,curved.replay_speed);
  await page.locator('[data-action=redo]').click();await save();
  await page.reload();await page.waitForSelector('.seq-key[data-channel=x]');await enterFixture(page);assert.equal(await page.locator('#replayFixedRate').inputValue(),'1');
  await page.locator('[data-action=workfit]').click();
  // Near-coincident keys stay intact and get a visible warning.
  await page.locator('.seq-key[data-channel=x]').nth(1).click();
  await page.locator('[data-field=time]').locator('..').locator('.number-value').dblclick();await page.locator('[data-field=time]').fill('12.022');await page.locator('[data-field=time]').press('Enter');
  await page.waitForFunction(()=>!document.querySelector('[data-key-warning]').hidden);
  assert.match(await page.locator('[data-key-warning]').textContent(),/12\.000000.*12\.022000.*0\.022000/);
  await page.locator('.sequence-panel').screenshot({path:path.join(out,'timeline-interactions.png')});
  await page.locator('[data-action=undo]').click();assert.equal(await page.locator('[data-key-warning]').isVisible(),false);
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({passed:true,scope:'synthetic fixture only',checks:['Ctrl-click all seven camera tracks at clicked time','rate Ctrl-click anchored after integral changes','selection and dragging do not seek playhead','default speed 1x clears intermediate rate keys','reset undo redo and persistence','camera tracks and work area preserved','near-key warning does not merge keys'],errors},null,2));
  console.log('PASS: Ctrl-click property and rate keys, stationary playhead, speed reset and near-key warning (synthetic).');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
