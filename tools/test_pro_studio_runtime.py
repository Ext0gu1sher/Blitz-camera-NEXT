"""Exercise real WPF/WebView2 UI + packaged Python/CNG with isolated keys."""
import argparse
import base64
import json
from pathlib import Path
import subprocess
from uuid import uuid4

from blitzcam import package_crypto as crypto
from blitzcam.offline_updater import write_json
from blitzcam.packages import decrypt_pro, digest, read_signed
from publisher.master import create_master, read_master
from publisher.store import Studio
from tools.publish_updates import initialize

ROOT=Path(__file__).resolve().parents[1]


def run(executable):
    root=ROOT/'output'/('studio-runtime-'+uuid4().hex[:10]); root.mkdir()
    data=root/'data'; report=root/'report'; configs=[]; devices=[]
    try:
        key=root/'publisher.dpapi'; trust=root/'trust.json'; initialize(key,trust)
        master=root/'master.bcpro'; create_master(ROOT/'adapters/steam-international-11.21/adapter.json',master)
        bad=root/'invalid.bcpro'; bad.write_bytes(b'invalid master')
        for label in ('测试用户甲','测试用户乙'):
            name='BlitzCamera-Studio-Runtime-Test-'+uuid4().hex; provider='Microsoft Software Key Storage Provider'
            public=crypto.device_public(name,provider,create=True); identity=digest(public)
            devices.append({'key_name':name,'provider':provider,'device':identity})
            path=root/(label+'.bcconfig'); configs.append(str(path))
            write_json(path,{'format':'blitz-camera-device-v1','api':1,'app_version':'0.9.6-beta','device':identity,
                             'public_key':base64.b64encode(public).decode(),'protection':'windows-user'})
        settings={'key_path':str(key),'trust_path':str(trust),'master_hint':str(master),
                  'output_dir':str(root/'batches'),'recipe_path':str(ROOT/'adapters/steam-international-11.21/adapter.json')}
        Studio(data).save_settings(settings)
        fixture={'configs':configs,'bad':str(bad),'recipe':settings['recipe_path'],'newMaster':str(root/'made-in-app.bcpro')}
        script=root/'interactions.js'
        script.write_text('const fixture='+json.dumps(fixture,ensure_ascii=False)+';\n'+r'''
(async()=>{
  const $=id=>document.getElementById(id), wait=ms=>new Promise(r=>setTimeout(r,ms));
  const assert=(ok,message)=>{if(!ok)throw Error(message);};
  async function until(fn,label){for(let i=0;i<200;i++){if(fn())return;await wait(100);}throw Error('timeout: '+label+' / '+$('status').textContent);}
  const pending=new Map();let sequence=1000000;
  window.chrome.webview.addEventListener('message',e=>{const p=pending.get(e.data?.id);if(p){pending.delete(e.data.id);e.data.ok?p.resolve(e.data.result):p.reject(Error(e.data.error));}});
  const rpc=(action,value={})=>new Promise((resolve,reject)=>{const id=++sequence;pending.set(id,{resolve,reject});window.chrome.webview.postMessage({id,action,value});});
  const idle=()=>until(()=>!document.body.classList.contains('busy'),'idle');
  function tab(name){document.querySelector(`[data-tab="${name}"]`).click();}
  try{
    await idle();assert($('masterVersion').textContent==='11.21-r1','master auto-import');
    assert($('issueBatch').disabled,'empty device guard');
    $('inspectMaster').click();await idle();assert($('status').textContent.includes('检查通过'),'static master validation');
    let rejected=false;try{await rpc('import_master',{path:fixture.bad});}catch(e){rejected=true;}assert(rejected,'invalid master rejection');
    tab('settings');$('verifyKey').click();await idle();assert($('status').textContent.includes('公钥一致'),'real packaged signing key');
    await rpc('import_configs',{paths:[...fixture.configs,fixture.configs[0]]});
    $('saveSettings').click();await idle();tab('issue');
    assert(document.querySelectorAll('.device-row').length===2,'device import deduplication');
    $('selectAll').click();assert(!$('issueBatch').disabled,'selection enables issue');
    $('selectAll').click();assert($('issueBatch').disabled,'empty selection disabled');$('selectAll').click();
    $('checkBatch').click();await idle();assert($('status').textContent.includes('检查通过'),'batch preflight');
    $('issueBatch').click();await idle();assert(!$('batchResult').hidden,'successful batch displayed');
    assert($('batchSummary').textContent.includes('2 个'),'two packages displayed');
    assert($('batchFiles').textContent.includes('测试用户甲'),'human recipient names');
    const state=await rpc('state');assert(state.history.length===1,'saved history');
    tab('history');assert(document.querySelectorAll('.history-card').length===1,'history rendered');
    tab('make');$('recipePath').value=fixture.recipe;$('masterOutput').value=fixture.newMaster;
    $('makeMaster').click();await idle();assert($('status').textContent.includes('母包已制作'),'make from recipe');
    assert($('masterSelect').options.length===1,'identical master merges');
    tab('issue');window.scrollTo(0,document.body.scrollHeight);
    assert(document.documentElement.scrollWidth<=innerWidth,'no horizontal overflow');
    window.__studioSmoke={ok:true,checks:14,batch:state.history[0].directory,recipients:2};
  }catch(e){window.__studioSmoke={error:e.stack||e.message};}
})();
''',encoding='utf-8')
        process=subprocess.run([str(executable),'--data',str(data),'--smoke',str(report),'--smoke-script',str(script)],timeout=240)
        if process.returncode: raise RuntimeError('Desktop test failed: '+str(report))
        interaction=json.loads((report/'interaction.json').read_text(encoding='utf-8-sig'))
        if not interaction.get('ok'): raise AssertionError(interaction)
        batch=json.loads((Path(interaction['batch'])/'batch.json').read_text(encoding='utf-8'))
        _,expected,_=read_master(master)
        for row in batch['recipients']:
            manifest,payload=read_signed(Path(interaction['batch'])/row['filename'],trust)
            device=next(d for d in devices if d['device']==row['device'])
            assert decrypt_pro(manifest,payload,device)==expected
        assert (root/'made-in-app.bcpro').read_bytes()==master.read_bytes()
        # Reopen the actual executable to check data persistence across processes.
        subprocess.run([str(executable),'--data',str(data),'--smoke',str(root/'reopen')],check=True,timeout=90)
        saved=Studio(data).state(); assert len(saved['devices'])==2 and len(saved['history'])==1
        result={'ok':True,'native_ui_checks':interaction['checks'],'encrypted_recipients':2,
                'restart_persistence':True,'made_master_identical':True,'report':str(report),'screenshot':str(report/'window.png')}
        write_json(root/'result.json',result); print(json.dumps(result,ensure_ascii=False,indent=2));return result
    finally:
        for device in devices:
            with crypto.device_key(device['key_name'],device['provider']) as (dll,keyhandle):
                crypto._check(crypto._fn(dll,'NCryptDeleteKey',[crypto.HANDLE,crypto.U32])(keyhandle,0),'清理测试密钥');keyhandle.value=0


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('executable',nargs='?',type=Path,default=ROOT/'dist/BlitzCameraProStudio-1.0.0/ProStudio.exe')
    run(parser.parse_args().executable.resolve())
