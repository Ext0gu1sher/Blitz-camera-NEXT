const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{
  const [base,alpha,beta,forgotten,replay]=process.argv.slice(2);
  const out=path.resolve('output/project-management-acceptance');fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],requests=[],opens=[],folders=[];let listings=0;
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{
    if(r.url().endsWith('/api/projects/delete'))requests.push(r.postDataJSON());
    if(r.url().endsWith('/api/projects/open'))opens.push(r.postDataJSON());
    if(r.url().endsWith('/api/projects/open_folder'))folders.push(r.postDataJSON());
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
    // The folder action uses the selected row even when another project is active.
    await row('旧项目').locator('.home-more').click();
    await menu.screenshot({path:path.join(out,'project-menu-folder.png')});
    const folderResponse=page.waitForResponse(base+'/api/projects/open_folder');
    await menu.getByRole('menuitem',{name:'打开项目所在文件夹',exact:true}).click();await idle();
    assert.equal((await folderResponse).ok(),true);assert.equal(await menu.isVisible(),false);
    assert.equal(await page.evaluate(()=>state.projectPath),beta);assert.equal(opens.length,0);
    assert.equal(folders.length,1,'one folder request per click');
    assert.equal(await page.evaluate(()=>!!document.activeElement.closest('.home-project')),false,'mouse menu action must not leave the old row focused');
    await row('当前项目').hover();
    assert.equal(await page.locator('.home-project').evaluateAll(rows=>rows.filter(r=>getComputedStyle(r).backgroundColor==='rgb(39, 42, 37)').length),1,'only the hovered row is highlighted');
    await page.screenshot({path:path.join(out,'folder-action-focus.png')});
    await row('当前项目').locator('.home-more').click();await page.keyboard.press('ArrowDown');
    assert.equal(await page.locator(':focus').getAttribute('data-home-action'),'folder');
    await page.keyboard.press('Enter');await idle();
    await choose('已丢失','folder');await idle();
    assert.deepEqual(folders.map(item=>item.path),[alpha,beta,path.join(path.dirname(beta),'已丢失.json')]);
    // A native host must receive one request; Python only validates the path.
    // Hold the reply to ensure success is not reported before native activation.
    const nativePage=await browser.newPage();
    try{
      await nativePage.addInitScript(()=>{
        const listeners=[];
        window.folderNativeMessages=[];
        window.folderNativeReply=data=>listeners.forEach(fn=>fn({data}));
        window.chrome.webview={
          addEventListener:(type,fn)=>{if(type==='message')listeners.push(fn);},
          postMessage:message=>{
            if(message.command==='ready')window.folderNativeReply({type:'host-state',projectFolder:true});
            if(message.command==='open-project-folder')window.folderNativeMessages.push(message);
          },
        };
      });
      const nativeRequests=[];
      nativePage.on('request',r=>{if(r.url().endsWith('/api/projects/open_folder'))nativeRequests.push(r.postDataJSON());});
      await nativePage.goto(base+'/?home=1');
      await nativePage.waitForFunction(()=>document.body.dataset.appReady==='true'&&!homeLoading&&nativeHostState?.projectFolder);
      const nativeRow=nativePage.locator('.home-project').filter({has:nativePage.locator('.home-project-name',{hasText:'旧项目'})});
      const nativeClick=async()=>{
        await nativeRow.locator('.home-more').click();
        await nativePage.locator('[data-home-action=folder]').click();
      };
      await nativeClick();
      await nativePage.waitForFunction(()=>folderNativeMessages.length===1);
      assert.deepEqual(nativeRequests,[{path:alpha,native:true}]);
      assert.equal(await nativePage.evaluate(()=>folderNativeMessages[0].directory),path.dirname(alpha));
      assert.equal(await nativePage.evaluate(()=>state.busy&&folderOpenRequests.size===1),true);
      assert.equal(await nativePage.locator('#toast').textContent(),'');
      await nativePage.evaluate(()=>folderNativeReply({type:'project-folder-opened',id:folderNativeMessages[0].id}));
      await nativePage.waitForFunction(()=>!state.busy&&folderOpenRequests.size===0);
      assert.equal(await nativePage.locator('#toast').textContent(),'已打开项目所在文件夹。');
      await nativeClick();
      await nativePage.waitForFunction(()=>folderNativeMessages.length===2);
      await nativePage.evaluate(()=>folderNativeReply({type:'project-folder-opened',id:folderNativeMessages[1].id,error:'文件夹已打开，但未能切到前台。'}));
      await nativePage.waitForFunction(()=>!state.busy&&folderOpenRequests.size===0);
      assert.equal(await nativePage.locator('#toast').textContent(),'文件夹已打开，但未能切到前台。');
      assert.equal(nativeRequests.length,2,'native failure must not open Explorer a second time through Python');
    }finally{await nativePage.close();}
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
    console.log('PASS: local search/sort, one-click open, details/menu isolation, selected project folder via mouse/keyboard including missing file, remove-only, cancel/Escape, delete inactive/current, preserve drafts/replay, prevent resurrection and reuse names.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
