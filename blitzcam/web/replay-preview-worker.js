import init,{parsePlayback,parseResult,parseAiReview} from './vendor/agent/wotb_replay_wasm.js';
let ready;
self.onmessage=async ({data})=>{
  try{
    if(!ready)ready=(async()=>{
      const f=await fetch('/vendor/agent/fingerprint.json').then(r=>r.json());
      if(f.tag!=='v0.4.11'||f.upstream_commit!=='0a9da93a0074a95af406db3468e6a81a5a6b139f')throw Error('回放解析器版本不匹配。');
      await init({module_or_path:'/vendor/agent/wotb_replay_wasm_bg.wasm'});
      return f;
    })();
    const engine=await ready;
    const b=new Uint8Array(data.bytes);
    let playback=JSON.parse(parsePlayback(b));
    // prop2 stores a fraction of the mounted gun's yaw-dependent pitch range.
    // Without these anchors Agent substitutes hull pitch for barrel elevation.
    // Follow WotbTools' roster -> limits -> second parse flow, off the UI thread.
    const response=await fetch('/api/preview/pitch-limits',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({vehicles:playback.vehicles.map(({eid,nickname,tank_id,turret_local,gun_local})=>({eid,nickname,tank_id,turret_local,gun_local}))})});
    const aim=await response.json();if(!response.ok)throw Error(aim.error||'炮管俯仰参数读取失败。');
    if(Object.keys(aim.limits).length)playback=JSON.parse(parsePlayback(b,undefined,JSON.stringify(aim.limits)));
    self.postMessage({id:data.id,bundle:{engine,aim:{anchored:aim.anchored,missing:aim.missing},playback,result:JSON.parse(parseResult(b)),ai:JSON.parse(parseAiReview(b))}});
  }catch(error){self.postMessage({id:data.id,error:String(error.message||error)});}
};
