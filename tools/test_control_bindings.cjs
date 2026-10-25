const {chromium}=require('playwright'),{enterFixture}=require('./ui_fixture.cjs');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const out=path.resolve('output/control-bindings-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/preview/select',r=>r.fulfill({status:400,json:{error:'合成测试场景'}}));
  const value=fn=>page.evaluate(fn),wait=fn=>page.waitForFunction(fn),pose=()=>value(()=>structuredClone(replayPreviewPane.override));
  const bind=async(id,key)=>{await page.locator(`[data-binding="${id}"]`).click();await page.keyboard.press(key);};
  const open=async()=>{await page.locator('#settingsButton').click();await wait(()=>applicationSettings&&!settingsLoading);await page.locator('#settingsControlsTab').click();};
  const save=async()=>{await page.keyboard.press('Control+s');await wait(()=>!state.busy&&document.getElementById('controlsResult').textContent==='快捷键与控制已保存。');};
  try{
    await page.goto(process.argv[2]);await enterFixture(page);await open();
    assert.equal(await page.locator('[data-binding-row]').count(),33);
    assert.equal(await page.locator('#controlsSave').isDisabled(),true);
    await bind('rear','Space');assert.match(await page.locator('#controlsResult').textContent(),/保持固定/);
    await page.keyboard.press('Escape');assert.equal(await page.locator('#settingsView').isVisible(),true);
    await bind('forward','s');assert.match(await page.locator('#controlsResult').textContent(),/前进.*后退|后退.*前进/);
    assert.equal(await page.locator('.binding-row.conflict').count(),2);assert.equal(await page.locator('#controlsSave').isDisabled(),true);
    await page.locator('[data-binding-row="forward"] .binding-reset').first().click();
    await bind('rear','Backspace');assert.equal(await page.locator('[data-binding="rear"]').textContent(),'未绑定');
    const bindings={forward:'r',rollLeft:'u',rollRight:'j',rear:'h',enterFlight:'g',exitFlight:'y',recordPreview:'k',seekBack:'b',seekForward:'n',snap:'t',workStart:'F7',workEnd:'F8',jumpStart:'Shift+F7',jumpEnd:'Shift+F8',yawLeft:'Numpad7'};
    for(const [id,key] of Object.entries(bindings))await bind(id,key);
    await page.locator('summary').filter({hasText:'飞行速度'}).click();await bind('speed6','0');
    await page.locator('[data-binding="exitFlightMouse"]').click();await page.mouse.down({button:'right'});await page.mouse.up({button:'right'});
    assert.equal(await page.locator('[data-binding="exitFlightMouse"]').textContent(),'鼠标右键');
    for(const [id,n] of Object.entries({mouseSensitivity:2,rollSpeed:90,flightSpeedScale:2,seekDelay:.1,seekRamp:.5,seekMax:128})){
      const input=page.locator(`[data-tuning="${id}"]`);await input.locator('..').locator('.number-value').dblclick();await input.fill(String(n));await input.press('Enter');
    }
    assert.equal(await value(()=>BlitzControls.key('forward')),'KeyW','draft bindings must not apply before save');
    await save();assert.equal(await value(()=>BlitzControls.key('forward')),'KeyR');
    assert.equal(await page.locator('#controlsSave').isDisabled(),true);
    await page.locator('#settingsControlsTab').click();await page.locator('#settingsView').screenshot({path:path.join(out,'shortcuts.png')});
    await page.locator('#controlTuning').scrollIntoViewIfNeeded();await page.locator('#settingsView').screenshot({path:path.join(out,'control-tuning.png')});
    const config=await value(()=>structuredClone(BlitzControls.config));
    const saved=await (await page.request.get(process.argv[2]+'/api/settings')).json();assert.deepEqual(saved.input_controls,config);
    await page.reload();await enterFixture(page);assert.deepEqual(await value(()=>BlitzControls.config),config,'reload must restore bindings before entering the editor');
    await value(async()=>{
      const p=replayPreviewPane,T=await import('/vendor/three/build/three.module.js');p.setView('camera');p.initRenderer();p.scene.add(new T.GridHelper(100,20));p.status='ready';document.getElementById('previewEmpty').hidden=true;p.render();
      p.sampler={at:()=>[],rawTime:t=>t,recorderAt:()=>({pose:{x:50,y:7,z:80,yaw:Math.PI/2}})};
    });
    const enter=async()=>{await page.keyboard.press('g');await wait(()=>replayPreviewPane.flying&&document.pointerLockElement);};
    await page.locator('#previewCamera').click();await enter();
    assert.match(await page.locator('#previewFlightHud').textContent(),/H 回到主角后方/);
    const initial=await pose();await page.keyboard.down('w');await page.waitForTimeout(120);await page.keyboard.up('w');assert.deepEqual(await pose(),initial,'old movement binding must be inactive');
    await page.keyboard.down('r');await page.waitForFunction(p=>Math.hypot(...replayPreviewPane.override.position.map((v,i)=>v-p[i]))>.5,initial.position);await page.keyboard.up('r');
    await page.keyboard.press('h');assert.deepEqual((await pose()).position,[35,80,13]);
    const rear=await pose();await page.keyboard.press('x');assert.deepEqual(await pose(),rear);
    await page.keyboard.down('z');await page.waitForTimeout(100);await page.keyboard.up('z');assert.equal((await pose()).roll,0);
    await page.keyboard.down('u');await wait(()=>replayPreviewPane.override.roll<-3);await page.keyboard.up('u');
    await page.keyboard.down('j');await wait(()=>replayPreviewPane.override.roll>3);await page.keyboard.up('j');
    await page.keyboard.down('Numpad7');await wait(()=>replayPreviewPane.override.yaw>1);await page.keyboard.up('Numpad7');
    await page.keyboard.press('0');assert.equal(await value(()=>replayPreviewPane.flightSpeed),6);
    await value(()=>{replayPreviewPane.flightSpeed=4;});await page.keyboard.press('6');assert.equal(await value(()=>replayPreviewPane.flightSpeed),4);
    await value(()=>seek(1));await page.keyboard.press('ArrowRight');assert.equal(await value(()=>state.previewTime),1);
    await page.keyboard.press('n');assert.ok(Math.abs(await value(()=>state.previewTime)-1-1/60)<1e-9);
    await page.keyboard.press('b');assert.ok(Math.abs(await value(()=>state.previewTime)-1)<1e-9);
    await page.keyboard.down('n');await wait(()=>state.previewTime>10);await page.keyboard.up('n');
    await value(()=>seek(1));await page.keyboard.press('Tab');assert.equal(await value(()=>replayPreviewPane.flying),true,'old exit key must be inactive');
    await page.keyboard.press('Space');await wait(()=>state.playing&&state.previewTime>1.1);
    await page.mouse.down();await page.mouse.up();assert.equal(await value(()=>replayPreviewPane.flying&&state.playing),true,'old mouse exit must be inactive');
    const chosen=await pose();await page.keyboard.press('y');await wait(()=>!replayPreviewPane.flying&&!document.pointerLockElement);
    assert.equal(await value(()=>state.playing),false);await page.waitForTimeout(120);assert.deepEqual(await pose(),chosen);
    await enter();await page.mouse.down({button:'right'});await page.mouse.up({button:'right'});await wait(()=>!replayPreviewPane.flying&&!document.pointerLockElement);
    await enter();await page.keyboard.press('Escape');await wait(()=>!replayPreviewPane.flying&&!document.pointerLockElement);
    // Rebound timeline keys work both with and without timeline focus.
    await value(()=>{seek(2);document.activeElement.blur();});await page.keyboard.press('F7');assert.equal(await value(()=>state.timeline.work_start_sec),2);
    await value(()=>seek(3));await page.keyboard.press('F8');assert.equal(await value(()=>state.timeline.work_end_sec),3);
    await page.keyboard.press('Shift+F7');assert.equal(await value(()=>state.previewTime),2);
    await page.keyboard.press('Shift+F8');assert.equal(await value(()=>state.previewTime),3);
    const snap=await value(()=>sequenceEditor.snap);await page.keyboard.press('t');assert.equal(await value(()=>sequenceEditor.snap),!snap);
    await value(()=>{seek(2);sequenceEditor.root.tabIndex=0;sequenceEditor.root.focus();});await page.keyboard.press('n');assert.ok(Math.abs(await value(()=>state.previewTime)-2-1/60)<1e-9);
    await value(()=>{seek(2);document.activeElement.blur();});await enter();await page.keyboard.press('h');const recorded=await pose();await page.keyboard.press('k');
    await wait(()=>!replayPreviewPane.flying&&state.tracks.x.some(k=>k.time_sec===2));
    assert.deepEqual(await value(()=>['x','y','z'].map(n=>state.tracks[n].find(k=>k.time_sec===2).value)),recorded.position);
    await open();await page.locator('#controlsDefault').click();assert.equal(await value(()=>BlitzControls.key('rear')),'KeyH');await save();
    assert.equal(await value(()=>BlitzControls.key('rear')),'KeyX');assert.equal(await value(()=>BlitzControls.value('mouseSensitivity')),1);
    assert.match(await page.locator('#previewFly').getAttribute('title'),/X 回到主角后方/);
    // Browser layout remains usable at a smaller desktop window size.
    await page.setViewportSize({width:1000,height:760});await page.locator('#settingsControlsTab').click();
    const overflow=await value(()=>document.documentElement.scrollWidth>innerWidth);assert.equal(overflow,false);
    await page.locator('#settingsView').screenshot({path:path.join(out,'shortcuts-compact.png')});
    // Exercise the settings bridge separately from browser pointer lock.
    const desktop=await browser.newPage({viewport:{width:1440,height:1000}});
    desktop.on('pageerror',e=>errors.push(e.message));
    await desktop.addInitScript(()=>{
      const bridge=new EventTarget();window.hostRequests=[];
      let saved=JSON.parse(sessionStorage.getItem('host-keys')||'{"captureKey":"F8","hideKey":"F9"}');
      bridge.postMessage=m=>{
        window.hostRequests.push(m);
        if(m.command==='settings'&&!window.failHostKeys){saved={...saved,...m};sessionStorage.setItem('host-keys',JSON.stringify(saved));}
        if(['ready','settings','shortcut-capture'].includes(m.command))setTimeout(()=>bridge.dispatchEvent(new MessageEvent('message',{data:{type:'host-state',...saved,captureHotkeyRegistered:true,hideHotkeyRegistered:true,warnings:window.failHostKeys?['快捷键已被占用，保留原绑定。']:[]}})),0);
      };
      window.chrome=window.chrome||{};window.chrome.webview=bridge;
    });
    await desktop.route('**/api/preview/select',r=>r.fulfill({status:400,json:{error:'合成测试场景'}}));
    await desktop.goto(process.argv[2]+'?workbench');await enterFixture(desktop);
    await desktop.locator('#settingsButton').click();await desktop.waitForFunction(()=>applicationSettings&&!settingsLoading);await desktop.locator('#settingsControlsTab').click();
    const globalBind=async(id,key)=>{await desktop.locator('#'+id).click();await desktop.keyboard.press(key);};
    await globalBind('globalCaptureKey','Control+Shift+F10');await globalBind('globalHideKey','Control+Shift+F10');
    await desktop.locator('#applyGlobalKeys').click();assert.match(await desktop.locator('#globalKeyStatus').textContent(),/相同按键/);
    assert.equal(await desktop.evaluate(()=>hostRequests.filter(m=>m.command==='settings').length),0);
    await globalBind('globalHideKey','Control+Shift+F9');await desktop.locator('#applyGlobalKeys').click();
    await desktop.waitForFunction(()=>nativeHostState.captureKey==='Ctrl+Shift+F10'&&nativeHostState.hideKey==='Ctrl+Shift+F9');
    assert.equal(await desktop.locator('#globalCaptureKey').textContent(),'Ctrl+Shift+F10');
    assert.equal(await desktop.evaluate(()=>hostRequests.some(m=>m.command==='shortcut-capture'&&m.active)),true);
    await desktop.evaluate(()=>{window.failHostKeys=true;});await globalBind('globalCaptureKey','Control+Shift+F7');await desktop.locator('#applyGlobalKeys').click();
    // Capture status can arrive before the settings response; wait for rollback
    // to render as well, rather than accepting an earlier warning alone.
    await desktop.waitForFunction(()=>document.getElementById('globalKeyStatus').textContent.includes('被占用')&&document.getElementById('globalCaptureKey').textContent==='Ctrl+Shift+F10');
    assert.equal(await desktop.locator('#globalCaptureKey').textContent(),'Ctrl+Shift+F10');
    await desktop.evaluate(()=>{window.failHostKeys=false;});
    await desktop.locator('[data-binding="rear"]').click();await desktop.keyboard.press('Control+Shift+F10');
    assert.match(await desktop.locator('#controlsResult').textContent(),/全局快捷键/);assert.equal(await desktop.locator('#controlsSave').isDisabled(),true);
    await desktop.locator('[data-binding-row="rear"] .binding-reset').first().click();
    await desktop.locator('[data-binding="rear"]').click();await desktop.keyboard.press('Control+Alt+h');
    await desktop.keyboard.press('Control+s');await desktop.waitForFunction(()=>!state.busy&&document.getElementById('controlsResult').textContent==='快捷键与控制已保存。');
    await globalBind('globalCaptureKey','Control+Alt+h');await desktop.locator('#applyGlobalKeys').click();assert.match(await desktop.locator('#globalKeyStatus').textContent(),/冲突/);
    await desktop.reload();await enterFixture(desktop);await desktop.locator('#settingsButton').click();await desktop.waitForFunction(()=>!settingsLoading);await desktop.locator('#settingsControlsTab').click();
    assert.equal(await desktop.locator('#globalCaptureKey').textContent(),'Ctrl+Shift+F10');
    await desktop.locator('#globalKeysDefault').click();await desktop.locator('#applyGlobalKeys').click();await desktop.waitForFunction(()=>nativeHostState.captureKey==='Ctrl+Alt+F8');
    await desktop.close();
    assert.deepEqual(errors,[]);
    const result={passed:true,reservedKeys:true,conflictDetection:true,unbinding:true,saveAndReload:true,oldKeysInactive:true,customFlightKeys:true,customMouseExit:true,fixedEscape:true,exitPreservesPose:true,customTimelineKeys:true,recordPreviewShortcut:true,restoreDefaults:true,globalBindingsUI:true,globalLocalConflicts:true,globalFailurePreservesBinding:true,errors};
    fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
  }catch(error){await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});console.error(errors);throw error;}
  finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
