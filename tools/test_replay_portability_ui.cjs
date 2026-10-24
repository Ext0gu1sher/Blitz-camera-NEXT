const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],opens=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/preview/select',r=>r.fulfill({status:400,json:{error:'测试环境跳过地图预览。'}}));
  await page.route('**/api/replay/open_project',r=>{opens.push(r.request().postDataJSON());return r.fulfill({json:{ok:true}});});
  await page.route('**/api/replay/open',()=>{throw Error('Project replay bypassed portable relinking');});
  const ready=()=>page.waitForFunction(()=>document.body.dataset.appReady==='true'&&state.loaded&&sequenceEditor?.doc&&!pendingEditorRestore);
  try{
    await page.goto(process.argv[2]);await ready();
    const before=await page.evaluate(()=>({tracks:structuredClone(state.tracks),speed:structuredClone(sequenceEditor.doc.speed)}));
    await page.evaluate(()=>applyReplayInfo({duration_sec:100,replay_file:'C:\\Old PC\\shot.wotbreplay',replay_sha256:'a'.repeat(64),name:'shot.wotbreplay'}));
    await page.waitForFunction(()=>!state.dirty&&state.timeline.replay_sha256==='a'.repeat(64));
    await page.evaluate(()=>applyReplayInfo({duration_sec:100,replay_file:'D:\\新电脑\\renamed.wotbreplay',sha256:'b'.repeat(64),name:'renamed.wotbreplay'}));
    await page.waitForFunction(()=>!state.dirty&&state.timeline.replay_sha256==='b'.repeat(64));
    await page.keyboard.press('Control+z');
    await page.waitForFunction(()=>!state.dirty&&state.timeline.replay_sha256==='a'.repeat(64));
    await page.keyboard.press('Control+Shift+z');
    await page.waitForFunction(()=>!state.dirty&&state.timeline.replay_sha256==='b'.repeat(64));
    const saved=await page.evaluate(async()=>({
      project:await (await fetch('/api/export')).json(),
      tracks:state.tracks,speed:sequenceEditor.doc.speed
    }));
    assert.equal(saved.project.replay_timeline.replay_sha256,'b'.repeat(64));
    assert.equal(saved.project.replay_timeline.replay_file,'D:\\新电脑\\renamed.wotbreplay');
    assert.deepEqual(saved.tracks,before.tracks);assert.deepEqual(saved.speed,before.speed);
    await page.locator('#playProjectReplay').click();
    await page.waitForFunction(()=>!state.busy);assert.deepEqual(opens,[{}]);
    await page.reload();await page.locator('#startupContinue').click();await ready();
    assert.equal(await page.evaluate(()=>state.timeline.replay_sha256),'b'.repeat(64));
    assert.deepEqual(errors,[]);
    console.log('PASS: replay identity persists through UI save, undo/redo and reload; project replay uses relinking.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
