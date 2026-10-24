const fs=require('node:fs'),T=require('../../blitzcam/web/preview-time.js'),{ClockMap}=require('../../blitzcam/web/timeline.js');
const cases=JSON.parse(fs.readFileSync(0,'utf8'));
const result=cases.map(({speed,start,end,times})=>{
 const map=new ClockMap({x:[{time_sec:0},{time_sec:100}]},speed,{duration_sec:100,work_start_sec:start,work_end_sec:end});
 return {duration:T.windowDuration(start,end,speed),knots:speed.keyframes.map(k=>map.rateTime(k.progress)),
  samples:times.map(time=>{const frame=T.atWindowCamera(start,end,speed,time),back=T.atWindowShooting(start,end,speed,frame.shootingElapsed);
   return {time,...frame,back:start+back.cameraProgress*(end-start),mapBack:map.atSeconds(map.atTime(time))};})};
});
process.stdout.write(JSON.stringify(result));
