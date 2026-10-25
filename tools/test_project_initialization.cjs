const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const base=process.argv[2];
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  const errors=[],requests=[];
  try{
    const page=await browser.newPage();page.on('pageerror',e=>errors.push(e.message));
    let heldSelect=null,heldPicker=null;
    const source={id:'fixture',sha256:'a'.repeat(64),replay_file:'chosen.wotbreplay',name:'chosen',duration_sec:300,battle_start_status:'identified',battle_start_sec:15.75,replay_origin_sec:4.25};
    await page.route('**/api/preview/select',async route=>{requests.push(route.request().postDataJSON());heldSelect=route;});
    await page.route('**/api/replay/select',route=>{heldPicker=route;});
    await page.route('**/api/preview/replay/*',route=>route.fulfill({body:Buffer.from('fixture')}));
    const ready=()=>page.waitForFunction(()=>state.loaded&&replayPreviewPane&&state.samples.length&&!state.busy);
    const fresh=async name=>{
      await page.evaluate(async name=>{await window.BlitzFlushEditorSession();await api('/api/projects/new',{name});await refreshState(true);},name);
      await page.waitForFunction(()=>state.loaded&&replayPreviewPane&&state.samples.length);
    };
    const empty=async()=>{
      assert.deepEqual(await page.evaluate(()=>({source:replayPreviewPane.source,data:replayPreviewPane.data,
        sampler:replayPreviewPane.sampler,status:replayPreviewPane.status,file:state.timeline?.replay_file||null,
        label:$('previewSourceFile').textContent,disabled:$('retryPreview').disabled})),
        {source:null,data:null,sampler:null,status:'empty',file:null,label:'—',disabled:true});
    };
    await page.goto(base);await ready();await page.evaluate(()=>refreshState());
    await empty();assert.equal(requests.length,0,'A previous launch must not bind the new project');

    // A slow file picker result belongs only to the project that opened it.
    let requested=page.waitForRequest(r=>r.url().endsWith('/api/replay/select'));
    await page.evaluate(()=>{window.pendingSelect=selectProjectReplay();});await requested;
    await page.waitForFunction(()=>$('openReplayButton').disabled);
    await fresh('new-during-picker');
    assert.ok(heldPicker);await heldPicker.fulfill({json:{info:source}});heldPicker=null;
    await page.evaluate(()=>window.pendingSelect);await empty();

    // A late parser result must not repopulate source/data or bind another project.
    requested=page.waitForRequest(r=>r.url().endsWith('/api/preview/select'));
    await page.evaluate(()=>{
      replayPreviewPane.parse=()=>new Promise(resolve=>window.finishParse=resolve);
      const select=replayPreviewPane.select.bind(replayPreviewPane);
      replayPreviewPane.select=(...args)=>(window.pendingSelect=select(...args));
      applyReplayInfo({replay_file:'chosen.wotbreplay',name:'chosen',duration_sec:300,battle_start_status:'identified',battle_start_sec:15.75,replay_origin_sec:4.25});
    });
    await page.waitForFunction(()=>$('retryPreview').disabled);
    await requested;
    assert.ok(heldSelect);await heldSelect.fulfill({json:{source}});heldSelect=null;
    await page.waitForFunction(()=>!!window.finishParse);
    assert.deepEqual(await page.evaluate(()=>sequenceEditor.doc.tracks.x.map(k=>k.time_sec)),[15.75,23.75]);
    assert.deepEqual(await page.evaluate(()=>[state.timeline.work_start_sec,state.timeline.work_end_sec]),[15.75,23.75]);
    await page.evaluate(()=>window.BlitzFlushEditorSession());
    const saved=await (await page.request.get(base+'/api/state')).json();
    assert.deepEqual(saved.project.camera_tracks.x.map(k=>k.time_sec),[15.75,23.75]);
    await fresh('new-during-parse');
    await page.evaluate(async()=>{window.finishParse({stale:true});await window.pendingSelect;});
    await empty();
    const before=requests.length;
    await page.reload();await ready();await page.evaluate(()=>refreshState());
    await empty();assert.equal(requests.length,before,'Reload must not adopt remembered game telemetry');

    // Default keys move once, including seven tracks and their speed range.
    await page.evaluate(()=>{replayPreviewPane.select=async()=>{};});
    assert.equal(await page.evaluate(info=>applyReplayInfo(info),source),true);
    const aligned=await page.evaluate(()=>sequenceEditor.data());
    for(const rows of Object.values(aligned.tracks))assert.deepEqual(rows.map(k=>k.time_sec),[15.75,23.75]);
    assert.deepEqual(aligned.speed.time_range,{start_sec:15.75,end_sec:23.75});
    await page.evaluate(()=>window.BlitzFlushEditorSession());
    await page.evaluate(info=>applyReplayInfo({...info,battle_start_sec:25}),source);
    assert.deepEqual(await page.evaluate(()=>sequenceEditor.doc.tracks.x.map(k=>k.time_sec)),[15.75,23.75]);
    await fresh('edited-defaults');
    await page.evaluate(()=>sequenceEditor.edit(()=>{sequenceEditor.doc.tracks.x[0].value+=2;}));
    assert.equal(await page.evaluate(()=>state.timeline.starter_keyframes_pending||false),false);
    await page.evaluate(info=>applyReplayInfo(info),source);
    assert.deepEqual(await page.evaluate(()=>sequenceEditor.doc.tracks.x.map(k=>k.time_sec)),[0,8]);
    await fresh('short-replay');
    await page.evaluate(info=>applyReplayInfo({...info,battle_start_sec:299.5}),source);
    assert.deepEqual(await page.evaluate(()=>sequenceEditor.doc.tracks.x.map(k=>k.time_sec)),[299.5,300]);
    await page.evaluate(()=>window.BlitzFlushEditorSession());
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({previousReplayIsolated:true,stalePickerCancelled:true,staleParserDiscarded:true,
      defaultKeysAligned:true,allTracksAndSpeedAligned:true,authoredKeysPreserved:true,shortReplayFits:true}));
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
