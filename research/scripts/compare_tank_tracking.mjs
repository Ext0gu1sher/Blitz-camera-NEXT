// Read-only comparison with the exact pinned WotbTools sampler.
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import * as wasm from '../../blitzcam/web/vendor/agent/wotb_replay_wasm.js';
import {createReplaySampler} from '../../blitzcam/web/replay-preview-core.js';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const folder=process.argv[2];if(!folder)throw Error('Usage: node research/scripts/compare_tank_tracking.mjs RUN_DIRECTORY');
const report=JSON.parse(fs.readFileSync(path.join(folder,'tracking-report.json')));
const bytes=fs.readFileSync(report.source.replay_file);
if(createHash('sha256').update(bytes).digest('hex')!==report.source.replay_sha256)throw Error('Replay identity changed');
wasm.initSync({module:fs.readFileSync(path.join(root,'blitzcam/web/vendor/agent/wotb_replay_wasm_bg.wasm'))});
const bundle={playback:JSON.parse(wasm.parsePlayback(bytes)),result:JSON.parse(wasm.parseResult(bytes)),ai:JSON.parse(wasm.parseAiReview(bytes))};
const sampler=createReplaySampler(bundle,report.source.replay_origin_sec??0);
const camera=fs.readFileSync(path.join(folder,'events.jsonl'),'utf8').trim().split('\n').filter(Boolean).map(JSON.parse);
const targets=new Map(JSON.parse(fs.readFileSync(path.join(folder,'tracking-targets.json'))).map(x=>[x.commit,x]));
const draws=camera.filter(c=>c.kind===2&&c.stage===2&&targets.get(c.commit)?.valid);
function stats(v){const a=v.slice().sort((a,b)=>a-b);return a.length?{count:a.length,median:a[Math.floor(a.length/2)],p95:a[Math.ceil(a.length*.95)-1],max:a.at(-1),rms:Math.sqrt(a.reduce((s,x)=>s+x*x,0)/a.length)}:null;}
function project(p,c){const q=[0,1,2,3].map(j=>p.reduce((s,v,i)=>s+v*c.view[i*4+j],c.view[12+j]));const clip=[0,1,2,3].map(j=>q.reduce((s,v,i)=>s+v*c.projection[i*4+j],0));return clip[3]>0?[clip[0]/clip[3]*960,-clip[1]/clip[3]*540]:null;}
function compare(offset){
 const errors=[],pixels=[];let unavailable=0;
 for(const c of draws){
  const native=targets.get(c.commit),f=sampler.poseAtRaw(report.config.eid,c.raw_time+offset);
  if(!f){unavailable++;continue;}
  const p=[f.pose.x,f.pose.z,f.pose.y];errors.push(Math.hypot(...p.map((v,i)=>v-native.root[i])));
  // Reuse the native anchor's offset to isolate root-position reconstruction
  // error. This intentionally does not assess reconstructed hull articulation.
  const xy=project(p.map((v,i)=>v+native.anchor[i]-native.root[i]),c);
  if(xy)pixels.push(Math.hypot(...xy));
 }
 return {offset_seconds:offset,root_position_error_m:stats(errors),root_only_screen_error_px:stats(pixels),unavailable};
}
const baseline=compare(0),sweep=[];
for(let i=-50;i<=50;i++)sweep.push(compare(i*.005));
const best=sweep.filter(x=>x.root_position_error_m&&x.unavailable===baseline.unavailable).sort((a,b)=>a.root_position_error_m.rms-b.root_position_error_m.rms)[0];
const output={replay_sha256:report.source.replay_sha256,eid:report.config.eid,baseline,
 best_offset_for_this_clip_only:best,native:report.measurement.center_error_px,
 caveat:'Offset sweep is diagnostic, not a global time correction. Native metric uses matrices at shadow draw entry; no rendered-pixel/occlusion guarantee. Root-only comparison keeps native local-anchor offset.'};
fs.writeFileSync(path.join(folder,'reconstruction-comparison.json'),JSON.stringify(output,null,2)+'\n');
console.log(JSON.stringify(output,null,2));
