/* Direct speed editing; the timeline owns the document and undo history. */
(function(root){
  'use strict';
  const T=root.BlitzPreviewTime,clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  class SpeedEditor{
    constructor(pane,editor,adapter){
      this.pane=pane;this.editor=editor;this.adapter=adapter;this.svg=pane.querySelector('#speedGraph');this.drag=null;
      this.view={start:0,zoom:1};this.scroll=pane.querySelector('#speedScroll');this.zoomInput=pane.querySelector('#speedZoom');
      this.zoomInput.addEventListener('input',()=>this.setZoom(2**Number(this.zoomInput.value)));
      for(const name of ['in','out','fit'])pane.querySelector(`[data-speed-view=${name}]`).onclick=()=>name==='fit'?this.resetView():this.setZoom(this.view.zoom*(name==='in'?1.5:1/1.5));
      this.scroll.addEventListener('scroll',()=>{
        if(!this.scroll.clientWidth)return;
        this.view.start=clamp(this.scroll.scrollLeft/(this.scroll.clientWidth*this.view.zoom),0,1-1/this.view.zoom);
        this.viewLabel();this.adapter.draw();
      });
      this.svg.addEventListener('wheel',e=>{
        if(this.drag||!this.editor.doc)return;
        if(e.altKey||e.ctrlKey||e.metaKey){e.preventDefault();this.setZoom(this.view.zoom*Math.exp(-e.deltaY*.002),this.point(e).p);}
        else if(this.view.zoom>1){e.preventDefault();this.setView(this.view.start+(e.deltaX||e.deltaY)/(Math.max(1,this.svg.clientWidth)*this.view.zoom),this.view.zoom);}
      },{passive:false});
      this.fields=Object.fromEntries(['progress','rate','segment'].map(n=>[n,pane.querySelector(`[data-speed-field=${n}]`)]));
      this.svg.addEventListener('pointerdown',e=>this.down(e));this.svg.addEventListener('pointermove',e=>this.move(e));
      this.svg.addEventListener('pointerup',e=>this.up(e));this.svg.addEventListener('pointercancel',()=>this.cancel());
      this.svg.addEventListener('lostpointercapture',()=>{if(this.drag)this.cancel();});
      this.svg.addEventListener('dblclick',e=>{if(!e.target.closest('[data-speed-key],[data-speed-handle]'))this.add(this.point(e));});
      pane.addEventListener('keydown',e=>this.key(e));
      pane.querySelector('[data-speed-action=add]').onclick=()=>this.add({p:this.editor.map().rateProgress(this.editor.playhead)});
      pane.querySelector('[data-speed-action=delete]').onclick=()=>this.remove();
      for(const name of ['undo','redo'])pane.querySelector(`[data-speed-action=${name}]`).onclick=()=>{this.adapter.pause();this.editor.action(name);};
      for(const name of ['progress','rate'])BlitzNumbers.configure(this.fields[name],{
        get:()=>{const k=this.speed()?.keyframes[this.index()];return k?k[name]*(name==='progress'?100:1):'';},
        set:value=>this.applyFields(name,value),
        bounds:()=>{const i=this.index(),ks=this.speed()?.keyframes;return name==='rate'?{min:.0625,max:1}:{min:i>0?(ks[i-1].progress+1.01e-5)*100:0,max:i>=0&&i<ks.length-1?(ks[i+1].progress-1.01e-5)*100:100};},
      });
      this.fields.segment.addEventListener('change',()=>{
        const index=this.segment(),mode=this.fields.segment.value;if(index<0)return;
        this.edit(()=>{const s=this.speed(),a=s.keyframes[index];if(mode==='default')delete a.ease;else a.ease=mode==='linear'?[1/3,1/3,2/3,2/3]:mode==='smooth'?[1/3,0,2/3,1]:T.segmentEase(s,index);});
      });
      new ResizeObserver(()=>{this.syncView();this.adapter.draw();}).observe(this.svg);
      window.addEventListener('blur',()=>{if(this.drag)this.cancel();});
    }
    speed(){return this.editor.doc?.speed;}
    viewLabel(){
      this.pane.querySelector('#speedZoomValue').textContent=Number(this.view.zoom.toFixed(1))+'×';
      this.pane.querySelector('#speedViewRange').textContent=`${(this.view.start*100).toFixed(1)}–${((this.view.start+1/this.view.zoom)*100).toFixed(1)}%`;
    }
    syncView(){
      this.zoomInput.value=Math.log2(this.view.zoom);this.scroll.firstElementChild.style.width=(this.view.zoom*100)+'%';
      this.scroll.scrollLeft=this.view.start*this.view.zoom*this.scroll.clientWidth;
      this.pane.querySelector('[data-speed-view=out]').disabled=this.view.zoom<=1;
      this.pane.querySelector('[data-speed-view=in]').disabled=this.view.zoom>=64;
      this.viewLabel();
    }
    setView(start,zoom){if(this.drag)return;this.view.zoom=clamp(zoom,1,64);this.view.start=clamp(start,0,1-1/this.view.zoom);this.syncView();this.adapter.draw();}
    setZoom(zoom,anchor=this.speed()?.keyframes[this.index()]?.progress??this.view.start+.5/this.view.zoom){
      const fraction=clamp((anchor-this.view.start)*this.view.zoom,0,1),next=clamp(zoom,1,64);
      this.setView(anchor-fraction/next,next);
    }
    resetView(){this.setView(0,1);}
    index(){return this.speed()?.keyframes.findIndex(k=>this.editor.selected.has(k._id))??-1;}
    segment(){const i=this.index();return i<0?-1:Math.min(i,this.speed().keyframes.length-2);}
    locked(){return !this.editor.doc||this.editor.locked||this.adapter.locked();}
    edit(fn){if(this.locked())return false;this.adapter.pause();const result=this.editor.edit(fn);this.refresh();return result;}
    curve(){const s=this.speed();if(s.mode!=='curve'){const rate=s.mode==='fixed'?s.rate:1;s.mode='curve';s.keyframes=[{progress:0,rate,_id:++this.editor.ids},{progress:1,rate,_id:++this.editor.ids}];}this.editor.anchorSpeed();return s;}
    point(e){const r=this.svg.getBoundingClientRect(),l=this.svg.speedLayout,x=(e.clientX-r.left)*l.width/r.width,y=(e.clientY-r.top)*l.height/r.height;return {p:clamp(this.view.start+(x-l.left)/(l.right-l.left)/this.view.zoom,0,1),rate:clamp((l.bottom-y)/(l.bottom-l.top),.0625,1)};}
    add(point){
      this.edit(()=>{const s=this.curve(),p=point.p,near=s.keyframes.find(k=>Math.abs(k.progress-p)<1e-5);if(near){this.editor.selected=new Set([near._id]);return;}
        const k=T.insertKey(s,p,point.rate??T.rateAt(s,p));k._id=++this.editor.ids;T.boundHandles(s);this.editor.selected=new Set([k._id]);
      });
    }
    remove(){if(!this.speed()?.keyframes.slice(1,-1).some(k=>this.editor.selected.has(k._id)))return;this.edit(()=>{const keys=this.speed().keyframes;this.speed().keyframes=keys.filter((k,i)=>i===0||i===keys.length-1||!this.editor.selected.has(k._id));T.boundHandles(this.speed());this.editor.selected.clear();});}
    applyFields(name,value){
      const i=this.index();if(i<0)return false;
      return this.edit(()=>{const s=this.speed(),k=s.keyframes[i];k[name]=value/(name==='progress'?100:1);T.boundHandles(s);});
    }
    refresh(){
      const s=this.speed();if(!s)return;const i=this.index(),k=s.keyframes[i],locked=this.locked(),selected=!!k&&s.mode==='curve';
      if(this.drag&&locked){this.cancel();return;}
      this.pane.querySelector('[data-speed-selection]').textContent=selected?`速度点 ${i+1} / ${s.keyframes.length}`:'选择速度点';
      for(const [n,value]of [['progress',selected?Number((k.progress*100).toFixed(4)):''],['rate',selected?Number(k.rate.toFixed(4)):'']]){const f=this.fields[n];if(document.activeElement!==f)f.value=value;f.disabled=locked||!selected||(n==='progress'&&(i===0||i===s.keyframes.length-1));}
      const seg=this.segment(),ease=seg>=0?s.keyframes[seg].ease:null;
      this.fields.segment.value=ease?(JSON.stringify(ease)===JSON.stringify([1/3,0,2/3,1])?'smooth':JSON.stringify(ease)===JSON.stringify([1/3,1/3,2/3,2/3])?'linear':'custom'):'default';
      this.fields.segment.disabled=locked||!selected;
      this.fields.segment.title=seg>=0?`第 ${seg+1} → ${seg+2} 个速度点之间的过渡`:'';
      for(const [name,disabled]of [['add',locked||s.keyframes.length>=64],['delete',locked||!selected||i===0||i===s.keyframes.length-1],['undo',locked||!this.editor.undoStack.length],['redo',locked||!this.editor.redoStack.length]])this.pane.querySelector(`[data-speed-action=${name}]`).disabled=disabled;
      const r=s.time_range||this.editor.doc.timeline;
      this.pane.querySelector('[data-speed-range]').textContent=s.mode==='curve'&&r?`曲线 · 对局 ${Number((r.start_sec??r.work_start_sec).toFixed(3))}–${Number((r.end_sec??r.work_end_sec).toFixed(3))} s`:`固定 ${s.mode==='paused'?0:s.rate}×`;
      this.adapter.draw();
    }
    down(e){
      if(e.button!==0||!this.editor.doc)return;e.preventDefault();this.svg.focus({preventScroll:true});
      const key=e.target.closest('[data-speed-key]'),handle=e.target.closest('[data-speed-handle]');
      if((e.ctrlKey||e.metaKey)&&!key&&!handle)return this.add(this.point(e));
      if(key){const k=this.speed().keyframes[Number(key.dataset.speedKey)];this.editor.selected=new Set([k._id]);this.editor.render();}
      if(this.locked())return;
      this.adapter.pause();this.svg.setPointerCapture(e.pointerId);
      const before=this.editor.snapshot(),p=this.point(e);
      if(handle)this.drag={kind:'handle',index:Number(handle.dataset.speedSegment),handle:Number(handle.dataset.speedHandle),before};
      else if(key)this.drag={kind:'key',index:Number(key.dataset.speedKey),before,p,x:e.clientX,y:e.clientY};
      else{this.drag={kind:'seek'};this.seek(p.p);}
      this.refresh();
    }
    seek(p){const map=this.editor.map();this.adapter.seek(map.rateTime(p));}
    move(e){
      const d=this.drag;if(!d)return;const p=this.point(e);if(d.kind==='seek')return this.seek(p.p);
      if(d.kind==='key'&&!d.moved&&Math.abs(e.clientX-d.x)+Math.abs(e.clientY-d.y)<3)return;
      d.moved=true;this.editor.doc=JSON.parse(JSON.stringify(d.before));const s=this.speed(),keys=s.keyframes;
      if(d.kind==='key'){
        const k=keys[d.index],factor=e.altKey ? .1 : 1,dp=(p.p-d.p.p)*factor,dr=(p.rate-d.p.rate)*factor;
        if(d.index>0&&d.index<keys.length-1&&(!e.shiftKey||Math.abs(e.clientX-d.x)>=Math.abs(e.clientY-d.y)))k.progress=clamp(k.progress+dp,keys[d.index-1].progress+1.01e-5,keys[d.index+1].progress-1.01e-5);
        if(!e.shiftKey||Math.abs(e.clientY-d.y)>Math.abs(e.clientX-d.x))k.rate=clamp(k.rate+dr,.0625,1);
        T.boundHandles(s);
      }else{
        const a=keys[d.index],b=keys[d.index+1],ease=T.segmentEase(s,d.index),h=d.handle;
        ease[h*2]=clamp((p.p-a.progress)/(b.progress-a.progress),h?ease[0]:0,h?1:ease[2]);
        ease[h*2+1]=(p.rate-a.rate)/(b.rate-a.rate);a.ease=ease;
      }
      this.editor.render();this.refresh();
    }
    up(e){const d=this.drag;if(!d)return;this.drag=null;if(this.svg.hasPointerCapture(e.pointerId))this.svg.releasePointerCapture(e.pointerId);
      if(d.before&&d.moved){try{this.editor.validate();this.editor.commit(d.before);}catch(error){this.editor.doc=d.before;this.editor.render();this.adapter.error(error.message);}}this.refresh();}
    cancel(){if(this.drag?.before)this.editor.doc=this.drag.before;this.drag=null;this.editor.render();this.refresh();}
    key(e){
      if(this.drag&&(e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();e.stopPropagation();this.cancel();return;}
      if(e.key==='Escape'&&this.drag){e.preventDefault();e.stopPropagation();this.cancel();return;}
      if(e.target.closest('input,select')){if(e.key==='Enter'){e.preventDefault();e.target.blur();this.svg.focus();}return;}
      if(e.key==='Delete'||e.key==='Backspace'){e.preventDefault();e.stopPropagation();this.remove();}
      if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key)&&this.index()>=0){e.preventDefault();e.stopPropagation();const i=this.index(),step=e.shiftKey?10:1;this.edit(()=>{const ks=this.speed().keyframes,k=ks[i];if(e.key==='ArrowUp'||e.key==='ArrowDown')k.rate=clamp(k.rate+(e.key==='ArrowUp'?1:-1)*.01*step,.0625,1);else if(i>0&&i<ks.length-1)k.progress=clamp(k.progress+(e.key==='ArrowRight'?1:-1)*.001*step,ks[i-1].progress+1.01e-5,ks[i+1].progress-1.01e-5);T.boundHandles(this.speed());});}
    }
  }
  root.BlitzSpeedEditor=SpeedEditor;
})(globalThis);
