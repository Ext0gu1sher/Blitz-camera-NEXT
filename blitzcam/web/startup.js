/* Local startup choreography; readiness comes from the actual workbench. */
(()=>{
  'use strict';
  const root=document.getElementById('appSplash'),$=s=>root.querySelector(s),$$=s=>[...root.querySelectorAll(s)];
  const pro=()=>root.dataset.edition==='pro',introToken=pro()?document.documentElement.dataset.proIntro:'';
  const ease='cubic-bezier(.22,1,.36,1)',expo='cubic-bezier(.16,1,.3,1)';
  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  const started=performance.now(),minimum=reduced?250:pro()?(introToken?2600:1600):2550;
  const content=[...document.body.children].filter(el=>el!==root&&el instanceof HTMLElement&&el.tagName!=='SCRIPT');
  content.forEach(el=>el.inert=true);
  let check=null,timer=null,done=false,revealing=false,forcedError=null,readySince=null;
  function animate(target,frames,options={}){
    const el=typeof target==='string'?$(target):target;
    return el.animate(frames,{fill:'both',easing:'cubic-bezier(.22,1,.36,1)',...options});
  }
  const sfx=(()=>{
    let ctx=null,master,verb,bus=null,noiseBuf,enabled=document.documentElement.dataset.startupSound!=='false',t0=0;
    function init(){
      if(!enabled)return;
      try{
      if(!ctx){
        ctx=new AudioContext();
        master=ctx.createGain();master.gain.value=.5;
        const comp=ctx.createDynamicsCompressor();comp.threshold.value=-14;comp.ratio.value=4;
        master.connect(comp).connect(ctx.destination);
        const len=ctx.sampleRate*1.8,ir=ctx.createBuffer(2,len,ctx.sampleRate);
        for(let c=0;c<2;c++){const d=ir.getChannelData(c);for(let i=0;i<len;i++)d[i]=(Math.random()*2-1)*Math.pow(1-i/len,3.2);}
        verb=ctx.createConvolver();verb.buffer=ir;
        noiseBuf=ctx.createBuffer(1,ctx.sampleRate,ctx.sampleRate);
        const n=noiseBuf.getChannelData(0);for(let i=0;i<n.length;i++)n[i]=Math.random()*2-1;
      }
      if(ctx.state!=='running')ctx.resume().catch(stop);
      // A normal browser may block autoplay. Never play queued cues on a later click.
      setTimeout(()=>{if(ctx&&ctx.state!=='running')stop();},250);
      }catch(_){stop();}
    }
    function start(){
      if(bus){const old=bus;old.gain.setTargetAtTime(0,ctx.currentTime,.03);setTimeout(()=>old.disconnect(),300);}
      bus=null;if(!ctx||!enabled)return;
      bus=ctx.createGain();bus.connect(master);verb.connect(bus);t0=ctx.currentTime+.04;
    }
    function stop(){
      if(!ctx)return;
      const old=ctx;ctx=null;bus=null;
      old.close().catch(()=>{});
    }
    const at=ms=>t0+ms/1000;
    function out(node,pan=0,panTo=pan,t=0,dur=0,wet=0){
      const p=ctx.createStereoPanner();p.pan.setValueAtTime(pan,t);if(panTo!==pan)p.pan.linearRampToValueAtTime(panTo,t+dur);
      node.connect(p);p.connect(bus);
      if(wet){const g=ctx.createGain();g.gain.value=wet;p.connect(g).connect(verb);}
    }
    function env(t,peak,attack,decay){const g=ctx.createGain();g.gain.setValueAtTime(0.0001,t);g.gain.exponentialRampToValueAtTime(peak,t+attack);g.gain.exponentialRampToValueAtTime(0.0001,t+attack+decay);return g;}
    function noise(t,dur){const s=ctx.createBufferSource();s.buffer=noiseBuf;s.loop=true;s.start(t,Math.random());s.stop(t+dur+.05);return s;}
    const api={
      // Air movement for text sliding in; pans with the motion.
      whoosh(ms,{dur=.4,from=350,to=2800,gain=.3,pan=0,panTo=0,wet=.15}={}){
        if(!bus)return;const t=at(ms),f=ctx.createBiquadFilter();f.type='bandpass';f.Q.value=1.1;
        f.frequency.setValueAtTime(from,t);f.frequency.exponentialRampToValueAtTime(to,t+dur*.7);
        const g=ctx.createGain();g.gain.setValueAtTime(0.0001,t);g.gain.exponentialRampToValueAtTime(gain,t+dur*.55);g.gain.exponentialRampToValueAtTime(0.0001,t+dur);
        noise(t,dur).connect(f).connect(g);out(g,pan,panTo,t,dur,wet);
      },
      // Punchy low hit for cuts and the Pro stamp.
      hit(ms,{gain=.7,freq=140,end=42,decay=.45,wet=.25}={}){
        if(!bus)return;const t=at(ms),o=ctx.createOscillator();o.frequency.setValueAtTime(freq,t);o.frequency.exponentialRampToValueAtTime(end,t+.22);
        const g=env(t,gain,.004,decay);o.connect(g);o.start(t);o.stop(t+decay+.1);out(g,0,0,t,0,wet);
        const f=ctx.createBiquadFilter();f.type='highpass';f.frequency.value=2500;const c=env(t,gain*.35,.001,.05);noise(t,.08).connect(f).connect(c);out(c,0,0,t,0,wet);
      },
      // Short dry click for single characters landing.
      tick(ms,{freq=1700,gain=.16,pan=0}={}){
        if(!bus)return;const t=at(ms),f=ctx.createBiquadFilter();f.type='bandpass';f.frequency.value=freq;f.Q.value=4;
        const g=env(t,gain,.001,.07);noise(t,.1).connect(f).connect(g);out(g,pan,pan,t,0,.12);
        const o=ctx.createOscillator();o.type='triangle';o.frequency.setValueAtTime(freq/3,t);o.frequency.exponentialRampToValueAtTime(freq/6,t+.08);
        const og=env(t,gain*.6,.001,.08);o.connect(og);o.start(t);o.stop(t+.15);out(og,pan,pan,t,0,0);
      },
      // Noise rising into the flash before the logo.
      riser(ms,dur,{gain=.22}={}){
        if(!bus)return;const t=at(ms),d=dur/1000,f=ctx.createBiquadFilter();f.type='highpass';
        f.frequency.setValueAtTime(300,t);f.frequency.exponentialRampToValueAtTime(7000,t+d);
        const g=ctx.createGain();g.gain.setValueAtTime(0.0001,t);g.gain.exponentialRampToValueAtTime(gain,t+d);g.gain.setValueAtTime(0.0001,t+d+.01);
        noise(t,d).connect(f).connect(g);out(g,0,0,t,0,.3);
      },
      // 808-style sub drop when "Pro" lands: a short low swell sucks in, then a
      // gliding sine with a saturated copy so it still reads on laptop speakers.
      sub(ms,{gain=.95,freq=64,end=33,decay=1.9,pre=.22}={}){
        if(!bus)return;const t=at(ms);
        if(pre){
          const s=t-pre,f=ctx.createBiquadFilter();f.type='lowpass';f.frequency.setValueAtTime(200,s);f.frequency.exponentialRampToValueAtTime(1100,t);
          const g=ctx.createGain();g.gain.setValueAtTime(0.0001,s);g.gain.exponentialRampToValueAtTime(.16,t-.005);g.gain.setValueAtTime(0.0001,t);
          noise(s,t-s).connect(f).connect(g);out(g);
        }
        const o=ctx.createOscillator();o.frequency.setValueAtTime(freq*1.6,t);o.frequency.exponentialRampToValueAtTime(freq,t+.06);o.frequency.exponentialRampToValueAtTime(end,t+decay*.6);
        const body=env(t,gain,.006,decay);o.connect(body);out(body,0,0,t,0,.12);
        const drive=ctx.createWaveShaper(),curve=new Float32Array(1024);
        for(let i=0;i<curve.length;i++){const x=i/511.5-1;curve[i]=Math.tanh(x*3.2);}
        drive.curve=curve;
        const lp=ctx.createBiquadFilter();lp.type='lowpass';lp.frequency.value=420;
        const grit=env(t,gain*.32,.006,decay*.55);o.connect(drive).connect(lp).connect(grit);out(grit);
        const o2=ctx.createOscillator();o2.frequency.setValueAtTime(freq*2,t);o2.frequency.exponentialRampToValueAtTime(end*2,t+.4);
        const punch=env(t,gain*.22,.003,.35);o2.connect(punch);out(punch);
        o.start(t);o.stop(t+decay+.1);o2.start(t);o2.stop(t+.5);
      },
      // Re-anchor the timeline (for the exit) without cutting sounds still ringing.
      cue(){if(bus)t0=ctx.currentTime+.01;else start();},
      start,init,stop
    };
    return api;
  })();
  // A shot is on screen only for [start,end): hard cuts, like an edit.
  const shot=(sel,start,end)=>animate(sel,[{opacity:1},{opacity:1}],{duration:end-start,delay:start,fill:end===Infinity?'forwards':'none',easing:'linear'});

  function playNext(){
    animate('.bc-halo',[{opacity:0},{opacity:1}],{duration:1300});
    animate('.bc-safe-frame',[{opacity:0,transform:'scale(1.025)'},{opacity:.7,transform:'scale(1)'}],{duration:1300,delay:180});
    animate('.bc-focus',[{opacity:0,transform:'scale(2.3)',filter:'blur(3px)'},{opacity:1,transform:'scale(.94)',filter:'blur(0px)',offset:.72},{opacity:.78,transform:'scale(1)',filter:'blur(0px)'}],{duration:1000,delay:100});
    animate('.bc-symbol-inner',[{opacity:0,transform:'translateY(8px) scale(.85)',filter:'blur(5px)'},{opacity:1,transform:'translateY(0) scale(1)',filter:'blur(0px)'}],{duration:750,delay:540});
    animate('.bc-glyph',[{transform:'rotate(-50deg) scale(.82)'},{transform:'rotate(0deg) scale(1)'}],{duration:1000,delay:540});
    animate('.bc-focus-dot',[{opacity:0},{opacity:.8,offset:.3},{opacity:0}],{duration:600,delay:900});
    animate('.bc-wordmark>span',[{opacity:0,transform:'translateY(110%)',letterSpacing:'1px'},{opacity:1,transform:'translateY(0)',letterSpacing:'-1.5px'}],{duration:820,delay:820});
    $$('.bc-next>span').forEach((el,i)=>animate(el,[{opacity:0,transform:'translateY(8px)'},{opacity:1,transform:'translateY(0)'}],{duration:520,delay:1260+i*75}));
    animate('.bc-loading',[{opacity:0,transform:'translate(-50%,5px)'},{opacity:1,transform:'translate(-50%,0)'}],{duration:600,delay:1480});
    animate('.bc-footnote',[{opacity:0},{opacity:1}],{duration:900,delay:1350});
  }

  // first: the full PV, played once after an upgrade package is installed.
  // Otherwise the launch starts straight at the logo shot.
  function playPro(first){
    const T1=0,T2=620,T3=1080,T4=first?1720:0;
    if(first)playIntro(T1,T2,T3,T4);
    playLogo(T4);
  }

  function playIntro(T1,T2,T3,T4){
    sfx.whoosh(T1,{dur:.45,pan:.7,panTo:0,gain:.32});
    [0,1,2].forEach(i=>sfx.tick(T1+150+i*55,{freq:1500+i*150,pan:.25-i*.12}));
    sfx.whoosh(T1+220,{dur:.28,from:1800,to:6500,gain:.12,pan:-.5,panTo:.5});
    sfx.whoosh(T2-70,{dur:.12,from:600,to:3000,gain:.22});
    sfx.hit(T2,{gain:.9,freq:120,end:36,decay:.6});
    [0,1,2].forEach(i=>sfx.tick(T3+70+i*85,{freq:1900+i*260,gain:.2}));
    sfx.whoosh(T3+260,{dur:.3,from:900,to:5000,gain:.12,pan:-.4,panTo:.4});
    sfx.riser(T3+200,T4-T3-200);
    sfx.hit(T4-20,{gain:1,freq:90,end:30,decay:.9,wet:.4});

    // Shot 1 — 每一帧: characters slam in from the right, camera creeps forward.
    shot('.s1',T1,T2);
    animate('.s1 .pv-cam',[{transform:'scale(1)'},{transform:'scale(1.1)'}],{duration:T2-T1,delay:T1,easing:'linear'});
    $$('.s1 .pv-big>span').forEach((el,i)=>animate(el,[{transform:'translateX(70vw) skewX(-14deg)',opacity:0},{transform:'translateX(0) skewX(0)',opacity:1}],{duration:520,delay:T1+40+i*55,easing:expo}));
    animate('.s1 .pv-rule',[{transform:'scaleX(0)'},{transform:'scaleX(1)'}],{duration:420,delay:T1+220,easing:expo});
    animate('.s1 .pv-cap',[{transform:'translateX(-3em)',opacity:0},{transform:'translateX(0)',opacity:1}],{duration:480,delay:T1+260,easing:expo});

    // Shot 2 — 都是: pink card wipes on diagonally, type punches down from huge.
    shot('.s2',T2,T3);
    animate('.s2',[{clipPath:'polygon(0 0,0 0,-25% 100%,-25% 100%)'},{clipPath:'polygon(0 0,125% 0,100% 100%,-25% 100%)'}],{duration:200,delay:T2,easing:'cubic-bezier(.5,0,.2,1)'});
    animate('.s2 .pv-cam',[{transform:'rotate(-6deg) scale(2.4)'},{transform:'rotate(-6deg) scale(1)',offset:.55},{transform:'rotate(-6deg) scale(1.07)'}],{duration:T3-T2,delay:T2,easing:'linear'});
    animate('.s2 .pv-cam',[{filter:'blur(6px)'},{filter:'blur(0)'}],{duration:220,delay:T2,easing:expo});
    animate('.s2 .pv-cap',[{opacity:0,transform:'translateY(-1em)'},{opacity:1,transform:'none'}],{duration:300,delay:T2+160,easing:expo});

    // Shot 3 — 名场面: characters drop out of soft focus one by one, then the
    // camera dives through the word into the logo.
    shot('.s3',T3,T4);
    $$('.s3 .pv-big>span').forEach((el,i)=>animate(el,[{transform:'translateY(-.5em) scale(1.7)',filter:'blur(14px)',opacity:0},{transform:'none',filter:'blur(0)',opacity:1}],{duration:420,delay:T3+i*85,easing:expo}));
    animate('.s3 .pv-block',[{transform:'scaleX(0)'},{transform:'scaleX(1)'}],{duration:380,delay:T3+260,easing:expo});
    animate('.s3 .pv-cap',[{opacity:0,letterSpacing:'1.4em'},{opacity:1,letterSpacing:'.6em'}],{duration:500,delay:T3+300,easing:expo});
    animate('.s3 .pv-cam',[{transform:'scale(1)',filter:'blur(0)'},{transform:'scale(1.12)',filter:'blur(0)',offset:.72},{transform:'scale(3.2)',filter:'blur(10px)'}],{duration:T4-T3,delay:T3,easing:'cubic-bezier(.5,0,.9,.4)'});

    // Cut flash.
    animate('.pv-flash',[{opacity:0},{opacity:.55,offset:.2},{opacity:0}],{duration:260,delay:T4-40,easing:'ease-out'});
  }

  function playLogo(T4){
    sfx.whoosh(T4+20,{dur:.5,pan:-.85,panTo:-.1,gain:.3,from:300,to:2400});
    sfx.whoosh(T4+70,{dur:.5,pan:.85,panTo:.1,gain:.3,from:320,to:2600});
    sfx.hit(T4+380,{gain:.45,freq:180,end:70,decay:.18,wet:.1});
    sfx.sub(T4+380);

    // Shot 4 — logo: words slide in from opposite sides while the camera pulls back.
    shot('.s4',T4,Infinity);
    animate('.s4 .pv-ghost',[{transform:'translate(-50%,-50%) scale(1.35)',opacity:0},{transform:'translate(-50%,-50%) scale(1)',opacity:1}],{duration:1600,delay:T4,easing:expo});
    animate('.s4 .pv-ghost',[{marginLeft:'3vw'},{marginLeft:'-3vw'}],{duration:9000,delay:T4,easing:'linear'});
    animate('.s4 .pv-cam',[{transform:'translate(-50%,-50%) scale(1.22)'},{transform:'translate(-50%,-50%) scale(1)'}],{duration:1500,delay:T4,easing:expo});
    animate('.pv-glyph',[{transform:'rotate(-180deg) scale(0)'},{transform:'rotate(0) scale(1)'}],{duration:700,delay:T4,easing:expo});
    animate('.pv-w1',[{transform:'translateX(-40vw)',opacity:0},{transform:'translateX(0)',opacity:1}],{duration:700,delay:T4+30,easing:expo});
    animate('.pv-w2',[{transform:'translateX(40vw)',opacity:0},{transform:'translateX(0)',opacity:1}],{duration:700,delay:T4+80,easing:expo});
    animate('.pv-pro>i',[{transform:'skewX(-10deg) scaleX(0)'},{transform:'skewX(-10deg) scaleX(1)'}],{duration:300,delay:T4+380,easing:expo});
    animate('.pv-pro>b',[{opacity:0,transform:'translateY(.4em)'},{opacity:1,transform:'none'}],{duration:380,delay:T4+480,easing:expo});
    animate('.pv-pro',[{transform:'scale(1.35)'},{transform:'scale(1)'}],{duration:500,delay:T4+380,easing:expo});
    animate('.pv-logo-rule',[{transform:'scaleX(0)'},{transform:'scaleX(1)'}],{duration:900,delay:T4+520,easing:expo});
    animate('.bc-loading',[{opacity:0,transform:'translate(-50%,6px)'},{opacity:1,transform:'translate(-50%,0)'}],{duration:600,delay:T4+700});
    animate('.bc-footnote',[{opacity:0},{opacity:1}],{duration:800,delay:T4+800});
  }

  function showStatic(){
    if(pro()){
      $('.s4').style.opacity='1';
      $$('.pv-w1,.pv-w2,.pv-pro>b,.bc-loading,.bc-footnote').forEach(el=>el.style.opacity='1');
      $('.pv-pro>i').style.transform='skewX(-10deg)';$('.pv-logo-rule').style.transform='none';
      return;
    }
    $$('.bc-halo,.bc-safe-frame,.bc-focus,.bc-symbol-inner,.bc-wordmark>span,.bc-loading,.bc-footnote,.bc-next>span').forEach(el=>{el.style.opacity='1';el.style.transform=el.classList.contains('bc-loading')?'translateX(-50%)':'none';});
  }

  if(reduced)showStatic();
  else if(pro()){sfx.init();sfx.start();playPro(!!introToken);}
  else playNext();
  addEventListener('pagehide',()=>sfx.stop(),{once:true});

  async function reveal(){
    if(done||revealing)return;
    revealing=true;clearTimeout(timer);
    // Even the partial-failure Continue action respects the edition's minimum.
    await new Promise(resolve=>setTimeout(resolve,Math.max(0,minimum-(performance.now()-started))));
    root.dataset.ready='true';
    $('.bc-loading-label').textContent='准备就绪';root.setAttribute('aria-busy','false');
    // Keep the laid-out editor rendered while the opaque splash fades away.
    await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    document.body.classList.add('app-revealing');
    document.body.classList.remove('app-starting');
    if(pro()&&!reduced){
      const o={easing:'cubic-bezier(.76,0,.24,1)'};
      sfx.cue();
      sfx.whoosh(0,{dur:.42,pan:-.7,panTo:.3,gain:.28,from:250,to:3200});
      sfx.whoosh(380,{dur:.5,pan:-.2,panTo:.8,gain:.2,from:2000,to:600,wet:.3});
      animate('.s4 .pv-cam',[{transform:'translate(-50%,-50%) scale(1)'},{transform:'translate(-50%,-50%) scale(1.15)'}],{duration:380,...o});
      await animate('.pv-wipe',[{clipPath:'inset(0 100% 0 0)'},{clipPath:'inset(0 0 0 0)'}],{duration:380,...o}).finished;
      [...root.children].forEach(el=>{if(!el.classList.contains('pv-wipe'))el.style.visibility='hidden';});
      root.style.background='transparent';
      await animate('.pv-wipe',[{clipPath:'inset(0 0 0 0)'},{clipPath:'inset(0 0 0 100%)'}],{duration:460,...o}).finished;
    }else{
      await animate(root,[{opacity:1},{opacity:0}],{duration:reduced?150:700,easing:'cubic-bezier(.4,0,.2,1)'}).finished;
    }
    root.hidden=true;done=true;revealing=false;content.forEach(el=>el.inert=false);
    document.body.classList.remove('app-revealing');document.body.dataset.appReady='true';
    root.getAnimations({subtree:true}).forEach(a=>a.cancel());
    setTimeout(()=>sfx.stop(),300);
    // A GET/reload alone must not consume the upgrade animation.
    if(introToken)fetch('/api/deployment/startup-seen',{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:introToken}),keepalive:true
    }).catch(()=>{});
    dispatchEvent(new Event('blitz-app-ready'));
  }
  function update(){
    if(done||revealing)return;
    let status=forcedError||{message:'正在准备工作台'};
    try{if(!forcedError&&check)status=check();}catch(error){status={error:error.message};}
    const failed=!!status.error;
    root.dataset.failed=String(failed);$('.bc-error').hidden=!failed;
    $('.bc-error').textContent=status.error||'';$('.bc-error-actions').hidden=!failed;
    $('#startupContinue').hidden=!status.canEnter;
    $('.bc-loading-label').textContent=failed?'载入未完成':status.ready?'正在准备工作台':status.message||'正在准备工作台';
    if(status.ready&&!failed&&performance.now()-started>=minimum){
      if(readySince===null){readySince=performance.now();root.dataset.ready='true';}
      $('.bc-loading-label').textContent='准备就绪';
      if(performance.now()-readySince>=(reduced?0:350)){reveal();return;}
    }else{readySince=null;root.dataset.ready='false';}
    timer=setTimeout(update,100);
  }
  $('#startupRetry').addEventListener('click',()=>location.reload());
  $('#startupContinue').addEventListener('click',()=>{if(!$('#startupContinue').hidden)reveal();});
  const bridge=window.chrome?.webview;
  if(bridge){$('.bc-window').hidden=false;root.querySelectorAll('[data-window]').forEach(el=>el.addEventListener('click',()=>bridge.postMessage({command:'window',action:el.dataset.window})));}
  window.BlitzStartup={
    watch(fn){check=fn;},
    error(message,canEnter=false){if(!done&&!revealing){forcedError={error:message,canEnter};}},
    get active(){return !done;}
  };
  addEventListener('error',event=>{
    if(done||revealing)return;
    const source=event.target;
    if(source instanceof HTMLScriptElement||source instanceof HTMLLinkElement)window.BlitzStartup.error('工作台资源未能读取，请重新加载。');
    else if(event.message)window.BlitzStartup.error('工作台初始化失败：'+event.message);
  },true);
  addEventListener('unhandledrejection',event=>{if(!done&&!revealing)window.BlitzStartup.error('工作台初始化失败：'+(event.reason?.message||'请重新加载。'));});
  update();
})();
