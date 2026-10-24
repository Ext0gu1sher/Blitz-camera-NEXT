const {chromium}=require('playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const out=path.resolve('output/preview-controls-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],launches=[],requests=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(r.url().includes('/api/'))requests.push(r.url());if(r.url().endsWith('/api/replay/open'))launches.push(r.postDataJSON());});
  // Exercise real renderer/input without depending on installed game map assets.
  await page.route('**/api/preview/select',r=>r.fulfill({json:{cancelled:true}}));
  const value=fn=>page.evaluate(fn),wait=fn=>page.waitForFunction(fn);
  try{
    await page.goto(process.argv[2]);await wait(()=>state.loaded&&replayPreviewPane);
    await page.locator('#playProjectReplay').click();
    await wait(()=>state.replayLaunch?.state==='launched');
    assert.deepEqual(launches,[{path:process.argv[3]}]);
    await page.locator('#playProjectReplay').click();
    await wait(()=>state.replayLaunch?.state==='launched');
    assert.deepEqual(launches,[{path:process.argv[3]},{path:process.argv[3]}]);
    const iconSizes=await value(()=>['playProjectReplay','connectButton','disconnectButton','openReplayButton','previewFit'].map(id=>{const r=document.querySelector('#'+id+' .ic').getBoundingClientRect();return [r.width,r.height];}));
    for(const size of iconSizes)assert.deepEqual(size,iconSizes[0]);
    for(const width of [1100,1440]){
      await page.setViewportSize({width,height:1000});
      const buttons=await value(()=>['playProjectReplay','connectButton','disconnectButton'].map(id=>{
        const r=document.getElementById(id).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right};
      }));
      assert.ok(buttons.every(b=>b.x>=0&&b.right<=width&&b.width>0&&b.height>0));
      for(let i=1;i<buttons.length;i++){assert.equal(buttons[i].y,buttons[0].y);assert.equal(buttons[i].height,buttons[0].height);assert.ok(buttons[i].x-buttons[i-1].right>=0&&buttons[i].x-buttons[i-1].right<=4);}
    }
    await page.locator('#titlebar').screenshot({path:path.join(out,'launch-and-connect-toolbar.png')});
    await value(()=>{window.boundPath=state.timeline.replay_file;delete state.timeline.replay_file;updateButtons();});
    assert.equal(await page.locator('#playProjectReplay').isDisabled(),true);
    await value(()=>{state.timeline.replay_file=window.boundPath;updateButtons();replayPreviewPane.setView('camera');});
    assert.equal(await page.locator('#previewFly').isDisabled(),true);
    await value(async()=>{
      const p=replayPreviewPane,T=await import('/vendor/three/build/three.module.js');
      p.initRenderer();p.scene.add(new T.GridHelper(100,20));
      p.status='ready';document.getElementById('previewEmpty').hidden=true;p.render();
    });
    const before=await value(()=>({tracks:structuredClone(state.tracks),time:state.previewTime,dirty:state.dirty,snap:sequenceEditor.snap,position:[...replayPreviewPane.evaluated.position]}));
    const sensitivity=await value(()=>{
      const p=replayPreviewPane,measure=(w,h)=>{
        p.override={...p.evaluated,position:[...p.evaluated.position],yaw:0,pitch:0,zoom:60};
        p.renderWidth=w;p.renderHeight=h;p.lookFlight(100,100);return [p.override.yaw,p.override.pitch];
      };
      const small=measure(320,180),large=measure(1600,900);p.override=null;p.render();return {small,large};
    });
    assert.deepEqual(sensitivity.small,sensitivity.large);
    assert.ok(Math.abs(sensitivity.small[1])<4&&Math.abs(sensitivity.small[1])<Math.abs(sensitivity.small[0]));
    const enter=async()=>{await page.locator('#previewFly').click();await wait(()=>replayPreviewPane.flying&&document.pointerLockElement);};
    const pose=()=>value(()=>structuredClone(replayPreviewPane.override));
    await value(()=>{state.playing=true;});await enter();
    assert.equal(await value(()=>state.playing),false);
    await page.keyboard.press('Digit6');await page.keyboard.down('KeyW');
    await wait(()=>Math.hypot(...replayPreviewPane.override.position.map((v,i)=>v-replayPreviewPane.evaluated.position[i]))>.5);
    await page.keyboard.up('KeyW');
    const moving=await pose();
    await page.keyboard.down('KeyQ');await wait(()=>replayPreviewPane.override.position[2]>10.5);await page.keyboard.up('KeyQ');
    await page.keyboard.press('KeyS');assert.equal(await value(()=>sequenceEditor.snap),before.snap);
    await page.mouse.move(700,450);const look=await pose();await page.mouse.move(740,460);
    await wait(()=>replayPreviewPane.override.yaw<replayPreviewPane.evaluated.yaw);
    const zoom=(await pose()).zoom;await page.mouse.wheel(0,-100);await wait(()=>replayPreviewPane.override.zoom<60);
    assert.ok((await pose()).zoom<zoom);
    await page.mouse.click(740,460);await wait(()=>!replayPreviewPane.flying&&!document.pointerLockElement);
    const stopped=await pose();await page.waitForTimeout(120);assert.deepEqual(await pose(),stopped);
    assert.deepEqual(await value(()=>state.tracks),before.tracks);assert.equal(await value(()=>state.previewTime),before.time);
    assert.equal(await value(()=>state.dirty),before.dirty);
    assert.equal(await page.locator('#previewFlightHud').isVisible(),false);
    assert.equal(await page.locator('#previewOverride').isVisible(),true);
    await page.screenshot({path:path.join(out,'controls.png')});
    await enter();await page.keyboard.press('Escape');await wait(()=>!replayPreviewPane.flying&&!document.pointerLockElement);
    await enter();await value(()=>replayPreviewPane.setView('observer'));await wait(()=>!document.pointerLockElement);
    assert.equal(await page.locator('#previewFly').isVisible(),false);
    await value(()=>replayPreviewPane.setView('camera'));await enter();await value(()=>window.dispatchEvent(new Event('blur')));await wait(()=>!replayPreviewPane.flying&&!document.pointerLockElement);
    await enter();await value(()=>seek(1));await wait(()=>!replayPreviewPane.flying&&!document.pointerLockElement);
    assert.equal(await value(()=>replayPreviewPane.override),null);
    await enter();await page.keyboard.down('KeyD');await page.waitForTimeout(120);await page.keyboard.up('KeyD');await page.keyboard.press('Escape');
    const recorded=await pose();await page.locator('#previewRecord').click();
    await wait(()=>state.dirty&&state.tracks.x.some(k=>k.time_sec===1));
    const keys=await value(()=>Object.fromEntries(Object.entries(state.tracks).map(([n,r])=>[n,r.find(k=>k.time_sec===1).value])));
    assert.deepEqual([keys.x,keys.y,keys.z],recorded.position);
    for(const n of ['yaw','pitch','roll'])assert.equal(keys[n],recorded[n]);assert.equal(keys.zoom,recorded.zoom);
    await wait(()=>!document.getElementById('previewFly').disabled);
    await value(()=>{window.lockRequest=replayPreviewPane.renderer.domElement.requestPointerLock;replayPreviewPane.renderer.domElement.requestPointerLock=()=>Promise.reject(new Error('fixture denial'));});
    await page.locator('#previewFly').click();await wait(()=>!replayPreviewPane.flightPending);
    assert.equal(await value(()=>replayPreviewPane.flying),false);
    assert.match(await page.locator('#previewStatus').textContent(),/未能锁定鼠标/);
    await value(()=>{replayPreviewPane.renderer.domElement.requestPointerLock=window.lockRequest;});
    await page.locator('[name=shootingMode][value=camera_only]').check();
    assert.equal(await page.locator('#previewFly').isVisible(),false);
    assert.ok(!requests.some(u=>/\/api\/(connect|playback\/start)$/.test(u)));
    assert.deepEqual(errors,[]);
    const result={passed:true,boundReplayWithoutPicker:true,repeatedLaunch:true,connectionBesideLaunch:true,realPointerLock:true,movement:true,zoom:true,exitPreservesPose:true,shortcutsIsolated:true,recordSevenAttributes:true,releaseOnBlurSeekAndViewSwitch:true,errors};
    fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
  }catch(error){await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});console.error(await value(()=>({flight:replayPreviewPane?.flying,pending:replayPreviewPane?.flightPending,status:document.getElementById('previewStatus').textContent})),errors);throw error;}
  finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
