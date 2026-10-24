/* Local startup choreography; readiness comes from the actual workbench. */
(()=>{
  'use strict';
  const root=document.getElementById('appSplash'),$=s=>root.querySelector(s);
  const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
  const started=performance.now(),minimum=reduced?250:2550;
  const content=[...document.body.children].filter(el=>el!==root&&el instanceof HTMLElement&&el.tagName!=='SCRIPT');
  content.forEach(el=>el.inert=true);
  let check=null,timer=null,done=false,revealing=false,forcedError=null,readySince=null;
  function animate(target,frames,options={}){
    const el=typeof target==='string'?$(target):target;
    return el.animate(frames,{fill:'both',easing:'cubic-bezier(.22,1,.36,1)',...options});
  }
  if(reduced){
    for(const s of ['.bc-halo','.bc-safe-frame','.bc-focus','.bc-symbol-inner','.bc-wordmark>span','.bc-loading','.bc-footnote']){
      const el=$(s);el.style.opacity='1';el.style.transform=s==='.bc-loading'?'translateX(-50%)':'none';
    }
    root.querySelectorAll('.bc-next>span').forEach(el=>{el.style.opacity='1';el.style.transform='none';});
  }else{
    animate('.bc-halo',[{opacity:0},{opacity:1}],{duration:1300});
    animate('.bc-safe-frame',[{opacity:0,transform:'scale(1.025)'},{opacity:.7,transform:'scale(1)'}],{duration:1300,delay:180});
    animate('.bc-focus',[{opacity:0,transform:'scale(2.3)',filter:'blur(3px)'},{opacity:1,transform:'scale(.94)',filter:'blur(0px)',offset:.72},{opacity:.78,transform:'scale(1)',filter:'blur(0px)'}],{duration:1000,delay:100});
    animate('.bc-symbol-inner',[{opacity:0,transform:'translateY(8px) scale(.85)',filter:'blur(5px)'},{opacity:1,transform:'translateY(0) scale(1)',filter:'blur(0px)'}],{duration:750,delay:540});
    animate('.bc-glyph',[{transform:'rotate(-50deg) scale(.82)'},{transform:'rotate(0deg) scale(1)'}],{duration:1000,delay:540});
    animate('.bc-focus-dot',[{opacity:0},{opacity:.8,offset:.3},{opacity:0}],{duration:600,delay:900});
    animate('.bc-wordmark>span',[{opacity:0,transform:'translateY(110%)',letterSpacing:'1px'},{opacity:1,transform:'translateY(0)',letterSpacing:'-1.5px'}],{duration:820,delay:820});
    root.querySelectorAll('.bc-next>span').forEach((el,i)=>animate(el,[{opacity:0,transform:'translateY(8px)'},{opacity:1,transform:'translateY(0)'}],{duration:520,delay:1260+i*75}));
    animate('.bc-loading',[{opacity:0,transform:'translate(-50%,5px)'},{opacity:1,transform:'translate(-50%,0)'}],{duration:600,delay:1480});
    animate('.bc-footnote',[{opacity:0},{opacity:1}],{duration:900,delay:1350});
  }
  async function reveal(){
    if(done||revealing)return;
    revealing=true;clearTimeout(timer);root.dataset.ready='true';
    $('.bc-loading-label').textContent='准备就绪';root.setAttribute('aria-busy','false');
    // Keep the laid-out editor rendered while the opaque splash fades away.
    await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    document.body.classList.add('app-revealing');
    document.body.classList.remove('app-starting');
    const fade=animate(root,[{opacity:1},{opacity:0}],{duration:reduced?150:700,easing:'cubic-bezier(.4,0,.2,1)'});
    await fade.finished;
    root.hidden=true;done=true;revealing=false;content.forEach(el=>el.inert=false);
    document.body.classList.remove('app-revealing');document.body.dataset.appReady='true';
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
