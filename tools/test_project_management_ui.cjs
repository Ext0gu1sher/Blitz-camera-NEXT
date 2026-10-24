const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{
  const [base,alpha,beta,forgotten,replay]=process.argv.slice(2);
  const out=path.resolve('output/project-management-acceptance');fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],requests=[],opens=[];let listings=0;
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{
    if(r.url().endsWith('/api/projects/delete'))requests.push(r.postDataJSON());
    if(r.url().endsWith('/api/projects/open'))opens.push(r.postDataJSON());
    if(r.url().endsWith('/api/projects/recent'))listings++;
  });
  const row=name=>page.locator('#homeRows .home-project').filter({has:page.locator('.home-project-name',{hasText:name})});
  const menu=page.locator('#homeProjectMenu');
  const choose=async(name,action)=>{await row(name).locator('.home-more').click();await menu.locator(`[data-home-action="${action}"]`).click();};
  const idle=()=>page.waitForFunction(()=>!state.busy&&!homeLoading&&!homeOpening);
  try{
    await page.goto(base+'/?home=1');
    await page.waitForFunction(()=>document.body.dataset.appReady==='true'&&state.loaded&&!homeLoading);
    assert.equal(await page.locator('#homeRows .home-project').count(),4);
    assert.equal(await page.locator('.home-project-name').first().textContent(),'已丢失');
    const beforeFilter=listings;
    await page.locator('#homeSort').selectOption('name-asc');
    assert.equal(await page.locator('.home-project-name').first().textContent(),'当前项目');
    await page.locator('#homeSort').selectOption('name-desc');
    assert.equal(await page.locator('.home-project-name').first().textContent(),'已丢失');
    await page.locator('#homeFilter').fill('仅移');
    assert.equal(await page.locator('#homeRows .home-project').count(),1);
    await page.locator('#homeFilter').fill('不匹配的项目');assert.equal(await page.locator('#homeEmpty').isVisible(),true);
    await page.locator('#homeFilter').fill('');await page.locator('#homeSort').selectOption('recent');
    assert.equal(listings,beforeFilter,'Search and sorting must not refetch or open projects.');
    await choose('当前项目','info');
    assert.equal(await page.locator('#homeInfoPath').textContent(),beta);
    await page.keyboard.press('Escape');assert.equal(opens.length,0);
    await row('当前项目').locator('.home-project-open').click();await idle();
    assert.equal(await page.locator('#homeView').isVisible(),false);assert.equal(opens.length,1);assert.equal(opens[0].path,beta);
    await page.locator('#homeButton').click();await idle();
    await page.screenshot({path:path.join(out,'project-list.png')});
    assert.equal(await row('已丢失').locator('.home-project-open').isDisabled(),true);
    await row('已丢失').locator('.home-more').click();assert.equal(await menu.locator('.home-delete').isVisible(),false);
    await menu.locator('.home-remove').click();await idle();
    await choose('仅移出列表','forget');await idle();
    assert.ok(fs.existsSync(forgotten));assert.equal(await row('仅移出列表').count(),0);
    // Cancel and Escape cannot send a deletion or trigger the row's Open action.
    await choose('旧项目','delete');
    assert.equal(await page.locator('#projectDeleteName').textContent(),'旧项目');
    assert.equal(await page.locator('#projectDeletePath').textContent(),alpha);
    await page.screenshot({path:path.join(out,'delete-confirmation.png')});
    await page.locator('#projectDeleteDialog button[value=cancel]').click();
    assert.ok(fs.existsSync(alpha));assert.equal(requests.length,0);
    await choose('旧项目','delete');await page.keyboard.press('Escape');
    assert.ok(fs.existsSync(alpha));assert.equal(requests.length,0);
    assert.equal(await page.evaluate(()=>state.projectPath),beta);
    // Keep a pending edit to the current project while deleting another project.
    const edited=await page.evaluate(()=>{sequenceEditor.edit(()=>sequenceEditor.doc.tracks.x[0].value+=11);clearTimeout(autoSaveTimer);return structuredClone(state.tracks);});
    await choose('旧项目','delete');await page.locator('#projectDeleteConfirm').click();
    await page.waitForFunction(()=>!state.busy&&!homeLoading&&document.querySelectorAll('#homeRows .home-project').length===1);
    assert.ok(!fs.existsSync(alpha));assert.ok(fs.existsSync(beta));
    assert.equal(await page.evaluate(()=>state.projectPath),beta);
    assert.deepEqual(await page.evaluate(()=>state.tracks),edited);
    // Delete the active project with an unsaved draft. Wait beyond the autosave
    // interval, then reload: neither the file nor its recent entry can return.
    await choose('当前项目','delete');
    assert.equal(await page.locator('#projectDeleteDraft').isVisible(),true);
    await page.locator('#projectDeleteConfirm').click();
    await page.waitForFunction(()=>!state.busy&&!homeLoading&&document.querySelectorAll('#homeRows .home-project').length===0);
    await page.waitForTimeout(2100);
    assert.ok(!fs.existsSync(beta));assert.equal(await page.locator('#homeEmpty').isVisible(),true);
    const blank=await page.evaluate(()=>({path:state.projectPath,dirty:state.dirty}));
    assert.ok(!fs.existsSync(blank.path));assert.equal(blank.dirty,false);
    assert.equal(fs.readFileSync(replay,'utf8'),'keep replay');
    await page.screenshot({path:path.join(out,'empty-after-delete.png')});
    await page.reload();await page.waitForFunction(()=>document.body.dataset.appReady==='true'&&!homeLoading);
    assert.equal(await page.locator('#homeRows .home-project').count(),0);assert.ok(!fs.existsSync(beta));
    // A deleted project name can be reused, without restoring its old edit state.
    await page.locator('#homeNew').click();await page.locator('#homeNewName').fill('当前项目');await page.locator('#homeNewName').press('Enter');
    await page.waitForFunction(()=>!state.busy&&!state.home&&document.getElementById('projectName').textContent==='当前项目');
    assert.ok(fs.existsSync(beta));
    assert.notDeepEqual(await page.evaluate(()=>state.tracks),edited);
    assert.equal(requests.length,2);assert.equal(opens.length,1);assert.deepEqual(errors,[]);
    console.log('PASS: local search/sort, one-click open, details/menu isolation, remove-only, cancel/Escape, delete inactive/current, preserve drafts/replay, prevent resurrection and reuse names.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
