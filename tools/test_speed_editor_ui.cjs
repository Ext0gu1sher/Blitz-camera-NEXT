const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const T=require('../blitzcam/web/preview-time.js'),out=path.resolve('output/speed-editor-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const page=await browser.newPage({viewport:{width:1500,height:1100}}),errors=[],gameRequests=[];
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/\/api\/(connect|playback\/start|replay\/open)$/.test(r.url()))gameRequests.push(r.url());});
 const speed=()=>page.evaluate(()=>sequenceEditor.data().speed);
 const point=async(p,r)=>page.evaluate(([p,r])=>{const s=document.getElementById('speedGraph'),b=s.getBoundingClientRect(),l=s.speedLayout;return {x:b.left+l.left+p*(l.right-l.left),y:b.top+l.bottom-r*(l.bottom-l.top)};},[p,r]);
 const click=async(p,r,ctrl=false)=>{const a=await point(p,r);if(ctrl)await page.keyboard.down('Control');await page.mouse.click(a.x,a.y);if(ctrl)await page.keyboard.up('Control');};
 const drag=async(a,b)=>{const p=await point(...a),q=await point(...b);await page.mouse.move(p.x,p.y);await page.mouse.down();await page.mouse.move(q.x,q.y,{steps:8});await page.mouse.up();};
 const undo=async()=>page.keyboard.press('Control+z'),redo=async()=>page.keyboard.press('Control+Shift+z');
 try{
  await page.goto(process.argv[2]);await page.waitForFunction(()=>state.loaded&&sequenceEditor?.doc&&state.samples.length>1);await page.locator('#tabSpeed').click();
  const original=await speed();
  const bounds=await page.evaluate(()=>{const s=document.getElementById('speedGraph'),r=s.getBoundingClientRect();return {height:r.height,view:s.viewBox.baseVal.height,plot:s.speedLayout.bottom-s.speedLayout.top};});
  assert.ok(Math.abs(bounds.view-bounds.height)<2);assert.ok(bounds.plot/bounds.height>.7);
  // Ctrl-click adds at the requested rate, and history works with the graph focused.
  await click(.55,.65,true);let s=await speed();assert.equal(s.keyframes.length,5);assert.ok(Math.abs(s.keyframes[2].progress-.55)<.002);assert.ok(Math.abs(s.keyframes[2].rate-.65)<.005);
  assert.equal(await page.locator('.seq-key[data-channel=rate]').count(),5);
  await undo();assert.deepEqual(await speed(),original);await redo();assert.equal((await speed()).keyframes.length,5);await undo();
  // The add button splits the exact function, including its integral, without changing travel.
  await page.evaluate(()=>seek(sequenceEditor.map().rateTime(.13)));await page.locator('[data-speed-action=add]').click();s=await speed();assert.equal(s.keyframes.length,5);
  for(let i=0;i<=100;i++){const p=i/100;assert.ok(Math.abs(T.rateAt(s,p)-T.rateAt(original,p))<1e-9);assert.ok(Math.abs(T.integral(s,p)-T.integral(original,p))<1e-9);}
  await undo();assert.deepEqual(await speed(),original); // Focus is still on the add button.
  // Dragging is one undo step, not one step per pointer movement.
  const history=await page.evaluate(()=>sequenceEditor.undoStack.length);await drag([.25,.25],[.32,.45]);s=await speed();assert.ok(Math.abs(s.keyframes[1].progress-.32)<.002);assert.ok(Math.abs(s.keyframes[1].rate-.45)<.005);
  assert.equal(await page.evaluate(()=>sequenceEditor.undoStack.length),history+1);await undo();assert.deepEqual(await speed(),original);await redo();
  // Numeric edits participate in the same history, including Ctrl-Z while the input has focus.
  const rate=page.locator('[data-speed-field=rate]'),rateView=rate.locator('..').locator('.number-value');await rateView.dblclick();await rate.fill('.6');await rate.press('Enter');assert.equal((await speed()).keyframes[1].rate,.6);
  await rateView.focus();await undo();assert.ok(Math.abs((await speed()).keyframes[1].rate-.45)<.005);
  await redo();await page.locator('[data-speed-field=segment]').selectOption('custom');
  const beforeHandle=await speed();const h=page.locator('[data-speed-segment="1"][data-speed-handle="0"]');assert.equal(await h.count(),1);
  const hb=await h.boundingBox(),target=await point(.48,.2);await page.mouse.move(hb.x+hb.width/2,hb.y+hb.height/2);await page.mouse.down();await page.mouse.move(target.x,target.y,{steps:8});await page.mouse.up();
  const custom=await speed();assert.notDeepEqual(custom.keyframes[1].ease,beforeHandle.keyframes[1].ease);assert.ok(Math.abs(T.integral(custom,.6)-T.integral(beforeHandle,.6))>.001);assert.ok(T.valid(custom));
  await undo();assert.deepEqual(await speed(),beforeHandle);await redo();assert.deepEqual(await speed(),custom);
  // Escape discards a handle drag and pointer cancellation does not commit it.
  const handle2=await page.locator('[data-speed-segment="1"][data-speed-handle="1"]').boundingBox();await page.mouse.move(handle2.x+handle2.width/2,handle2.y+handle2.height/2);await page.mouse.down();const q=await point(.65,.85);await page.mouse.move(q.x,q.y,{steps:3});await page.keyboard.press('Escape');await page.mouse.up();assert.deepEqual(await speed(),custom);
  // Global interpolation changes clear custom handles and are undoable from the select.
  await page.locator('#timelineRateInterpolation').selectOption('linear');assert.equal((await speed()).interpolation,'linear');assert.ok((await speed()).keyframes.every(k=>!k.ease));await undo();assert.deepEqual(await speed(),custom);
  // Work-area edits retain the new handles as well as all speed knots.
  await page.evaluate(()=>seek(18));await page.locator('.seq-scroll').focus();await page.keyboard.press('o');assert.deepEqual(await speed(),custom);
  await page.locator('#saveButton').click();await page.waitForFunction(()=>document.getElementById('savedLabel').textContent==='已保存');await page.reload();await page.waitForFunction(()=>state.loaded&&sequenceEditor?.doc&&state.samples.length>1);await page.locator('#tabSpeed').click();assert.deepEqual(await speed(),custom);
  await page.locator('#paneSpeed').screenshot({path:path.join(out,'speed-editor-narrow.png')});
  // A wide/tall inspector uses the full height, with handles at normal screen size.
  await page.evaluate(()=>{document.querySelector('.wb').style.setProperty('--v','.59');document.querySelector('.wb').style.setProperty('--h','.73');});
  await page.waitForFunction(()=>{const s=document.getElementById('speedGraph'),r=s.getBoundingClientRect(),v=s.viewBox.baseVal;return Math.abs(v.height-r.height)<2&&Math.abs(v.width-r.width)<2;});
  await click(custom.keyframes[1].progress,custom.keyframes[1].rate);await page.locator('#paneSpeed').screenshot({path:path.join(out,'speed-editor-wide.png')});
  // Delete keeps endpoints; undo restores the exact authored segment handles.
  await page.keyboard.press('Delete');assert.equal((await speed()).keyframes.length,3);await undo();assert.deepEqual(await speed(),custom);
  await click(custom.keyframes[1].progress,custom.keyframes[1].rate);
  await page.keyboard.down('Shift');await drag([custom.keyframes[1].progress,custom.keyframes[1].rate],[custom.keyframes[1].progress+.1,custom.keyframes[1].rate+.03]);await page.keyboard.up('Shift');
  assert.equal((await speed()).keyframes[1].rate,custom.keyframes[1].rate);await undo();
  await page.keyboard.down('Alt');await drag([custom.keyframes[1].progress,custom.keyframes[1].rate],[custom.keyframes[1].progress+.1,custom.keyframes[1].rate+.2]);await page.keyboard.up('Alt');
  assert.ok(Math.abs((await speed()).keyframes[1].progress-custom.keyframes[1].progress-.01)<.001);assert.ok(Math.abs((await speed()).keyframes[1].rate-custom.keyframes[1].rate-.02)<.002);await undo();
  await click(custom.keyframes[1].progress,custom.keyframes[1].rate);await page.keyboard.press('ArrowUp');assert.ok(Math.abs((await speed()).keyframes[1].rate-custom.keyframes[1].rate-.01)<1e-9);await undo();
  await click(0,1);assert.equal(await page.locator('[data-speed-action=delete]').isDisabled(),true);await page.keyboard.press('Delete');assert.equal((await speed()).keyframes.length,4);
  assert.deepEqual(errors,[]);assert.deepEqual(gameRequests,[]);const result={passed:true,responsivePlot:true,ctrlAdd:true,shapePreservingInsert:true,dragSingleUndo:true,numericUndo:true,bezierHandles:true,escapeCancels:true,selectUndo:true,trimPreservesCurve:true,saveReload:true,protectedEndpoints:true,errors,gameRequests};
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }catch(e){await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});console.error(errors,await page.evaluate(()=>({toast:document.getElementById('toast').textContent,speed:sequenceEditor.data().speed,undo:sequenceEditor.undoStack.length})));throw e;}
 finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
