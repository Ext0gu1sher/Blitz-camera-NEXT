import assert from 'node:assert/strict';
import {flightSeekSeconds,cameraBasis,CameraMotionMeter} from '../../blitzcam/web/replay-preview-core.js';

// World-space distance per real second, independent of extra renders, display
// refresh rate and camera orientation. Explicit cuts never count as travel.
for(const fps of [30,60,144]){
  const meter=new CameraMotionMeter();meter.sample([0,0,0],0);
  for(let i=1;i<=fps;i++){
    const t=i/fps,position=[3*t,4*t,0],now=t*1000;
    meter.sample(position,now);meter.sample(position,now);
  }
  assert.ok(Math.abs(meter.speed-5)<1e-8);
  meter.reset();assert.equal(meter.sample([10000,0,0],1100),0);
  assert.equal(meter.sample([10000,0,0],1300),0);
  assert.equal(meter.sample([10020,0,0],1400),200);
  assert.equal(meter.sample([0,0,0],3000),0,'resume after idle starts a new measurement');
  assert.equal(meter.sample([NaN,0,0],3100),0);
  assert.equal(meter.sample([],3200),0);
}

for(const t of [-1,0,.1,.25])assert.equal(flightSeekSeconds(t),0,'quick taps must stay single-frame');
let previousRate=0;
for(let start=.25;start<5;start+=.1){
  const rate=(flightSeekSeconds(start+.01)-flightSeekSeconds(start))/.01;
  assert.ok(rate>=previousRate-1e-8,'hold speed must increase monotonically');
  assert.ok(rate<=64+1e-8,'hold speed must have a fixed cap');
  previousRate=rate;
}
assert.ok(flightSeekSeconds(.5)<.3,'initial hold must remain fine enough to position');
assert.ok(flightSeekSeconds(2.25)-flightSeekSeconds(1.25)>10,'holding longer must move substantially faster');
for(const start of [3.25,4,10,60]){
  assert.ok(Math.abs(flightSeekSeconds(start+1)-flightSeekSeconds(start)-64)<1e-8,'sustained maximum must advance 64 replay seconds per second');
}
for(const settings of [{seekDelay:0,seekRamp:.25,seekMax:256},{seekDelay:1,seekRamp:10,seekMax:2}]){
  const {seekDelay,seekRamp,seekMax}=settings;
  assert.equal(flightSeekSeconds(seekDelay,settings),0);
  const end=seekDelay+seekRamp;
  assert.ok(Math.abs(flightSeekSeconds(end+1,settings)-flightSeekSeconds(end,settings)-seekMax)<1e-8,'custom cap must remain constant');
  let previous=0;
  for(let t=seekDelay;t<end+1;t+=.1){const rate=(flightSeekSeconds(t+.001,settings)-flightSeekSeconds(t,settings))/.001;assert.ok(rate>=previous-1e-7&&rate<=seekMax+1e-7);previous=rate;}
}
// Verify camera bank convention, including cameras already looking up/sideways.
const dot=(a,b)=>a.reduce((sum,v,i)=>sum+v*b[i],0);
for(const [yaw,pitch] of [[0,0],[90,-30],[-160,70]]){
  const neutral=cameraBasis(yaw,pitch,0),ccw=cameraBasis(yaw,pitch,-15),cw=cameraBasis(yaw,pitch,15);
  assert.ok(dot(ccw.up,neutral.right)<0,'negative roll tilts the camera counterclockwise');
  assert.ok(dot(cw.up,neutral.right)>0,'positive roll tilts the camera clockwise');
  assert.deepEqual(ccw.forward,neutral.forward);assert.deepEqual(cw.forward,neutral.forward);
}
console.log(JSON.stringify({passed:true}));
