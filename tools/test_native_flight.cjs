const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const [url,port,root,out]=process.argv.slice(2);
const delay=ms=>new Promise(r=>setTimeout(r,ms));
async function until(fn,label,timeout=30000){const end=Date.now()+timeout;while(Date.now()<end){if(await fn())return;await delay(100);}throw Error('Timed out: '+label);}
const native=()=>JSON.parse(fs.readFileSync(path.join(root,'output/overlay-status.json'))).workbench;
async function phase(name,page){
  fs.writeFileSync(path.join(out,'phase.json'),JSON.stringify({phase:name,...native()}));
  console.log('Desktop input phase: '+name);
  await until(()=>fs.existsSync(path.join(out,name+'.done')),name+' desktop input',300000);
}
(async()=>{
  let browser;
  await until(async()=>{try{browser=await chromium.connectOverCDP('http://127.0.0.1:'+port);return true;}catch{return false;}},'native debugger');
  const context=browser.contexts()[0];let page;
  await until(()=>{page=context.pages().find(p=>p.url().startsWith(url.split('?')[0]));return page;},'workbench: '+JSON.stringify(context.pages().map(p=>p.url())));
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/preview/select',r=>r.fulfill({json:{cancelled:true}}));
  await page.reload();await page.waitForFunction(()=>state.loaded&&replayPreviewPane);
  await page.evaluate(async()=>{
    const p=replayPreviewPane,T=await import('/vendor/three/build/three.module.js');
    p.setView('camera');p.initRenderer();p.scene.add(new T.GridHelper(100,20));p.status='ready';
    document.getElementById('previewEmpty').hidden=true;p.render();
  });
  const enter=async()=>{
    await page.locator('#previewFly').click();
    await page.waitForFunction(()=>replayPreviewPane.flying&&!document.pointerLockElement);
    await until(()=>native()?.mouseCaptured,'Win32 capture');
    assert.deepEqual(native().mouseCapture,{active:true,clipped:true,hidden:true});
  };
  const released=async()=>{await page.waitForFunction(()=>!replayPreviewPane.flying&&!replayPreviewPane.flightPending);await until(()=>!native()?.mouseCaptured,'Win32 release');};
  await enter();
  const before=await page.evaluate(()=>structuredClone(replayPreviewPane.override));
  await phase('motion',page);
  const moved=await page.evaluate(()=>structuredClone(replayPreviewPane.override));
  // Desktop automation positions the cursor absolutely; real hardware supplies
  // RAWMOUSE relative counts. Their gain is checked by the browser acceptance.
  await page.keyboard.press('Escape');await released();
  await enter();await phase('click',page);await released();
  assert.ok(await page.evaluate(()=>!!replayPreviewPane.override),'Exit lost pose');
  await enter();await phase('blur',page);await released();
  assert.deepEqual(errors,[]);
  const result={passed:true,nativeCompositionHost:true,win32MouseCapture:true,cursorHidden:true,cursorClipped:true,leftClickRelease:true,escapeRelease:true,focusLossRelease:true,errors};
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
  await page.evaluate(()=>window.chrome.webview.postMessage({command:'window',action:'close'}));
  process.exit(0);
})().catch(e=>{console.error(e);process.exit(1);});
