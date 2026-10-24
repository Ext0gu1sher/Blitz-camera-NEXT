/* Pure clipboard regression checks. Run with node; no browser or game needed. */
const assert=require('node:assert/strict');
const C=require('../blitzcam/web/keyframe-clipboard.js'),T=require('../blitzcam/web/preview-time.js');
const channels=['x','y','z','yaw','pitch','roll','zoom'],copy=x=>JSON.parse(JSON.stringify(x));
let assertions=0;
function test(name,fn){fn();assertions++;console.log(`PASS ${name}`);}
function fixture(){let n=0;return {mode:'replay',timeline:{duration_sec:100,work_start_sec:10,work_end_sec:50},tracks:Object.fromEntries(channels.map(channel=>[channel,[{time_sec:10,value:channel==='zoom'?60:0,_id:++n},{time_sec:50,value:channel==='zoom'?70:2,_id:++n}]])),speed:{mode:'curve',camera_clock:'replay',interpolation:'smooth',rate:1,time_range:{start_sec:10,end_sec:50},keyframes:[{progress:0,rate:1,_id:++n},{progress:.3,rate:.25,ease:[.2,.1,.8,.9],_id:++n},{progress:.7,rate:.6,_id:++n},{progress:1,rate:1,_id:++n}]}};}
function apply(doc,payload,head){let n=10000;return C.paste(doc,payload,head,()=>++n);}
function times(doc){const s=doc.speed,r=s.time_range;return s.keyframes.map(k=>r.start_sec+T.atShooting(r.end_sec-r.start_sec,s,k.progress).cameraProgress*(r.end_sec-r.start_sec));}
function near(a,b){assert.ok(Math.abs(a-b)<1e-6,`${a} != ${b}`);}
function camera(channel,time,value,extra={}){return {channel,time_sec:time,key:{time_sec:time,value,_id:999,...extra}};}
function rate(time,value,extra={}){return {channel:'rate',time_sec:time,key:{progress:.5,rate:value,_id:998,...extra}};}
test('capture anchors the earliest point, preserves metadata, and takes a snapshot',()=>{
  const source=[camera('zoom',8,80,{ease:[.2,.1,.8,.9],curve:'auto'}),camera('x',5,42)],before=copy(source),p=C.capture(source);
  assert.equal(p.type,'blitzcam-keyframes');assert.equal(p.version,1);assert.deepEqual(p.items.map(i=>i.offset_sec),[0,3]);assert.deepEqual(p.items[1].key,{value:80,ease:[.2,.1,.8,.9],curve:'auto'});assert.deepEqual(source,before);
  source[0].key.ease[0]=.9;assert.equal(p.items[1].key.ease[0],.2);assert.ok(!('_id'in p.items[0].key));
});
test('multiple camera channels preserve relative times and only replace matching channels',()=>{
  const doc=fixture(),before=copy(doc),p=C.capture([camera('x',5,8),camera('y',8,9),camera('x',10,10)]),payloadBefore=copy(p),r=apply(doc,p,20);
  assert.equal(r.count,3);assert.equal(r.replaced,0);assert.equal(r.selected.length,3);assert.deepEqual(r.doc.tracks.x.map(k=>k.time_sec),[10,20,25,50]);assert.equal(r.doc.tracks.y.find(k=>k.time_sec===23).value,9);assert.deepEqual(r.doc.speed,doc.speed);assert.deepEqual(doc,before);assert.deepEqual(p,payloadBefore);
});
test('same-channel same-time paste replaces and creates a fresh selection',()=>{
  const doc=fixture(),r=apply(doc,C.capture([camera('x',0,99)]),10+5e-7);
  assert.equal(r.replaced,1);assert.equal(r.doc.tracks.x.length,2);assert.equal(r.doc.tracks.x[0].value,99);assert.notEqual(r.doc.tracks.x[0]._id,doc.tracks.x[0]._id);assert.deepEqual(r.selected,[r.doc.tracks.x[0]._id]);
});
test('four original speed points plus two pasted Bezier points retain exact replay times',()=>{
  const doc=fixture(),oldTimes=times(doc),p=C.capture([rate(0,.4,{ease:[1/3,0,2/3,1]}),rate(5,.7)]),before=copy(doc),r=apply(doc,p,25),newTimes=times(r.doc);
  assert.equal(r.doc.speed.keyframes.length,6);assert.equal(r.count,2);assert.equal(r.replaced,0);assert.ok(T.valid(r.doc.speed));
  for(let i=0;i<doc.speed.keyframes.length;i++){const index=r.doc.speed.keyframes.findIndex(k=>k._id===doc.speed.keyframes[i]._id);near(newTimes[index],oldTimes[i]);}
  near(newTimes[r.doc.speed.keyframes.findIndex(k=>k._id===r.selected[0])],25);near(newTimes[r.doc.speed.keyframes.findIndex(k=>k._id===r.selected[1])],30);assert.deepEqual(r.doc.speed.keyframes.find(k=>k._id===r.selected[0]).ease,[1/3,0,2/3,1]);assert.deepEqual(doc,before);
});
test('speed range extends to copied endpoints without moving old replay points',()=>{
  const doc=fixture(),oldTimes=times(doc),r=apply(doc,C.capture([rate(0,.4),rate(60,.8)]),5),newTimes=times(r.doc);
  assert.deepEqual(r.doc.speed.time_range,{start_sec:5,end_sec:65});near(newTimes[0],5);near(newTimes.at(-1),65);for(let i=0;i<oldTimes.length;i++)near(newTimes[i+1],oldTimes[i]);
});
test('speed overwrite replaces one point and retains all unaffected point times',()=>{
  const doc=fixture(),oldTimes=times(doc),r=apply(doc,C.capture([rate(0,.5,{ease:[.25,-.5,.75,1.5]})]),oldTimes[1]),newTimes=times(r.doc);
  assert.equal(r.replaced,1);assert.equal(r.doc.speed.keyframes.length,4);for(let i=0;i<oldTimes.length;i++)near(newTimes[i],oldTimes[i]);assert.equal(r.doc.speed.keyframes[1].rate,.5);assert.ok(T.valid(r.doc.speed));
});
test('mixed camera and speed selection uses one shared earliest anchor',()=>{
  const doc=fixture(),p=C.capture([camera('x',5,100),rate(8,.45),camera('zoom',12,80)]),r=apply(doc,p,60);
  assert.equal(r.doc.tracks.x.find(k=>k.time_sec===60).value,100);assert.equal(r.doc.tracks.zoom.find(k=>k.time_sec===67).value,80);const k=r.doc.speed.keyframes.find(k=>k._id===r.selected.at(-1));near(times(r.doc)[r.doc.speed.keyframes.indexOf(k)],63);assert.equal(r.selected.length,3);
});
test('explicit effective ease survives a different destination interpolation',()=>{
  const doc=fixture();doc.speed.interpolation='linear';const p=C.capture([{...rate(1,.45),effectiveEase:[1/3,0,2/3,1]}]),r=apply(doc,p,30);
  assert.deepEqual(p.items[0].key.ease,[1/3,0,2/3,1]);assert.deepEqual(r.doc.speed.keyframes.find(k=>r.selected.includes(k._id)).ease,p.items[0].key.ease);
});
test('legal handles on a flat original speed segment keep their exact metadata',()=>{
  const doc=fixture();doc.speed.keyframes[2].rate=.25;const original=copy(doc.speed.keyframes[1].ease),r=apply(doc,C.capture([rate(0,.5)]),45);
  assert.deepEqual(r.doc.speed.keyframes.find(k=>k._id===doc.speed.keyframes[1]._id).ease,original);
});
test('fixed speed converts to a curve and keeps both old endpoint times',()=>{
  const doc=fixture();doc.speed.mode='fixed';doc.speed.rate=.5;const r=apply(doc,C.capture([rate(0,.25)]),30);
  assert.equal(r.doc.speed.mode,'curve');assert.equal(r.doc.speed.keyframes.length,3);assert.deepEqual(times(r.doc).map(t=>Math.round(t)),[10,30,50]);assert.ok(T.valid(r.doc.speed));
});
test('mode one accepts camera keys but atomically rejects any speed keys',()=>{
  const doc=fixture();doc.mode='camera_only';doc.timeline=null;const before=copy(doc);
  assert.equal(apply(doc,C.capture([camera('x',0,10)]),500).doc.tracks.x.at(-1).time_sec,500);assert.throws(()=>apply(doc,C.capture([camera('x',0,10),rate(1,.5)]),20),/模式一/);assert.deepEqual(doc,before);
});
test('out of range, too-close keys, invalid ids, and speed capacity reject the whole paste',()=>{
  const doc=fixture(),before=copy(doc);assert.throws(()=>apply(doc,C.capture([camera('x',0,10),camera('y',3,10)]),99),/目标时间/);assert.throws(()=>apply(doc,C.capture([camera('x',0,10)]),-1),/粘贴时刻/);assert.throws(()=>apply(doc,C.capture([camera('x',0,10)]),10+5e-6),/过近/);assert.throws(()=>C.paste(doc,C.capture([camera('x',0,10)]),20,()=>1),/重复/);assert.throws(()=>C.paste(doc,C.capture([camera('x',0,10)]),20,()=>NaN),/标识/);
  doc.speed.keyframes=Array.from({length:64},(_,i)=>({progress:i/63,rate:1,_id:100+i}));assert.throws(()=>apply(doc,C.capture([rate(0,.5)]),30.1),/64/);delete doc.speed.keyframes;assert.deepEqual(before.tracks,doc.tracks);
});
test('clipboard payload strictly rejects malformed data and prototype pollution',()=>{
  const base=C.capture([camera('x',0,1)]),bad=[null,[],{}, {...base,version:2},{...base,type:'other'},{...base,extra:1},{...base,items:[]},{...base,items:[{channel:'__proto__',offset_sec:0,key:{value:1}}]}, {...base,items:[{channel:'x',offset_sec:NaN,key:{value:1}}]}, {...base,items:[{channel:'x',offset_sec:-1,key:{value:1}}]}, {...base,items:[{channel:'x',offset_sec:1,key:{value:1}}]}, {...base,items:[{channel:'x',offset_sec:0,key:{value:Infinity}}]}, {...base,items:[{channel:'x',offset_sec:0,key:{value:1,_id:2}}]}, {...base,items:[{channel:'pitch',offset_sec:0,key:{value:81}}]}, {...base,items:[{channel:'zoom',offset_sec:0,key:{value:180}}]}, {...base,items:[{channel:'rate',offset_sec:0,key:{rate:.01}}]}, {...base,items:[{channel:'rate',offset_sec:0,key:{rate:.5,ease:[.8,0,.2,1]}}]}, JSON.parse('{"type":"blitzcam-keyframes","version":1,"items":[{"channel":"x","offset_sec":0,"key":{"value":1,"__proto__":{"polluted":true}}}]}')];
  for(const payload of bad)assert.throws(()=>apply(fixture(),payload,20));assert.equal({}.polluted,undefined);
  const accessor={...base};Object.defineProperty(accessor,'version',{enumerable:true,get(){throw Error('getter executed');}});assert.throws(()=>apply(fixture(),accessor,20),/未知字段/);
  const sparse=[,...base.items];sparse.extra=base.items[0];assert.throws(()=>apply(fixture(),{...base,items:sparse},20));
  const extra=copy(base);extra.items[Symbol('extra')]=true;assert.throws(()=>apply(fixture(),extra,20));
  const arrayGetter=copy(base);Object.defineProperty(arrayGetter.items,'0',{enumerable:true,get(){throw Error('getter executed');}});assert.throws(()=>apply(fixture(),arrayGetter,20),/格式/);
  assert.throws(()=>C.capture([camera('x',0,1),camera('x',0,2)]),/重合/);assert.throws(()=>C.capture([]));assert.throws(()=>C.capture(Array.from({length:65},(_,i)=>rate(i,.5))),/64/);
});
test('failed mixed paste does not change its source document or clipboard snapshot',()=>{
  const doc=fixture(),p=C.capture([camera('x',0,1),rate(2,.5)]),before=copy(doc),payloadBefore=copy(p);assert.throws(()=>apply(doc,p,99));assert.deepEqual(doc,before);assert.deepEqual(p,payloadBefore);
});
console.log(`PASS ${assertions} keyframe clipboard groups`);
