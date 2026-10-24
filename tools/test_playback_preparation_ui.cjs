const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const out=path.resolve('output/playback-preparation-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],starts=[];
  const base=process.argv[2];let connected=false,paused=true,gameTime=12,playback={state:'idle',active:false};
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/state',async r=>{
    const data=await (await r.fetch()).json();
    data.connection={state:connected?'connected':'disconnected'};data.playback=playback;
    data.sample=connected?{replay:{time:gameTime,paused,rate:1},camera:{position:[12,0,10],yaw_deg:0,pitch_deg:0,roll_deg:0,horizontal_fov_deg:60},quality:{}}:null;
    await r.fulfill({json:data});
  });
  await page.route('**/api/playback/start',async r=>{
    starts.push(r.request().postDataJSON());
    playback={active:true,state:'seeking_replay',preparing_replay:true,current_time:12,target_time:10,
      message:'正在实验性跳转到入点 10.000 秒…'};
    await r.fulfill({json:{ok:true}});
  });
  await page.route('**/api/playback/stop',async r=>{playback={state:'stopped',active:false};await r.fulfill({json:{ok:true}});});
  await page.route('**/api/preview/select',r=>r.fulfill({json:{cancelled:true}}));
  const wait=fn=>page.waitForFunction(fn);
  try{
    await page.goto(base);await wait(()=>state.loaded&&sequenceEditor);
    const locate=page.locator('[data-action=locate]');
    assert.equal(await locate.isDisabled(),true);
    connected=true;await wait(()=>!document.querySelector('[data-action=locate]').disabled);
    assert.equal(await page.locator('#liveControls [data-action=locate]').count(),1);
    assert.equal(await page.locator('.seq-range [data-action=locate]').count(),0);
    assert.equal(await page.locator('#liveDuration, #retimeButton').count(),0);
    assert.equal(await page.locator('#liveContinue').count(),0);
    assert.ok(!(await page.locator('#liveControls').textContent()).includes('工作区间'));
    const original=await page.evaluate(()=>({tracks:structuredClone(state.tracks),timeline:structuredClone(state.timeline)}));
    const retainedButtons=await page.locator('.seq-range button').evaluateAll(es=>es.map(e=>[e.dataset.action,e.querySelector('use').getAttribute('href'),e.title]));
    assert.deepEqual(retainedButtons.map(e=>e.slice(0,2)),[['inpoint','#i-inpoint'],['follow','#i-clock']]);
    assert.equal(await page.locator('.seq-range input, [data-action=range], [data-action=align]').count(),0);
    const sizes=await page.locator('.seq-range .ic').evaluateAll(es=>es.map(e=>[e.getBoundingClientRect().width,e.getBoundingClientRect().height]));
    assert.ok(sizes.every(s=>s[0]===13&&s[1]===13));
    // Retained buttons use the game clock; I/O still uses the editor playhead.
    await page.evaluate(()=>seek(16));await page.locator('[data-action=follow]').click();
    assert.equal(await page.evaluate(()=>state.previewTime),12);assert.equal(starts.length,0);
    await page.evaluate(()=>seek(16));await page.locator('[data-action=inpoint]').click();
    assert.equal(await page.evaluate(()=>state.timeline.work_start_sec),12);
    await page.keyboard.press('Control+z');
    await page.evaluate(()=>seek(11));await page.locator('.seq-scroll').focus();await page.keyboard.press('i');
    await page.evaluate(()=>seek(17));await page.locator('.seq-scroll').focus();await page.keyboard.press('o');
    assert.deepEqual(await page.evaluate(()=>[state.timeline.work_start_sec,state.timeline.work_end_sec]),[11,17]);
    await page.keyboard.press('Control+z');await page.keyboard.press('Control+z');
    assert.deepEqual(await page.evaluate(()=>({tracks:state.tracks,timeline:state.timeline})),original);
    await page.keyboard.press('Shift+i');assert.equal(await page.evaluate(()=>state.previewTime),10);
    await page.keyboard.press('Shift+o');assert.equal(await page.evaluate(()=>state.previewTime),18);
    await page.evaluate(()=>seek(16)); // Locator must ignore the editor playhead.
    await locate.click();await wait(()=>!state.busy&&state.playback.active);
    assert.equal(starts.at(-1).mode,'locate');
    assert.equal(await locate.isDisabled(),true);
    assert.equal(await page.locator('#liveBadge').textContent(),'实验跳转中');
    assert.equal(await page.locator('#liveStop').isDisabled(),false);
    await page.screenshot({path:path.join(out,'waiting.png')});
    await page.keyboard.press('Escape');await wait(()=>!state.playback.active);
    assert.equal(await page.locator('#liveForward').getAttribute('title'),'从当前游戏时刻播放至出点');
    await page.locator('#liveForward').click();await wait(()=>!state.busy&&state.playback.active);
    assert.equal(starts.at(-1).mode,'auto');
    await page.locator('#liveStop').click();await wait(()=>!state.playback.active);
    gameTime=17.5;await wait(()=>state.sample.replay.time===17.5);
    assert.equal(await page.locator('#liveForward').getAttribute('title'),'从当前游戏时刻播放至出点');
    await page.locator('#liveForward').click();await wait(()=>!state.busy&&state.playback.active);
    assert.equal(starts.at(-1).mode,'auto');
    await page.locator('#liveStop').click();await wait(()=>!state.playback.active);
    gameTime=17.8;await wait(()=>state.sample.replay.time===17.8);
    assert.equal(await page.locator('#liveForward').getAttribute('title'),'距离出点不足 0.5 秒，剩余区间太短');
    gameTime=8;await wait(()=>state.sample.replay.time===8);
    assert.equal(await page.locator('#liveForward').getAttribute('title'),'准备入点并播放');
    await page.locator('#liveForward').click();await wait(()=>!state.busy&&state.playback.active);
    assert.equal(starts.at(-1).mode,'auto');
    await page.locator('#liveStop').click();await wait(()=>!state.playback.active);
    assert.deepEqual(await page.evaluate(()=>({tracks:state.tracks,timeline:state.timeline})),original);
    paused=false;await wait(()=>state.sample.replay.paused===false);
    assert.equal(await page.locator('#liveForward').getAttribute('title'),'等待游戏暂停后播放');
    assert.equal(await page.locator('#liveForward').isDisabled(),false);
    assert.equal(await locate.isDisabled(),true);
    gameTime=18;paused=true;await wait(()=>state.sample.replay.time===18&&state.sample.replay.paused);
    assert.equal(await page.locator('#liveForward').getAttribute('title'),'已到出点，请先跳转到入点');
    gameTime=12;
    // A modified in-point is saved before preparing, with the new revision.
    paused=true;await wait(()=>!document.querySelector('[data-action=locate]').disabled);await page.evaluate(()=>sequenceEditor.edit(()=>sequenceEditor.doc.timeline.work_start_sec=11));
    await locate.click();await wait(()=>!state.busy&&state.playback.active);
    const saved=await (await page.request.get(base+'/api/state')).json();
    assert.equal(saved.project.replay_timeline.work_start_sec,11);
    assert.equal(starts.at(-1).expected_revision,saved.project_revision);
    await page.locator('#liveStop').click();await wait(()=>!state.playback.active);
    playback={state:'completed',active:false,experimental_seek:true,target_time:11,replay_time:11.08,run_path:'isolated-seek-1'};
    await wait(()=>state.appliedSeekId==='isolated-seek-1'&&state.previewTime===11);
    await page.evaluate(()=>seek(15));await page.waitForTimeout(600);
    assert.equal(await page.evaluate(()=>state.previewTime),15); // Subsequent polls must not reset the playhead.
    assert.deepEqual(await page.locator('.seq-range button').evaluateAll(es=>es.map(e=>[e.dataset.action,e.querySelector('use').getAttribute('href'),e.title])),retainedButtons);
    // Polling may skip the last playing frame. Completion still reaches the
    // exact endpoint once; subsequent polls must leave manual scrubbing alone.
    playback={state:'playing',active:true,run_path:'isolated-completion',timeline_start:12,timeline_end:18,progress:.75,replay_controlled:true};
    await wait(()=>state.previewTime===16.5);
    playback={...playback,state:'completed',active:false,progress:1,message:'播放完成，镜头已交还手动控制。'};
    await wait(()=>state.previewTime===18);await page.evaluate(()=>seek(15));await page.waitForTimeout(650);assert.equal(await page.evaluate(()=>state.previewTime),15);
    playback={state:'playing',active:true,run_path:'isolated-reverse',timeline_start:0,timeline_end:18,progress:.5,reverse:true};await wait(()=>state.previewTime===9);
    playback={...playback,state:'completed',active:false,progress:1};await wait(()=>state.previewTime===0);
    playback={state:'playing',active:true,run_path:'isolated-stop',timeline_start:12,timeline_end:18,progress:.25};await wait(()=>state.previewTime===13.5);
    playback={...playback,state:'stopped',active:false,progress:.3,timeline_position:13.875,message:'已停止'};await wait(()=>state.previewTime===13.875);
    playback={state:'playing',active:true,run_path:'isolated-error',timeline_start:12,timeline_end:18,progress:.25,replay_controlled:true};await wait(()=>state.previewTime===13.5);
    playback={...playback,state:'error',active:false,progress:.25,timeline_position:13.51,actual_replay_time:13.527,native_error:27,message:'检测到其他播放速度或暂停控制'};
    await wait(()=>state.previewTime===13.51&&document.getElementById('liveBadge').textContent==='播放中断');
    assert.match(await page.locator('#toast').textContent(),/播放中断.*13\.527.*出点 18\.000.*暂停控制/);assert.equal(await page.locator('#toast').isVisible(),true);assert.equal(await page.locator('#liveBadge').getAttribute('class').then(c=>c.includes('error')),true);
    await page.screenshot({path:path.join(out,'interrupted.png')});await page.evaluate(()=>{document.getElementById('toast').hidden=true;seek(15);});await page.waitForTimeout(650);assert.equal(await page.locator('#toast').isVisible(),false);assert.equal(await page.evaluate(()=>state.previewTime),15);
    await page.evaluate(()=>BlitzFlushEditorSession());await page.reload();await wait(()=>document.body.dataset.appReady==='true'&&state.loaded&&!pendingEditorRestore);assert.equal(await page.evaluate(()=>state.previewTime),15);assert.equal(await page.locator('#toast').isVisible(),false);
    await page.locator('[name=shootingMode][value=camera_only]').check();
    assert.equal(await page.locator('#liveContinue').count(),0);
    assert.equal(await locate.isVisible(),false);
    await page.locator('#liveForward').click();await wait(()=>!state.busy&&state.playback.active);
    assert.equal(starts.at(-1).mode,'current');
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({passed:true,requests:starts.map(s=>s.mode),retainedIconsPreserved:true,rangeFieldsRemoved:true,inpointAndFollowUseGameClock:true,keyboardInOut:true,iconSize:13,escCancels:true,draftSavedBeforePreparation:true,completionReachesOutpoint:true,reverseCompletionReachesStart:true,terminalSyncOnce:true,interruptionShowsTimeAndReason:true,errorNotificationOnce:true,reloadPreservesPlayhead:true,errors},null,2));
    console.log('PASS two retained game-clock buttons, removed range fields and actions, I/O shortcuts, merged main play, experimental seek, persistence and cancellation');
  }catch(e){await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});console.error(errors);throw e;}
  finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
