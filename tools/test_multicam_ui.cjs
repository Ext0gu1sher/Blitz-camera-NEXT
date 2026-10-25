const {chromium}=require('playwright');
const assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs');
const out=path.resolve('output/multicam-ui-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 try{
  const context=await browser.newContext({viewport:{width:1280,height:900},permissions:['clipboard-read','clipboard-write']});
  const page=await context.newPage(),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  const ready=()=>page.waitForFunction(()=>state.loaded&&state.tracks&&!document.body.classList.contains('app-starting'));
  const saved=()=>page.waitForFunction(()=>!state.dirty&&!autoSavePromise,{},{timeout:15000});
  const count=()=>page.locator('#multicamList [data-camera-id]').count();
  const row=i=>page.locator('#multicamList [data-camera-id]').nth(i);
  const menu=async(i,action)=>{await row(i).click({button:'right'});await page.locator('[data-camera-action='+action+']').click();};
  await page.goto(process.argv[2]);await ready();
  await page.locator('#tabMulticam').click();
  assert.equal(await count(),1);
  assert.equal(await page.locator('#multicamNew').count(),1);
  assert.equal(await page.locator('#paneMulticam select').count(),0);
  await page.locator('#multicamNew').click();
  assert.equal(await count(),2);
  assert.deepEqual(await page.evaluate(()=>Object.values(state.tracks).map(r=>r.length)),[0,0,0,0,0,0,0]);
  assert.equal(await page.locator('.seq-key:not([data-channel=rate])').count(),0);
  await saved();await page.evaluate(()=>persistEditorSession());await page.reload();await ready();
  await page.waitForFunction(()=>state.workspaceTab==='Multicam');
  assert.equal(await count(),2);
  assert.equal(await page.evaluate(()=>state.controls.length),0);
  assert.equal(await page.evaluate(()=>state.samples.length),0);
  // Start a true empty track by adding just one parameter, then undo/redo.
  await page.evaluate(()=>seek(80));
  await page.locator('[data-add=x]').click();
  await page.waitForFunction(()=>state.tracks.x.length===1);
  assert.equal(await page.evaluate(()=>state.tracks.zoom.length),0);
  await page.locator('[data-action=undo]').click();
  assert.equal(await page.evaluate(()=>state.tracks.x.length),0);
  await page.locator('[data-action=redo]').click();
  assert.equal(await page.evaluate(()=>state.tracks.x[0].time_sec),80);
  await page.locator('#addKeyframeButton').click();
  await page.waitForFunction(()=>state.tracks.zoom.length===1);
  await menu(1,'rename');
  await page.locator('.camera-rename').fill('侧面跟拍');await page.locator('.camera-rename').press('Enter');
  assert.match(await row(1).innerText(),/侧面跟拍/);
  // Native copy/paste and cut/paste on focused camera cards.
  await row(1).click();await page.keyboard.press('Control+c');await page.keyboard.press('Control+v');
  await page.waitForFunction(()=>state.multicam.cameras.length===3&&!state.busy);
  assert.equal(await count(),3);
  assert.equal(await page.evaluate(()=>state.tracks.x[0].time_sec),80);
  await page.keyboard.press('Control+x');
  assert.equal(await count(),2);
  await page.keyboard.press('Control+v');
  await page.waitForFunction(()=>state.multicam.cameras.length===3&&!state.busy);
  // Change copied camera only; preserve its own undo after switching.
  await page.locator('.seq-key[data-channel=zoom]').first().click();
  const field=page.locator('#keyInspector [data-field=value]');
  await field.locator('..').locator('.number-value').dblclick();await field.fill('86');await field.press('Enter');
  assert.equal(await page.evaluate(()=>state.tracks.zoom[0].value),86);
  await row(1).click();assert.equal(await page.evaluate(()=>state.tracks.zoom[0].value),60);
  await row(2).click();assert.equal(await page.evaluate(()=>state.tracks.zoom[0].value),86);
  await page.locator('[data-action=undo]').click();assert.equal(await page.evaluate(()=>state.tracks.zoom[0].value),60);
  await page.locator('[data-action=redo]').click();assert.equal(await page.evaluate(()=>state.tracks.zoom[0].value),86);
  // Independent speed and work range through real editor changes.
  await page.evaluate(()=>sequenceEditor.edit(()=>{sequenceEditor.doc.timeline.work_start_sec=76;sequenceEditor.doc.speed.mode='fixed';sequenceEditor.doc.speed.rate=.5;}));
  await row(1).click();assert.deepEqual(await page.evaluate(()=>[state.timeline.work_start_sec,speedSettings().rate]),[72,1]);
  await row(2).click();assert.deepEqual(await page.evaluate(()=>[state.timeline.work_start_sec,speedSettings().rate]),[76,.5]);
  const playhead=await page.evaluate(()=>state.previewTime);
  await row(0).click();assert.equal(await page.evaluate(()=>state.previewTime),playhead);
  assert.equal(await page.evaluate(()=>state.tracks.zoom.length),3);
  await row(2).click();await saved();
  // Text input copy/paste retains normal browser behavior and never creates cameras.
  await page.locator('#tabProject').click();
  await page.locator('#tabMulticam').click();
  await row(2).click({button:'right'});
  await page.screenshot({path:path.join(out,'app-independent-cameras-menu.png'),fullPage:true});
  await page.keyboard.press('Escape');
  assert.equal(await row(2).evaluate(el=>el===document.activeElement),true);
  await page.screenshot({path:path.join(out,'app-independent-cameras.png'),fullPage:true});
  // Clipboard shortcuts remain scoped to timeline keys and text fields.
  await page.locator('[data-action=workfit]').click();
  await page.locator('.seq-key[data-channel=zoom]').first().click();
  await page.keyboard.press('Control+c');
  await row(2).click();await page.keyboard.press('Control+v');
  assert.equal(await count(),3);
  await page.locator('#presetName').fill('机位名称文本');
  await page.locator('#presetName').press('Control+a');await page.keyboard.press('Control+c');
  await page.locator('#presetName').fill('');await page.keyboard.press('Control+v');
  assert.equal(await page.locator('#presetName').inputValue(),'机位名称文本');assert.equal(await count(),3);
  // Invalid camera data is rejected before editor mutation.
  await row(2).click();
  const beforeInvalid=await page.evaluate(()=>JSON.stringify(state.multicam));
  await page.evaluate(async()=>{const bad={kind:'blitzcam-camera',version:1,camera:{...currentCamera(),camera_tracks:{x:[]}}};await navigator.clipboard.writeText('BlitzCamera camera\n'+JSON.stringify(bad));});
  await page.keyboard.press('Control+v');
  await page.waitForFunction(()=>!state.busy);
  assert.equal(await page.evaluate(()=>JSON.stringify(state.multicam)),beforeInvalid);
  // Context copy/paste.
  await menu(1,'copy');await menu(1,'paste');
  await page.waitForFunction(()=>state.multicam.cameras.length===4&&!state.busy);
  await menu(3,'delete');await page.locator('#cameraDeleteConfirm').click();await page.waitForFunction(()=>state.multicam.cameras.length===3);assert.equal(await count(),3);
  await saved();await page.evaluate(()=>persistEditorSession());await page.reload();await ready();
  await page.waitForFunction(()=>state.workspaceTab==='Multicam');
  assert.equal(await count(),3);
  await row(2).click();assert.equal(await page.evaluate(()=>state.tracks.zoom[0].value),86);
  assert.deepEqual(await page.evaluate(()=>[state.timeline.work_start_sec,speedSettings().rate]),[76,.5]);
  // Last camera can be cut; paste restores a complete camera into an empty list.
  // Quick switching and list reorder preserve the selected camera and its badge.
  const slots=await page.evaluate(()=>Object.fromEntries(state.multicam.cameras.map(c=>[c.id,c.slot])));
  const firstId=await row(0).getAttribute('data-camera-id');
  await page.locator(`#multicamStrip [data-camera-id="${firstId}"]`).click();
  assert.equal(await page.evaluate(()=>currentCamera().id),firstId);
  assert.equal(await page.locator('#cameraEditContext').isVisible(),true);
  const beforeOrder=await page.evaluate(()=>state.multicam.cameras.map(c=>c.id));
  const a=await row(0).boundingBox(),b=await row(2).boundingBox();
  await page.mouse.move(a.x+20,a.y+a.height/2);await page.mouse.down();
  await page.mouse.move(b.x+20,b.y+b.height-2,{steps:8});await page.mouse.up();
  assert.deepEqual(await page.evaluate(()=>state.multicam.cameras.map(c=>c.id)),[...beforeOrder.slice(1),firstId]);
  assert.deepEqual(await page.evaluate(()=>Object.fromEntries(state.multicam.cameras.map(c=>[c.id,c.slot]))),slots);
  await page.keyboard.press('Control+z');
  assert.deepEqual(await page.evaluate(()=>state.multicam.cameras.map(c=>c.id)),beforeOrder);
  await row(2).click();await row(2).press('Delete');
  assert.equal(await page.locator('#cameraDeleteDialog').isVisible(),true);
  await page.locator('#cameraDeleteDialog button[value=cancel]').click();assert.equal(await count(),3);
  await row(2).click();
  while(await count()>0){await row(0).click();await page.keyboard.press('Control+x');}
  assert.equal(await page.evaluate(()=>state.multicam.active_camera_id),null);await saved();
  await page.keyboard.press('Control+v');await page.waitForFunction(()=>state.multicam.cameras.length===1&&!state.busy);
  assert.equal(await page.evaluate(()=>state.tracks.zoom[0].value),86);
  // UI and backend agree on the upper bound.
  while(await count()<16)await page.locator('#multicamNew').click();
  assert.equal(await page.locator('#multicamNew').isDisabled(),true);
  await page.keyboard.press('Control+v');assert.equal(await count(),16);
  assert.deepEqual(errors,[]);
  await saved();
  console.log('PASS: empty creation/reload, partial first key, undo/redo, right-click menu, native Ctrl+C/V/X, independent tracks/speed/work range, save/reload, last-camera cut/paste, maximum 16. No page errors.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
