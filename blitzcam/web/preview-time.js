/* Offline timing and rate graphs. Matches the native clock's piecewise integral. */
(function(root,factory){const api=factory();if(typeof module!=="undefined"&&module.exports)module.exports=api;else root.BlitzPreviewTime=api;})(typeof globalThis!=="undefined"?globalThis:this,function(){
  "use strict";
  const clamp=x=>Math.max(0,Math.min(1,x));
  const paused={mode:"paused",camera_clock:"shooting"};
  function valid(s){
    if(!s||s.mode==="paused")return true;
    if(!["fixed","curve"].includes(s.mode))return false;
    if(s.mode==="fixed")return Number.isFinite(s.rate)&&s.rate>=.0625&&s.rate<=1;
    const bounds=s.time_range;if(bounds&&(!Number.isFinite(bounds.start_sec)||!Number.isFinite(bounds.end_sec)||bounds.start_sec<0||bounds.end_sec>3600||bounds.start_sec>=bounds.end_sec))return false;
    const fs=s.keyframes;
    return ["linear","smooth"].includes(s.interpolation)&&Array.isArray(fs)&&fs.length>=2&&fs.length<=64&&fs[0].progress===0&&fs.at(-1).progress===1&&fs.every((f,i)=>Number.isFinite(f.progress)&&Number.isFinite(f.rate)&&f.rate>=.0625&&f.rate<=1&&(!i||f.progress-fs[i-1].progress>=1e-5)&&(!('ease' in f)||Array.isArray(f.ease)&&f.ease.length===4&&f.ease.every((v,j)=>Number.isFinite(v)&&(j%2?Math.abs(v)<=1e6:v>=0&&v<=1))&&f.ease[0]<=f.ease[2]&&(!fs[i+1]||[1,3].every(j=>{const r=f.rate+(fs[i+1].rate-f.rate)*f.ease[j];return r>=.0625-1e-9&&r<=1+1e-9;}))));
  }
  const segmentEase=(s,i)=>s.keyframes[i].ease?.slice()||(s.interpolation==='smooth'?[1/3,0,2/3,1]:[1/3,1/3,2/3,2/3]);
  function boundHandles(s){for(let i=1;i<s.keyframes.length;i++){const a=s.keyframes[i-1],b=s.keyframes[i],d=b.rate-a.rate;if(!a.ease)continue;for(const j of [1,3])a.ease[j]=Math.abs(d)>1e-12?(Math.max(.0625,Math.min(1,a.rate+d*a.ease[j]))-a.rate)/d:j===1?0:1;}}
  function bezierPoint(e,t){const q=1-t;return [3*q*q*t*e[0]+3*q*t*t*e[2]+t*t*t,3*q*q*t*e[1]+3*q*t*t*e[3]+t*t*t];}
  function bezierParameter(e,u){if(u<=0)return 0;if(u>=1)return 1;let lo=0,hi=1;for(let i=0;i<42;i++){const t=(lo+hi)/2;if(bezierPoint(e,t)[0]<u)lo=t;else hi=t;}return (lo+hi)/2;}
  function bezierArea(e,u){
    const t=bezierParameter(e,u),x=[0,3*e[0],3*e[2]-6*e[0],1+3*e[0]-3*e[2]],y=[0,3*e[1],3*e[3]-6*e[1],1+3*e[1]-3*e[3]];
    let sum=0;for(let i=1;i<4;i++)for(let j=1;j<4;j++)sum+=y[i]*j*x[j]*t**(i+j)/(i+j);return sum;
  }
  function rateAt(s,p){
    s=s||paused;p=clamp(p);if(s.mode==="paused")return 0;if(s.mode==="fixed")return s.rate;
    const fs=s.keyframes;for(let i=1;i<fs.length;i++)if(p<=fs[i].progress){const a=fs[i-1],b=fs[i];let u=(p-a.progress)/(b.progress-a.progress);if(a.ease)u=bezierPoint(a.ease,bezierParameter(a.ease,u))[1];else if(s.interpolation==="smooth")u=u*u*(3-2*u);return a.rate+(b.rate-a.rate)*u;}return fs.at(-1).rate;
  }
  function integral(s,p){
    s=s||paused;p=clamp(p);if(s.mode==="paused")return 0;if(s.mode==="fixed")return s.rate*p;
    let total=0;for(let i=1;i<s.keyframes.length;i++){const a=s.keyframes[i-1],b=s.keyframes[i],span=b.progress-a.progress,u=clamp((p-a.progress)/span);if(u<=0)break;const area=a.ease?bezierArea(a.ease,u):s.interpolation==="smooth"?u*u*u-.5*u*u*u*u:.5*u*u;total+=span*(a.rate*u+(b.rate-a.rate)*area);}return total;
  }
  // Split at the evaluated rate without changing the curve or its integral.
  function insertKey(s,p,rate=rateAt(s,p)){
    const fs=s.keyframes,i=fs.findIndex((b,j)=>j&&p<b.progress);if(i<1||fs.some(f=>Math.abs(f.progress-p)<1e-5)||fs.length>=64)throw Error('速度关键帧不能重合，最多保留 64 个点。');
    const a=fs[i-1],b=fs[i],u=(p-a.progress)/(b.progress-a.progress),e=segmentEase(s,i-1),t=bezierParameter(e,u),v=bezierPoint(e,t)[1];
    const key={progress:p,rate};
    if(Math.abs(rate-(a.rate+(b.rate-a.rate)*v))<1e-9){
      const mix=(a,b)=>a.map((v,i)=>v+(b[i]-v)*t),A=mix([0,0],e.slice(0,2)),B=mix(e.slice(0,2),e.slice(2)),C=mix(e.slice(2),[1,1]),D=mix(A,B),E=mix(B,C);
      const norm=(point,x,y,w,h)=>[clamp((point[0]-x)/w),Math.abs(h)>1e-12?(point[1]-y)/h:(point[0]-x)/w];
      a.ease=[...norm(A,0,0,u,v),...norm(D,0,0,u,v)];key.ease=[...norm(E,u,v,1-u,1-v),...norm(C,u,v,1-u,1-v)];
    }
    fs.splice(i,0,key);return key;
  }
  function duration(pathDuration,s){return s?.mode!=="paused"&&s?.camera_clock==="replay"?pathDuration/integral(s,1):pathDuration;}
  function atShooting(pathDuration,s,p){
    s=s||paused;p=clamp(p);const seconds=duration(pathDuration,s),replayElapsed=seconds*integral(s,p);
    return {shootingProgress:p,shootingDuration:seconds,shootingElapsed:p*seconds,replayElapsed,rate:rateAt(s,p),cameraProgress:s.mode!=="paused"&&s.camera_clock==="replay"?(pathDuration>0?clamp(replayElapsed/pathDuration):0):p};
  }
  function atCamera(pathDuration,s,p){
    p=clamp(p);let shooting=p;
    if(s?.mode==="curve"&&s?.camera_clock==="replay"&&p>0&&p<1){
      const target=integral(s,1)*p;let lo=0,hi=1;for(let i=0;i<44;i++){const mid=(lo+hi)/2;if(integral(s,mid)<target)lo=mid;else hi=mid;}shooting=(lo+hi)/2;
    }
    return atShooting(pathDuration,s,shooting);
  }
  const anchored=s=>s?.mode==='curve'&&s.camera_clock==='replay'&&s.time_range;
  function scheduleTime(s,time){
    const {start_sec:a,end_sec:b}=s.time_range,total=duration(b-a,s);
    if(time<=a)return (time-a)/rateAt(s,0);
    if(time>=b)return total+(time-b)/rateAt(s,1);
    return atCamera(b-a,s,(time-a)/(b-a)).shootingElapsed;
  }
  function scheduleReplay(s,seconds){
    const {start_sec:a,end_sec:b}=s.time_range,total=duration(b-a,s);
    if(seconds<=0)return a+seconds*rateAt(s,0);
    if(seconds>=total)return b+(seconds-total)*rateAt(s,1);
    return a+total*integral(s,seconds/total);
  }
  function windowDuration(start,end,s){return end>start?(anchored(s)?scheduleTime(s,end)-scheduleTime(s,start):duration(end-start,s)):0;}
  function windowFrame(start,end,s,time,elapsed){
    const offset=scheduleTime(s,start),seconds=windowDuration(start,end,s),total=duration(s.time_range.end_sec-s.time_range.start_sec,s);
    return {shootingProgress:clamp((elapsed+offset)/total),shootingDuration:seconds,shootingElapsed:elapsed,
      replayElapsed:time-start,rate:rateAt(s,(elapsed+offset)/total),cameraProgress:clamp((time-start)/(end-start))};
  }
  function atWindowCamera(start,end,s,time){
    if(!(end>start))return atCamera(0,s,0);
    time=Math.max(start,Math.min(end,time));
    if(!anchored(s))return atCamera(end-start,s,(time-start)/(end-start));
    return windowFrame(start,end,s,time,scheduleTime(s,time)-scheduleTime(s,start));
  }
  function atWindowShooting(start,end,s,elapsed){
    if(!(end>start))return atShooting(0,s,0);
    const seconds=windowDuration(start,end,s);elapsed=Math.max(0,Math.min(seconds,elapsed));
    if(!anchored(s))return atShooting(end-start,s,seconds>0?elapsed/seconds:0);
    const time=scheduleReplay(s,scheduleTime(s,start)+elapsed);
    return windowFrame(start,end,s,time,elapsed);
  }
  function draw(svg,s,p,options={}){
    s=s||paused;
    svg.replaceChildren();
    let layer=svg;
    const make=(tag,attrs,text)=>{const el=document.createElementNS("http://www.w3.org/2000/svg",tag);for(const[k,v]of Object.entries(attrs))el.setAttribute(k,v);if(text!==undefined)el.textContent=text;layer.append(el);return el;};
    const rect=svg.getBoundingClientRect(),scale=globalThis.BlitzUIScale||1,width=Math.max(160,rect.width/scale||300),height=Math.max(90,rect.height/scale||92);svg.setAttribute("viewBox",`0 0 ${width} ${height}`);svg.setAttribute('preserveAspectRatio','none');
    if(!valid(s)){make("text",{x:12,y:45,fill:"#ffb2a5","font-size":11},"请修正速度关键帧后预览");return;}
    const start=options.view?.start||0,span=1/(options.view?.zoom||1),end=start+span;
    const left=options.editable?42:32,right=width-(options.editable?18:10),top=options.editable?20:8,bottom=height-(options.editable?28:24),x=p=>left+(p-start)/span*(right-left),y=r=>bottom-r*(bottom-top);
    svg.speedLayout={left,right,top,bottom,width,height};
    if(options.work)for(const [a,b]of [[0,options.work[0]],[options.work[1],1]]){const lo=Math.max(a,start),hi=Math.min(b,end);if(hi>lo)make('rect',{x:x(lo),y:top,width:x(hi)-x(lo),height:bottom-top,fill:'#ffffff','fill-opacity':.025,'pointer-events':'none'});}
    for(const r of [0,.25,.5,.75,1]){make("line",{x1:left,y1:y(r),x2:right,y2:y(r),stroke:"#52666b","stroke-opacity":.3});make("text",{x:left-7,y:y(r)+3,fill:"#8b9b9e","text-anchor":"end","font-size":10},r+"×");}
    const divisions=width>400?4:2;
    for(let i=0;i<=divisions;i++){const p=start+span*i/divisions;make('line',{x1:x(p),y1:top,x2:x(p),y2:bottom,stroke:'#52666b','stroke-opacity':.15});make("text",{x:x(p),y:height-9,fill:"#8b9b9e","text-anchor":"middle","font-size":10},Number((p*100).toFixed(span<.1?2:1))+"%");}
    if(options.work)options.work.forEach((v,i)=>{if(v>start&&v<end){make('line',{x1:x(v),y1:top,x2:x(v),y2:bottom,stroke:'#e0c886','stroke-opacity':.55,'stroke-dasharray':'3 4'});make('text',{x:x(v)+4,y:top-6,fill:'#e0c886','font-size':9},i?'出':'入');}});
    const clipId=(svg.id||'speed')+'-plot-clip',defs=make('defs',{}),clip=document.createElementNS(svg.namespaceURI,'clipPath');clip.id=clipId;defs.append(clip);
    const clipRect=document.createElementNS(svg.namespaceURI,'rect');for(const[k,v]of Object.entries({x:left-10,y:top-10,width:right-left+20,height:bottom-top+20}))clipRect.setAttribute(k,v);clip.append(clipRect);
    layer=make('g',{'clip-path':`url(#${clipId})`});
    const curvePoints=[...Array.from({length:301},(_,i)=>start+span*i/300),...(s.keyframes||[]).map(k=>k.progress).filter(p=>p>=start&&p<=end)].sort((a,b)=>a-b);
    make("polyline",{class:'speed-curve-line',points:curvePoints.map(p=>x(p)+","+y(rateAt(s,p))).join(" "),fill:"none",stroke:"#cfe98b","stroke-width":2,'pointer-events':'none'});
    if(options.editable&&s.mode==='curve'&&options.selected>=0){
      for(const i of [options.selected-1,options.selected]){const a=s.keyframes[i],b=s.keyframes[i+1];if(!a||!b||Math.abs(b.rate-a.rate)<1e-8)continue;const e=segmentEase(s,i);
        for(let h=0;h<2;h++){const k=h?b:a,cx=x(a.progress+(b.progress-a.progress)*e[h*2]),cy=y(a.rate+(b.rate-a.rate)*e[h*2+1]);make('line',{x1:x(k.progress),y1:y(k.rate),x2:cx,y2:cy,stroke:'#88cfd0','stroke-opacity':.7});const g=make('g',{'data-speed-segment':i,'data-speed-handle':h,class:'speed-handle',role:'button','aria-label':`第 ${i+1} 段${h?'入':'出'}手柄`});for(const attrs of [{r:10,fill:'transparent'},{r:4,fill:'#182323',stroke:'#88cfd0','stroke-width':1.5}]){const c=document.createElementNS(svg.namespaceURI,'circle');for(const [k,v]of Object.entries({cx,cy,...attrs}))c.setAttribute(k,v);g.append(c);}}
      }
    }
    make("line",{x1:x(p),y1:top,x2:x(p),y2:bottom,stroke:"#87dbe0","stroke-width":1,"data-speed-cursor":"",'pointer-events':'none'});
    make("circle",{cx:x(p),cy:y(rateAt(s,p)),r:3,fill:"#a8eff1",'pointer-events':'none'});
    if(s?.mode==="curve")s.keyframes.forEach((f,i)=>{const g=make('g',{'data-speed-key':i,class:'speed-graph-key'+(i===options.selected?' selected':''),role:'button','aria-label':`速度点 ${i+1} · ${(f.progress*100).toFixed(2)}% · ${f.rate.toFixed(3)}×`});for(const attrs of [{r:10,fill:'transparent'},{r:i===options.selected?5:3.5,fill:i===options.selected?'#cfed83':'#dcefaf',stroke:'#182018','stroke-width':1.5}]){const c=document.createElementNS(svg.namespaceURI,'circle');for(const [k,v]of Object.entries({cx:x(f.progress),cy:y(f.rate),...attrs}))c.setAttribute(k,v);g.append(c);}});
  }
  return {valid,rateAt,integral,duration,atShooting,atCamera,windowDuration,atWindowCamera,atWindowShooting,segmentEase,boundHandles,bezierPoint,bezierParameter,bezierArea,insertKey,draw};
});
