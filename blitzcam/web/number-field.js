/* Shared scrub numbers: drag to adjust, double-click for precise text entry. */
(()=>{
  'use strict';
  const widgets=new WeakMap(),nativeValue=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value');
  let active=null,pointer=null,lastTap=null,frame=0,pending=null;
  const dragThreshold=5,doubleTapDelay=600,tapRadius=6;
  const event=(input,name,detail={})=>input.dispatchEvent(new CustomEvent(name,{bubbles:true,detail}));
  const finite=v=>v!==''&&Number.isFinite(Number(v));
  const format=v=>Number(Number(v).toFixed(3)).toString();
  const attr=(el,name,value)=>{value=String(value);if(el.getAttribute(name)!==value)el.setAttribute(name,value);};
  const stepOf=widget=>typeof widget.options.step==='function'?widget.options.step():widget.options.step??Number(widget.input.dataset.scrubStep||widget.input.step||1);
  const factor=e=>e.shiftKey ? .1 : e.ctrlKey||e.metaKey ? 10 : 1;
  function limits(widget){
    const custom=widget.options.bounds?.()||{};
    return {min:custom.min??(widget.input.min===''?-1e7:Number(widget.input.min)),max:custom.max??(widget.input.max===''?1e7:Number(widget.input.max))};
  }
  function sync(widget){
    const {input,view,host,up,down}=widget,value=input.value,text=finite(value)?format(value):'—';
    if(view.textContent!==text)view.textContent=text;
    const disabled=input.disabled||input.readOnly,label=input.getAttribute('aria-label')||widget.label||'数值';
    if(view.disabled!==disabled)view.disabled=disabled;attr(host,'data-readonly',input.readOnly);
    attr(view,'aria-label',label);
    if(finite(value))attr(view,'aria-valuenow',value);else view.removeAttribute('aria-valuenow');
    const bounds=limits(widget);attr(view,'aria-valuemin',bounds.min);attr(view,'aria-valuemax',bounds.max);
    attr(view,'title',disabled?(input.title||'只读数值'):`${finite(value)?value+' · ':''}左右或上下拖动调整 · Shift 精调 · Ctrl 加速 · 双击输入完整数值`);
    for(const [button,direction]of [[up,1],[down,-1]]){
      const blocked=disabled||!finite(value)||(direction>0?Number(value)>=bounds.max:Number(value)<=bounds.min);
      if(button.disabled!==blocked)button.disabled=blocked;
      const name=(direction>0?'增加':'减少')+label;attr(button,'aria-label',name);attr(button,'title',name+' · Shift 精调 · Ctrl 加速');
    }
  }
  function begin(widget,kind){
    if(active?.widget===widget)return;
    finish();lastTap=null;active={widget,kind,original:widget.input.value,last:widget.input.value};
    event(widget.input,'number-start',{kind});
  }
  function flush(){
    if(frame)cancelAnimationFrame(frame);frame=0;
    const next=pending;pending=null;
    if(next&&active?.widget===next.widget)write(next.widget,next.value);
  }
  function queue(widget,value){
    pending={widget,value};
    if(!frame)frame=requestAnimationFrame(()=>{frame=0;flush();});
  }
  function write(widget,value,typed=false){
    const {input,options}=widget,bounds=limits(widget);
    if(!Number.isFinite(value)||value<bounds.min||value>bounds.max){input.setAttribute('aria-invalid','true');return false;}
    const previous=active?.widget===widget?active.last:input.value;
    input.removeAttribute('aria-invalid');widget.writing=true;
    try{
      // Display rounding must never quantize the saved or editable value.
      // Assigning value while typing resets the browser's caret and its private
      // number-edit buffer (e.g. the decimal point in "31."). Never rewrite it,
      // even when a partial value is rejected by the model.
      if(!typed)input.value=String(value);
      if(options.set?.(value)===false){if(!typed)input.value=previous;input.setAttribute('aria-invalid','true');return false;}
      const actual=options.get?.(),accepted=finite(actual)?String(actual):String(value);
      if(!typed)input.value=accepted;
      if(active?.widget===widget)active.last=accepted;
      input.dispatchEvent(new Event('input',{bubbles:true}));
      input.dispatchEvent(new Event('change',{bubbles:true}));
      return true;
    }finally{widget.writing=false;sync(widget);}
  }
  function finish(cancelled=false,focus=false){
    const session=active;if(!session)return;
    const {widget}=session,{input,view,host}=widget;
    // An unfinished/invalid final string must not save a valid prefix that was
    // previewed while typing (e.g. 9 from an out-of-range pitch of 90).
    cancelled=cancelled||(session.kind==='text'&&(!finite(input.value)||input.hasAttribute('aria-invalid')));
    if(cancelled){if(frame)cancelAnimationFrame(frame);frame=0;pending=null;}else flush();
    if(cancelled&&finite(session.original))write(widget,Number(session.original));
    input.value=cancelled?session.original:session.last;input.removeAttribute('aria-invalid');
    active=null;host.classList.remove('number-editing','number-dragging');delete host.dataset.scrubAxis;
    if(pointer?.widget===widget){const id=pointer.id;pointer=null;if(view.hasPointerCapture(id))view.releasePointerCapture(id);}
    event(input,'number-end',{cancelled,kind:session.kind});sync(widget);
    if(focus&&view.isConnected&&!view.disabled)view.focus({preventScroll:true});
  }
  function edit(widget){
    if(widget.input.disabled||widget.input.readOnly)return;
    if(active?.widget===widget&&active.kind==='text')return;
    const value=widget.options.get?.();if(finite(value))widget.input.value=String(value);
    begin(widget,'text');widget.host.classList.add('number-editing');
    widget.input.focus({preventScroll:true});widget.input.select();
  }
  function endPointer(e,cancelled=false){
    const drag=pointer;if(!drag||drag.id!==e.pointerId)return;
    const {widget}=drag,{view}=widget;pointer=null;
    if(view.hasPointerCapture(e.pointerId))view.releasePointerCapture(e.pointerId);
    if(drag.moved){lastTap=null;if(active?.widget===widget)finish(cancelled);return;}
    if(cancelled||e.type!=='pointerup'||e.timeStamp-drag.startAt>doubleTapDelay||Math.max(Math.abs(e.clientX-drag.startX),Math.abs(e.clientY-drag.startY))>=dragThreshold){lastTap=null;return;}
    // Recognize two completed taps ourselves: composition hosts do not always
    // deliver a native dblclick after pointer capture. Open only after release
    // so that this pointerup/lostpointercapture cannot close the new text edit.
    const previous=lastTap;
    lastTap={widget,time:e.timeStamp,x:e.clientX,y:e.clientY};
    if(previous?.widget===widget&&e.timeStamp-previous.time<=doubleTapDelay&&Math.hypot(e.clientX-previous.x,e.clientY-previous.y)<=tapRadius){lastTap=null;edit(widget);}
  }
  function adjust(widget,direction,e){
    if(widget.input.disabled||widget.input.readOnly)return;
    if(active?.widget===widget)flush();else finish();
    const actual=widget.options.get?.()??widget.input.value;if(!finite(actual))return;
    widget.input.value=String(actual);begin(widget,'step');
    const b=limits(widget),value=Math.max(b.min,Math.min(b.max,Number(actual)+direction*stepOf(widget)*factor(e)));
    if(value!==Number(actual))write(widget,Number(value.toFixed(12)));
    finish();
  }
  function attach(input){
    if(widgets.has(input))return widgets.get(input);
    const label=input.labels?.[0]?.textContent.trim(),host=document.createElement('span'),view=document.createElement('button');
    host.className='number-field';view.className='number-value';view.type='button';view.setAttribute('role','spinbutton');
    const steps=document.createElement('span'),up=document.createElement('button'),down=document.createElement('button');
    steps.className='number-steps';
    for(const [button,direction]of [[up,1],[down,-1]]){
      button.type='button';button.className='number-step';button.dataset.direction=direction;button.textContent=direction>0?'+':'−';steps.append(button);
    }
    input.before(host);host.append(view,input,steps);input.classList.add('number-input');input.tabIndex=-1;
    const widget={input,host,view,up,down,label,options:{},writing:false};widgets.set(input,widget);
    for(const [button,direction]of [[up,1],[down,-1]]){
      // Keep an open text edit alive until click, so committing cannot replace
      // a dynamic row (and its button) halfway through the pointer gesture.
      button.addEventListener('pointerdown',e=>{if(e.button===0)e.preventDefault();e.stopPropagation();});
      button.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();adjust(widget,direction,e);});
      button.addEventListener('keydown',e=>{if(e.key==='ArrowUp'||e.key==='ArrowDown'){e.preventDefault();e.stopPropagation();adjust(widget,e.key==='ArrowUp'?1:-1,e);}});
    }
    Object.defineProperty(input,'value',{configurable:true,get(){return nativeValue.get.call(this);},set(value){nativeValue.set.call(this,value);sync(widget);}});
    // Native dblclick can still arrive after the tap pair; it must not restart
    // the edit, reselect text, or turn a completed drag into text entry.
    view.addEventListener('dblclick',e=>e.preventDefault());
    view.addEventListener('pointerdown',e=>{
      if(e.button!==0||view.disabled)return;finish();e.preventDefault();view.focus({preventScroll:true});
      pointer={widget,id:e.pointerId,startAt:e.timeStamp,startX:e.clientX,startY:e.clientY,lastX:e.clientX,lastY:e.clientY,moved:false,axis:null};view.setPointerCapture(e.pointerId);
    });
    view.addEventListener('pointermove',e=>{
      const drag=pointer;if(!drag||drag.widget!==widget||drag.id!==e.pointerId)return;
      if(input.disabled||input.readOnly){finish(true);pointer=null;return;}
      if(!drag.moved){
        const dx=e.clientX-drag.startX,dy=e.clientY-drag.startY;
        if(Math.max(Math.abs(dx),Math.abs(dy))<dragThreshold)return;
        // Keep the initial dominant axis for the whole gesture so diagonal drift cannot reverse or double the adjustment.
        drag.axis=Math.abs(dy)>Math.abs(dx)?'y':'x';drag.moved=true;begin(widget,'drag');
        host.dataset.scrubAxis=drag.axis;host.classList.add('number-dragging');
      }
      const step=stepOf(widget);
      const delta=drag.axis==='y'?drag.lastY-e.clientY:e.clientX-drag.lastX;drag.lastX=e.clientX;drag.lastY=e.clientY;
      if(delta===0)return;
      const bounds=limits(widget),base=pending?.widget===widget?pending.value:Number(active.last||0),value=base+delta*step*factor(e);
      queue(widget,Math.max(bounds.min,Math.min(bounds.max,Number(value.toFixed(6)))));
    });
    // Capture can be dropped by the desktop host before pointerup arrives.
    // Only an explicit cancel/Escape rolls back an otherwise valid edit.
    view.addEventListener('lostpointercapture',e=>{if(pointer?.widget===widget)endPointer(e);});
    view.addEventListener('keydown',e=>{
      if(view.disabled)return;
      if(e.key==='Enter'||e.key==='F2'){e.preventDefault();e.stopPropagation();edit(widget);}
      if(e.key==='ArrowUp'||e.key==='ArrowDown'){
        e.preventDefault();e.stopPropagation();adjust(widget,e.key==='ArrowUp'?1:-1,e);
      }
    });
    input.addEventListener('input',e=>{
      if(widget.writing)return;
      // Deliver one validated notification, not both the original keystroke
      // and a nested input event. Incomplete '-' / empty strings stay local.
      e.stopImmediatePropagation();
      if(active?.widget===widget&&finite(input.value))write(widget,Number(input.value),true);else sync(widget);
    });
    input.addEventListener('change',e=>{if(!widget.writing)e.stopImmediatePropagation();});
    input.addEventListener('keydown',e=>{
      if(e.key==='Enter'){e.preventDefault();e.stopPropagation();finish(false,true);}
      if(e.key==='Escape'){e.preventDefault();e.stopPropagation();finish(true,true);}
    });
    input.addEventListener('blur',()=>{if(active?.widget===widget&&active.kind==='text')finish();});
    sync(widget);return widget;
  }
  function scan(root){if(root.namespaceURI==='http://www.w3.org/2000/svg')return;if(root instanceof HTMLInputElement&&root.type==='number')attach(root);root.querySelectorAll?.('input[type=number]').forEach(attach);}
  window.BlitzNumbers={configure(input,options){const widget=attach(input);Object.assign(widget.options,options);sync(widget);return widget;},finish,
    get active(){return active?.widget.input||null;}};
  scan(document);
  new MutationObserver(records=>{for(const record of records){
    if(record.type==='childList')record.addedNodes.forEach(node=>{if(node.nodeType===1)scan(node);});
    else{const widget=widgets.get(record.target);if(widget)sync(widget);}
  }}).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['disabled','readonly','min','max','step','aria-label','title']});
  document.addEventListener('pointerdown',e=>{if(lastTap&&(e.button!==0||!lastTap.widget.view.contains(e.target)))lastTap=null;if(active&&!active.widget.host.contains(e.target))finish();},true);
  document.addEventListener('pointerup',e=>endPointer(e),true);
  document.addEventListener('pointercancel',e=>endPointer(e,true),true);
  document.addEventListener('keydown',e=>{lastTap=null;if(active&&e.key==='Escape'){e.preventDefault();e.stopPropagation();finish(true,true);}},true);
  window.addEventListener('blur',()=>{finish();pointer=null;lastTap=null;});
})();
