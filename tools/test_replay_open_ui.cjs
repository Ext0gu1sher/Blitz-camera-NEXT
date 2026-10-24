// Own app, synthetic replay, mocked picker/launcher. Never starts the game.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {enterFixture}=require('./ui_fixture.cjs');
const base=process.argv[2],chosen=process.argv[3],out=path.resolve('output/replay-open-072-acceptance');
fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'}),errors=[];
 try{
  const context=await browser.newContext({viewport:{width:1550,height:1150}});
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base+'/');await page.waitForSelector('.seq-key[data-channel=x]');await enterFixture(page);
  const state=async()=>(await page.request.get(base+'/api/state')).json(),before=await state();
  const keys=before.project.camera_tracks;
  // Preserve an unsaved edit while the backend binds a new replay source.
  await page.locator('.seq-key[data-channel=x]').nth(1).click();
  await page.locator('[data-field=value]').locator('..').locator('.number-value').dblclick();await page.locator('[data-field=value]').fill('77');await page.locator('[data-field=value]').press('Enter');
  await page.locator('#openReplayButton').click();
  await page.waitForFunction(()=>document.querySelector('#openReplayButton').textContent.includes('选择回放中'));
  assert.equal(await page.locator('#openReplayButton').isDisabled(),true);
  await page.waitForFunction(()=>document.querySelector('#openedReplayFile').textContent.includes('307.500'));
  await page.waitForFunction(()=>Number(document.querySelector('#timelineSlider').max)===307.5);
  assert.equal((await state()).replay_launch.state,'launched');
  assert.equal((await state()).replay_launch.verified,false);
  assert.deepEqual((await state()).project.camera_tracks,keys);
  assert.equal((await state()).project.replay_timeline.replay_file,chosen);
  assert.equal(Number(await page.locator('[data-field=value]').inputValue()),77);
  assert.equal(await page.locator('#externalChange').isVisible(),true);
  await page.locator('.connection-panel').screenshot({path:path.join(out,'open-file-workbench.png')});
  // Reload sees the source and full length saved by the launch action.
  await page.reload();await page.waitForSelector('.seq-key[data-channel=x]').catch(async error=>{
    console.error('reload diagnostics',await page.evaluate(()=>({errors:document.getElementById('serviceError')?.textContent,loaded:typeof state!=='undefined'?state.loaded:null,tracks:typeof state!=='undefined'?state.tracks:null,keys:document.querySelectorAll('.seq-key').length,sequence:document.getElementById('sequenceEditor')?.getBoundingClientRect().toJSON()})),errors);
    await page.screenshot({path:path.join(out,'reload-failure.png')});throw error;
  });
  await enterFixture(page);
  assert.equal(Number(await page.locator('#timelineSlider').getAttribute('max')),307.5);
  // Native-sized connection strip: launch button and source line fit its viewport.
  const native=await browser.newContext({viewport:{width:830,height:66}});
  await native.addInitScript(()=>{window.chrome.webview={postMessage:()=>{},addEventListener:()=>{}};});
  const top=await native.newPage();top.on('pageerror',e=>errors.push(e.message));
  await top.goto(base+'/overlay?panel=connection');
  await top.waitForFunction(()=>document.querySelector('#statusLine').textContent.includes('电影 A & B'));
  const layout=await top.evaluate(()=>{const b=document.querySelector('#openReplay').getBoundingClientRect(),footer=document.querySelector('#statusLine').getBoundingClientRect();return{left:b.left,right:b.right,bottom:footer.bottom,width:innerWidth,height:innerHeight,scrollWidth:document.documentElement.scrollWidth};});
  assert.ok(layout.left>=0&&layout.right<=layout.width,JSON.stringify(layout));
  assert.ok(layout.bottom<=layout.height,JSON.stringify(layout));
  assert.ok(layout.scrollWidth<=layout.width,JSON.stringify(layout));
  await top.screenshot({path:path.join(out,'open-file-overlay.png'),omitBackground:true});
  // A bound project launches its replay file straight from the floating bar.
  const openedInfo=(await state()).replay_launch.info;
  const after=(await state()).project;
  await top.waitForFunction(()=>document.querySelector('#openReplay').textContent==='启动回放');
  assert.match(await top.locator('#openReplay').getAttribute('title'),/启动已绑定回放/);
  await top.route('**/api/replay/open',route=>route.fulfill({json:{ok:true}}));
  const launchReq=top.waitForRequest('**/api/replay/open');
  await top.locator('#openReplay').click();
  assert.deepEqual((await launchReq).postDataJSON(),{path:chosen});
  // Without a bound file the same button falls back to the picker request.
  const unboundState=await state();delete unboundState.project.replay_timeline;
  const unbound=await native.newPage();unbound.on('pageerror',e=>errors.push(e.message));
  await unbound.route('**/api/state',route=>route.fulfill({json:unboundState}));
  await unbound.route('**/api/replay/open',route=>route.fulfill({json:{ok:true}}));
  await unbound.goto(base+'/overlay?panel=connection');
  await unbound.waitForFunction(()=>document.querySelector('#openReplay').textContent==='选择回放…');
  assert.equal(await unbound.locator('#openReplay').getAttribute('title'),'当前项目未绑定回放，选择回放文件');
  const pickReq=unbound.waitForRequest('**/api/replay/open');
  await unbound.locator('#openReplay').click();
  assert.deepEqual((await pickReq).postDataJSON(),{});
  // Experimental seek: the right panel posts mode:'locate' like the workbench.
  const liveState=await state();
  liveState.connection={state:'connected',message:'测试连接'};
  liveState.sample={camera:{position:[0,0,20],quaternion:[1,0,0,0],yaw_deg:0,pitch_deg:0,roll_deg:0,horizontal_fov_deg:60},replay:{time:12,paused:true,rate:1}};
  const right=await native.newPage();right.on('pageerror',e=>errors.push(e.message));
  await right.route('**/api/state',route=>route.fulfill({json:liveState}));
  await right.route('**/api/playback/start',route=>route.fulfill({json:{ok:true}}));
  await right.goto(base+'/overlay?panel=keyframes');
  await right.waitForFunction(()=>typeof model!=='undefined'&&model.ready&&!document.getElementById('liveSeekStart').hidden&&!document.getElementById('liveSeekStart').disabled);
  const seekReq=right.waitForRequest('**/api/playback/start');
  await right.locator('#liveSeekStart').click();
  const seekBody=(await seekReq).postDataJSON();
  assert.equal(seekBody.mode,'locate');assert.equal(seekBody.reverse,false);
  assert.equal(seekBody.orientation_enabled,true);assert.equal(seekBody.fov_enabled,true);
  // Hidden for camera-only projects; disabled while the replay is not paused.
  const freeState=JSON.parse(JSON.stringify(liveState));freeState.project.shooting_mode='camera_only';
  const freePage=await native.newPage();freePage.on('pageerror',e=>errors.push(e.message));
  await freePage.route('**/api/state',route=>route.fulfill({json:freeState}));
  await freePage.goto(base+'/overlay?panel=keyframes');
  await freePage.waitForFunction(()=>typeof model!=='undefined'&&model.ready);
  assert.equal(await freePage.evaluate(()=>document.getElementById('liveSeekStart').hidden),true);
  const playingState=JSON.parse(JSON.stringify(liveState));playingState.sample.replay.paused=false;
  const playing=await native.newPage();playing.on('pageerror',e=>errors.push(e.message));
  await playing.route('**/api/state',route=>route.fulfill({json:playingState}));
  await playing.goto(base+'/overlay?panel=keyframes');
  await playing.waitForFunction(()=>typeof model!=='undefined'&&model.ready);
  assert.equal(await playing.evaluate(()=>{const b=document.getElementById('liveSeekStart');return !b.hidden&&b.disabled;}),true);
  // The workbench picker's cancel remains non-destructive.
  await page.locator('#openReplayButton').click();
  for(let i=0;i<60&&(await state()).replay_launch.state!=='cancelled';i++)await page.waitForTimeout(100);
  assert.equal((await state()).replay_launch.state,'cancelled');
  assert.deepEqual((await state()).project,after);
  assert.equal((await state()).playback.active,false);
  // A service restart has no in-memory launch ticket; still show the source
  // actually read from the running game's arguments, without a false mismatch.
  const restored={...await state(),replay_launch:{state:'idle',message:'选择回放'},replay_info:{...openedInfo,source:'launch_argument'}};
  const reconnected=await context.newPage();reconnected.on('pageerror',e=>errors.push(e.message));
  await reconnected.route('**/api/state',route=>route.fulfill({json:restored}));
  await reconnected.goto(base+'/');
  await reconnected.waitForFunction(()=>document.querySelector('#openedReplayFile').textContent.includes('电影 A & B'));
  assert.match(await reconnected.locator('#replayLaunchMessage').innerText(),/已读取回放启动信息/);
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({passed:true,layout,source:chosen,errors},null,2));
  console.log('Replay open UI acceptance passed.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
