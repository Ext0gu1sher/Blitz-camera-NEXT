const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const out=path.resolve('output/pro-startup-acceptance');fs.mkdirSync(out,{recursive:true});
const base=process.argv[2],errors=[],game=[];
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',args:['--autoplay-policy=no-user-gesture-required']});
 let current;
 const pageFor=async options=>{
  const page=await browser.newPage({viewport:{width:1440,height:1000},...options});current=page;
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',r=>{if(/\/api\/(connect|playback\/start|replay\/open)$/.test(r.url()))game.push(r.url());});
  await page.addInitScript(()=>{
   window.audioContexts=[];window.audioPeak=0;window.splashExitAt=0;
   const Original=window.AudioContext,connect=AudioNode.prototype.connect;
   window.AudioContext=class extends Original{constructor(...args){super(...args);window.audioContexts.push(this);}};
   AudioNode.prototype.connect=function(destination,...args){
    if(destination instanceof AudioDestinationNode){
     const analyser=this.context.createAnalyser();connect.call(this,analyser);
     const buffer=new Float32Array(analyser.fftSize),timer=setInterval(()=>{
      if(this.context.state==='closed'){clearInterval(timer);return;}
      analyser.getFloatTimeDomainData(buffer);for(const sample of buffer)window.audioPeak=Math.max(window.audioPeak,Math.abs(sample));
     },30);
    }
    return connect.call(this,destination,...args);
   };
   new MutationObserver(()=>{if(document.body?.classList.contains('app-revealing')&&!window.splashExitAt)window.splashExitAt=performance.now();}).observe(document,{attributes:true,subtree:true,attributeFilter:['class']});
  });
  return page;
 };
 const ready=page=>page.waitForFunction(()=>document.body.dataset.appReady==='true');
 const pauseSample=async page=>{
  let release;const blocked=new Promise(resolve=>release=resolve);
  await page.route('**/api/sample',async route=>{await blocked;await route.continue().catch(()=>{});});
  return release;
 };
 try{
  // Inspect every intro shot without consuming the durable first-play marker.
  const frames=await pageFor(),releaseFrames=await pauseSample(frames);await frames.goto(base);
  assert.equal(await frames.locator('#appSplash').getAttribute('data-edition'),'pro');
  assert.equal(await frames.locator('.bc-brand').isVisible(),false);
  assert.equal(await frames.locator('.bc-loading').count(),1);
  for(const [name,time] of [['every-frame',450],['is-a',850],['highlight',1400],['logo',3200]]){
   await frames.evaluate(t=>document.querySelector('#appSplash').getAnimations({subtree:true}).forEach(a=>{a.pause();a.currentTime=t;}),time);
   await frames.screenshot({path:path.join(out,name+'.png')});
  }
  assert.equal(await frames.locator('#wb').evaluate(el=>el.inert),true);
  assert.equal(await frames.locator('#appSplash').getAttribute('data-ready'),'false');
  releaseFrames();await frames.close();

  const first=await pageFor();await first.goto(base);
  assert.equal(await first.locator('html').getAttribute('data-pro-intro'),'a'.repeat(32));
  await ready(first);
  assert.ok(await first.evaluate(()=>splashExitAt>=2600));
  assert.ok(await first.evaluate(()=>audioPeak>.01));
  await first.waitForFunction(()=>audioContexts.length===1&&audioContexts[0].state==='closed');
  await first.waitForFunction(async()=>!(await(await fetch('/')).text()).includes('data-pro-intro="'+'a'.repeat(32)+'"'));
  await first.close();

  const daily=await pageFor();await daily.goto(base);
  assert.equal(await daily.locator('html').getAttribute('data-pro-intro'),'');
  assert.equal(await daily.locator('.s1').evaluate(el=>getComputedStyle(el).opacity),'0');
  await daily.waitForFunction(()=>document.body.classList.contains('app-revealing'));
  assert.equal(await daily.locator('#wb').evaluate(el=>el.inert),true);
  await ready(daily);assert.ok(await daily.evaluate(()=>splashExitAt>=1600&&splashExitAt<3000));
  assert.equal(await daily.locator('#wb').evaluate(el=>el.inert),false);
  await daily.screenshot({path:path.join(out,'workbench.png')});await daily.close();

  const slow=await pageFor(),releaseSlow=await pauseSample(slow);await slow.goto(base);
  await slow.waitForTimeout(4400);
  assert.equal(await slow.locator('#appSplash').isVisible(),true);
  assert.match(await slow.locator('.bc-loading-label').textContent(),/轨迹/);
  // A long load must not loop the sound choreography.
  assert.equal(await slow.evaluate(()=>audioContexts.length),1);
  releaseSlow();await ready(slow);await slow.close();

  const failed=await pageFor();let fail=true;
  await failed.route('**/api/state',route=>fail?route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'测试：服务未就绪'})}):route.continue());
  await failed.goto(base);await failed.waitForFunction(()=>document.querySelector('#appSplash').dataset.failed==='true');
  assert.equal(await failed.locator('#startupContinue').isVisible(),false);
  assert.equal(await failed.locator('#startupRetry').isVisible(),true);
  await failed.screenshot({path:path.join(out,'failure.png')});
  fail=false;await failed.locator('#startupRetry').click();await ready(failed);await failed.close();

  const partial=await pageFor();await partial.route('**/api/sample',route=>route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({error:'测试：轨迹无法读取'})}));
  await partial.goto(base);await partial.locator('#startupContinue').click();await ready(partial);
  assert.ok(await partial.evaluate(()=>splashExitAt>=1600));await partial.close();

  const reduced=await pageFor({reducedMotion:'reduce'}),releaseReduced=await pauseSample(reduced);await reduced.goto(base);
  assert.equal(await reduced.locator('.s4').evaluate(el=>getComputedStyle(el).opacity),'1');
  assert.equal(await reduced.evaluate(()=>audioContexts.length),0);
  assert.equal(await reduced.locator('#appSplash').evaluate(el=>el.getAnimations({subtree:true}).length),0);
  await reduced.screenshot({path:path.join(out,'reduced.png')});releaseReduced();await ready(reduced);await reduced.close();

  const prefs=await pageFor({reducedMotion:'reduce'});await prefs.goto(base);await ready(prefs);
  await prefs.locator('#settingsButton').click();await prefs.waitForFunction(()=>!settingsLoading);
  await prefs.locator('#startupSound').selectOption('false');await prefs.locator('#settingsSave').click();
  await prefs.waitForFunction(()=>!state.busy&&document.querySelector('#settingsResult').textContent==='设置已保存。');
  await prefs.close();
  const muted=await pageFor(),releaseMuted=await pauseSample(muted);await muted.goto(base);
  assert.equal(await muted.locator('html').getAttribute('data-startup-sound'),'false');
  await muted.waitForTimeout(1700);assert.equal(await muted.evaluate(()=>audioContexts.length),0);
  await muted.evaluate(()=>document.documentElement.style.setProperty('--ui-scale',2));
  const bounds=await muted.locator('.pv-logo').boundingBox();assert.ok(bounds.x>=0&&bounds.x+bounds.width<=1441,bounds);
  await muted.screenshot({path:path.join(out,'scale-200.png')});releaseMuted();await ready(muted);await muted.close();
  assert.deepEqual(errors,[]);assert.deepEqual(game,[]);
  const result={passed:true,firstIntro:true,dailyLogo:true,acknowledgeAfterPlayback:true,minimumDurations:true,slowLoad:true,retry:true,partialFailure:true,reducedMotion:true,realAudioSignal:true,audioCleanup:true,soundSetting:true,scale200:true,errors,game};
  fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }catch(error){if(current&&!current.isClosed())await current.screenshot({path:path.join(out,'unexpected.png')});throw error;}finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
