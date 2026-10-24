const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const out=path.resolve('output/editor-session-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const context=await browser.newContext({viewport:{width:1500,height:1100}}),page=await context.newPage(),errors=[],gameRequests=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/\/api\/(connect|playback\/start|replay\/open)$/.test(r.url()))gameRequests.push(r.url());});
 const loaded=()=>page.waitForFunction(()=>document.body.dataset.appReady==='true'&&state.loaded&&sequenceEditor?.doc&&state.samples.length>1&&!pendingEditorRestore);
 try{
  await page.goto(process.argv[2]);await loaded();
  const before=await page.evaluate(()=>state.serverRevision);
  await page.evaluate(()=>{sequenceEditor.zoom(4);sequenceEditor.scroll.scrollLeft=210;sequenceEditor.scroll.scrollTop=30;seek(24.5);showTab('Speed');state.zoom=2.25;state.pan=[31,-17];state.yaw=.92;state.elevation=.32;drawCanvas();sequenceEditor.edit(()=>sequenceEditor.doc.tracks.x[0].value+=11);});
  await page.waitForFunction(()=>!state.dirty&&state.serverRevision>0);
  const saved=await page.evaluate(()=>({tracks:sequenceEditor.data().tracks,undo:sequenceEditor.undoStack.length,scale:sequenceEditor.scale,left:sequenceEditor.scroll.scrollLeft,top:sequenceEditor.scroll.scrollTop,time:state.previewTime,zoom:state.zoom,pan:state.pan,revision:state.serverRevision}));
  assert.ok(saved.revision>before);assert.ok(saved.undo>0);assert.equal(saved.zoom,2.25);assert.deepEqual(saved.pan,[31,-17]);
  await page.keyboard.press('Control+z');await page.waitForFunction(()=>!state.dirty);await page.keyboard.press('Control+Shift+z');await page.waitForFunction(()=>!state.dirty);
  await page.evaluate(()=>window.BlitzFlushEditorSession());
  // The disk snapshot must restore in a different browser context without localStorage.
  await context.close();const context2=await browser.newContext({viewport:{width:1500,height:1100}});const restored=await context2.newPage();restored.on('pageerror',e=>errors.push(e.message));await restored.goto(process.argv[2]);await restored.waitForFunction(()=>document.body.dataset.appReady==='true'&&state.loaded&&state.samples.length>1&&!pendingEditorRestore);
  const actual=await restored.evaluate(()=>({tracks:sequenceEditor.data().tracks,scale:sequenceEditor.scale,left:sequenceEditor.scroll.scrollLeft,top:sequenceEditor.scroll.scrollTop,time:state.previewTime,zoom:state.zoom,pan:state.pan,inspector:document.getElementById('tabSpeed').getAttribute('aria-selected')}));
  assert.deepEqual(actual.tracks,saved.tracks);assert.equal(actual.scale,saved.scale);assert.ok(Math.abs(actual.left-saved.left)<=1);assert.ok(Math.abs(actual.top-saved.top)<=1);assert.equal(actual.time,saved.time);assert.equal(actual.zoom,2.25);assert.deepEqual(actual.pan,[31,-17]);assert.equal(actual.inspector,'true');
  // Restore both observer and unrecorded mode-two camera positions without changing keys or capturing the mouse.
  const preview=await restored.evaluate(()=>{
    const vec=n=>({values:Array(n).fill(0),toArray(){return [...this.values];},fromArray(v){this.values=[...v];return this;},normalize(){return this;}});
    const pane={status:'ready',view:'camera',flightSpeed:6,override:{position:[10,20,30],yaw:75,pitch:-12,roll:3,zoom:63},observer:{position:vec(3),quaternion:vec(4),fov:54,updateProjectionMatrix(){}},orbit:{target:vec(3),update(){}},stopFlight(){this.stopped=true;},setView(v){this.view=v;},render(){}};
    pane.observer.position.fromArray([101,202,303]);pane.observer.quaternion.fromArray([0,0,0,1]);pane.orbit.target.fromArray([3,4,5]);
    const value=BlitzEditorSession.capturePreview(pane);pane.override=null;pane.observer.position.fromArray([0,0,0]);pane.view='observer';BlitzEditorSession.restorePreview(pane,value);return {value,actual:BlitzEditorSession.capturePreview(pane),stopped:pane.stopped};
  });assert.deepEqual(preview.actual,preview.value);assert.equal(preview.stopped,true);
  // The desktop close handshake saves a last edit immediately, before debounce fires.
  const closePreview=await restored.evaluate(async()=>{
    const vec=n=>({values:Array(n).fill(0),toArray(){return [...this.values];},fromArray(v){this.values=[...v];return this;},normalize(){return this;}}),real=replayPreviewPane;
    const pane={status:'ready',view:'camera',flightSpeed:4,lastTracks:state.tracks,override:{position:[71,82,93],yaw:47,pitch:-9,roll:2,zoom:68},observer:{position:vec(3),quaternion:vec(4),fov:50,updateProjectionMatrix(){}},orbit:{target:vec(3),update(){}},stopFlight(){},setView(v){this.view=v;},render(){},syncFlightUI(){},update({tracks}){if(this.lastTracks!==tracks)this.override=null;this.lastTracks=tracks;}};
    replayPreviewPane=pane;sequenceEditor.edit(()=>sequenceEditor.doc.tracks.z[0].value+=7);pane.override={position:[71,82,93],yaw:47,pitch:-9,roll:2,zoom:68};await window.BlitzFlushEditorSession();const result=BlitzEditorSession.capturePreview(pane);replayPreviewPane=real;return result;
  });assert.deepEqual(closePreview.override.position,[71,82,93]);assert.equal(closePreview.override.yaw,47);
  assert.equal(await restored.evaluate(()=>state.dirty),false);
  // Closing waits for the newest snapshot even when an earlier view save is still pending.
  let delayed=false;await restored.route('**/api/ui/editor',async route=>{if(!delayed){delayed=true;await new Promise(resolve=>setTimeout(resolve,250));}await route.continue();});
  await restored.evaluate(async()=>{seek(17);const earlier=persistEditorSession();seek(23);await window.BlitzFlushEditorSession();await earlier;});
  const diskState=await(await restored.request.get(process.argv[2]+'/api/state')).json();assert.equal(diskState.editor_state.timeline.playhead,23);
  await restored.screenshot({path:path.join(out,'restored.png')});assert.deepEqual(errors,[]);assert.deepEqual(gameRequests,[]);
  const result={passed:true,automaticProjectSave:true,undoAfterAutosave:true,diskRestoresWithoutBrowserCache:true,timelineZoomAndScroll:true,playheadAndPathView:true,modeTwoCameraState:true,closeFlush:true,errors,gameRequests};fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));await context2.close();
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
