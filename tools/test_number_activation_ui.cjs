const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const page=await browser.newPage({viewport:{width:1500,height:1100}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 try{
  await page.goto(process.argv[2]);await page.waitForFunction(()=>document.body.dataset.appReady==='true'&&state.loaded&&sequenceEditor?.doc&&state.samples.length>1&&!pendingEditorRestore);
  await page.evaluate(()=>{sequenceEditor.selected=new Set([sequenceEditor.doc.tracks.x[1]._id]);sequenceEditor.hadSelection=false;sequenceEditor.render();});
  const input=page.locator('#keyInspector [data-field=value]'),view=input.locator('..').locator('.number-value');
  const original=await page.evaluate(()=>JSON.stringify(sequenceEditor.data())),undo=await page.evaluate(()=>sequenceEditor.undoStack.length);
  let attempts=0;
  // Send separate physical presses with clickCount=1. Unlike dblclick(), this
  // cannot supply the very native dblclick event the control must tolerate
  // missing in the desktop host. Include ordinary cursor jitter and rendering.
  const tap=async(x,y,jitter=0)=>{await page.mouse.move(x,y);await page.mouse.down({clickCount:1});if(jitter)await page.mouse.move(x+jitter,y+1);await page.mouse.up({clickCount:1});};
  for(const jitter of [0,1,3,4])for(let i=0;i<10;i++){
   const b=await view.boundingBox(),x=b.x+12,y=b.y+b.height/2;
   await tap(x,y,jitter);assert.equal(await input.isVisible(),false,'one tap must remain a number');
   await page.evaluate(()=>sequenceEditor.render());await page.waitForTimeout(70+i*25);
   await tap(x+1,y,jitter);
   assert.equal(await input.isVisible(),true,`two completed taps must activate: jitter=${jitter}, attempt=${i}`);
   assert.equal(await input.evaluate(el=>document.activeElement===el),true);
   await page.keyboard.type('-29.7123',{delay:5});assert.equal(await input.inputValue(),'-29.7123');
   await page.keyboard.press('Escape');assert.equal(await page.evaluate(()=>JSON.stringify(sequenceEditor.data())),original);attempts++;
  }
  const b=await view.boundingBox(),x=b.x+12,y=b.y+b.height/2;
  // Unrelated clicks, a slow pair, and actual drags must not enter text mode.
  await tap(x,y);await page.waitForTimeout(700);await tap(x,y);assert.equal(await input.isVisible(),false);await page.keyboard.press('Escape');
  await tap(x,y);await tap(x+20,y);assert.equal(await input.isVisible(),false);await page.keyboard.press('Escape');
  await tap(x,y);await page.locator('#keyInspector [data-selection]').click();await tap(x,y);assert.equal(await input.isVisible(),false);await page.keyboard.press('Escape');
  await tap(x,y);await page.mouse.move(x,y);await page.mouse.down();await page.mouse.move(x+15,y,{steps:5});await page.mouse.up();assert.equal(await input.isVisible(),false);await tap(x,y);assert.equal(await input.isVisible(),false);await page.keyboard.press('Control+z');
  assert.equal(await page.evaluate(()=>JSON.stringify(sequenceEditor.data())),original);
  assert.equal(await page.evaluate(()=>sequenceEditor.undoStack.length),undo);
  assert.deepEqual(errors,[]);
  const result={passed:true,independentPressPairs:attempts,jitterPixels:[0,1,3,4],nativeDoubleClickRequired:false,typedAfterEveryPair:true,slowAndUnrelatedClicksIgnored:true,dragDoesNotActivateText:true,errors};
  fs.mkdirSync('output/number-activation-acceptance',{recursive:true});fs.writeFileSync('output/number-activation-acceptance/result.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
