const T=require('../../blitzcam/web/preview-time.js'),fs=require('node:fs');
const cases=JSON.parse(fs.readFileSync(0,'utf8'));
console.log(JSON.stringify(cases.map(s=>{
  const ps=Array.from({length:101},(_,i)=>i/100),before=ps.map(p=>[T.rateAt(s,p),T.integral(s,p)]),copy=JSON.parse(JSON.stringify(s));
  for(const p of [.13,.42,.91])T.insertKey(copy,p);
  return {valid:T.valid(s),samples:before,split:ps.map(p=>[T.rateAt(copy,p),T.integral(copy,p)]),splitValid:T.valid(copy),
    window:[T.windowDuration(12,22,s),T.atWindowShooting(12,22,s,2)]};
})));
