const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{
  const [base,projects,baseline]=process.argv.slice(2),out=path.resolve('output/home-navigation-acceptance');
  fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],opens=[];
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>{if(request.url().endsWith('/api/projects/open'))opens.push(request.postDataJSON());});
  const row=name=>page.locator('.home-project-open').filter({has:page.locator('.home-project-name',{hasText:name})});
  const idle=()=>page.waitForFunction(()=>!state.busy&&!homeLoading&&!homeOpening);
  let release=null;
  try{
    if(baseline)await page.route(/\/app\.js(?:\?|$)/,route=>route.fulfill({path:baseline,contentType:'application/javascript'}));
    await page.goto(base+'/?home=1');
    await page.waitForFunction(()=>document.body.dataset.appReady==='true'&&state.loaded&&!homeLoading);
    // Hold the first click while focus starts a rescan. This is the ordering
    // produced when the desktop's first click also activates its WebView.
    await page.route('**/api/projects/recent',async route=>{
      await new Promise(resolve=>{release=resolve;});
      await route.continue();
    });
    await page.locator('#homeFilter').focus();
    const first=await row('项目甲').elementHandle(),box=await first.boundingBox();
    await page.mouse.move(box.x+box.width/2,box.y+box.height/2);
    await page.mouse.down();
    await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
    await page.waitForFunction(()=>homeLoading);
    while(!release)await new Promise(resolve=>setTimeout(resolve,10));
    assert.equal(await first.evaluate(element=>element.isConnected),true,'Focus must not remove the pressed project row.');
    // Even a changed directory response must wait for the held click.
    fs.copyFileSync(path.join(projects,'项目乙.json'),path.join(projects,'新增项目.json'));
    release();release=null;
    await page.waitForFunction(()=>!homeLoading);
    await page.waitForTimeout(100);
    assert.equal(await first.evaluate(element=>element.isConnected),true,'A rescan response must not cancel a held click.');
    await page.mouse.up();
    await page.waitForFunction(()=>!state.home&&!state.busy&&!homeOpening);
    assert.equal(opens.length,1);assert.equal(opens[0].path,path.join(projects,'项目甲.json'));
    await page.unroute('**/api/projects/recent');
    assert.equal(await page.locator('#projectName').innerText(),'项目甲');
    assert.equal(await page.locator('.tb-project').isVisible(),true);
    await page.locator('#homeButton').click();await idle();
    assert.equal(await page.locator('.tb-project').isVisible(),false,'Home must hide the previous project title.');
    assert.equal(await row('新增项目').count(),1);
    await page.screenshot({path:path.join(out,'home.png')});
    // An unchanged focus refresh keeps the current buttons and keyboard focus.
    const second=await row('项目乙').elementHandle();await second.focus();
    const response=page.waitForResponse('**/api/projects/recent');
    await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await response;await idle();
    await page.waitForTimeout(100);
    assert.equal(await second.evaluate(element=>element.isConnected&&document.activeElement===element),true);
    await page.keyboard.press('Enter');await page.waitForFunction(()=>!state.home&&!state.busy&&!homeOpening);
    assert.equal(opens.length,2);assert.equal(await page.locator('#projectName').innerText(),'项目乙');
    assert.equal(await page.locator('.tb-project').isVisible(),true);
    // External copies still appear on focus, without requiring a reload.
    await page.locator('#homeButton').click();await idle();
    fs.copyFileSync(path.join(projects,'项目乙.json'),path.join(projects,'外部复制.json'));
    await page.evaluate(()=>window.dispatchEvent(new Event('focus')));
    await row('外部复制').waitFor();
    assert.equal(await page.locator('.tb-project').isVisible(),false);
    assert.deepEqual(errors,[]);
    const result={firstClickOpensOnce:true,heldClickSurvivesRescan:true,keyboardFocusPreserved:true,homeHidesProjectName:true,editorRestoresProjectName:true,externalProjectDiscovery:true};
    fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
  }finally{if(release)release();await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
