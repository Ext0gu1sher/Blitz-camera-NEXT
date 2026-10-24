/* Replay-anchored parameter keys with a separate shooting-time rate track. */
(function(root,factory){const common=typeof module!=="undefined"&&module.exports,api=factory(common?require('./preview-time.js'):root.BlitzPreviewTime,common?require('./keyframe-clipboard.js'):root.BlitzKeyframeClipboard);if(common)module.exports=api;else root.BlitzTimeline=api;})(typeof globalThis!=="undefined"?globalThis:this,function(Timing,Clipboard){
  "use strict";
  const CHANNELS=[['x','X','#d99589'],['y','Y','#98c889'],['z','Z','#80b6e3'],['yaw','摄像机水平角度','#b5a0e1'],['pitch','俯仰','#b5a0e1'],['roll','横滚','#b5a0e1'],['zoom','缩放','#e0b96e']];
  const clone=x=>JSON.parse(JSON.stringify(x)),clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
  const clean=rows=>rows.map(({_id,...r})=>r);
  const rateMean=(speed,i)=>{const a=speed.keyframes[i],b=speed.keyframes[i+1];return a.rate+(b.rate-a.rate)*(a.ease?Timing.bezierArea(a.ease,1):.5);};
  const pretty=t=>Number.isFinite(t)?t.toFixed(3):'—';
  const clipboardType='application/x-blitzcam-keyframes',clipboardPrefix='BlitzCamera keyframes\n';
  class ClockMap{
    constructor(tracks,speed,timeline=null){const ts=Object.values(tracks).flat().map(k=>k.time_sec);this.start=timeline?0:Math.min(...ts);this.end=timeline?timeline.duration_sec:Math.max(...ts);this.duration=this.end-this.start;this.speed=speed;this.workStart=timeline?.work_start_sec??this.start;this.workEnd=timeline?.work_end_sec??this.end;this.workDuration=this.workEnd-this.workStart;this.workSeconds=Timing.windowDuration(this.workStart,this.workEnd,speed);this.seconds=this.duration-this.workDuration+this.workSeconds;const range=speed.mode==='curve'?speed.time_range:null;this.rateStart=range?.start_sec??this.workStart;this.rateEnd=range?.end_sec??this.workEnd;this.rateDuration=this.rateEnd-this.rateStart;this.rateSeconds=Timing.duration(this.rateDuration,speed);}
    atTime(t){t=clamp(t,this.start,this.end);if(t<this.workStart)return t-this.start;if(t>this.workEnd)return this.workStart-this.start+this.workSeconds+t-this.workEnd;return this.workStart-this.start+Timing.atWindowCamera(this.workStart,this.workEnd,this.speed,t).shootingElapsed;}
    atSeconds(s){s=clamp(s,0,this.seconds);const before=this.workStart-this.start;if(s<before)return this.start+s;if(s>before+this.workSeconds)return this.workEnd+s-before-this.workSeconds;return this.workStart+Timing.atWindowShooting(this.workStart,this.workEnd,this.speed,s-before).cameraProgress*this.workDuration;}
    rateTime(p){return this.rateStart+Timing.atShooting(this.rateDuration,this.speed,p).cameraProgress*this.rateDuration;}
    rateProgress(t){return Timing.atCamera(this.rateDuration,this.speed,(t-this.rateStart)/this.rateDuration).shootingProgress;}
  }
  class Editor{
    constructor(root,adapter){
      this.root=root;this.adapter=adapter;this.ids=0;this.doc=null;this.selected=new Set();this.undoStack=[];this.redoStack=[];
      this.clipboard=null;
      this.scale=65;this.axis='replay';this.fps=60;this.snap=true;this.playhead=0;this.drag=null;
      root.innerHTML=`<div class="seq-top"><span class="ph" id="sequenceTitle">时间轴</span><span class="seq-bound" id="shootingModeBadge">对局时间绑定</span><div class="seq-counter"><output data-counter>00:00:00:00</output><small data-battle>对局 +0.000 s</small></div><div class="seq-range"><button data-action="inpoint" title="将游戏当前暂停时刻设为入点" aria-label="用游戏当前时间设入点"><svg class="ic"><use href="#i-inpoint"/></svg></button><button data-action="follow" title="将编辑器播放头定位到游戏当前暂停时刻" aria-label="定位到游戏当前时间"><svg class="ic"><use href="#i-clock"/></svg></button><small data-source hidden></small></div><div class="seq-tools"><button data-action="undo" title="撤销 Ctrl+Z" aria-label="撤销"><svg class="ic"><use href="#i-undo"/></svg></button><button data-action="redo" title="重做 Ctrl+Shift+Z" aria-label="重做"><svg class="ic"><use href="#i-redo"/></svg></button><span class="seq-divider"></span><button data-action="previous" title="上一个关键帧" aria-label="上一个关键帧"><svg class="ic"><use href="#i-prev"/></svg></button><button data-action="next" title="下一个关键帧" aria-label="下一个关键帧"><svg class="ic"><use href="#i-next"/></svg></button><button data-action="snap" aria-pressed="true" title="帧与关键帧吸附" aria-label="吸附"><svg class="ic"><use href="#i-snap"/></svg></button><label title="标尺"><select data-option="axis" aria-label="标尺"><option value="shooting">拍摄</option><option value="replay">对局</option></select></label><label title="帧率"><select data-option="fps" aria-label="时间轴帧率"><option value="24">24</option><option value="30">30</option><option value="60" selected>60</option></select></label><button data-action="out" title="缩小时间轴" aria-label="缩小"><svg class="ic"><use href="#i-zoom-out"/></svg></button><button data-action="in" title="放大时间轴" aria-label="放大"><svg class="ic"><use href="#i-zoom-in"/></svg></button><button data-action="fit" title="适配全部" aria-label="适配"><svg class="ic"><use href="#i-fit"/></svg></button><button data-action="workfit" title="放大到当前工作区间" aria-label="放大到工作区间"><svg class="ic"><use href="#i-range"/></svg></button></div><button class="ib" id="addKeyframeButton" title="在播放头添加全部属性关键帧" aria-label="播放头添加全部属性"><svg class="ic"><use href="#i-plus"/></svg></button></div>
        <div class="seq-body"><div class="seq-labels"><div class="seq-ruler-label">对局时间 / 拍摄参考</div>${CHANNELS.map(([id,label,color])=>`<div class="seq-label" style="--track:${color}"><i></i><span>${label}</span><button data-add="${id}" title="在播放头添加${label}关键帧" aria-label="添加${label}关键帧"><svg class="ic"><use href="#i-plus"/></svg></button></div>`).join('')}<div class="seq-rate-label"><i></i><span>播放速率</span><button data-add="rate" title="添加速率关键帧" aria-label="添加速率关键帧"><svg class="ic"><use href="#i-plus"/></svg></button><small>工作区间内变速</small></div></div><div class="seq-scroll" tabindex="0" aria-label="七条摄像机参数轨道与播放速率轨道"><div class="seq-content"><svg class="seq-svg" aria-label="参数关键帧时间轴"></svg><div class="seq-head" aria-label="时间轴播放头"><i></i></div><div class="seq-box" hidden></div></div></div></div>
        <div class="seq-inspector"><span class="seq-keyframe-guard" data-keyframe-guard hidden></span><span class="seq-status" data-status>摄像机关键帧绑定对局时间</span></div>
        <p class="seq-key-warning" data-key-warning hidden></p>`;
      root.querySelector('.seq-tools .seq-divider').insertAdjacentHTML('beforebegin',`<button data-action="copy" title="复制选中关键帧 Ctrl+C" aria-label="复制选中关键帧" disabled><svg class="ic"><use href="#i-copy"/></svg></button><button data-action="paste" title="将最近复制的关键帧粘贴到播放头 Ctrl+V · 同轨同刻覆盖" aria-label="粘贴关键帧到播放头" disabled><svg class="ic"><use href="#i-paste"/></svg></button>`);
      root.querySelector('[data-option=axis]').value=this.axis;
      root.querySelector('#addKeyframeButton').addEventListener('click',()=>this.add('all'));
      this.scroll=root.querySelector('.seq-scroll');this.labels=root.querySelector('.seq-labels');this.content=root.querySelector('.seq-content');this.svg=root.querySelector('.seq-svg');this.head=root.querySelector('.seq-head');
      this.inspectorRoot=adapter.inspector||root;
      root.ownerDocument.addEventListener('copy',e=>this.onClipboardCopy(e));
      root.ownerDocument.addEventListener('paste',e=>this.onClipboardPaste(e));
      const number=(field)=>this.inspectorRoot.querySelector(`[data-field=${field}]`);
      for(const field of ['time','value'])if(number(field)&&globalThis.BlitzNumbers)BlitzNumbers.configure(number(field),{
        get:()=>this.inspectValue(field),set:value=>this.setInspectorValue(field,value),
        step:()=>field==='time'?1/this.fps:this.singleSelection()?.row.name==='rate'?.01:.1,
        bounds:()=>this.inspectBounds(field),
      });
      this.inspectorRoot.addEventListener('click',e=>{const a=e.target.closest('[data-action]');if(a)this.action(a.dataset.action);});
      this.inspectorRoot.addEventListener('keydown',e=>{if(e.target.closest('.number-value')&&(e.key==='Delete'||e.key==='Backspace')){e.preventDefault();e.stopPropagation();this.action('delete');}});
      root.addEventListener('click',e=>{const a=e.target.closest('[data-action]');if(a)this.action(a.dataset.action);const add=e.target.closest('[data-add]');if(add)this.add(add.dataset.add);});
      root.addEventListener('change',e=>{const key=e.target.dataset.option;if(key==='axis'){this.axis=e.target.value;this.fit();}if(key==='fps'){this.fps=Number(e.target.value);this.updatePlayhead(this.playhead);} });
      root.addEventListener('pointerdown',e=>this.down(e));root.addEventListener('pointermove',e=>this.move(e));root.addEventListener('pointerup',e=>this.up(e));root.addEventListener('pointercancel',()=>this.cancel());
      root.addEventListener('lostpointercapture',e=>{if(this.drag?.kind==='work')this.cancel();else if(this.drag?.pointerId===e.pointerId)this.up(e);});
      root.ownerDocument.addEventListener('pointerup',e=>{if(this.drag?.pointerId===e.pointerId)this.up(e);},true);
      root.ownerDocument.defaultView.addEventListener('blur',()=>{if(['work','seek'].includes(this.drag?.kind))this.cancel();});
      // A pointer transaction owns the range until release or cancellation;
      // do not let editor/global playback shortcuts commit its temporary data.
      root.ownerDocument.addEventListener('keydown',e=>{
        if(this.drag?.kind!=='work'||e.key==='Alt')return;
        e.preventDefault();e.stopImmediatePropagation();
        if(e.key==='Escape')this.cancel();
      },true);
      root.addEventListener('keydown',e=>this.key(e));
      this.scroll.addEventListener('wheel',e=>{
        if(e.altKey){e.preventDefault();if(this.drag)return;const anchor=e.clientX-this.scroll.getBoundingClientRect().left,now=performance.now();if(!this.wheelAnchor||now-this.wheelAnchor.now>400||Math.abs(anchor-this.wheelAnchor.anchor)>1)this.wheelAnchor={anchor,time:(this.scroll.scrollLeft+anchor-14)/this.scale};this.wheelAnchor.now=now;this.zoom(e.deltaY<0?1.2:1/1.2,anchor,this.wheelAnchor.time);return;}
        e.preventDefault();this.wheelAnchor=null;
        if(e.ctrlKey||e.shiftKey){this.scroll.scrollTop+=e.deltaY;return;}
        this.scroll.scrollLeft+=e.deltaY+e.deltaX;
      },{passive:false});
      this.scroll.addEventListener('scroll',()=>{this.labels.scrollTop=this.scroll.scrollTop;if(this.free()&&this.scroll.scrollLeft+this.scroll.clientWidth>=this.content.clientWidth-120)this.grow((this.scroll.scrollLeft+this.scroll.clientWidth*3)/this.scale);if(!this.scrollFrame)this.scrollFrame=requestAnimationFrame(()=>{this.scrollFrame=0;this.render();});});
      new ResizeObserver(()=>{if(!this.doc)return;if(this.pendingFit&&this.scroll.clientWidth>0)this.fit();else this.render();}).observe(this.scroll);
    }
    load(tracks,speed,preserve=false,timeline=null,mode=timeline?'replay':'camera_only'){
      if(this.drag)this.cancel();
      if(this.numberEdit)globalThis.BlitzNumbers?.finish();
      const previous=this.doc;this.doc={tracks:clone(tracks),speed:clone(speed),timeline:timeline?clone(timeline):null,mode};this.anchorSpeed();this.horizon=Math.max(30,preserve?this.horizon||0:0,...Object.values(tracks).flat().map(k=>k.time_sec+10));if(this.free())this.axis='shooting';
      for(const name of CHANNELS.map(c=>c[0]))this.doc.tracks[name].forEach(k=>k._id=preserve?previous?.tracks[name].find(p=>p.time_sec===k.time_sec)?._id||++this.ids:++this.ids);
      this.doc.speed.keyframes.forEach(k=>k._id=preserve?previous?.speed.keyframes.find(p=>p.progress===k.progress)?._id||++this.ids:++this.ids);
      if(!preserve){this.selected.clear();this.undoStack=[];this.redoStack=[];this.fit();}else this.render();
    }
    data(){return {tracks:Object.fromEntries(Object.entries(this.doc.tracks).map(([n,r])=>[n,clean(r)])),speed:{...this.doc.speed,keyframes:clean(this.doc.speed.keyframes),mode:this.free()?'paused':this.doc.speed.mode,camera_clock:this.free()?'shooting':'replay'},timeline:clone(this.doc.timeline),mode:this.doc.mode};}
    free(){return this.doc?.mode==='camera_only';}
    anchorSpeed(){const d=this.doc;if(!this.free()&&d.timeline&&d.speed.mode==='curve'&&!d.speed.time_range)d.speed.time_range={start_sec:d.timeline.work_start_sec,end_sec:d.timeline.work_end_sec};}
    expandSpeedRange(time){
      const s=this.doc.speed,r=s.time_range;if(!r||time>=r.start_sec&&time<=r.end_sec)return false;
      const start=Math.min(time,r.start_sec),end=Math.max(time,r.end_sec),old=Timing.duration(r.end_sec-r.start_sec,s);
      const before=(r.start_sec-start)/s.keyframes[0].rate,after=(end-r.end_sec)/s.keyframes.at(-1).rate,total=before+old+after;
      for(const k of s.keyframes)k.progress=(before+k.progress*old)/total;
      if(before)s.keyframes.unshift({progress:0,rate:s.keyframes[0].rate,_id:++this.ids});
      if(after)s.keyframes.push({progress:1,rate:s.keyframes.at(-1).rate,_id:++this.ids});
      s.time_range={start_sec:start,end_sec:end};return true;
    }
    setMode(mode,timeline){this.edit(()=>{this.doc.mode=mode;this.doc.timeline=clone(timeline);if(mode==='replay'&&this.doc.speed.mode==='paused')this.doc.speed.mode='curve';});this.axis=mode==='camera_only'?'shooting':'replay';this.fit();}
    map(){if(this.free()){const end=Math.max(this.horizon||30,...Object.values(this.doc.tracks).flat().map(k=>k.time_sec+10));this.horizon=end;return new ClockMap(this.doc.tracks,{...this.doc.speed,mode:'paused'},{duration_sec:end,work_start_sec:0,work_end_sec:end});}return new ClockMap(this.doc.tracks,this.doc.speed,this.doc.timeline);}
    height(){return this.free()?208:310;}
    grow(time){if(this.free())this.horizon=Math.max(this.horizon||30,time+Math.max(10,this.scroll.clientWidth/this.scale));}
    autoPan(e){
      this.lastPointer={clientX:e.clientX,clientY:e.clientY,altKey:e.altKey,auto:true};
      if(this.autoFrame)return;
      const frame=now=>{this.autoFrame=0;const d=this.drag;if(!d||!['key','work','seek'].includes(d.kind))return;
        const smooth=d.kind==='seek',band=smooth?40:30,r=this.scroll.getBoundingClientRect(),p=this.lastPointer;
        const edge=p.clientX>r.right-band?1:p.clientX<r.left+band?-1:0;
        if(!edge){d.panEdge=0;d.panVelocity=0;d.panFraction=0;return;}
        let step=12;
        if(smooth){
          if(d.panEdge!==edge){d.panEdge=edge;d.panAt=now;d.panVelocity=0;d.panFraction=0;}
          const dt=clamp((now-d.panAt)/1000,0,.05);d.panAt=now;
          const depth=clamp((edge>0?p.clientX-r.right+band:r.left+band-p.clientX)/band,0,1);
          // Ease into a gentle pixels-per-second speed, increasing toward the
          // edge. Cap frame time so a busy preview cannot cause a large jump.
          const target=180*depth*depth;
          d.panVelocity+=(target-d.panVelocity)*(1-Math.exp(-dt/.22));
          step=d.panVelocity*dt;
        }
        const horizon=this.horizon;
        if(edge>0)this.grow((this.scroll.scrollLeft+this.scroll.clientWidth+step)/this.scale);
        if(!smooth||this.horizon!==horizon)this.render();
        const before=this.scroll.scrollLeft,max=this.scroll.scrollWidth-this.scroll.clientWidth;
        // Keep subpixel movement until the browser can scroll a physical pixel.
        // A very slow start must not stall because scrollLeft rounds each frame.
        const delta=edge*step+(smooth?d.panFraction:0);
        this.scroll.scrollLeft=clamp(before+delta,0,max);
        const moved=this.scroll.scrollLeft-before;if(smooth)d.panFraction=delta-moved;
        if(moved)this.move(p);
        if(smooth?(edge>0?this.scroll.scrollLeft<max:this.scroll.scrollLeft>0):moved)this.autoFrame=requestAnimationFrame(frame);
      };this.autoFrame=requestAnimationFrame(frame);
    }

    rows(){return [...CHANNELS.map(([name],i)=>({name,y:40+i*24,height:24,keys:this.doc.tracks[name]})),...(this.free()?[]:[{name:'rate',y:208,height:102,keys:this.doc.speed.keyframes}])];}
    locate(id){for(const row of this.rows()){const key=row.keys.find(k=>k._id===id);if(key)return {row,key};}return null;}
    displayTime(time,map=this.map()){return this.free()?time:this.axis==='shooting'?map.atTime(time):time-map.start;}
    fromDisplay(value,map=this.map()){return this.free()?value:this.axis==='shooting'?map.atSeconds(value):map.start+value;}
    total(map=this.map()){return this.axis==='shooting'?map.seconds:map.duration;}
    rateDisplay(p,map=this.map()){return this.displayTime(map.rateTime(p),map);}
    x(time,map){return 14+this.displayTime(time,map)*this.scale;}
    fit(){if(!this.doc)return;this.pendingFit=this.scroll.clientWidth<=0;if(this.pendingFit)return;this.scale=clamp((this.scroll.clientWidth-32)/Math.max(.5,this.free()?Math.max(10,...Object.values(this.doc.tracks).flat().map(k=>k.time_sec)):this.total()),.000001,1000);this.scroll.scrollLeft=0;this.render();}
    zoom(factor,anchor=this.scroll.clientWidth/2,at=(this.scroll.scrollLeft+anchor-14)/this.scale){this.scale=clamp(this.scale*factor,.000001,2000);this.render();this.scroll.scrollLeft=14+at*this.scale-anchor;}
    render(){
      if(!this.doc)return;const map=this.free()||this.drag?.rate?this.map():this.drag?.map||this.map(),total=this.total(map),width=Math.max(this.scroll.clientWidth-1,28+total*this.scale),height=this.height();
      this.root.classList.toggle('seq-camera-only',this.free());this.content.style.height=height+'px';this.head.style.height=height+'px';
      this.root.querySelector('.seq-range').hidden=this.free();this.root.querySelector('.seq-rate-label').hidden=this.free();
      for(const selector of ['[data-option=axis]','[data-action=workfit]'])this.root.querySelector(selector).closest(selector==='[data-option=axis]'?'label':'button').hidden=this.free();
      this.root.querySelector('.seq-ruler-label').textContent=this.free()?'镜头时间':'对局时间 / 拍摄参考';
      this.content.style.width=width+'px';this.svg.setAttribute('width',width);this.svg.setAttribute('height',height);this.svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
      const html=[],line=(x1,y1,x2,y2,cls)=>`<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" class="${cls}"/>`;
      let step=1;const target=78/this.scale;step=[.05,.1,.2,.5,1,2,5,10,20,30,60,120,300,600].find(n=>n>=target)||1200;
      const visibleStart=Math.max(0,Math.floor((this.scroll.scrollLeft-100)/this.scale/step)*step),visibleEnd=Math.min(total,(this.scroll.scrollLeft+this.scroll.clientWidth+100)/this.scale);
      for(let t=visibleStart;t<=visibleEnd+1e-6;t+=step){const x=14+t*this.scale,battle=this.axis==='shooting'?map.atSeconds(t):map.start+t,shoot=this.axis==='shooting'?t:map.atTime(map.start+t);
        html.push(line(x,0,x,height,'seq-grid'),`<text x="${x+4}" y="13" class="seq-ruler-main">${this.axis==='replay'?this.labelTime(battle):shoot.toFixed(step<1?2:1)+'s'}</text><text x="${x+4}" y="27" class="seq-ruler-sub">${this.axis==='replay'?'拍摄 '+shoot.toFixed(2)+'s':(this.free()?'镜头时间':'对局 '+this.labelTime(battle))}</text>`);
      }
      const guard=this.free()?null:this.adapter.keyframeGuard?.(this.data()),guardStart=guard?.enabled&&Number.isFinite(guard.start_sec)?guard.start_sec:null;
      const guardX=guard?.enabled?this.x(guardStart===null?map.end:clamp(guardStart,map.start,map.end),map):null;
      // A range edit changes the shooting clock. Keep the ruler frozen while
      // drawing the live boundaries through the map captured on pointerdown.
      const workStart=this.doc.timeline?.work_start_sec??map.workStart,workEnd=this.doc.timeline?.work_end_sec??map.workEnd;
      const workX=this.x(workStart,map),workEndX=this.x(workEnd,map);
      if(this.snapLine!=null){const sx=14+this.snapLine*this.scale;html.push(`<line x1="${sx}" y1="0" x2="${sx}" y2="${height}" class="seq-snap-line"/>`);}
      html.push(`<rect x="0" y="0" width="${width}" height="40" class="seq-ruler-hit" data-ruler=""/>`);
      if(!this.free()){
        const duration=pretty(workEnd-workStart),active=this.drag?.kind==='work'?this.drag.part:'';
        html.push(`<g class="seq-work${active?' dragging':''}" aria-label="游戏播放区间：入点 ${pretty(workStart)} 秒，出点 ${pretty(workEnd)} 秒，长度 ${duration} 秒"><rect x="${workX}" y="30" width="${Math.max(1,workEndX-workX)}" height="9" class="seq-work-area${active==='range'?' active':''}" data-work="range"><title>拖动平移游戏播放区间 · Alt 暂停吸附</title></rect><path d="M ${workX} 28 v 11 M ${workEndX} 28 v 11" class="seq-work-edges"/>`);
        for(const [part,x,label] of [['start',workX,'入'],['end',workEndX,'出']]){
          const hitX=part==='start'?x-14:x,gripX=part==='start'?x-13:x+1;
          html.push(`<g class="seq-work-handle${active===part?' active':''}" data-work="${part}" role="slider" aria-label="${label}点" aria-valuemin="0" aria-valuemax="${map.end}" aria-valuenow="${part==='start'?workStart:workEnd}"><title>拖动调整${label}点 · Alt 暂停吸附</title><rect x="${hitX}" y="24" width="14" height="15" class="seq-work-hit"/><rect x="${gripX}" y="27" width="12" height="12" rx="2" class="seq-work-grip"/><text x="${gripX+6}" y="36" class="seq-work-label" text-anchor="middle">${label}</text></g>`);
        }
        html.push('</g>');
      }
      for(const [i,row] of this.rows().entries()){
        html.push(`<rect x="0" y="${row.y}" width="${width}" height="${row.height}" class="seq-row-bg ${i%2?'alt':''}"/>`);
        if(row.name!=='rate'){
          if(guardX!==null)html.push(`<rect x="${this.x(map.start,map)}" y="${row.y}" width="${Math.max(0,guardX-this.x(map.start,map))}" height="${row.height}" class="seq-keyframe-blocked"/>`);
          const keys=row.keys,first=keys[0],last=keys.at(-1);html.push(line(this.x(first.time_sec,map),row.y+12,this.x(last.time_sec,map),row.y+12,'seq-track-span'));
          for(const k of keys){const x=this.x(k.time_sec,map),y=row.y+12;html.push(this.diamond(k,x,y,row.name,`${CHANNELS[i][1]} · ${this.free()?'镜头':'对局'} ${pretty(k.time_sec)}s · ${pretty(k.value)}`));}
        }else{
          const sy=r=>row.y+82-r*65,sx=p=>14+this.rateDisplay(p,map)*this.scale;
          for(const rate of [.25,.5,1])html.push(line(0,sy(rate),width,sy(rate),'seq-rate-grid'),`<text x="${width-28}" y="${sy(rate)-4}" class="seq-ruler-sub">${rate}×</text>`);
          const speed=this.doc.speed,valid=Timing.valid(speed);
          if(valid){
            // progress->screen is strongly nonlinear (rate integral + window
            // warp), so a fixed sample grid lets long chords cut across sharp
            // dips. Refine chords until the true curve stays sub-pixel, and
            // seed with every key so the line passes through its diamonds.
            const ev=p=>[sx(p),sy(Timing.rateAt(speed,p)),p];
            let pts=[...new Set([0,1,...speed.keyframes.map(k=>k.progress)])].sort((a,b)=>a-b).map(ev);
            const off=(a,b,m)=>{const dx=b[0]-a[0],dy=b[1]-a[1],len2=dx*dx+dy*dy||1,t=((m[0]-a[0])*dx+(m[1]-a[1])*dy)/len2,ex=a[0]+t*dx-m[0],ey=a[1]+t*dy-m[1];return ex*ex+ey*ey;};
            for(let round=0;round<11&&pts.length<4000;round++){
              const out=[pts[0]];let refined=false;
              for(let i=1;i<pts.length;i++){
                const a=pts[i-1],b=pts[i],dx=b[0]-a[0],dy=b[1]-a[1];
                if(Math.abs(dx)>1||Math.abs(dy)>1){
                  const m1=ev(a[2]+(b[2]-a[2])/3),m2=ev(a[2]+(b[2]-a[2])*2/3);
                  if(Math.max(off(a,b,m1),off(a,b,m2))>.36||Math.abs(dx)>64){out.push(m1,m2);refined=true;}
                }
                out.push(b);
              }
              pts=out;if(!refined)break;
            }
            html.push(`<polyline class="seq-rate-curve" points="${pts.map(p=>`${p[0]},${p[1]}`).join(' ')}"/>`);
          }
          if(speed.mode==='curve')for(const k of row.keys)html.push(this.diamond(k,sx(k.progress),sy(k.rate),'rate',`速率 ${pretty(k.rate)}× · 对局 ${pretty(map.rateTime(k.progress))}s`));
          else html.push(`<text x="16" y="${row.y+99}" class="seq-ruler-sub">${speed.mode==='paused'?'战斗暂停，仅摄像机运动':'固定倍率 · '+speed.rate+'×'}</text>`);
        }
      }
      if(guardStart!==null)html.push(`<line x1="${guardX}" y1="40" x2="${guardX}" y2="208" class="seq-keyframe-boundary"/><text x="${guardX+4}" y="204" class="seq-keyframe-boundary-label">比赛开始</text>`);
      this.svg.innerHTML=html.join('');this.updatePlayhead(this.playhead);this.inspector();
      this.root.querySelector('[data-action=undo]').disabled=!this.undoStack.length||this.locked;
      this.root.querySelector('[data-action=redo]').disabled=!this.redoStack.length||this.locked;
      this.updateClipboardButtons();
      this.root.querySelectorAll('[data-add]').forEach(b=>b.disabled=!!this.locked);
      this.root.querySelector('[data-status]').textContent=this.free()?`镜头 · 结束 ${pretty(Math.max(...Object.values(this.doc.tracks).flat().map(k=>k.time_sec)))} s`:`全片 ${this.labelTime(map.end)} · 入 ${pretty(workStart)} s · 出 ${pretty(workEnd)} s · 长 ${pretty(workEnd-workStart)} s${this.drag?.kind==='work'?' · Alt 暂停吸附':''}`;
      this.root.querySelector('[data-action=inpoint]').disabled=!!this.locked;
      const guardNote=this.root.querySelector('[data-keyframe-guard]');guardNote.hidden=!guard?.enabled;
      if(guard?.enabled){guardNote.textContent=guard.message||(guardStart===null?'比赛开始时间尚未解析，请在设置中填写赛前长度后设置入点或添加关键帧。':`比赛开始：${pretty(guardStart)} s；此前不能设置入点或新增、移入摄像机关键帧。`);guardNote.title=guardNote.textContent;}
      const near=CHANNELS.flatMap(([channel,label])=>this.doc.tracks[channel].slice(1).flatMap((key,i)=>{
        const previous=this.doc.tracks[channel][i],gap=key.time_sec-previous.time_sec;
        return gap>0&&gap<.05?[{label,from:previous.time_sec,to:key.time_sec,gap}]:[];
      })).sort((a,b)=>a.gap-b.gap)[0],warning=this.root.querySelector('[data-key-warning]');
      warning.hidden=!near;
      if(near)warning.textContent=`${near.label} 有两个相邻关键帧：${near.from.toFixed(6)} / ${near.to.toFixed(6)} s，仅相隔 ${near.gap.toFixed(6)} s。放大时间轴可分别选中；不会自动合并或删除。`;
    }
    diamond(k,x,y,channel,title){const body=Array.isArray(k.ease)?`<path d="M ${x-4.5} ${y-5} L ${x+4.5} ${y-5} L ${x} ${y} Z M ${x-4.5} ${y+5} L ${x+4.5} ${y+5} L ${x} ${y} Z"/>`:`<path d="M ${x} ${y-5} l 5 5 -5 5 -5 -5 z"/>`;return `<g class="seq-key${this.selected.has(k._id)?' selected':''}" data-key="${k._id}" data-channel="${channel}" tabindex="0" role="button" aria-label="${title}"><title>${title}</title><rect x="${x-8}" y="${y-9}" width="16" height="18" class="seq-key-hit"/>${body}</g>`;}
    updatePlayhead(time){
      this.playhead=time;if(!this.doc)return;const map=this.free()?this.map():this.drag?.map||this.map(),seconds=map.atTime(time),frames=Math.max(0,Math.round((this.axis==='replay'?time:seconds)*this.fps));
      const f=frames%this.fps,s=Math.floor(frames/this.fps)%60,m=Math.floor(frames/this.fps/60)%60,h=Math.floor(frames/this.fps/3600);
      this.root.querySelector('[data-counter]').textContent=[h,m,s,f].map(v=>String(v).padStart(2,'0')).join(':');
      this.root.querySelector('[data-battle]').textContent=this.free()?`镜头 ${pretty(time)} s`:`对局 ${pretty(time)} s · 拍摄 ${pretty(seconds)} s`;
      this.head.style.left=this.x(time,map)+'px';
    }
    labelTime(t){return `${String(Math.floor(t/60)).padStart(2,'0')}:${(t%60).toFixed(2).padStart(5,'0')}`;}
    inspector(){
      const items=[...this.selected].map(id=>this.locate(id)).filter(Boolean),single=items.length===1?items[0]:null;
      if(items.length&&!this.hadSelection)this.adapter.onSelection?.();
      this.hadSelection=!!items.length;
      const root=this.inspectorRoot;
      root.querySelector('[data-selection]').textContent=single?(single.row.name==='rate'?'播放速率':CHANNELS.find(c=>c[0]===single.row.name)[1])+' · 关键帧':items.length?`已选择 ${items.length} 个关键帧`:'选择关键帧，或拖动标尺预演';
      const t=root.querySelector('[data-field=time]'),v=root.querySelector('[data-field=value]');
      t.disabled=v.disabled=!single||!!this.locked;
      const guard=single&&single.row.name!=='rate'&&!this.free()?this.adapter.keyframeGuard?.(this.data()):null;
      if(guard?.enabled&&!Number.isFinite(guard.start_sec)){t.disabled=true;t.title='比赛开始时间尚未解析，请先在设置中填写赛前片段长度。';}else t.title='';
      if(single?.row.name==='rate'&&(single.key.progress===0||single.key.progress===1))t.disabled=true;
      if(document.activeElement!==t)t.value=single?Number((single.row.name==='rate'?this.map().rateTime(single.key.progress):single.key.time_sec).toFixed(6)):'';
      if(document.activeElement!==v)v.value=single?Number((single.row.name==='rate'?single.key.rate:single.key.value).toFixed(6)):'';
      root.querySelector('[data-time-label]').textContent=this.free()?'镜头时刻':'对局时刻';
      root.querySelector('[data-value-label]').textContent=single?.row.name==='rate'?'倍率 ×':'数值';
      this.adapter.onInspect?.();
    }
    snapshot(){return clone(this.doc);}
    clipboardBusy(){return !!(this.drag||this.numberEdit||this.adapter.clipboardBusy?.());}
    clipboardScope(target){
      if(!target?.closest||target.closest('input,textarea,select,[contenteditable]:not([contenteditable=false])'))return false;
      return this.root.contains(target)||this.inspectorRoot.contains(target)||!!this.adapter.clipboardScope?.(target);
    }
    clipboardEventScope(event){
      const doc=this.root.ownerDocument,target=event.target;
      // WebView2 can dispatch native clipboard events on BODY even while an
      // editor control owns keyboard focus. Text fields still keep their scope.
      return this.clipboardScope(target===doc||target===doc.body||target===doc.documentElement?doc.activeElement:target);
    }
    updateClipboardButtons(){
      const busy=this.clipboardBusy();
      this.root.querySelector('[data-action=copy]').disabled=!Clipboard||!this.doc||busy||![...this.selected].some(id=>this.locate(id));
      this.root.querySelector('[data-action=paste]').disabled=!Clipboard||!this.doc||busy||this.locked||!this.clipboard;
    }
    copyKeyframes(){
      if(!this.doc||!Clipboard||this.clipboardBusy())return null;
      try{
        const map=this.map(),items=[];
        for(const row of this.rows())for(const [index,key] of row.keys.entries())if(this.selected.has(key._id)){
          const item={channel:row.name,key,time_sec:row.name==='rate'?map.rateTime(key.progress):key.time_sec};
          if(row.name==='rate'&&index<row.keys.length-1)item.effectiveEase=Timing.segmentEase(this.doc.speed,index);
          items.push(item);
        }
        if(!items.length)return null;
        this.clipboard=Clipboard.capture(items);this.updateClipboardButtons();
        return clone(this.clipboard);
      }catch(error){this.adapter.error(error.message);return null;}
    }
    pasteKeyframes(payload=this.clipboard,time=this.playhead){
      if(!this.doc||!Clipboard||this.locked||this.clipboardBusy())return false;
      if(!payload){this.adapter.error('请先选择关键帧并复制。');return false;}
      const before=this.snapshot(),selection=new Set(this.selected);
      try{
        const result=Clipboard.paste(this.doc,payload,time,()=>++this.ids);
        this.doc=result.doc;this.validate(before);this.selected=new Set(result.selected);
        if(this.free())this.grow(Math.max(...Object.values(this.doc.tracks).flat().map(key=>key.time_sec)));
        this.clipboard=clone(payload);this.commit(before);return true;
      }catch(error){this.doc=before;this.selected=selection;this.render();this.adapter.error(error.message);return false;}
    }
    onClipboardCopy(event){
      if(event.defaultPrevented||(!this.copyRequested&&!this.clipboardEventScope(event))||this.clipboardBusy())return;
      if(!this.copyRequested&&!this.root.ownerDocument.getSelection()?.isCollapsed)return;
      const payload=this.copyKeyframes();if(!payload)return;
      try{event.clipboardData.setData(clipboardType,JSON.stringify(payload));}catch{}
      try{
        event.clipboardData.setData('text/plain',clipboardPrefix+JSON.stringify(payload));event.preventDefault();
      }catch{} // The in-editor copy remains available when native clipboard access is unavailable.
    }
    onClipboardPaste(event){
      if(event.defaultPrevented||!this.clipboardEventScope(event))return;
      const custom=event.clipboardData?.getData(clipboardType),text=custom||event.clipboardData?.getData('text/plain')||'';
      if(!custom&&!text.startsWith(clipboardPrefix))return;
      event.preventDefault();
      if(this.clipboardBusy()||this.locked)return;
      try{
        if(text.length>1024*1024)throw new Error('复制的关键帧数据过大。');
        const raw=custom?text:text.slice(clipboardPrefix.length);this.pasteKeyframes(JSON.parse(raw));
      }catch{this.adapter.error('剪贴板中的关键帧数据无效，请重新复制。');}
    }
    singleSelection(){return this.selected.size===1?this.locate([...this.selected][0]):null;}
    inspectValue(field){const item=this.singleSelection();if(!item)return '';return field==='time'?(item.row.name==='rate'?this.map().rateTime(item.key.progress):item.key.time_sec):item.row.name==='rate'?item.key.rate:item.key.value;}
    inspectBounds(field){
      const item=this.singleSelection(),name=item?.row.name;
      if(field==='time'){
        const guard=item&&name!=='rate'&&!this.free()?this.adapter.keyframeGuard?.(this.data()):null;
        return {min:name==='rate'?this.map().rateStart:guard?.enabled&&Number.isFinite(guard.start_sec)?guard.start_sec:0,max:name==='rate'?this.map().rateEnd:this.free()?1e7:this.doc?.timeline?.duration_sec??1e7};
      }
      return name==='rate'?{min:.0625,max:1}:name==='pitch'?{min:-80,max:80}:name==='zoom'?{min:.001,max:179.999}:{min:-1e7,max:1e7};
    }
    setInspectorValue(field,value){
      const item=this.singleSelection();if(!item)return false;
      return this.edit(()=>{
        if(item.row.name==='rate'){
          const map=this.map(),keys=this.doc.speed.keyframes,times=keys.map(k=>map.rateTime(k.progress)),i=keys.indexOf(item.key);
          if(field==='time'){
            if(i===0||i===keys.length-1||value<=times[i-1]||value>=times[i+1])throw new Error('速率关键帧需位于相邻点之间，首尾时间固定。');
            times[i]=value;
          }else item.key.rate=value;
          this.boundRateHandles();this.setRateTimes(times);
        }else item.key[field==='time'?'time_sec':'value']=value;
      });
    }
    beginNumberEdit(){if(!this.locked&&!this.numberEdit)this.numberEdit=this.snapshot();}
    endNumberEdit(cancelled=false){
      const before=this.numberEdit;if(!before)return;this.numberEdit=null;
      if(cancelled){this.doc=before;this.render();this.adapter.change(this.data());}else try{this.validate(before);this.commit(before);}catch(error){this.doc=before;this.render();this.adapter.change(this.data());this.adapter.error(error.message);}
    }
    commit(before){
      if(JSON.stringify(before)===JSON.stringify(this.doc)){this.render();return;}
      // Once the user authors camera keys, binding a replay must preserve them.
      if(this.doc.timeline?.starter_keyframes_pending&&(this.free()||JSON.stringify(before.tracks)!==JSON.stringify(this.doc.tracks)))delete this.doc.timeline.starter_keyframes_pending;
      if(!this.numberEdit){this.undoStack.push(before);if(this.undoStack.length>100)this.undoStack.shift();this.redoStack=[];}
      this.render();this.adapter.change(this.data());
    }
    changeSpeed(speed){if(!this.doc)return;this.edit(()=>{const previous=this.doc.speed;this.doc.speed=clone(speed);this.anchorSpeed();this.doc.speed.keyframes.forEach((k,i)=>k._id=previous.keyframes[i]?._id||++this.ids);});}
    validate(before=null){
      if(!Timing.valid(this.doc.speed))throw new Error('速度曲线时间范围或倍率无效。');
      for(const row of this.rows()){
        if(!row.keys.length)throw new Error('每条参数轨道至少保留一个关键帧。');
        const field=row.name==='rate'?'progress':'time_sec';row.keys.sort((a,b)=>a[field]-b[field]);
        for(let i=0;i<row.keys.length;i++){const k=row.keys[i],t=k[field],v=row.name==='rate'?k.rate:k.value;
          if(!Number.isFinite(t)||!Number.isFinite(v)||Math.abs(t)>1e7||Math.abs(v)>1e7)throw new Error('请输入有效数值。');
          if(i&&t-row.keys[i-1][field]<1e-5)throw new Error('同一轨道的关键帧不能重合。');
          if(row.name==='zoom'&&(v<=0||v>=180))throw new Error('缩放需大于 0°、小于 180°。');
          if(row.name==='pitch'&&Math.abs(v)>80)throw new Error('俯仰需在 -80° 至 80° 内。');
          if(row.name==='rate'&&(t<0||t>1||v<.0625||v>1))throw new Error('倍率需在 1/16×–1× 内。');
        }
        if(row.name==='rate'&&(row.keys.length<2||row.keys[0].progress!==0||row.keys.at(-1).progress!==1))throw new Error('速率轨道需保留首尾关键帧。');
      }
      if(!this.free()&&this.map().duration>3600)throw new Error('轨迹最长一小时。');
      if(!this.free()&&this.doc.timeline){const t=this.doc.timeline;if(![t.duration_sec,t.work_start_sec,t.work_end_sec].every(Number.isFinite)||!(0<=t.work_start_sec&&t.work_start_sec<t.work_end_sec&&t.work_end_sec<=t.duration_sec&&t.duration_sec<=3600))throw new Error('请设置有效的全片长度、入点和出点。');for(const k of Object.values(this.doc.tracks).flat())if(k.time_sec<0||k.time_sec>t.duration_sec)throw new Error('关键帧不能超出整场回放时间范围。');}
      if(this.free()&&Object.values(this.doc.tracks).flat().some(k=>k.time_sec<0))throw new Error('镜头时间不能小于零。');
      if(new Set(Object.values(this.doc.tracks).flat().map(k=>k.time_sec)).size>200)throw new Error('最多 200 个不同的摄像机关键帧时刻。');
      if(before&&!this.free()){
        const guard=this.adapter.keyframeGuard?.(this.data());
        const t=this.doc.timeline,old=before.timeline;
        if(guard?.enabled&&t&&t.work_start_sec!==old?.work_start_sec)this.validateWorkStart(t.work_start_sec,guard);
        if(guard?.enabled)for(const [name] of CHANNELS)for(const key of this.doc.tracks[name]){
          const previous=before.tracks[name]?.find(k=>k._id===key._id);
          if(previous&&Math.abs(previous.time_sec-key.time_sec)<1e-9)continue;
          if(!Number.isFinite(guard.start_sec)||key.time_sec<guard.start_sec-1e-6)throw new Error(guard.message||(Number.isFinite(guard.start_sec)?`比赛开始前不能新增或移入摄像机关键帧，请使用 ${pretty(guard.start_sec)} s 之后的时刻。`:'比赛开始时间尚未解析，暂不能新增或移动摄像机关键帧。'));
        }
      }
    }
    validateWorkStart(time,guard=this.adapter.keyframeGuard?.(this.data())){
      if(!guard?.enabled)return;
      if(!Number.isFinite(guard.start_sec))throw new Error('比赛开始时间尚未解析，请在设置中填写赛前片段长度后设置入点。');
      if(time<guard.start_sec-1e-6)throw new Error(`入点不能早于比赛开始（${pretty(guard.start_sec)} s）。`);
    }
    edit(fn){if(this.locked)return false;const before=this.snapshot();try{this.anchorSpeed();fn();this.anchorSpeed();this.validate(before);this.commit(before);return true;}catch(e){this.doc=before;this.render();this.adapter.error(e.message);return false;}}
    action(name){
      if(!this.doc)return;
      if(name==='copy'){
        if(!this.copyKeyframes())return;
        this.copyRequested=true;
        try{this.root.ownerDocument.execCommand('copy');}catch{}finally{this.copyRequested=false;}
        return;
      }
      if(name==='paste')return this.pasteKeyframes();
      if(name==='workfit'){const map=this.map(),from=this.displayTime(map.workStart,map),to=this.displayTime(map.workEnd,map);this.scale=clamp((this.scroll.clientWidth-32)/Math.max(.5,to-from),.1,2000);this.render();this.scroll.scrollLeft=from*this.scale;return;}
      if(name==='follow'){const t=this.adapter.currentTime?.();if(Number.isFinite(t)){this.adapter.seek(t);this.scroll.scrollLeft=Math.max(0,this.x(t)-this.scroll.clientWidth/2);}else this.adapter.error('连接回放后可查看当前对局时刻。');return;}
      if(name==='fit')return this.fit();if(name==='in'||name==='out')return this.zoom(name==='in'?1.25:.8);
      if(name==='snap'){this.snap=!this.snap;this.root.querySelector('[data-action=snap]').setAttribute('aria-pressed',String(this.snap));return;}
      if(name==='previous'||name==='next'){
        const times=[...new Set(Object.values(this.doc.tracks).flat().map(k=>k.time_sec))].sort((a,b)=>a-b),t=name==='next'?times.find(t=>t>this.playhead+1e-6):times.filter(t=>t<this.playhead-1e-6).at(-1);
        if(t!==undefined)this.adapter.seek(t);return;
      }
      if(this.locked)return;
      if(name==='reset-speed')return this.edit(()=>{
        this.doc.speed={mode:'fixed',rate:1,camera_clock:'replay',interpolation:'smooth',
          keyframes:[{progress:0,rate:1,_id:++this.ids},{progress:1,rate:1,_id:++this.ids}]};
        this.selected.clear();
      });
      if(name==='inpoint'){const now=this.adapter.currentTime?.();if(!Number.isFinite(now))return this.adapter.error('请连接并暂停回放后设置入点。');return this.edit(()=>{this.doc.timeline.work_start_sec=now;});}
      if(name==='undo'||name==='redo'){
        const source=name==='undo'?this.undoStack:this.redoStack,target=name==='undo'?this.redoStack:this.undoStack;if(!source.length)return;
        const before=this.snapshot();this.doc=clone(source.at(-1));
        try{this.validate(before);}catch(error){this.doc=before;this.render();this.adapter.error(error.message);return;}
        source.pop();target.push(before);this.selected=new Set([...this.selected].filter(id=>this.locate(id)));this.render();this.adapter.change(this.data());return;
      }
      if(name==='delete')this.edit(()=>{for(const row of this.rows())row.keys.splice(0,row.keys.length,...row.keys.filter(k=>!this.selected.has(k._id)));this.selected.clear();});
    }
    async add(channel,time=this.playhead){
      if(this.locked||!this.doc)return;
      if(channel==='rate')return this.edit(()=>{
        if(this.doc.speed.mode!=='curve'){
          const rate=this.doc.speed.mode==='fixed'?this.doc.speed.rate:1;
          this.doc.speed.keyframes=[{progress:0,rate,_id:++this.ids},{progress:1,rate,_id:++this.ids}];
        }
        this.doc.speed.mode='curve';this.anchorSpeed();
        if(!Number.isFinite(time)||time<0||time>this.doc.timeline.duration_sec)throw new Error('速率关键帧需位于整场回放时间范围内。');
        const extended=this.expandSpeedRange(time),map=this.map();
        const progress=map.rateProgress(time),keys=this.doc.speed.keyframes;
        if(extended){this.selected=new Set([progress===0?keys[0]._id:keys.at(-1)._id]);return;}
        if(keys.some(k=>Math.abs(k.progress-progress)<1e-5))throw new Error('当前时刻已有速率关键帧。');
        const k=Timing.insertKey(this.doc.speed,progress);k._id=++this.ids;this.selected=new Set([k._id]);
      });
      try{
        const version=JSON.stringify(this.data());const values=await this.adapter.evaluate(time);
        if(this.locked||version!==JSON.stringify(this.data()))throw new Error('草稿已改变，请重新添加关键帧。');
        this.edit(()=>{const channels=channel==='all'?CHANNELS.map(c=>c[0]):[channel];this.selected.clear();
          for(const name of channels){const rows=this.doc.tracks[name];let k=rows.find(k=>Math.abs(k.time_sec-time)<1e-5);if(k)continue;k={time_sec:time,value:values[name],_id:++this.ids};rows.push(k);this.selected.add(k._id);}
        });
      }catch(e){this.adapter.error(e.message);}
    }
    snapTargets(exclude,map=this.map(),includePlayhead=true,skipRow=null){
      const targets=[0,this.displayTime(map.workStart,map),this.displayTime(map.workEnd,map)];
      for(const row of this.rows())if(row.name!=='rate'&&row.name!==skipRow)for(const k of row.keys){if(exclude?.has(k._id))continue;targets.push(this.displayTime(k.time_sec,map));}
      if(includePlayhead)targets.push(this.displayTime(this.playhead,map));
      return targets;
    }
    snapTo(time,targets){let best=null;for(const t of targets){const dist=Math.abs(t-time)*this.scale;if(dist<10&&(!best||dist<best.dist))best={time:t,dist};}return best;}
    point(e){const r=this.scroll.getBoundingClientRect();return {x:e.clientX-r.left+this.scroll.scrollLeft,y:e.clientY-r.top+this.scroll.scrollTop};}
    down(e){
      this.wheelAnchor=null;
      if(e.button!==0||!this.doc||e.target.closest('input,select,button'))return;
      const key=e.target.closest('[data-key]'),work=e.target.closest('[data-work]'),p=this.point(e),map=this.map();
      if(!this.scroll.contains(e.target))return;
      if(work&&!this.free()){
        if(this.locked||this.drag)return;
        if(work.dataset.work!=='end')try{
          const guard=this.adapter.keyframeGuard?.(this.data());
          if(guard?.enabled){
            this.validateWorkStart(guard.start_sec??-1,guard);
            const t=this.doc.timeline,length=work.dataset.work==='range'?t.work_end_sec-t.work_start_sec:.001;
            if(guard.start_sec>t.duration_sec-length||work.dataset.work==='start'&&guard.start_sec>t.work_end_sec-.001)throw new Error('当前区间无法容纳比赛开始后的入点，请先调整出点或缩短区间。');
          }
        }catch(error){e.preventDefault();this.adapter.error(error.message);return;}
        e.preventDefault();e.stopPropagation();this.scroll.focus({preventScroll:true});
        this.adapter.onWorkRangeDragStart?.();
        this.root.setPointerCapture(e.pointerId);
        this.drag={kind:'work',part:work.dataset.work,x:p.x,y:p.y,map,before:this.snapshot(),pointerId:e.pointerId,moved:false};
        this.root.classList.add('seq-work-dragging');this.render();return;
      }
      if(e.ctrlKey&&!key&&p.y>=40){
        if(this.locked)return;e.preventDefault();this.scroll.focus({preventScroll:true});
        const row=this.rows().find(row=>p.y>=row.y&&p.y<row.y+row.height);if(!row)return;
        let display=clamp((p.x-14)/this.scale,0,this.total(map));
        if(this.snap&&!e.altKey){const hit=this.snapTo(display,this.snapTargets(null,map));display=hit?hit.time:Math.round(display*this.fps)/this.fps;}
        this.add(row.name,this.fromDisplay(clamp(display,0,this.total(map)),map));return;
      }
      this.root.setPointerCapture(e.pointerId);e.preventDefault();this.scroll.focus({preventScroll:true});
      if(key){
        const id=Number(key.dataset.key),item=this.locate(id);if(e.shiftKey){if(this.selected.has(id))this.selected.delete(id);else this.selected.add(id);}else if(!this.selected.has(id))this.selected=new Set([id]);
        // Keep camera and rate drags separate: their clocks have different units.
        for(const selected of this.selected)if((this.locate(selected)?.row.name==='rate')!==(item.row.name==='rate'))this.selected.delete(selected);
        if(!this.locked&&this.selected.has(id))this.drag={kind:'key',x:p.x,y:p.y,map,before:this.snapshot(),ids:new Set(this.selected),anchor:id,rate:item.row.name==='rate',pointerId:e.pointerId,moved:false};
        this.render();return;
      }
      if(p.y<40||e.target.closest('.seq-head')){this.drag={kind:'seek',map,pointerId:e.pointerId};this.scrub(p.x,map,e);return;}
      if(this.locked)return;
      this.drag={kind:'box',x:p.x,y:clamp(p.y,40,this.height()),prior:e.shiftKey?new Set(this.selected):new Set()};if(!e.shiftKey)this.selected.clear();this.render();
    }
    scrub(x,map,e){
      let d=clamp((x-14)/this.scale,0,this.total(map));
      if(this.snap&&!e?.altKey){const hit=this.snapTo(d,this.snapTargets(null,map,false));d=hit?hit.time:Math.round(d*this.fps)/this.fps;}
      this.adapter.seek(this.fromDisplay(clamp(d,0,this.total(map)),map));
    }
    boundRateHandles(){
      const keys=this.doc.speed.keyframes;
      // Leave legal handles (including handles on flat segments) byte-for-byte
      // intact. Only clamp a segment whose changed rates put it out of bounds.
      for(let i=1;i<keys.length;i++){const a=keys[i-1],b=keys[i];
        if(a.ease&&[1,3].some(j=>{const r=a.rate+(b.rate-a.rate)*a.ease[j];return r<.0625||r>1;}))Timing.boundHandles({keyframes:[a,b]});
      }
    }
    setRateTimes(times){
      const s=this.doc.speed,segments=times.slice(1).map((time,i)=>(time-times[i])/rateMean(s,i)),total=segments.reduce((sum,v)=>sum+v,0);
      let elapsed=0;
      // Progress is stored in shooting time. Rebuild every segment from its
      // replay duration, so changing one point cannot retime its neighbours.
      for(let i=0;i<s.keyframes.length;i++){if(i)elapsed+=segments[i-1];s.keyframes[i].progress=i===s.keyframes.length-1?1:elapsed/total;}
      return segments;
    }
    moveRate(d,delta,rateDelta){
      const s=this.doc.speed,keys=s.keyframes,originals=d.before.speed.keyframes;
      const times=originals.map(k=>d.map.rateTime(k.progress)),anchor=keys.findIndex(k=>k._id===d.anchor);
      const applyRates=fraction=>{
        for(let i=0;i<keys.length;i++){
          keys[i].rate=d.ids.has(keys[i]._id)?clamp(originals[i].rate+rateDelta*fraction,.0625,1):originals[i].rate;
          if(originals[i].ease)keys[i].ease=originals[i].ease.slice();
        }
        this.boundRateHandles();this.setRateTimes(times);return Timing.valid(s);
      };
      // At the minimum spacing, changing a rate can also exhaust the stored
      // progress precision. Stop at that limit instead of jumping on release.
      if(!applyRates(1)){
        if(!applyRates(0)){this.doc.speed=clone(d.before.speed);return;}
        let lo=0,hi=1;for(let i=0;i<40;i++){const mid=(lo+hi)/2;if(applyRates(mid))lo=mid;else hi=mid;}applyRates(lo);
      }
      if(anchor<=0||anchor===keys.length-1)return;
      const moving=keys.map((k,i)=>i>0&&i<keys.length-1&&d.ids.has(k._id)?1:0);
      const segments=this.setRateTimes(times),slopes=segments.map((_,i)=>(moving[i+1]-moving[i])/rateMean(s,i));
      const total=segments.reduce((sum,v)=>sum+v,0),slope=slopes.reduce((sum,v)=>sum+v,0);
      let lo=-Infinity,hi=Infinity;
      // Both segment duration and total shooting duration vary linearly with
      // a replay-time offset. Enforce the actual normalized storage gap, rather
      // than a fixed progress offset that moves other points on the ruler.
      for(let i=0;i<segments.length;i++){
        const gap=Math.min(1.01e-5,segments[i]/total),coefficient=slopes[i]-gap*slope,bound=gap*total-segments[i];
        if(coefficient>0)lo=Math.max(lo,bound/coefficient);else if(coefficient<0)hi=Math.min(hi,bound/coefficient);
      }
      const apply=offset=>this.setRateTimes(times.map((time,i)=>time+moving[i]*offset));
      if(this.axis==='replay'){apply(clamp(delta,lo,hi));return;}
      // On the shooting ruler, invert the edited clock while keeping all
      // unselected replay times fixed. Selected points retain their spacing.
      const display=offset=>{apply(offset);return this.rateDisplay(keys[anchor].progress,this.map());},target=this.displayTime(times[anchor],d.map)+delta;
      const left=display(lo),right=display(hi),increasing=right>=left;
      if(target<=Math.min(left,right)){display(increasing?lo:hi);return;}
      if(target>=Math.max(left,right)){display(increasing?hi:lo);return;}
      // Disjoint selections can shorten an earlier slow segment enough that
      // their anchor moves the other way in shooting time.
      for(let i=0;i<40;i++){const mid=(lo+hi)/2;if((display(mid)<target)===increasing)lo=mid;else hi=mid;}display((lo+hi)/2);
    }
    moveWork(p,d,e){
      if(Math.abs(p.x-d.x)<3&&!d.moved)return;
      d.moved=true;const original=d.before.timeline,t=this.doc.timeline,map=d.map;
      const minGap=Math.min(.001,original.duration_sec),toTime=x=>this.fromDisplay((x-14)/this.scale,map);
      const guard=this.adapter.keyframeGuard?.(this.data()),minimum=guard?.enabled&&Number.isFinite(guard.start_sec)?guard.start_sec:0;
      let start=original.work_start_sec,end=original.work_end_sec;
      this.snapLine=null;
      if(d.part==='range'){
        const delta=toTime(p.x)-toTime(d.x);start+=delta;end+=delta;
      }else{
        const initial=d.part==='start'?start:end;
        const at=this.fromDisplay(this.displayTime(initial,map)+(p.x-d.x)/this.scale,map);
        if(d.part==='start')start=at;else end=at;
      }
      if(this.snap&&!e.altKey){
        const targets=[this.displayTime(minimum,map),this.displayTime(map.end,map),this.displayTime(this.playhead,map)];
        for(const row of this.rows())for(const key of row.keys)targets.push(row.name==='rate'?this.rateDisplay(key.progress,map):this.displayTime(key.time_sec,map));
        const edges=d.part==='range'?[['start',start],['end',end]]:[[d.part,d.part==='start'?start:end]];
        let best=null;
        for(const [part,time] of edges){const hit=this.snapTo(this.displayTime(time,map),targets);if(hit&&(!best||hit.dist<best.dist))best={...hit,part};}
        const part=best?.part??(d.part==='end'?'end':'start'),at=part==='start'?start:end;
        const snapped=best?this.fromDisplay(best.time,map):this.fromDisplay(Math.round(this.displayTime(at,map)*this.fps)/this.fps,map),correction=snapped-at;
        if(d.part==='range'){start+=correction;end+=correction;}else if(d.part==='start')start=snapped;else end=snapped;
        if(best)this.snapLine=best.time;
      }
      if(d.part==='range'){
        const length=original.work_end_sec-original.work_start_sec;
        start=clamp(start,minimum,original.duration_sec-length);end=start+length;
      }else if(d.part==='start')start=clamp(start,minimum,end-minGap);
      else end=clamp(end,start+minGap,original.duration_sec);
      // Do not touch camera keys or the independently authored speed range.
      t.work_start_sec=Number(start.toFixed(9));t.work_end_sec=Number(end.toFixed(9));
      d.anchorTime=d.part==='range'?clamp(toTime(d.x)+start-original.work_start_sec,start,end):d.part==='start'?start:end;
      if(this.snapLine!=null&&Math.min(Math.abs(this.displayTime(start,map)-this.snapLine),Math.abs(this.displayTime(end,map)-this.snapLine))*this.scale>.1)this.snapLine=null;
      this.render();
    }
    settleWorkView(anchor){
      if(!anchor||this.axis!=='shooting')return;
      const map=this.map(),display=this.displayTime(anchor.time,map);
      let scroll=14+display*this.scale-anchor.screen;
      const max=this.scroll.scrollWidth-this.scroll.clientWidth;
      if((scroll<0||scroll>max)&&display>0&&anchor.screen>14){
        // When the viewport edge prevents scrolling, adjust the zoom just
        // enough to keep the released boundary under the pointer.
        this.scale=clamp((anchor.screen-14)/display,.000001,2000);this.render();
        scroll=14+display*this.scale-anchor.screen;
      }
      this.scroll.scrollLeft=Math.max(0,scroll);this.render();
    }
    move(e){
      if(!this.drag)return;const p=this.point(e),d=this.drag;
      if(['key','work','seek'].includes(d.kind)&&!e.auto)this.autoPan(e);
      if(d.kind==='work')return this.moveWork(p,d,e);
      if(d.kind==='seek')return this.scrub(p.x,this.free()?this.map():d.map,e);
      if(d.kind==='box'){
        const box=this.root.querySelector('.seq-box'),loX=Math.min(d.x,p.x),hiX=Math.max(d.x,p.x),loY=Math.min(d.y,p.y),hiY=Math.max(d.y,p.y);box.hidden=false;Object.assign(box.style,{left:loX+'px',top:loY+'px',width:hiX-loX+'px',height:hiY-loY+'px'});this.selected=new Set(d.prior);
        for(const row of this.rows())for(const key of row.keys){const x=row.name==='rate'?14+this.rateDisplay(key.progress)*this.scale:this.x(key.time_sec),y=row.name==='rate'?row.y+82-key.rate*65:row.y+12;if(x>=loX&&x<=hiX&&y>=loY&&y<=hiY)this.selected.add(key._id);}
        for(const el of this.svg.querySelectorAll('[data-key]'))el.classList.toggle('selected',this.selected.has(Number(el.dataset.key)));this.inspector();return;
      }
      if(Math.abs(p.x-d.x)+Math.abs(p.y-d.y)<3&&!d.moved)return;d.moved=true;this.doc=clone(d.before);
      const originals=[];for(const row of this.rows())for(const key of row.keys)if(d.ids.has(key._id))originals.push({row,key});
      let delta=(p.x-d.x)/this.scale;this.snapLine=null;
      if(!d.rate&&this.snap&&!e.altKey&&originals.length){
        let best=null;const targets={};
        for(const o of originals){
          targets[o.row.name]??=this.snapTargets(d.ids,d.map,true,o.row.name);
          const at=this.displayTime(o.key.time_sec,d.map)+delta,hit=this.snapTo(at,targets[o.row.name]);
          if(hit&&(!best||hit.dist<best.dist))best={target:hit.time,dist:hit.dist,correction:hit.time-at};
        }
        if(best){delta+=best.correction;this.snapLine=best.target;}
        else{const first=originals[0];delta=Math.round((this.displayTime(first.key.time_sec,d.map)+delta)*this.fps)/this.fps-this.displayTime(first.key.time_sec,d.map);}
      }
      if(!d.rate&&originals.length){const starts=originals.map(o=>this.displayTime(o.key.time_sec,d.map));delta=clamp(delta,-Math.min(...starts),this.free()?Infinity:this.total(d.map)-Math.max(...starts));}
      if(d.rate)this.moveRate(d,delta,-(p.y-d.y)/65);
      else for(const {key} of originals)key.time_sec=Number(clamp(this.fromDisplay(this.displayTime(key.time_sec,d.map)+delta,d.map),d.map.start,this.free()?Infinity:d.map.end).toFixed(6));
      if(this.free())this.grow(Math.max(...Object.values(this.doc.tracks).flat().map(k=>k.time_sec)));
      this.render();
    }
    up(e){
      if(!this.drag)return;const d=this.drag,anchor=d.kind==='work'&&d.moved?{time:d.anchorTime,screen:this.x(d.anchorTime,d.map)-this.scroll.scrollLeft}:null;this.drag=null;this.snapLine=null;cancelAnimationFrame(this.autoFrame);this.autoFrame=0;this.root.querySelector('.seq-box').hidden=true;
      if(this.root.hasPointerCapture(e.pointerId))this.root.releasePointerCapture(e.pointerId);
      this.root.classList.remove('seq-work-dragging');
      if(['key','work'].includes(d.kind)&&d.moved){try{this.validate(d.before);this.commit(d.before);this.settleWorkView(anchor);}catch(error){this.doc=d.before;this.render();this.adapter.error(error.message);}}else this.render();
    }
    cancel(){cancelAnimationFrame(this.autoFrame);this.autoFrame=0;if(this.drag?.before)this.doc=this.drag.before;const pointer=this.drag?.pointerId;this.drag=null;if(pointer!=null&&this.root.hasPointerCapture(pointer))this.root.releasePointerCapture(pointer);this.root.classList.remove('seq-work-dragging');this.snapLine=null;this.root.querySelector('.seq-box').hidden=true;this.render();}
    key(e){
      if(e.target.closest('input,select'))return;
      if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();e.stopPropagation();this.action(e.shiftKey?'redo':'undo');}
      if(e.key==='Delete'||e.key==='Backspace'){e.preventDefault();e.stopPropagation();this.action('delete');}
      if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='a'){e.preventDefault();this.selected=new Set(this.rows().filter(r=>r.name!=='rate').flatMap(r=>r.keys.map(k=>k._id)));this.render();}
      if(e.key==='Escape'&&!this.locked){const work=this.drag?.kind==='work';this.cancel();if(!work)this.selected.clear();this.render();}
      if(e.key==='ArrowLeft'||e.key==='ArrowRight'){
        e.preventDefault();e.stopPropagation();const map=this.map();
        this.adapter.seek(this.free()?Math.max(0,this.playhead+(e.key==='ArrowRight'?1:-1)/this.fps):this.axis==='replay'?clamp(this.playhead+(e.key==='ArrowRight'?1:-1)/this.fps,map.start,map.end):map.atSeconds(map.atTime(this.playhead)+(e.key==='ArrowRight'?1:-1)/this.fps));
      }
    }
    lock(value){if(this.locked===!!value)return;if(value&&this.numberEdit){globalThis.BlitzNumbers?.finish(true);this.endNumberEdit(true);}this.locked=!!value;if(this.locked)this.cancel();this.root.classList.toggle('seq-locked',this.locked);this.render();}
  }
  return {Editor,ClockMap,CHANNELS};
});
