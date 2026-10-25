/* Uniform musical beats in shooting seconds, mapped to the camera clock. */
(function(root,factory){const api=factory();if(typeof module==='object'&&module.exports)module.exports=api;else root.BlitzBeatGrid=api;})(globalThis,function(){
  'use strict';
  const defaults=()=>({version:1,enabled:false,bpm:120,division:1,origin:'inpoint',anchor_sec:0,offset_sec:0});
  function grid(settings,map){
    if(!settings?.enabled)return null;
    const step=60/settings.bpm/settings.division;
    const anchor=settings.origin==='playhead'?settings.anchor_sec:map.workStart;
    // Keep anchors beyond a shortened range intact, rather than clamping them
    // into it and inventing a beat at the new endpoint.
    const seconds=t=>t<map.start?t-map.start:t>map.end?map.seconds+t-map.end:map.atTime(t);
    const base=seconds(anchor)+settings.offset_sec,start=map.atTime(map.workStart),end=map.atTime(map.workEnd);
    const first=Math.max(0,Math.ceil((start-base)/step-1e-8)),last=Math.floor((end-base)/step+1e-8);
    return {base,step,first,last,count:Math.max(0,last-first+1),map,division:settings.division};
  }
  function timeAt(g,index){return g.map.atSeconds(g.base+index*g.step);}
  function nearest(g,time,distance=candidate=>Math.abs(candidate-time)){
    if(!g?.count)return null;
    const index=(g.map.atTime(time)-g.base)/g.step;
    const a=timeAt(g,Math.max(g.first,Math.min(g.last,Math.floor(index))));
    const b=timeAt(g,Math.max(g.first,Math.min(g.last,Math.ceil(index))));
    return distance(a)<=distance(b)?a:b;
  }
  function visible(g,start,end,limit=250){
    if(!g?.count)return [];
    const first=Math.max(g.first,Math.ceil((g.map.atTime(start)-g.base)/g.step-1e-8));
    const last=Math.min(g.last,Math.floor((g.map.atTime(end)-g.base)/g.step+1e-8));
    let stride=Math.max(1,Math.ceil((last-first+1)/Math.max(1,limit)));
    const bar=4*g.division;if(stride>1)stride=Math.ceil(stride/bar)*bar;
    const result=[];
    for(let i=Math.ceil(first/stride)*stride;i<=last;i+=stride)result.push({index:i,time:timeAt(g,i),major:i%bar===0});
    return result;
  }
  return {defaults,grid,nearest,visible,timeAt};
});
