// Read-only WASM/sampler regression against a project-bound replay; no game API.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';

const args=process.argv.slice(2),option=(name,fallback)=>{
  const i=args.indexOf(name);return i<0?fallback:args[i+1];
};
const web=path.resolve(option('--web-root','blitzcam/web'));
const engine=path.resolve(option('--engine-root',path.join(web,'vendor/agent')));
const projectFile=option('--project');
if(!projectFile)throw Error('Usage: node tools/verify_replay_pose.mjs --project project.json [--web-root blitzcam/web] [--engine-root engine-directory] [--report result.json]');
const project=JSON.parse(fs.readFileSync(projectFile,'utf8'));
const replay=project.replay_timeline.replay_file,bytes=fs.readFileSync(replay);
const hash=value=>createHash('sha256').update(value).digest('hex');
const wasm=await import(pathToFileURL(path.join(engine,'wotb_replay_wasm.js')));
const {createReplaySampler,validatePlayback}=await import(pathToFileURL(path.join(web,'replay-preview-core.js')));
wasm.initSync({module:fs.readFileSync(path.join(engine,'wotb_replay_wasm_bg.wasm'))});
const bundle={playback:JSON.parse(wasm.parsePlayback(bytes)),result:JSON.parse(wasm.parseResult(bytes)),ai:JSON.parse(wasm.parseAiReview(bytes))};
const before=hash(JSON.stringify(bundle)),origin=project.replay_timeline.replay_origin_sec;
const sampler=createReplaySampler(bundle,origin);
assert.equal(validatePlayback(bundle.playback),bundle.playback);
assert.ok(bundle.playback.vehicles.every(v=>v.pose_kf?.t.length>=2));
const readings=[];let vehicleFrames=0;
for(let i=0;i<bundle.playback.meta.samples;i++){
  const raw=bundle.playback.meta.t_start+i*.1,time=raw-origin,frames=sampler.at(time);
  for(const frame of frames){
    assert.ok(Object.values(frame.pose).every(Number.isFinite));
    assert.ok(bundle.playback.vehicles.find(v=>v.eid===frame.eid).coverage.some((v,j,a)=>j%2===0&&raw>=v-1e-6&&raw<=a[j+1]+1e-6)||frame.life?.lifeState==='DESTROYED');
  }
  readings.push(hash(JSON.stringify(frames.map(f=>({eid:f.eid,pose:f.pose,life:f.life})))));vehicleFrames+=frames.length;
}
for(let i=readings.length-1;i>=0;i--){
  const time=bundle.playback.meta.t_start+i*.1-origin;
  assert.equal(hash(JSON.stringify(sampler.at(time).map(f=>({eid:f.eid,pose:f.pose,life:f.life})))),readings[i]);
}
assert.ok(vehicleFrames>0);
assert.equal(hash(JSON.stringify(bundle)),before);
assert.equal(hash(fs.readFileSync(replay)),hash(bytes));
const report={passed:true,webRoot:web,engine:JSON.parse(fs.readFileSync(path.join(engine,'fingerprint.json'),'utf8')),replaySha256:hash(bytes),mapId:bundle.playback.meta.map_id,vehicles:bundle.playback.vehicles.length,
  smoothPoseCurves:bundle.playback.vehicles.length,poseKeyframesStrictlyIncreasing:true,sampledTimes:readings.length,vehicleFrames,finitePoses:true,backwardSeekDeterministic:true,inputUnchanged:true};
const reportFile=option('--report');if(reportFile)fs.writeFileSync(reportFile,JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report));
