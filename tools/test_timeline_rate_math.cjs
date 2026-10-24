// Replay-clock invariants for timeline rate editing; no DOM or game access.
const assert=require('node:assert/strict');
const {Editor}=require('../blitzcam/web/timeline.js'),T=require('../blitzcam/web/preview-time.js');
const clone=x=>JSON.parse(JSON.stringify(x)),near=(a,b,label='value')=>assert.ok(Math.abs(a-b)<1e-7,`${label}: ${a} != ${b}`);
let checks=0;
const test=(name,fn)=>{fn();checks++;console.log(`PASS ${name}`);};
function fixture(dense=false,custom=false){
 const e=Object.create(Editor.prototype),times=dense?[0,8.13,71.067,71.212,71.254,71.748,73.84]:[10,13,18,22,27,30];
 const rates=dense?[1,1,1,.0625,.0625,1,1]:[1,.7,.25,.6,.4,.8];
 e.axis='replay';e.doc={mode:'replay',timeline:{duration_sec:100,work_start_sec:dense?69.75:10,work_end_sec:dense?73.84:30},
  tracks:Object.fromEntries(['x','y','z','yaw','pitch','roll','zoom'].map((c,i)=>[c,[{time_sec:10,value:c==='zoom'?60:0,_id:100+i}]])),
  speed:{mode:'curve',camera_clock:'replay',interpolation:'smooth',rate:1,time_range:{start_sec:times[0],end_sec:times.at(-1)},
   keyframes:rates.map((rate,i)=>({progress:i/(rates.length-1),rate,_id:i+1,...(custom&&i<rates.length-1?{ease:[.15,.2,.65,.95]}:{})}))}};
 // Build a saved-format fixture from independently specified replay positions.
 const spans=times.slice(1).map((t,i)=>{const a=e.doc.speed.keyframes[i],b=e.doc.speed.keyframes[i+1];return (t-times[i])/(a.rate+(b.rate-a.rate)*(a.ease?T.bezierArea(a.ease,1):.5));});
 const total=spans.reduce((a,b)=>a+b,0);let elapsed=0;
 e.doc.speed.keyframes.forEach((k,i)=>{if(i)elapsed+=spans[i-1];k.progress=i===rates.length-1?1:elapsed/total;});
 return e;
}
const times=e=>e.doc.speed.keyframes.map(k=>e.map().rateTime(k.progress));
const rate=(speed,time)=>T.atCamera(speed.time_range.end_sec-speed.time_range.start_sec,speed,(time-speed.time_range.start_sec)/(speed.time_range.end_sec-speed.time_range.start_sec)).rate;
function drag(e,indices,anchor,dx,dy){
 const before=clone(e.doc),map=e.map(),d={before,map,anchor:before.speed.keyframes[anchor]._id,ids:new Set(indices.map(i=>before.speed.keyframes[i]._id))};
 e.doc=clone(before);e.moveRate(d,dx,dy);assert.ok(T.valid(e.doc.speed),'edited curve must be valid');
 assert.deepEqual(e.doc.tracks,before.tracks);assert.deepEqual(e.doc.timeline,before.timeline);assert.deepEqual(e.doc.speed.time_range,before.speed.time_range);
 return {before,d};
}
function unchanged(e,before,selected){
 const after=times(e),s=before.speed,r=s.time_range,old=s.keyframes.map(k=>r.start_sec+T.atShooting(r.end_sec-r.start_sec,s,k.progress).cameraProgress*(r.end_sec-r.start_sec));
 for(let i=0;i<old.length;i++)if(!selected.includes(i)){near(after[i],old[i],`unselected point ${i}`);assert.equal(e.doc.speed.keyframes[i].rate,s.keyframes[i].rate);}
 for(let i=0;i<old.length-1;i++)if(!selected.includes(i)&&!selected.includes(i+1)){
  assert.deepEqual(e.doc.speed.keyframes[i].ease,s.keyframes[i].ease,'unaffected handles must survive exactly');
  for(let j=0;j<=10;j++){const t=old[i]+(old[i+1]-old[i])*j/10;near(rate(e.doc.speed,t),rate(s,t),`unaffected segment ${i} at ${t}`);}
 }
}
for(const dense of [false,true])for(const custom of [false,true])test(`${dense?'dense low-rate':'spaced'} points, ${custom?'Bezier':'default'} segments stay local`,()=>{
 const count=fixture(dense,custom).doc.speed.keyframes.length;
 for(let i=0;i<count;i++)for(const [dx,dy]of [[0,.1],[0,-.1],[dense?.005:.2,0],[dense?-.005:-.2,.1]]){
  const e=fixture(dense,custom),initial=times(e),{before}=drag(e,[i],i,dx,dy);unchanged(e,before,[i]);
  near(times(e)[i],initial[i]+(i>0&&i<count-1?dx:0),'dragged replay time');
 }
});
test('contiguous and disjoint selections keep their replay spacing',()=>{
 for(const indices of [[1,2],[1,3],[0,2,4],[1,3,5]]){
  const e=fixture(false,true),initial=times(e),anchor=indices.find(i=>i>0&&i<5),{before}=drag(e,indices,anchor,.3,.08);
  unchanged(e,before,indices);for(const i of indices)near(times(e)[i],initial[i]+(i>0&&i<5?.3:0));
 }
});
test('crossing either neighbour clamps without moving it or invalidating the curve',()=>{
 for(const dx of [-100,100])for(const i of [1,2,3,4,5]){
  const e=fixture(true,true),old=times(e),{before}=drag(e,[i],i,dx,.14),now=times(e);unchanged(e,before,[i]);
  assert.ok(now[i]>old[i-1]&&now[i]<old[i+1]);assert.ok(Math.abs(now[i]-old[i+(dx>0?1:-1)])<.1);
 }
});
test('returning the pointer to the same position has no accumulated drift',()=>{
 const e=fixture(true,true),{d}=drag(e,[3],3,.005,.1),expected=clone(e.doc);
 for(let i=0;i<30;i++){e.doc=clone(d.before);e.moveRate(d,.02,.2);e.doc=clone(d.before);e.moveRate(d,.005,.1);assert.deepEqual(e.doc,expected);}
});
test('shooting ruler follows the anchor while retaining unselected replay times',()=>{
 for(const trim of [false,true])for(const indices of [[2],[1,2],[1,3]]){
  const e=fixture(false,true);e.axis='shooting';if(trim){e.doc.timeline.work_start_sec=14;e.doc.timeline.work_end_sec=25;}
  const anchor=indices.at(-1),original=e.rateDisplay(e.doc.speed.keyframes[anchor].progress),{before}=drag(e,indices,anchor,.2,.08);
  unchanged(e,before,indices);near(e.rateDisplay(e.doc.speed.keyframes[anchor].progress),original+.2,'shooting position');
 }
});
test('legal flat-segment handles are not rewritten',()=>{
 const e=fixture(true,true),original=clone(e.doc.speed.keyframes[0].ease),{before}=drag(e,[3],3,.005,.1);
 assert.deepEqual(e.doc.speed.keyframes[0].ease,original);unchanged(e,before,[3]);
});
test('disjoint shooting selection can invert its time response',()=>{
 const e=fixture();e.axis='shooting';[1,.0625,.0625,1,1,1].forEach((rate,i)=>e.doc.speed.keyframes[i].rate=rate);
 const original=e.rateDisplay(e.doc.speed.keyframes[4].progress),{before}=drag(e,[1,4],4,.2,0);
 unchanged(e,before,[1,4]);near(e.rateDisplay(e.doc.speed.keyframes[4].progress),original+.2);
});
test('minimum stored progress spacing survives vertical and horizontal limits',()=>{
 for(const dx of [-100,0,100])for(const dy of [-.8,.8]){
  const e=fixture(false,true);e.doc.speed.keyframes[2].progress=e.doc.speed.keyframes[1].progress+1.001e-5;
  const {before}=drag(e,[1],1,dx,dy);unchanged(e,before,[1]);
 }
});
test('precise time and rate entry retain all other replay positions',()=>{
 for(const field of ['time','value']){
  const e=fixture(true,true),before=clone(e.doc),old=times(e);e.selected=new Set([4]);
  e.snapshot=()=>clone(e.doc);e.render=()=>{};e.commit=()=>{};e.adapter={error:message=>{throw Error(message);}};
  assert.equal(e.setInspectorValue(field,field==='time'?old[3]+.005:.3),true);unchanged(e,before,[3]);
  near(times(e)[3],old[3]+(field==='time'?.005:0));
 }
});
test('varied curve lengths and multi-selections remain valid at drag limits',()=>{
 let seed=93287;const random=()=>((seed=(Math.imul(seed,1664525)+1013904223)>>>0)/2**32);
 for(let n=0;n<180;n++){
  const e=fixture(),count=2+Math.floor(random()*63),weights=Array.from({length:count-1},()=>.001+random()**3),total=weights.reduce((a,b)=>a+b,0);
  let sum=0;e.doc.speed.keyframes=Array.from({length:count},(_,i)=>{if(i)sum+=weights[i-1];return {_id:i+1,progress:i===count-1?1:sum/total,rate:.0625+random()*.9375,...(n%2?{ease:[.1,.15,.8,.95]}:{})};});
  const anchor=Math.floor(random()*count),selected=Array.from({length:count},(_,i)=>i).filter(i=>i===anchor||random()<.2);
  const {before}=drag(e,selected,anchor,(random()-.5)*80,(random()-.5)*2);unchanged(e,before,selected);
 }
});
console.log(JSON.stringify({passed:true,checks}));
