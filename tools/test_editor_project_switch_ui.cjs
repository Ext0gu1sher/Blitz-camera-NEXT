const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const out=path.resolve('output/editor-project-switch-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const context=await browser.newContext({viewport:{width:1500,height:1100}}),page=await context.newPage(),errors=[],gameRequests=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/\/api\/(connect|playback\/start|replay\/open)$/.test(r.url()))gameRequests.push(r.url());});
 const loaded=()=>page.waitForFunction(()=>document.body.dataset.appReady==='true'&&state.loaded&&sequenceEditor?.doc&&state.samples.length>1&&!pendingEditorRestore&&!state.busy);
 const view=()=>page.evaluate(()=>BlitzEditorSession.captureTimeline(sequenceEditor,state.previewTime));
 const checkView=(actual,saved)=>{for(const key of ['playhead','scale','scroll_left','scroll_top','axis','fps','snap'])assert.equal(actual[key],saved[key],key);};
 try{
  await page.goto(process.argv[2]);await loaded();
  const a=await page.evaluate(()=>state.projectPath);
  await page.evaluate(async()=>{sequenceEditor.zoom(5);sequenceEditor.scroll.scrollLeft=730;sequenceEditor.scroll.scrollTop=40;seek(24.5);await window.BlitzFlushEditorSession();});
  const savedA=await view();assert.ok(savedA.scroll_left>0);
  // Leave immediately after the latest view change, while an older save is in flight.
  let delayed=false;await page.route('**/api/ui/editor',async route=>{if(!delayed){delayed=true;await new Promise(resolve=>setTimeout(resolve,250));}await route.continue();});
  const latestA=await page.evaluate(async()=>{
   seek(25);const earlier=persistEditorSession();
   splitH=.78;splitV=.35;applySplits();sequenceEditor.axis='shooting';sequenceEditor.fps=30;sequenceEditor.snap=false;sequenceEditor.render();
   sequenceEditor.scroll.scrollLeft=895;sequenceEditor.scroll.scrollTop=62;seek(26.75);
   state.zoom=2.25;state.pan=[31,-17];showTab('Speed');
   const expected=BlitzEditorSession.captureTimeline(sequenceEditor,state.previewTime);
   showHome(true);await window.BlitzFlushEditorSession();await earlier;return expected;
  });
  Object.assign(savedA,latestA);assert.ok(savedA.scroll_top>0);
  await page.waitForTimeout(1800);
  const hidden=await page.evaluate(()=>({view:BlitzEditorSession.captureTimeline(sequenceEditor,state.previewTime),local:BlitzEditorSession.readLocal(localStorage,state.projectPath)}));
  const disk=await(await page.request.get(process.argv[2]+'/api/state')).json();
  fs.writeFileSync(path.join(out,'hidden-state.json'),JSON.stringify({savedA,hidden,disk:disk.editor_state},null,2));
  assert.equal(disk.editor_state.timeline.scroll_left,savedA.scroll_left,'returning home must not overwrite A with hidden scroll position');
  assert.equal(hidden.local.timeline.scroll_left,savedA.scroll_left);
  checkView(disk.editor_state.timeline,savedA);
  await page.unroute('**/api/ui/editor');
  await page.evaluate(async()=>{await switchHomeProject(()=>action(async()=>{await api('/api/projects/new',{name:'session-B'});await refreshState(true);showHome(false);}));});await loaded();
  await page.evaluate(async()=>{sequenceEditor.zoom(8);sequenceEditor.scroll.scrollLeft=420;seek(5);await window.BlitzFlushEditorSession();});
  const savedB=await view();
  await page.locator('#settingsButton').click();
  await page.evaluate(()=>window.BlitzFlushEditorSession());
  const settingsDisk=await(await page.request.get(process.argv[2]+'/api/state')).json();checkView(settingsDisk.editor_state.timeline,savedB);
  await context.close();
  const fresh=await browser.newContext({viewport:{width:1500,height:1100}}),reopened=await fresh.newPage();
  reopened.on('pageerror',e=>errors.push(e.message));
  reopened.on('request',r=>{if(/\/api\/(connect|playback\/start|replay\/open)$/.test(r.url()))gameRequests.push(r.url());});
  await reopened.goto(process.argv[2]);await reopened.waitForFunction(()=>state.loaded&&sequenceEditor?.doc&&!pendingEditorRestore&&state.samples.length>1);
  const actualB=await reopened.evaluate(()=>BlitzEditorSession.captureTimeline(sequenceEditor,state.previewTime));
  checkView(actualB,savedB);
  await reopened.locator('#homeButton').click();
  await reopened.evaluate(async p=>{await switchHomeProject(()=>openProjectFlow(p));},a);
  await reopened.waitForFunction(()=>!state.busy&&!pendingEditorRestore&&state.samples.length>1);
  const actualA=await reopened.evaluate(()=>BlitzEditorSession.captureTimeline(sequenceEditor,state.previewTime));
  checkView(actualA,savedA);
  const pathView=await reopened.evaluate(()=>({zoom:state.zoom,pan:state.pan,splitH,splitV,inspector:document.getElementById('tabSpeed').getAttribute('aria-selected')}));
  assert.deepEqual(pathView,{zoom:2.25,pan:[31,-17],splitH:.78,splitV:.35,inspector:'true'});
  // The browser keepalive/pagehide save also preserves the view while Home is open.
  await reopened.evaluate(()=>showHome(true));await reopened.evaluate(()=>persistEditorSession(true,true));
  await reopened.waitForTimeout(900);await reopened.reload();
  await reopened.waitForFunction(()=>state.loaded&&sequenceEditor?.doc&&!pendingEditorRestore&&state.samples.length>1);
  checkView(await reopened.evaluate(()=>BlitzEditorSession.captureTimeline(sequenceEditor,state.previewTime)),savedA);
  assert.deepEqual(errors,[]);assert.deepEqual(gameRequests,[]);
  const result={passed:true,hiddenAutosave:true,immediateHideWithPendingSave:true,closeFromSettings:true,reopenBThenAWithoutLocalStorage:true,closeFromHome:true,pathView,savedA,savedB,actualA,actualB,errors,gameRequests};fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
  await fresh.close();
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
