const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const out=path.resolve('output/startup-acceptance');fs.mkdirSync(out,{recursive:true});
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const base=process.argv[2],errors=[],external=[],game=[];let current;
 const pageFor=async options=>{
  const page=await browser.newPage({viewport:{width:1440,height:1000},...options});current=page;
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{
   if(!r.url().startsWith(base)&&!r.url().startsWith('blob:'))external.push(r.url());
   if(/\/api\/(connect|playback\/start|replay\/open)$/.test(r.url()))game.push(r.url());
  });return page;
 };
 const ready=page=>page.waitForFunction(()=>document.body.dataset.appReady==='true');
 try{
  const page=await pageFor();await page.goto(base);
  await page.waitForFunction(()=>state.loaded&&state.samples.length>1);
  assert.equal(await page.locator('#appSplash').isVisible(),true);
  assert.equal(await page.locator('#titlebar').evaluate(el=>getComputedStyle(el).opacity),'0');
  assert.equal(await page.locator('#wb').evaluate(el=>el.inert),true);
  assert.equal(await page.locator('#appSplash').evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(23, 23, 23)');
  assert.equal(await page.locator('.bc-footnote').textContent(),'爱吹灭火器的思源 - 2026');
  await pause(2100);await page.screenshot({path:path.join(out,'brand.png')});
  await ready(page);assert.equal(await page.locator('#appSplash').isVisible(),false);assert.equal(await page.locator('#wb').evaluate(el=>el.inert),false);
  await page.screenshot({path:path.join(out,'workbench.png')});await page.close();

  const slow=await pageFor();let release;const blocked=new Promise(r=>release=r);
  await slow.route('**/api/sample',async route=>{await blocked;await route.continue();});
  await slow.goto(base);await pause(4700);
  assert.equal(await slow.locator('#appSplash').isVisible(),true);assert.equal(await slow.locator('#appSplash').getAttribute('data-ready'),'false');
  assert.equal(await slow.locator('#titlebar').evaluate(el=>getComputedStyle(el).opacity),'0');
  assert.match(await slow.locator('.bc-loading-label').textContent(),/轨迹/);
  assert.equal(await slow.locator('.bc-loading-light').evaluate(el=>getComputedStyle(el).animationPlayState),'running');
  await slow.screenshot({path:path.join(out,'slow.png')});release();await ready(slow);await slow.close();

  const failed=await pageFor();let fail=true;
  await failed.route('**/api/state',route=>fail?route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'本地服务暂时不可用'})}):route.continue());
  await failed.goto(base);await failed.waitForFunction(()=>document.querySelector('#appSplash').dataset.failed==='true');
  await pause(2200);assert.equal(await failed.locator('#startupContinue').isVisible(),false);assert.match(await failed.locator('.bc-error').textContent(),/服务暂时不可用/);
  await failed.screenshot({path:path.join(out,'failure.png')});fail=false;await failed.locator('#startupRetry').click();await ready(failed);await failed.close();

  const sampleFailed=await pageFor();await sampleFailed.route('**/api/sample',route=>route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({error:'测试：轨迹读取失败'})}));
  await sampleFailed.goto(base);await sampleFailed.waitForFunction(()=>document.querySelector('#appSplash').dataset.failed==='true');
  await sampleFailed.locator('#startupContinue').click();await ready(sampleFailed);assert.equal(await sampleFailed.locator('#settingsButton').isEnabled(),true);await sampleFailed.close();

  const scene=await pageFor();let finishScene;const sceneBlocked=new Promise(r=>finishScene=r);
  await scene.route('**/api/state',async route=>{
   const response=await route.fetch(),data=await response.json();data.project.shooting_mode='replay';
   data.project.replay_timeline={time_basis:'replay',duration_sec:30,work_start_sec:0,work_end_sec:8,replay_file:'D:/fixture/replay.wotbreplay'};
   await route.fulfill({response,json:data});
  });
  await scene.route('**/api/preview/select',async route=>{await sceneBlocked;await route.fulfill({status:400,contentType:'application/json',body:JSON.stringify({error:'测试：回放资源无法读取'})});});
  await scene.goto(base);await pause(4400);assert.equal(await scene.locator('#appSplash').isVisible(),true);assert.equal(await scene.locator('#appSplash').getAttribute('data-ready'),'false');
  finishScene();await scene.waitForFunction(()=>document.querySelector('#appSplash').dataset.failed==='true');
  assert.match(await scene.locator('.bc-error').textContent(),/回放资源无法读取/);await scene.locator('#startupContinue').click();await ready(scene);await scene.close();

  const home=await pageFor({reducedMotion:'reduce'});await home.goto(base+'/?home=1');await ready(home);
  assert.equal(await home.locator('#homeView').isVisible(),true);assert.match(await home.locator('.home-title').textContent(),/Blitz Camera NEXT/);
  await home.locator('#settingsButton').click();await home.waitForFunction(()=>!settingsLoading);assert.equal(await home.locator('#settingsView').isVisible(),true);await home.close();
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);assert.deepEqual(game,[]);
  const result={passed:true,opaqueUntilReady:true,normalAnimation:true,slowSampleWait:true,slowSceneWait:true,failureRetry:true,partialFailureEnterEditor:true,reducedMotion:true,realHomeAndWorkbench:true,errors,external,game};
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }catch(error){if(current&&!current.isClosed())await current.screenshot({path:path.join(out,'unexpected.png')});throw error;}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
