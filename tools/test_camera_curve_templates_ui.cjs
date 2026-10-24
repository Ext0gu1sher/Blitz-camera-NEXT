// Synthetic project only. Does not launch, connect to, or control the game.
const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const out=path.resolve('output/camera-auto-curve-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  const page=await browser.newPage({viewport:{width:1500,height:1100}}),errors=[],gameRequests=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(/\/api\/(connect|playback\/start|replay\/open)$/.test(r.url()))gameRequests.push(r.url());});
  const data=()=>page.evaluate(()=>sequenceEditor.data());
  const history=()=>page.evaluate(()=>sequenceEditor.undoStack.length);
  const undo=()=>page.keyboard.press('Control+z'),redo=()=>page.keyboard.press('Control+Shift+z');
  const preset=name=>page.locator('#easePresets').getByRole('button',{name,exact:true});
  const selectAll=()=>page.evaluate(()=>{sequenceEditor.selected=new Set(Object.values(sequenceEditor.doc.tracks).flat().map(k=>k._id));sequenceEditor.render();});
  try{
    await page.goto(process.argv[2]);await page.waitForFunction(()=>state.loaded&&sequenceEditor?.doc&&curveMath);
    await page.locator('#tabCurve').click();await selectAll();
    const original=await data(),count=await history();
    await preset('缓入缓出').click();
    let applied=await data();
    for(const [name,rows]of Object.entries(applied.tracks)){
      assert.deepEqual(rows.map(k=>[k.time_sec,k.value]),original.tracks[name].map(k=>[k.time_sec,k.value]));
      assert.ok(rows.slice(0,-1).every(k=>k.curve==='auto'&&JSON.stringify(k.ease)==='[0.42,0,0.58,1]'));
      assert.equal(rows.at(-1).curve,undefined);
    }
    assert.equal(await history(),count+1,'one template = one undo step');
    assert.deepEqual(applied.speed,original.speed);assert.deepEqual(applied.timeline,original.timeline);
    const velocity=await page.evaluate(()=>{const f=curveMath.scalarTrack(sequenceEditor.data().tracks.x,false,'ease_in_out'),e=.001;return[(f(20)-f(20-e))/e,(f(20+e)-f(20))/e];});
    assert.ok(velocity.every(v=>Math.abs(v-1)<.003),'interior key must not stop');
    assert.equal(await page.locator('#easeGraph .ez-template').count(),1);
    assert.match(await page.locator('#easeCurveInfo').textContent(),/X 10\.00–20\.00/);
    await undo();assert.deepEqual(await data(),original);await redo();assert.deepEqual(await data(),applied);
    // Repeated template clicks do not manufacture duplicate history entries.
    const repeatCount=await history();await preset('缓入缓出').dblclick();assert.equal(await history(),repeatCount);
    await preset('自动衔接').click();const automatic=await data();
    assert.ok(Object.values(automatic.tracks).every(rows=>rows.slice(0,-1).every(k=>k.curve==='auto'&&!k.ease)));
    await undo();assert.deepEqual(await data(),applied);await redo();assert.deepEqual(await data(),automatic);
    // An explicit opt-out restores independent segment easing and is undoable.
    await page.locator('#easeContinuous').uncheck();await preset('缓入缓出').click();
    const stopped=await data();assert.ok(Object.values(stopped.tracks).every(rows=>rows.every(k=>!k.curve)));
    await page.locator('#easeContinuous').check();await undo();assert.deepEqual(await data(),stopped);
    await redo();
    // Handle drags use the main thread's numeric transaction: one undo, Escape cancels.
    const beforeDrag=await data(),dragHistory=await history();
    const handle=await page.locator('#easeGraph [data-h="0"]').boundingBox();
    await page.mouse.move(handle.x+handle.width/2,handle.y+handle.height/2);await page.mouse.down();
    await page.mouse.move(handle.x+handle.width/2+13,handle.y+handle.height/2-20,{steps:6});await page.mouse.up();
    const dragged=await data();assert.notDeepEqual(dragged,beforeDrag);assert.equal(await history(),dragHistory+1);
    await undo();assert.deepEqual(await data(),beforeDrag);await redo();assert.deepEqual(await data(),dragged);
    const handle2=await page.locator('#easeGraph [data-h="1"]').boundingBox();
    await page.mouse.move(handle2.x+handle2.width/2,handle2.y+handle2.height/2);await page.mouse.down();
    await page.mouse.move(handle2.x-12,handle2.y+15,{steps:4});await page.keyboard.press('Escape');await page.mouse.up();
    assert.deepEqual(await data(),dragged);
    // Single-channel selection leaves every other channel and segment untouched.
    await page.evaluate(()=>{sequenceEditor.selected=new Set([sequenceEditor.doc.tracks.x[0]._id]);sequenceEditor.render();});
    const beforeSingle=await data();await preset('五次').click();const single=await data();
    for(const name of ['y','z','yaw','pitch','roll','zoom'])assert.deepEqual(single.tracks[name],beforeSingle.tracks[name]);
    assert.deepEqual(single.tracks.x.slice(1),beforeSingle.tracks.x.slice(1));
    await page.locator('#saveButton').click();await page.waitForFunction(()=>!state.dirty);
    await page.reload();await page.waitForFunction(()=>state.loaded&&sequenceEditor?.doc&&curveMath);
    assert.deepEqual(await data(),single);
    await page.locator('#tabCurve').click();await selectAll();
    await page.locator('#paneCurve').screenshot({path:path.join(out,'camera-curves.png')});
    assert.deepEqual(errors,[]);assert.deepEqual(gameRequests,[]);
    console.log(JSON.stringify({passed:true,singleClick:true,nonStoppingJoin:true,undoRedo:true,oneUndoPerDrag:true,escapeCancel:true,selectionIsolation:true,saveReload:true,gameRequests}));
  }catch(error){await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});console.error(errors);throw error;}
  finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
