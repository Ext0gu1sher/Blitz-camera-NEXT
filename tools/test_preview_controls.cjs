const {chromium}=require('playwright');
const {enterFixture}=require('./ui_fixture.cjs');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const out=path.resolve('output/preview-controls-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],launches=[],requests=[];
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{if(r.url().includes('/api/'))requests.push(r.url());if(r.url().endsWith('/api/replay/open_project'))launches.push(r.postDataJSON());});
  // Exercise real renderer/input without depending on installed game map assets.
  await page.route('**/api/preview/select',r=>r.fulfill({status:400,json:{error:'测试场景使用合成车辆数据'}}));
  const value=fn=>page.evaluate(fn),wait=fn=>page.waitForFunction(fn);
  try{
    await page.goto(process.argv[2]);await enterFixture(page);
    await page.locator('#playProjectReplay').click();
    await wait(()=>state.replayLaunch?.state==='launched');
    assert.deepEqual(launches,[{}]);
    await page.locator('#playProjectReplay').click();
    await wait(()=>state.replayLaunch?.state==='launched');
    assert.deepEqual(launches,[{},{}]);
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
      // Register the desktop bridge listener while still using real browser
      // pointer lock for the input tests below.
      window.flightHostFixture=new EventTarget();window.flightHostMessages=[];
      window.flightHostFixture.postMessage=m=>window.flightHostMessages.push(m);
      p.flightHost=window.flightHostFixture;p.initRenderer();p.flightHost=null;
      p.scene.add(new T.GridHelper(100,20));
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
    // Use the real replay sampler, with a different first vehicle and a moving
    // recorder facing +x. Include the replay origin and manual preview offset.
    await value(async()=>{
      const {createReplaySampler}=await import('/replay-preview-core.js'),p=replayPreviewPane,samples=31;
      const vehicle=(eid,account_id,x)=>({eid,account_id,tank_id:6929,
        pos:Array.from({length:samples},(_,i)=>[x+i,7,80]).flat(),
        hull_yaw:Array(samples).fill(Math.PI/2),hull_pitch:Array(samples).fill(0),
        turret_yaw:Array(samples).fill(Math.PI/2),gun_pitch:Array(samples).fill(0),coverage:[4.25,7.25]});
      p.sampler=createReplaySampler({playback:{meta:{samples,t_start:4.25,duration:7.25,map_id:21},vehicles:[vehicle(7,1,-100),vehicle(8,2,50)]},
        result:{players:[{account_id:1,team:1,tank_id:6929},{account_id:2,team:2,tank_id:6929}],result_duration_secs:3,author_account_id:2},
        ai:{battle:{periods:[{period:3,clock:4.25}],winner:1},rosters:[{eid:7,account_id:1,team:1,tank_id:6929},{eid:8,account_id:2,team:2,tank_id:6929}],events:[],poses:[],turrets:[]}},4.25);
      p.offset=.25;p.flightVelocity=[12,6,3];p.flightKeys.add('KeyW');
    });
    await page.keyboard.press('x');
    const rear=await pose();assert.deepEqual(rear,{position:[37.5,80,13],yaw:0,pitch:-10,roll:0,zoom:54});
    assert.equal(await value(()=>replayPreviewPane.flying&&!!document.pointerLockElement),true);
    assert.deepEqual(await value(()=>replayPreviewPane.flightVelocity),[0,0,0]);
    assert.equal(await value(()=>replayPreviewPane.flightKeys.size),0);
    assert.equal(await value(()=>replayPreviewPane.flightSpeed),6);
    await page.waitForTimeout(120);assert.deepEqual(await pose(),rear,'reset must stop residual drift');
    assert.match(await page.locator('#previewFlightHud').textContent(),/X 回到主角后方/);
    await page.locator('#replayScene').screenshot({path:path.join(out,'flight-rear-shortcut.png')});
    await value(()=>{replayPreviewPane.offset=.75;});
    await page.keyboard.press('Control+x');assert.deepEqual(await pose(),rear,'Ctrl+X must not reset the camera');
    await value(()=>document.dispatchEvent(new KeyboardEvent('keydown',{code:'KeyX',repeat:true,bubbles:true})));
    assert.deepEqual(await pose(),rear,'holding X must not repeatedly reset');
    await page.keyboard.press('x');assert.deepEqual((await pose()).position,[42.5,80,13]);
    await page.keyboard.down('KeyW');await wait(()=>replayPreviewPane.override.position[0]>43);await page.keyboard.up('KeyW');
    await page.keyboard.press('x');
    const rearAgain=await pose();
    await value(()=>{replayPreviewPane.offset=30;});
    await page.keyboard.press('x');assert.deepEqual(await pose(),rearAgain,'missing recorder pose must preserve the camera');
    assert.match(await page.locator('#previewStatus').textContent(),/没有主角的可用位置/);
    await value(()=>{window.flightRecorderSampler=replayPreviewPane.sampler;replayPreviewPane.sampler=null;replayPreviewPane.offset=0;});
    await page.mouse.click(740,460);await wait(()=>!replayPreviewPane.flying&&!document.pointerLockElement);
    const stopped=await pose();await page.waitForTimeout(120);assert.deepEqual(await pose(),stopped);
    await page.keyboard.press('x');assert.deepEqual(await pose(),stopped,'X outside flight must not move the camera');
    assert.deepEqual(await value(()=>state.tracks),before.tracks);assert.equal(await value(()=>state.previewTime),before.time);
    assert.equal(await value(()=>state.dirty),before.dirty);
    assert.equal(await page.locator('#previewFlightHud').isVisible(),false);
    assert.equal(await page.locator('#previewOverride').isVisible(),true);
    await page.screenshot({path:path.join(out,'controls.png')});
    await enter();await page.keyboard.press('Escape');await wait(()=>!replayPreviewPane.flying&&!document.pointerLockElement);
    await enter();await value(()=>replayPreviewPane.setView('observer'));await wait(()=>!document.pointerLockElement);
    assert.equal(await page.locator('#previewFly').isVisible(),false);
    await value(()=>replayPreviewPane.setView('camera'));await enter();await value(()=>window.dispatchEvent(new Event('blur')));await wait(()=>!replayPreviewPane.flying&&!document.pointerLockElement);
    await enter();await value(()=>seek(1));
    const fixed=await pose(),captured=()=>value(()=>replayPreviewPane.flying&&!!document.pointerLockElement);
    assert.equal(await captured(),true,'time changes must keep flight capture');
    await page.keyboard.press('Space');await wait(()=>state.playing&&state.previewTime>1.1);
    assert.equal(await captured(),true);assert.deepEqual(await pose(),fixed,'playback must not follow the keyframed camera');
    await value(()=>document.dispatchEvent(new KeyboardEvent('keydown',{code:'Space',repeat:true,bubbles:true})));
    assert.equal(await value(()=>state.playing),true,'holding Space must not toggle repeatedly');
    await page.keyboard.press('Space');await wait(()=>!state.playing);
    const pausedTime=await value(()=>state.previewTime);
    await page.waitForTimeout(120);assert.equal(await value(()=>state.previewTime),pausedTime);
    await page.keyboard.press('ArrowRight');
    assert.ok(Math.abs(await value(()=>state.previewTime)-pausedTime-1/60)<1e-9);
    await page.keyboard.press('ArrowLeft');assert.ok(Math.abs(await value(()=>state.previewTime)-pausedTime)<1e-9);
    await value(()=>{for(let i=0;i<3;i++)document.dispatchEvent(new KeyboardEvent('keydown',{code:'ArrowRight',repeat:true,bubbles:true}));});
    assert.ok(Math.abs(await value(()=>state.previewTime)-pausedTime)<1e-9,'OS repeat events must not determine seek speed');
    await page.keyboard.down('ArrowRight');await wait(()=>state.previewTime>3);
    await page.keyboard.up('ArrowRight');const releasedTime=await value(()=>state.previewTime);
    await page.waitForTimeout(120);assert.equal(await value(()=>state.previewTime),releasedTime,'release must stop seeking immediately');
    await page.keyboard.press('ArrowLeft');assert.ok(Math.abs(await value(()=>state.previewTime)-releasedTime+1/60)<1e-9,'changing direction must start with one frame');
    // Both arrows cancel; after either is released the remaining direction
    // begins from its slow rate, independent of Windows key repeat settings.
    await page.keyboard.down('ArrowRight');await page.keyboard.down('ArrowLeft');
    const opposedTime=await value(()=>state.previewTime);
    await page.waitForTimeout(300);assert.equal(await value(()=>state.previewTime),opposedTime);
    await page.keyboard.up('ArrowLeft');await page.waitForFunction(t=>state.previewTime>t+.1,opposedTime);
    await page.keyboard.up('ArrowRight');
    await value(()=>seek(30));await page.keyboard.down('ArrowRight');
    await wait(()=>state.previewTime===60&&replayPreviewPane.flightSeek===null);
    await page.waitForTimeout(120);assert.equal(await value(()=>state.previewTime),60);
    await page.keyboard.up('ArrowRight');await page.keyboard.down('ArrowLeft');
    await wait(()=>state.previewTime===0&&replayPreviewPane.flightSeek===null);
    await page.keyboard.up('ArrowLeft');
    assert.deepEqual(await pose(),fixed);assert.equal(await captured(),true);
    // The camera banks around its own forward axis; releasing Z/C has no drift.
    await page.keyboard.down('KeyZ');await wait(()=>replayPreviewPane.override.roll<-2);await page.keyboard.up('KeyZ');
    const rolledLeft=await pose();await page.waitForTimeout(120);assert.deepEqual(await pose(),rolledLeft);
    assert.deepEqual(rolledLeft.position,fixed.position);assert.equal(rolledLeft.yaw,fixed.yaw);assert.equal(rolledLeft.pitch,fixed.pitch);
    await page.keyboard.down('KeyC');await wait(()=>replayPreviewPane.override.roll>2);await page.keyboard.up('KeyC');
    const rolledRight=await pose();assert.deepEqual(rolledRight.position,fixed.position);
    await page.keyboard.press('Control+z');await page.keyboard.press('Control+c');
    assert.deepEqual(await pose(),rolledRight,'modified Z/C must not roll or edit keys');
    await page.keyboard.down('KeyZ');await page.keyboard.down('KeyC');const opposedRoll=(await pose()).roll;
    await page.waitForTimeout(150);assert.equal((await pose()).roll,opposedRoll);
    await page.keyboard.up('KeyZ');await page.keyboard.up('KeyC');
    await value(()=>{replayPreviewPane.override.roll=0;seek(1.5);});
    await page.keyboard.press('Space');await wait(()=>state.playing);
    await page.keyboard.down('KeyD');await wait(()=>replayPreviewPane.override.position[1]<80-.1);
    await page.keyboard.up('KeyD');assert.equal(await value(()=>state.playing),true,'camera movement must work while replay plays');
    await page.keyboard.press('ArrowLeft');await wait(()=>!state.playing);
    assert.equal(await captured(),true,'stepping while playing must pause without releasing the mouse');
    await value(()=>{replayPreviewPane.sampler=window.flightRecorderSampler;replayPreviewPane.offset=.25;seek(1.5);});
    await page.keyboard.press('x');assert.deepEqual((await pose()).position,[52.5,80,13],'X must use the new playhead time');
    const currentRear=await pose();
    await value(()=>seek(0));await page.keyboard.press('ArrowLeft');assert.equal(await value(()=>state.previewTime),0);
    await value(()=>seek(state.timeline.duration_sec));await page.keyboard.press('ArrowRight');
    assert.equal(await value(()=>state.previewTime),60);assert.equal(await captured(),true);
    await value(()=>{state.loop=false;seek(state.timeline.duration_sec-.05);});
    await page.keyboard.press('Space');await wait(()=>!state.playing&&state.previewTime===state.timeline.duration_sec);
    assert.equal(await captured(),true);assert.deepEqual(await pose(),currentRear,'ending playback must keep the free camera');
    await page.keyboard.press('Space');await wait(()=>state.playing&&state.previewTime<1);
    await page.keyboard.press('Space');
    await value(()=>{state.loop=true;seek(state.timeline.duration_sec-.05);});
    await page.keyboard.press('Space');await wait(()=>state.playing&&state.previewTime<1);
    assert.equal(await captured(),true);assert.deepEqual(await pose(),currentRear,'loop wrap must keep the free camera');
    await page.keyboard.press('Space');
    await page.locator('#replayScene').screenshot({path:path.join(out,'flight-playback-shortcuts.png')});
    assert.deepEqual(await value(()=>state.tracks),before.tracks);assert.equal(await value(()=>state.dirty),before.dirty);
    await value(()=>{state.loop=false;replayPreviewPane.sampler=null;replayPreviewPane.offset=0;});
    // Every release path must freeze both time and the chosen pose, including
    // native desktop releases, which do not dispatch a DOM click/key event.
    for(const release of ['left','Escape','desktop','blur']){
      if(!await captured())await enter();
      await value(()=>seek(1.5));
      const chosen=await pose();
      await page.keyboard.press('Space');await wait(()=>state.playing&&state.previewTime>1.6);
      if(release==='left'){await page.mouse.down();await page.mouse.up();}
      else if(release==='Escape')await page.keyboard.press('Escape');
      else if(release==='desktop')await value(()=>{
        const p=replayPreviewPane;p.flightHost=window.flightHostFixture;
        try{p.flightHost.dispatchEvent(new MessageEvent('message',{data:{type:'flight-state',id:p.flightRequest,active:false}}));}
        finally{p.flightHost=null;}
      });
      else await value(()=>window.dispatchEvent(new Event('blur')));
      await wait(()=>!replayPreviewPane.flying&&!document.pointerLockElement);
      assert.equal(await value(()=>state.playing),false,`${release} must pause playback before releasing flight`);
      const frozenTime=await value(()=>state.previewTime);
      assert.deepEqual(await pose(),chosen,`${release} must preserve the chosen camera`);
      await page.waitForTimeout(200);
      assert.equal(await value(()=>state.previewTime),frozenTime,`${release} must cancel the next playback frame`);
      assert.deepEqual(await pose(),chosen,`${release} must not lose the camera on a later frame`);
      assert.equal(await page.locator('#previewFlightHud').isVisible(),false);
      assert.equal(await page.locator('#previewOverride').isVisible(),true);
      assert.deepEqual(await value(()=>state.tracks),before.tracks);
      assert.equal(await value(()=>state.dirty),before.dirty);
    }
    assert.equal(await value(()=>window.flightHostMessages.at(-1)?.action),'stop');
    // stopFlight also runs during ordinary playback updates; that must not
    // pause playback when there was no flight capture to release.
    const outsideTime=await value(()=>state.previewTime);
    await page.keyboard.press('Space');
    await page.waitForFunction(t=>state.playing&&state.previewTime>t+.1,outsideTime);
    assert.equal(await value(()=>replayPreviewPane.override),null);
    await page.keyboard.press('Space');await wait(()=>!state.playing);
    await value(()=>seek(1));assert.equal(await value(()=>replayPreviewPane.override),null,'normal seeking outside flight must still evaluate the path');
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
    const result={passed:true,boundReplayWithoutPicker:true,repeatedLaunch:true,connectionBesideLaunch:true,realPointerLock:true,movement:true,zoom:true,resetBehindPlayer:true,recorderClockAndHeading:true,resetClearsInertia:true,flightContinuesAfterReset:true,missingRecorderPreservesPose:true,flightPlaybackToggle:true,flightFrameStepping:true,flightHeldSeekAcceleration:true,flightSeekStopsAtEnds:true,flightRollZC:true,flightMovementDuringPlayback:true,flightPreservedAtEndAndLoop:true,exitPreservesPose:true,playingExitPausesAndPreservesPose:true,desktopReleasePauses:true,normalPlaybackStillWorks:true,shortcutsIsolated:true,recordSevenAttributes:true,releaseOnBlurAndViewSwitch:true,errors};
    fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
  }catch(error){await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});console.error(await value(()=>({flight:replayPreviewPane?.flying,pending:replayPreviewPane?.flightPending,status:document.getElementById('previewStatus').textContent})),errors);throw error;}
  finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
