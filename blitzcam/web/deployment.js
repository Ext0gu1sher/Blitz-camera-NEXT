/* One offline deployment entry, with no edition-specific navigation. */
(() => {
  const $=id=>document.getElementById(id);
  let pending=null,busy=false,restarting=false,options=null;
  function message(text,error=false){$('deploymentResult').textContent=text;$('deploymentResult').classList.toggle('error',error);}
  function lock(){
    $('deploymentChoose').disabled=$('deploymentExport').disabled=busy||restarting;
    $('deploymentInstall').disabled=busy||restarting||!pending;
    $('deploymentPanel').setAttribute('aria-busy',String(busy));
  }
  function edition(value){
    const enabled=value==='pro';document.body.classList.toggle('edition-pro',enabled);
    const brand=document.querySelector('.tb-brand .brand-next');
    if(brand){brand.textContent=enabled?'Pro':'NEXT';brand.classList.toggle('brand-pro',enabled);}
    const changed=document.body.dataset.edition!==value;document.body.dataset.edition=value;
    if(changed)window.chrome?.webview?.postMessage({command:'edition',enabled});
  }
  async function refresh(){
    if(!options)return;
    try{
      const value=await options.api('/api/deployment');
      $('deploymentVersion').textContent=value.version;edition(value.edition);
      restarting=!!value.restart_pending;
      if(!pending&&!busy)message(value.message||value.last_result?.message||'选择发布者提供的升级包，在本机完成部署。',!!value.message||value.last_result?.ok===false);
      lock();
    }catch(error){message(error.message,true);}
  }
  async function run(fn){
    if(busy||restarting)return;busy=true;lock();
    try{await fn();}catch(error){message(error.message,true);}finally{busy=false;lock();}
  }
  function mount(value){
    options=value;
    $('deploymentChoose').onclick=()=>run(async()=>{
      message('正在选择并检查升级包…');
      pending=null;$('deploymentPreview').hidden=true;
      const selected=await options.api('/api/deployment/select',{}, {timeout:0});
      if(selected.cancelled){message('已取消选择。');return;}
      pending=selected;
      $('deploymentName').textContent=selected.name;
      $('deploymentTarget').textContent=selected.version;
      $('deploymentSize').textContent=(selected.bytes/1024/1024).toFixed(2)+' MB';
      $('deploymentNotes').textContent=selected.notes||'此升级包没有附加说明。';
      $('deploymentInstall').textContent=selected.restart?'部署并重启':'部署升级包';
      $('deploymentPreview').hidden=false;
      message(selected.restart?'检查通过。部署会保存当前项目并重启应用。':'检查通过，可以部署。');
    });
    $('deploymentExport').onclick=()=>run(async()=>{
      message('正在导出配置…');
      const result=await options.api('/api/deployment/export',{}, {timeout:0});
      message(result.cancelled?'已取消导出。':result.message);
    });
    $('deploymentInstall').onclick=()=>run(async()=>{
      if(!pending)return;
      await options.save();message('正在部署升级包…');
      const result=await options.api('/api/deployment/install',{token:pending.token},{timeout:0});
      pending=null;$('deploymentPreview').hidden=true;message(result.message);
      restarting=!!result.restart;
      if(restarting)options.close();
      else if(result.reload)location.reload();
      else{
        if(result.edition)edition(result.edition);
        if(result.restart_failed){restarting=true;message(result.message,true);}
        else await options.refresh();
      }
    });
    lock();
  }
  window.BlitzDeployment={mount,refresh,edition};
})();
