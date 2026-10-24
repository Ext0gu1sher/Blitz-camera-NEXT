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
    self.postMessage({id:data.id,bundle:{engine,playback:JSON.parse(parsePlayback(b)),result:JSON.parse(parseResult(b)),ai:JSON.parse(parseAiReview(b))}});
  }catch(error){self.postMessage({id:data.id,error:String(error.message||error)});}
};
