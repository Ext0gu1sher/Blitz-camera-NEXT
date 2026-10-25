const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{
 const [base,first,second]=process.argv.slice(2),out=path.resolve('output/project-discovery-acceptance');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];let opens=0;
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.url().endsWith('/api/projects/open'))opens++;});
 const row=name=>page.locator('#homeRows .home-project').filter({has:page.locator('.home-project-name',{hasText:name})});
 const idle=()=>page.waitForFunction(()=>!state.busy&&!homeLoading&&!homeOpening);
 try{
  await page.goto(base);await page.waitForFunction(()=>document.body.dataset.appReady==='true'&&state.loaded&&!homeLoading);
  assert.equal(await page.locator('#homeRows .home-project').count(),2);assert.equal(opens,0);assert.equal(await page.evaluate(()=>state.project),null);
  assert.equal(await row('未打开甲').locator('.home-project-time').innerText(),'未打开');
  await row('未打开甲').locator('.home-project-open').click();await idle();assert.equal(opens,1);
  await page.locator('#homeButton').click();await idle();assert.equal(await row('未打开甲').count(),1);
  await page.locator('#settingsButton').click();await page.locator('#projectDirectory').fill(second);await page.locator('#settingsSave').click();await idle();await page.locator('#settingsBack').click();
  assert.equal(await row('另一个目录').count(),1);assert.equal(await row('未打开甲').count(),1);assert.equal(await row('未打开乙').count(),0);
  fs.copyFileSync(path.join(second,'另一个目录.json'),path.join(second,'刚复制的项目.json'));
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await idle();assert.equal(await row('刚复制的项目').count(),1);
  await row('刚复制的项目').locator('.home-more').click();await page.locator('[data-home-action="forget"]').click();await idle();
  await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await idle();assert.equal(await row('刚复制的项目').count(),0);assert.ok(fs.existsSync(path.join(second,'刚复制的项目.json')));
  await page.reload();await page.waitForFunction(()=>document.body.dataset.appReady==='true'&&!homeLoading);await page.locator('#homeButton').click();await idle();
  assert.equal(await row('刚复制的项目').count(),0);assert.equal(await row('另一个目录').count(),1);assert.equal(opens,1);
  await page.screenshot({path:path.join(out,'home.png')});assert.deepEqual(errors,[]);
  console.log('PASS home auto discovery, no auto-open, open/deduplicate, settings switch, focus rescan and persistent removal');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
