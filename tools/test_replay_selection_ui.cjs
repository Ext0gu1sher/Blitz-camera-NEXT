const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.argv[2],out=path.resolve('output/replay-selection-acceptance');
fs.mkdirSync(out,{recursive:true});
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],previews=[],launches=[];
  page.on('pageerror',e=>errors.push(e.message));
  const first={replay_file:'C:\\回放\\第一场.wotbreplay',name:'第一场.wotbreplay',duration_sec:100,replay_sha256:'a'.repeat(64)},
    second={...first,replay_file:'D:\\回放\\第二场.wotbreplay',name:'第二场.wotbreplay',replay_sha256:'b'.repeat(64)};
  let selected=first,heldPicker=null,holdPicker=false,previewFails=true,pickerCalls=0;
  await page.route('**/api/replay/select',route=>{
    pickerCalls++;
    if(holdPicker){heldPicker=route;return;}
    return route.fulfill({json:selected?{info:selected}:{cancelled:true}});
  });
  await page.route('**/api/preview/select',route=>{
    const data=route.request().postDataJSON();previews.push(data);
    return previewFails?route.fulfill({status:400,json:{error:'测试预览加载失败'}}):
      route.fulfill({json:{source:{...selected,id:'fixture',sha256:selected.replay_sha256}}});
  });
  await page.route('**/api/preview/replay/*',route=>route.fulfill({status:400,json:{error:'测试停止解析'}}));
  await page.route('**/api/replay/open',()=>{throw Error('Selecting a file must not launch the game');});
  await page.route('**/api/replay/open_project',async route=>{
    const saved=await (await page.request.get(base+'/api/state')).json();launches.push(saved.project.replay_timeline.replay_file);
    await route.fulfill({json:{ok:true}});
  });
  const idle=()=>page.waitForFunction(()=>state.loaded&&!state.busy&&replayPreviewPane?.status!=='loading');
  try{
    await page.goto(base);await page.waitForFunction(()=>document.body.dataset.appReady==='true'&&state.loaded&&replayPreviewPane);
    assert.equal(await page.locator('#loadPreviewReplay').count(),0);
    assert.equal(await page.locator('#retryPreview').isDisabled(),true);
    assert.equal(await page.locator('#playProjectReplay').isDisabled(),true);
    assert.match(await page.locator('#previewEmpty').textContent(),/载入回放/);
    assert.equal(await page.locator('#previewEmpty').getAttribute('aria-disabled'),'false');
    assert.equal(await page.locator('#previewEmpty').getAttribute('tabindex'),'0');
    await page.locator('#replayScene').screenshot({path:path.join(out,'empty-preview.png')});
    // The empty scene shares the top chooser, including cancellation and busy guards.
    holdPicker=true;await page.locator('#previewEmpty').click();await page.waitForFunction(()=>state.selectingReplay);
    assert.equal(await page.locator('#openReplayButton').isDisabled(),true);
    assert.equal(await page.locator('#previewEmpty').getAttribute('aria-disabled'),'true');
    await page.locator('#previewEmpty').dispatchEvent('click');
    await heldPicker.fulfill({json:{cancelled:true}});heldPicker=null;holdPicker=false;await idle();
    assert.equal(pickerCalls,1);assert.equal(previews.length,0);
    assert.equal(await page.evaluate(()=>state.timeline.replay_file||null),null);
    assert.equal(await page.locator('#previewEmpty').getAttribute('aria-disabled'),'false');
    // Keyboard activation works after a cancelled picker as well.
    selected=null;
    for(const key of ['Enter','Space']){
      const called=pickerCalls;await page.locator('#previewEmpty').focus();await page.keyboard.press(key);
      await idle();assert.equal(pickerCalls,called+1);assert.equal(previews.length,0);
    }
    selected=first;
    const before=await page.evaluate(()=>({tracks:structuredClone(state.tracks),speed:structuredClone(sequenceEditor.doc.speed)}));

    // The chooser is independent of preview parsing and leaves authored keys intact.
    await page.locator('#previewEmpty').click();await idle();
    assert.equal(await page.evaluate(()=>state.timeline.replay_file),first.replay_file);
    assert.deepEqual(previews,[{path:first.replay_file}]);assert.deepEqual(launches,[]);
    assert.equal(await page.locator('#previewFile').textContent(),first.name);
    assert.equal(await page.locator('#openReplayButton').getAttribute('aria-label'),'更换回放文件…');
    assert.equal(await page.locator('#retryPreview').isDisabled(),false);
    assert.deepEqual(await page.evaluate(()=>({tracks:state.tracks,speed:sequenceEditor.doc.speed})),before);

    // Cancel keeps the binding and preview intact, even while the picker is pending.
    holdPicker=true;await page.locator('#openReplayButton').click();await page.waitForFunction(()=>state.selectingReplay);
    assert.equal(await page.locator('#playProjectReplay').isDisabled(),true);
    assert.equal(await page.locator('#retryPreview').isDisabled(),true);
    await heldPicker.fulfill({json:{cancelled:true}});heldPicker=null;holdPicker=false;await idle();
    assert.equal(await page.evaluate(()=>state.timeline.replay_file),first.replay_file);assert.equal(previews.length,1);

    // After a failed replacement, reload must target the new binding, never the old source or a picker.
    selected=second;await page.locator('#openReplayButton').click();await idle();
    assert.equal(await page.locator('#previewFile').textContent(),second.name);
    assert.deepEqual(previews.at(-1),{path:second.replay_file});
    previewFails=false;await page.locator('#retryPreview').click();await idle();
    assert.deepEqual(previews.at(-1),{path:second.replay_file});
    assert.equal(await page.evaluate(()=>replayPreviewPane.source.replay_file),second.replay_file);
    const count=previews.length;await page.locator('#previewEmpty').focus();await page.keyboard.press('Enter');await idle();
    assert.equal(previews.length,count+1);assert.deepEqual(previews.at(-1),{path:second.replay_file});

    // Immediate launch saves a fresh selection before the server opens the project replay.
    selected=first;await page.locator('#openReplayButton').click();await idle();
    await page.locator('#playProjectReplay').click();await idle();assert.deepEqual(launches,[first.replay_file]);
    assert.equal(await page.evaluate(()=>state.dirty),false);
    await page.locator('#titlebar').screenshot({path:path.join(out,'toolbar.png')});
    await page.locator('#replayPreviewControls').screenshot({path:path.join(out,'preview-controls.png')});

    // Camera-only projects can select and launch a replay without moving independent camera keys.
    await page.locator('[name=shootingMode][value=camera_only]').check();
    const cameraBefore=await page.evaluate(()=>structuredClone(state.tracks)),previewCount=previews.length;
    selected=second;await page.locator('#openReplayButton').click();await idle();
    assert.equal(await page.evaluate(()=>state.timeline.replay_file),second.replay_file);
    assert.deepEqual(await page.evaluate(()=>state.tracks),cameraBefore);assert.equal(previews.length,previewCount);
    await page.locator('#playProjectReplay').click();await idle();assert.deepEqual(launches,[first.replay_file,second.replay_file]);
    await page.locator('[name=shootingMode][value=replay]').check();await idle();
    assert.deepEqual(previews.at(-1),{path:second.replay_file});
    assert.deepEqual(errors,[]);
    console.log('PASS: empty preview click/keyboard selection, cancellation and busy guards, unified selection, automatic preview, reload of current file, save before launch, both modes; no game launched.');
  }catch(error){await page.screenshot({path:path.join(out,'failure.png')});console.error(errors);throw error;}
  finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
