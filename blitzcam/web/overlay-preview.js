/* Small, read-only path renderer. It never calls a camera or replay API. */
(function(root,factory){
  const value=factory();
  if(typeof module!=="undefined"&&module.exports)module.exports=value;
  else root.BlitzMiniPreview=value;
})(typeof globalThis!=="undefined"?globalThis:this,function(){
  "use strict";
  function project(p,view,yaw=-.58,elevation=.65){
    if(view==="xy")return[p[0],-p[1]];
    if(view==="xz")return[p[0],-p[2]];
    return[p[0]*Math.cos(yaw)-p[1]*Math.sin(yaw),
      (p[0]*Math.sin(yaw)+p[1]*Math.cos(yaw))*Math.sin(elevation)-p[2]*Math.cos(elevation)];
  }
  function axes(q){
    const norm=Math.hypot(...q),[w,x,y,z]=q.map(v=>v/norm);
    return {forward:[-2*(x*z+y*w),-2*(y*z-x*w),-(1-2*(x*x+y*y))],
      right:[1-2*(y*y+z*z),2*(x*y+z*w),2*(x*z-y*w)]};
  }
  function nearest(samples,time){
    if(!samples.length)return null;
    let lo=0,hi=samples.length-1;
    while(lo<hi){const mid=(lo+hi)>>1;if(samples[mid].time_sec<time)lo=mid+1;else hi=mid;}
    if(lo>0&&time-samples[lo-1].time_sec<samples[lo].time_sec-time)return samples[lo-1];
    return samples[lo];
  }
  class Preview {
    constructor(canvas,onTime){
      this.canvas=canvas;this.onTime=onTime;this.samples=[];this.frames=[];this.times=[];
      this.progress=0;this.view="3d";this.playing=false;this.raf=0;
      this.yaw=-.58;this.elevation=.65;this.zoom=1;this.pan=[0,0];this.speed=null;
      let drag=null;
      canvas.addEventListener("pointerdown",e=>{if(e.button!==0&&e.button!==1)return;drag={x:e.clientX,y:e.clientY,pan:e.shiftKey||e.button===1};canvas.setPointerCapture(e.pointerId);e.preventDefault();});
      canvas.addEventListener("pointermove",e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;drag.x=e.clientX;drag.y=e.clientY;if(drag.pan||this.view!=="3d"){this.pan[0]+=dx;this.pan[1]+=dy;}else{this.yaw+=dx*.012;this.elevation=Math.max(.08,Math.min(1.5,this.elevation+dy*.01));}this.draw();});
      for(const name of ["pointerup","pointercancel","lostpointercapture"])canvas.addEventListener(name,()=>drag=null);
      canvas.addEventListener("wheel",e=>{e.preventDefault();this.zoom=Math.max(.2,Math.min(8,this.zoom*Math.exp(-e.deltaY*.0015)));this.draw();},{passive:false});
      canvas.addEventListener("dblclick",()=>this.fit());
      this.observer=new ResizeObserver(()=>this.draw());this.observer.observe(canvas);
    }
    fit(){this.yaw=-.58;this.elevation=.65;this.zoom=1;this.pan=[0,0];this.draw();}
    load(samples,frames,times,speed=null,timeline=null){
      this.pause();this.samples=samples;this.frames=frames;this.times=times;
      this.speed=speed;
      this.start=timeline?.work_start_sec??samples[0]?.time_sec??0;this.duration=(timeline?.work_end_sec??samples.at(-1)?.time_sec??this.start)-this.start;
      this.setProgress(0);
    }
    setProgress(value){this.progress=Math.max(0,Math.min(1,value));this.draw();this.onTime?.(this.progress,this.duration||0,this.playing);}
    pause(){this.playing=false;cancelAnimationFrame(this.raf);this.onTime?.(this.progress,this.duration||0,false);}
    toggle(){
      if(this.playing){this.pause();return;}
      if(!this.samples.length||!this.duration)return;
      if(this.progress>=1)this.progress=0;
      this.playing=true;const began=performance.now(),initial=BlitzPreviewTime.atWindowCamera(this.start,this.start+this.duration,this.speed,this.start+this.duration*this.progress);
      const tick=now=>{if(!this.playing)return;const elapsed=Math.min(initial.shootingDuration,initial.shootingElapsed+(now-began)/1000);this.setProgress(BlitzPreviewTime.atWindowShooting(this.start,this.start+this.duration,this.speed,elapsed).cameraProgress);if(elapsed>=initial.shootingDuration)this.pause();else this.raf=requestAnimationFrame(tick);};
      this.raf=requestAnimationFrame(tick);
    }
    draw(){
      const rect=this.canvas.getBoundingClientRect();if(rect.width<1||rect.height<1)return;
      const dpr=window.devicePixelRatio||1,w=rect.width,h=rect.height;
      this.canvas.width=Math.round(w*dpr);this.canvas.height=Math.round(h*dpr);
      const ctx=this.canvas.getContext("2d");ctx.scale(dpr,dpr);ctx.clearRect(0,0,w,h);
      ctx.fillStyle="rgba(6,14,20,.32)";ctx.fillRect(0,0,w,h);
      ctx.strokeStyle="rgba(134,165,172,.10)";ctx.lineWidth=1;
      for(let x=20;x<w;x+=24){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,h);ctx.stroke();}
      for(let y=16;y<h;y+=24){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke();}
      if(!this.samples.length){ctx.fillStyle="#a9bec0";ctx.font="11px Segoe UI";ctx.textAlign="center";ctx.fillText("在不同时刻记录属性关键帧以预览轨迹",w/2,h/2);return;}
      const positions=[...this.samples,...this.frames].map(s=>s.position);
      const low=[0,1,2].map(i=>Math.min(...positions.map(p=>p[i]))),high=[0,1,2].map(i=>Math.max(...positions.map(p=>p[i])));
      const extent=Math.max(2,...high.map((v,i)=>v-low[i])),center=low.map((v,i)=>(v+high[i])/2),ground=low[2]-extent*.12;
      const gridCorner=(x,y)=>[center[0]+x*extent*.6,center[1]+y*extent*.6,ground];
      const reference=this.view==="3d"?[-1,1].flatMap(x=>[-1,1].map(y=>gridCorner(x,y))):[];
      const all=[...positions,...reference].map(p=>project(p,this.view,this.yaw,this.elevation));
      const min=[Math.min(...all.map(p=>p[0])),Math.min(...all.map(p=>p[1]))];
      const max=[Math.max(...all.map(p=>p[0])),Math.max(...all.map(p=>p[1]))];
      const scale=this.zoom*Math.min((w-50)/Math.max(1,max[0]-min[0]),(h-46)/Math.max(1,max[1]-min[1]));
      const point=p=>{const q=project(p,this.view,this.yaw,this.elevation);return[w/2+this.pan[0]+(q[0]-(min[0]+max[0])/2)*scale,h/2+this.pan[1]+(q[1]-(min[1]+max[1])/2)*scale];};
      const time=this.start+this.progress*this.duration,pose=nearest(this.samples,time);
      const line=(rows,color,width)=>{ctx.beginPath();rows.forEach((p,i)=>{const q=point(p.position);if(i)ctx.lineTo(...q);else ctx.moveTo(...q);});ctx.strokeStyle=color;ctx.lineWidth=width;ctx.lineJoin="round";ctx.stroke();};
      if(this.view==="3d"){
        ctx.beginPath();[[ -1,-1],[1,-1],[1,1],[-1,1]].forEach(([x,y],i)=>{const q=point(gridCorner(x,y));if(i)ctx.lineTo(...q);else ctx.moveTo(...q);});ctx.closePath();ctx.fillStyle="rgba(70,105,109,.12)";ctx.fill();
        for(let i=-5;i<=5;i++){const t=i/5;line([{position:gridCorner(t,-1)},{position:gridCorner(t,1)}],"#526e7360",.6);line([{position:gridCorner(-1,t)},{position:gridCorner(1,t)}],"#526e7360",.6);}
        ctx.setLineDash([3,3]);line(this.samples.map(s=>({position:[s.position[0],s.position[1],ground]})),"#a8c27b45",1);
        ctx.setLineDash([]);
      }
      line(this.samples,"#8fa969",1.7);line(this.samples.filter(s=>s.time_sec<=time),"#dcf4a8",2.3);
      if(pose){
        const q=point(pose.position),basis=axes(pose.quaternion),depth=17/scale;
        const fov=Math.min(135,Math.max(5,pose.horizontal_fov_deg||60)),spread=Math.tan(fov*Math.PI/360)*depth;
        const end=sign=>point(pose.position.map((v,i)=>v+basis.forward[i]*depth+sign*basis.right[i]*spread));
        ctx.beginPath();ctx.moveTo(...q);ctx.lineTo(...end(-1));ctx.lineTo(...end(1));ctx.closePath();ctx.fillStyle="rgba(131,215,222,.2)";ctx.fill();ctx.strokeStyle="#92d3db";ctx.lineWidth=1;ctx.stroke();
        ctx.beginPath();ctx.arc(...q,2.5,0,Math.PI*2);ctx.fillStyle="#c3f1ef";ctx.fill();
      }
      const origin=[w-30,30];ctx.font="9px Consolas";ctx.textAlign="center";
      for(const [name,vec,color]of[["X",[1,0,0],"#e5b098"],["Y",[0,1,0],"#bdd889"],["Z",[0,0,1],"#93c7e0"]]){
        const d=project(vec,this.view,this.yaw,this.elevation);if(Math.hypot(...d)<.01)continue;const tip=[origin[0]+d[0]*18,origin[1]+d[1]*18];ctx.beginPath();ctx.moveTo(...origin);ctx.lineTo(...tip);ctx.strokeStyle=color;ctx.lineWidth=1;ctx.stroke();ctx.fillStyle=color;ctx.fillText(name,tip[0]+d[0]*7,tip[1]+d[1]*7+3);
      }
      ctx.font="9px Segoe UI";ctx.textAlign="left";ctx.fillStyle="#dce5e2";ctx.fillText("辅助网格 · 非实际地面",8,h-7);
    }
  }
  return {Preview,project,axes,nearest};
});
