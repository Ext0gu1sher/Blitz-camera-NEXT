(() => {
  'use strict';
  const $=id=>document.getElementById(id),bridge=window.chrome?.webview;
  let next=0,busy=false,model={settings:{},masters:[],devices:[],history:[]},current='',selected=new Set(),lastBatch=null;
  const requests=new Map();
  function rpc(action,value={}){
    if(!bridge)return Promise.reject(Error('请通过 Pro Studio 桌面应用打开。'));
    return new Promise((resolve,reject)=>{const id=++next;requests.set(id,{resolve,reject});bridge.postMessage({id,action,value});});
  }
  bridge?.addEventListener('message',event=>{
    const message=event.data,request=requests.get(message?.id);if(!request)return;requests.delete(message.id);
    if(message.ok)request.resolve(message.result);else request.reject(Error(message.error||'操作未完成。'));
  });
  function status(text,error=false){$('status').textContent=text;$('status').classList.toggle('error',error);}
  function locks(){
    document.body.classList.toggle('busy',busy);$('status').classList.toggle('busy',busy);
    document.querySelectorAll('button,input,select').forEach(element=>element.disabled=busy);
    $('issueBatch').disabled=$('checkBatch').disabled=busy||!current||!selected.size;
    $('inspectMaster').disabled=busy||!current;
  }
  async function run(text,fn){if(busy)return;busy=true;status(text);locks();try{await fn();}catch(error){status(error.message,true);}finally{busy=false;locks();}}
  const choose=async(kind,initial='')=>rpc('dialog',{kind,initial});
  function page(name){
    const names={issue:'批量发包',make:'制作母包',history:'发布记录',settings:'发布设置'};
    document.querySelectorAll('[data-tab]').forEach(button=>{button.classList.toggle('active',button.dataset.tab===name);button.setAttribute('aria-current',button.dataset.tab===name?'page':'false');});
    for(const key of Object.keys(names))$(key+'Page').hidden=key!==name;
    $('pageTitle').textContent=names[name];document.body.dataset.page=name;window.scrollTo(0,0);
  }
  function renderMaster(){
    const master=model.masters.find(m=>m.master_id===current);
    $('masterEmpty').hidden=!!master;$('masterDetails').hidden=!master;
    if(!master)return;
    $('masterVersion').textContent=master.version;$('clientVersion').textContent=master.client.version+' · '+master.client.architecture;
    $('clientChannel').textContent=master.client.channel;$('hostVersion').textContent=master.host_min_version;
    $('masterComposition').textContent=`${master.checks.modules} 个模块 · ${master.checks.native_dlls} 个原生组件`;
    $('masterIdentity').textContent=master.master_id;
    $('masterNotes').textContent=master.notes;$('validationSummary').textContent=master.validation.summary;
    $('validationLevel').textContent=master.validation.level==='game'?'已记录游戏验证':'离线验证';$('validationLevel').classList.toggle('verified',master.validation.level==='game');
  }
  function count(){
    $('selectionCount').textContent=`已选 ${selected.size} / ${model.devices.length} 台设备`;
    $('selectAll').checked=!!model.devices.length&&selected.size===model.devices.length;
    $('selectAll').indeterminate=selected.size>0&&selected.size<model.devices.length;locks();
  }
  function renderDevices(){
    const list=$('deviceList');list.replaceChildren();
    for(const device of model.devices){
      const row=document.createElement('div');row.className='device-row';row.dataset.device=device.device;
      const label=document.createElement('label'),input=document.createElement('input'),info=document.createElement('span'),name=document.createElement('strong'),description=document.createElement('small');
      input.type='checkbox';input.checked=selected.has(device.device);input.setAttribute('aria-label','选择 '+device.name);
      input.onchange=()=>{if(input.checked)selected.add(device.device);else selected.delete(device.device);count();};
      name.textContent=device.name;description.textContent=device.device.slice(0,12)+' · 主程序 '+device.app_version+' · '+(device.protection==='tpm'?'TPM':'Windows 用户');
      info.append(name,description);label.append(input,info);
      const remove=document.createElement('button');remove.textContent='移除';remove.title='从配置库移除';remove.onclick=()=>run('正在移除配置…',async()=>{await rpc('remove_device',{device:device.device});selected.delete(device.device);await refresh();status('已从配置库移除，原配置文件保持原样。');});
      row.append(label,remove);list.append(row);
    }
    $('deviceEmpty').hidden=!!model.devices.length;count();
  }
  function renderHistory(){
    const list=$('historyList');list.replaceChildren();$('historyEmpty').hidden=!!model.history.length;
    for(const batch of model.history){
      const card=document.createElement('section');card.className='card history-card';
      const heading=document.createElement('div');heading.className='card-heading';
      const title=document.createElement('h2');title.textContent=batch.version;
      const open=document.createElement('button');open.className='secondary';open.textContent='打开文件夹';open.onclick=()=>run('正在打开输出文件夹…',async()=>{await rpc('open_folder',{path:batch.directory});status('已打开输出文件夹。');});heading.append(title,open);
      const meta=document.createElement('div');meta.className='history-meta';
      for(const value of [new Date(batch.created_at).toLocaleString('zh-CN'),`${batch.recipients.length} 台设备`,batch.client.channel+' '+batch.client.version]){const span=document.createElement('span');span.textContent=value;meta.append(span);}
      const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='查看设备与包文件';details.append(summary);
      for(const row of batch.recipients){const line=document.createElement('div');line.textContent=(row.name||row.config)+' → '+row.filename;details.append(line);}
      card.append(heading,meta,details);list.append(card);
    }
  }
  async function refresh(){
    model=await rpc('state');
    const select=$('masterSelect');select.replaceChildren();
    if(!model.masters.length){const option=document.createElement('option');option.value='';option.textContent='请导入 .bcpro 母包';select.append(option);current='';}
    else{
      if(!model.masters.some(m=>m.master_id===current))current=model.masters[0].master_id;
      for(const master of model.masters){const option=document.createElement('option');option.value=master.master_id;option.textContent=master.version+' · '+master.client.channel;select.append(option);}select.value=current;
    }
    selected=new Set([...selected].filter(id=>model.devices.some(d=>d.device===id)));
    for(const [id,key] of [['keyPath','key_path'],['trustPath','trust_path'],['outputDirectory','output_dir'],['recipePath','recipe_path']])$(id).value=model.settings[key]||'';
    $('issueOutput').textContent=model.settings.output_dir||'请在发布设置中选择';
    renderMaster();renderDevices();renderHistory();document.body.dataset.ready='true';
  }
  document.querySelectorAll('[data-tab]').forEach(button=>button.onclick=()=>page(button.dataset.tab));
  $('masterSelect').onchange=()=>{current=$('masterSelect').value;renderMaster();count();};
  $('selectAll').onchange=()=>{selected=$('selectAll').checked?new Set(model.devices.map(d=>d.device)):new Set();renderDevices();};
  $('importMaster').onclick=()=>run('请选择适配母包…',async()=>{const value=await choose('master');if(value.cancelled){status('已取消。');return;}const master=await rpc('import_master',{path:value.paths[0]});current=master.master_id;await refresh();status('母包已校验并保存，可重复为不同设备发包。');});
  $('importConfigs').onclick=()=>run('请选择用户配置，可多选…',async()=>{const value=await choose('configs');if(value.cancelled){status('已取消。');return;}const old=new Set(model.devices.map(d=>d.device));const rows=await rpc('import_configs',{paths:value.paths});for(const row of rows)if(!old.has(row.device))selected.add(row.device);await refresh();status('配置已保存，重复设备已合并。');});
  $('inspectMaster').onclick=()=>run('正在校验母包…',async()=>{await rpc('inspect',{master_id:current});status('母包内容、模块入口、原生组件哈希与架构检查通过。检查过程未执行适配代码。');});
  $('chooseOutput').onclick=()=>run('请选择输出文件夹…',async()=>{const value=await choose('folder',model.settings.output_dir);if(value.cancelled){status('已取消。');return;}await rpc('settings',{output_dir:value.paths[0]});await refresh();status('输出文件夹已保存。');});
  $('checkBatch').onclick=()=>run('正在检查母包、用户配置与发布密钥…',async()=>{const value=await rpc('check',{master_id:current,devices:[...selected]});status(`检查通过：${value.version}，${value.count} 台设备。可以生成加密升级包。`);});
  $('issueBatch').onclick=()=>run('正在逐个加密并验证升级包，请稍候…',async()=>{
    lastBatch=await rpc('issue',{master_id:current,devices:[...selected]});
    $('batchResult').hidden=false;$('batchSummary').textContent=`${lastBatch.version} · 已生成 ${lastBatch.recipients.length} 个设备专属升级包。`;
    $('batchFiles').replaceChildren();for(const row of lastBatch.recipients){const line=document.createElement('div');line.textContent=(row.name||row.config)+' → '+row.filename;$('batchFiles').append(line);}
    await refresh();status('全部升级包已生成并验签，发布记录已保存。');
  });
  $('openBatch').onclick=()=>run('正在打开输出文件夹…',async()=>{await rpc('open_folder',{path:lastBatch.directory});status('已打开输出文件夹。');});
  $('chooseRecipe').onclick=()=>run('请选择适配源码清单…',async()=>{const value=await choose('recipe',$('recipePath').value);if(value.cancelled){status('已取消。');return;}$('recipePath').value=value.paths[0];await rpc('settings',{recipe_path:value.paths[0]});status('已选择源码清单。');});
  $('chooseMasterOutput').onclick=()=>run('请选择母包保存位置…',async()=>{const value=await choose('save_master',$('masterOutput').value);if(value.cancelled){status('已取消。');return;}$('masterOutput').value=value.paths[0];status('已选择母包保存位置。');});
  $('makeMaster').onclick=()=>run('正在检查适配组成并制作母包…',async()=>{if(!$('recipePath').value||!$('masterOutput').value)throw Error('请先选择源码清单和新的母包保存位置。');const value=await rpc('create',{recipe:$('recipePath').value,output:$('masterOutput').value});current=value.master_id;await refresh();page('issue');status('母包已制作并加入版本库。可以导入用户配置并加密发包。');});
  document.querySelectorAll('[data-pick]').forEach(button=>button.onclick=()=>run('请选择文件或文件夹…',async()=>{const value=await choose(button.dataset.kind,$(button.dataset.pick).value);if(value.cancelled){status('已取消。');return;}$(button.dataset.pick).value=value.paths[0];status('已选择，保存设置后生效。');}));
  async function save(){return rpc('settings',{key_path:$('keyPath').value,trust_path:$('trustPath').value,output_dir:$('outputDirectory').value});}
  $('saveSettings').onclick=()=>run('正在保存…',async()=>{await save();await refresh();status('发布设置已保存。');});
  $('verifyKey').onclick=()=>run('正在验证发布身份…',async()=>{await save();const value=await rpc('verify_key');$('keyResult').textContent=value.signer;status(value.message);});
  $('backupKey').onclick=()=>run('请选择加密备份保存位置…',async()=>{
    const password=$('backupPassword').value;if(password.length<16||password!==$('backupConfirm').value)throw Error('请输入至少 16 字符的口令，并确认两次输入一致。');
    const value=await choose('backup');if(value.cancelled){status('已取消。');return;}await save();const result=await rpc('backup_key',{path:value.paths[0],password});$('backupPassword').value=$('backupConfirm').value='';status(result.message);
  });
  $('restoreKey').onclick=()=>run('请选择加密备份…',async()=>{const password=$('backupPassword').value;if(!password)throw Error('请先输入备份口令。');const value=await choose('restore');if(value.cancelled){status('已取消。');return;}await save();const result=await rpc('restore_key',{path:value.paths[0],password});$('backupPassword').value=$('backupConfirm').value='';status(result.message);});
  page('issue');run('正在读取母包与用户配置…',async()=>{await refresh();status('选择母包与用户配置，即可开始离线发包。');});
})();
