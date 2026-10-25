const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const base=process.argv[2],root=process.argv[3],out=path.resolve('output/workbench-usability-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const page=await browser.newPage({viewport:{width:1600,height:1100}}),errors=[],writes=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/\/api\/(project\/edit|ui\/editor)$/.test(r.url()))writes.push(r.url());});
 const ready=()=>page.waitForFunction(()=>document.body.dataset.appReady==='true'&&state.loaded&&!state.busy);
 const settings=async()=>{await page.locator('#settingsButton').click();await page.waitForFunction(()=>applicationSettings&&!settingsLoading);};
 const saveSettings=async()=>{await page.locator('#settingsSave').click();await page.waitForFunction(()=>!state.busy&&$('settingsResult').textContent==='设置已保存。');};
 const data=()=>page.evaluate(()=>sequenceEditor.data());
 const cut=()=>page.evaluate(()=>{window.clipboardData=new DataTransfer();document.activeElement.dispatchEvent(new ClipboardEvent('cut',{bubbles:true,cancelable:true,clipboardData}));});
 const paste=()=>page.evaluate(()=>document.activeElement.dispatchEvent(new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData})));
 const point=(p,r)=>page.evaluate(([p,r])=>{const s=$('speedGraph'),b=s.getBoundingClientRect(),l=s.speedLayout,v=speedCurveEditor.view;return {x:b.left+(l.left+(p-v.start)*v.zoom*(l.right-l.left))*b.width/l.width,y:b.top+(l.bottom-r*(l.bottom-l.top))*b.height/l.height};},[p,r]);
 try{
  await page.goto(base);await ready();
  assert.equal(await page.locator('#homeView').isVisible(),true);
  assert.equal(await page.evaluate(()=>state.projectPath),null);assert.deepEqual(writes,[]);
  assert.equal(fs.existsSync(path.join(root,'project.json')),false);
  assert.equal(fs.existsSync(path.join(root,'Documents')),false);
  const overlay=await browser.newPage();overlay.on('pageerror',e=>errors.push(e.message));
  await overlay.goto(base+'/overlay?panel=keyframes');await overlay.waitForFunction(()=>model.ready&&model.data?.project===null);
  assert.equal(await overlay.locator('#miniPreview').isDisabled(),true);
  assert.match(await overlay.locator('#miniLiveStatus').textContent(),/新建或打开项目/);await overlay.close();
  await settings();assert.equal(await page.locator('#projectDirectory').inputValue(),path.join(root,'Documents','Blitz-Camera-Project'));
  await page.locator('#uiScale').selectOption('150');await saveSettings();
  assert.equal(await page.evaluate(()=>window.BlitzUIScale),1.5);
  await page.locator('#settingsView').screenshot({path:path.join(out,'settings-150.png')});
  await page.reload();await ready();assert.equal(await page.evaluate(()=>window.BlitzUIScale),1.5);
  assert.equal(await page.evaluate(()=>state.project),null);assert.deepEqual(writes,[]);
  await page.locator('#homeNew').click();await page.locator('#homeNewName').fill('使用体验验收');await page.locator('#homeNewName').press('Enter');
  await page.waitForFunction(()=>!!state.project&&!state.busy&&!state.home&&!!sequenceEditor.doc&&state.samples.length>1);
  assert.equal(path.dirname(await page.evaluate(()=>state.projectPath)),path.join(root,'Documents','Blitz-Camera-Project'));
  assert.equal(fs.existsSync(await page.evaluate(()=>state.projectPath)),true);

  // Cut retains clipboard data and is atomic, undoable, and scoped away from text fields.
  const before=await data();
  await page.evaluate(()=>{sequenceEditor.selected=new Set([sequenceEditor.doc.tracks.x[0]._id]);sequenceEditor.render();});
  assert.equal(await page.locator('[data-action=cut]').isEnabled(),true);
  await page.locator('.seq-scroll').focus();await cut();
  assert.equal((await data()).tracks.x.length,before.tracks.x.length-1);
  await page.evaluate(()=>seek(2));await page.locator('.seq-scroll').focus();await paste();assert.ok((await data()).tracks.x.some(k=>k.time_sec===2),JSON.stringify(await page.evaluate(()=>({tracks:state.tracks.x,time:sequenceEditor.playhead,clipboard:sequenceEditor.clipboard,types:[...clipboardData.types],active:document.activeElement.className}))));
  await page.keyboard.press('Control+z');await page.keyboard.press('Control+z');assert.deepEqual(await data(),before);
  await page.keyboard.press('Control+Shift+z');assert.equal((await data()).tracks.x.length,1);
  const clipboardBefore=await page.evaluate(()=>JSON.stringify(sequenceEditor.clipboard));
  await page.evaluate(()=>{sequenceEditor.selected=new Set(sequenceEditor.doc.tracks.x.map(k=>k._id));sequenceEditor.render();});
  const protectedBefore=await data();await cut();assert.deepEqual(await data(),protectedBefore);
  assert.equal(await page.evaluate(()=>JSON.stringify(sequenceEditor.clipboard)),clipboardBefore);
  await page.keyboard.press('Control+z');assert.deepEqual(await data(),before);
  await page.locator('#captureTime').dispatchEvent('cut',{clipboardData:null});assert.deepEqual(await data(),before);

  // Zoom and scroll only affect the view. Dragged positions remain accurate at 150% UI scale.
  await page.locator('#tabSpeed').click();
  await page.evaluate(()=>sequenceEditor.changeSpeed({...sequenceEditor.doc.speed,mode:'curve',keyframes:[{progress:0,rate:1},{progress:.90,rate:1},{progress:.91,rate:.1},{progress:1,rate:1}]}));
  const speedBefore=await data(),history=await page.evaluate(()=>sequenceEditor.undoStack.length);
  await page.evaluate(()=>{speedCurveEditor.setView(.88,16);});
  await page.waitForFunction(()=>$('speedScroll').scrollWidth>$('speedScroll').clientWidth*10);
  assert.deepEqual(await data(),speedBefore);assert.equal(await page.evaluate(()=>sequenceEditor.undoStack.length),history);
  const a=await point(.91,.1),b=await point(.915,.2);
  await page.mouse.move(a.x,a.y);await page.mouse.down();await page.mouse.move(b.x,b.y,{steps:8});await page.mouse.up();
  let speed=(await data()).speed;assert.ok(Math.abs(speed.keyframes[2].progress-.915)<.0005,JSON.stringify(speed));assert.ok(Math.abs(speed.keyframes[2].rate-.2)<.01);
  await page.keyboard.press('Control+z');assert.deepEqual(await data(),speedBefore);
  await page.locator('#paneSpeed').screenshot({path:path.join(out,'speed-zoom-150.png')});
  await page.evaluate(()=>{$('speedScroll').scrollLeft=0;});await page.waitForFunction(()=>speedCurveEditor.view.start<.001);
  await page.locator('[data-speed-view=fit]').click();assert.equal(await page.evaluate(()=>speedCurveEditor.view.zoom),1);
  await page.locator('[data-speed-view=in]').click();assert.equal(await page.evaluate(()=>speedCurveEditor.view.zoom),1.5);
  await page.locator('#speedZoom').focus();await page.keyboard.press('ArrowRight');assert.ok(await page.evaluate(()=>speedCurveEditor.view.zoom>1.5));
  await page.locator('[data-speed-view=fit]').click();
  const zoomAnchor=await point(.91,.5);await page.mouse.move(zoomAnchor.x,zoomAnchor.y);
  await page.keyboard.down('Alt');await page.mouse.wheel(0,-500);await page.keyboard.up('Alt');
  await page.waitForFunction(()=>speedCurveEditor.view.zoom>2);
  const anchored=await point(.91,.5);assert.ok(Math.abs(anchored.x-zoomAnchor.x)<3);
  await page.locator('[data-speed-view=fit]').click();
  assert.deepEqual(await data(),speedBefore);
  await page.locator('#speedGraph').focus();await page.evaluate(()=>{sequenceEditor.selected=new Set([sequenceEditor.doc.speed.keyframes[2]._id]);sequenceEditor.render();});
  await cut();assert.equal((await data()).speed.keyframes.length,3);await page.keyboard.press('Control+z');assert.deepEqual(await data(),speedBefore);
  await page.evaluate(()=>{sequenceEditor.selected=new Set([sequenceEditor.doc.speed.keyframes[0]._id]);sequenceEditor.render();});await cut();assert.deepEqual(await data(),speedBefore);
  await page.evaluate(()=>window.BlitzFlushEditorSession());

  // Every supported scale fits the viewport; settings remain accessible at 200%.
  await settings();
  for(const scale of ['200','125','100']){
   await page.locator('#uiScale').selectOption(scale);await saveSettings();
   const layout=await page.evaluate(()=>({height:document.body.getBoundingClientRect().height,viewport:innerHeight,width:document.body.getBoundingClientRect().width,viewportWidth:innerWidth}));
   assert.ok(Math.abs(layout.height-layout.viewport)<3,JSON.stringify(layout));assert.ok(layout.width<=layout.viewportWidth+2,JSON.stringify(layout));
  }
  assert.deepEqual(errors,[]);console.log('PASS: no-project Home, Documents default, persistent UI scale, cut/paste/undo/protected keys, zoom/pan and precise editing at 150%.');
 }catch(error){await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});console.error(errors,await page.evaluate(()=>({toast:$('toast').textContent,service:$('serviceError').textContent,home:state.home,project:state.projectPath})));throw error;}
 finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
