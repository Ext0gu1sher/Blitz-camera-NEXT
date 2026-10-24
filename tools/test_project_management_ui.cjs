const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{
  const [base,alpha,beta,forgotten,replay]=process.argv.slice(2);
  const out=path.resolve('output/project-management-acceptance');fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],requests=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.url().endsWith('/api/projects/delete'))requests.push(r.postDataJSON());});
  const row=name=>page.locator('#homeRows tr').filter({has:page.locator('td:first-child',{hasText:name})});
  const idle=()=>page.waitForFunction(()=>!state.busy&&!homeLoading);
  try{
    await page.goto(base+'/?home=1');
    await page.waitForFunction(()=>document.body.dataset.appReady==='true'&&state.loaded&&!homeLoading);
    assert.equal(await page.locator('#homeRows tr').count(),4);
    await page.screenshot({path:path.join(out,'project-list.png')});
    assert.equal(await row('已丢失').locator('.home-delete').count(),0);
    await row('已丢失').locator('.home-remove').click();await idle();
    await row('仅移出列表').locator('.home-remove').click();await idle();
    assert.ok(fs.existsSync(forgotten));assert.equal(await row('仅移出列表').count(),0);
    // Cancel and Escape cannot send a deletion or trigger the row's Open action.
    await row('旧项目').locator('.home-delete').click();
    assert.equal(await page.locator('#projectDeleteName').textContent(),'旧项目');
    assert.equal(await page.locator('#projectDeletePath').textContent(),alpha);
    await page.screenshot({path:path.join(out,'delete-confirmation.png')});
    await page.locator('#projectDeleteDialog button[value=cancel]').click();
    assert.ok(fs.existsSync(alpha));assert.equal(requests.length,0);
    await row('旧项目').locator('.home-delete').click();await page.keyboard.press('Escape');
    assert.ok(fs.existsSync(alpha));assert.equal(requests.length,0);
    assert.equal(await page.evaluate(()=>state.projectPath),beta);
    // Keep a pending edit to the current project while deleting another project.
    const edited=await page.evaluate(()=>{sequenceEditor.edit(()=>sequenceEditor.doc.tracks.x[0].value+=11);clearTimeout(autoSaveTimer);return structuredClone(state.tracks);});
    await row('旧项目').locator('.home-delete').click();await page.locator('#projectDeleteConfirm').click();
    await page.waitForFunction(()=>!state.busy&&!homeLoading&&document.querySelectorAll('#homeRows tr').length===1);
    assert.ok(!fs.existsSync(alpha));assert.ok(fs.existsSync(beta));
    assert.equal(await page.evaluate(()=>state.projectPath),beta);
    assert.deepEqual(await page.evaluate(()=>state.tracks),edited);
    // Delete the active project with an unsaved draft. Wait beyond the autosave
    // interval, then reload: neither the file nor its recent entry can return.
    await row('当前项目').locator('.home-delete').click();
    assert.equal(await page.locator('#projectDeleteDraft').isVisible(),true);
    await page.locator('#projectDeleteConfirm').click();
    await page.waitForFunction(()=>!state.busy&&!homeLoading&&document.querySelectorAll('#homeRows tr').length===0);
    await page.waitForTimeout(2100);
    assert.ok(!fs.existsSync(beta));assert.equal(await page.locator('#homeEmpty').isVisible(),true);
    const blank=await page.evaluate(()=>({path:state.projectPath,dirty:state.dirty}));
    assert.ok(!fs.existsSync(blank.path));assert.equal(blank.dirty,false);
    assert.equal(fs.readFileSync(replay,'utf8'),'keep replay');
    await page.screenshot({path:path.join(out,'empty-after-delete.png')});
    await page.reload();await page.waitForFunction(()=>document.body.dataset.appReady==='true'&&!homeLoading);
    assert.equal(await page.locator('#homeRows tr').count(),0);assert.ok(!fs.existsSync(beta));
    // A deleted project name can be reused, without restoring its old edit state.
    await page.locator('#homeNew').click();await page.locator('#homeNewName').fill('当前项目');await page.locator('#homeNewName').press('Enter');
    await page.waitForFunction(()=>!state.busy&&!state.home&&document.getElementById('projectName').textContent==='当前项目');
    assert.ok(fs.existsSync(beta));
    assert.notDeepEqual(await page.evaluate(()=>state.tracks),edited);
    assert.equal(requests.length,2);assert.deepEqual(errors,[]);
    console.log('PASS: remove-only, cancel/Escape, delete inactive/current, preserve drafts/replay, prevent resurrection and reuse names.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
