/* Shared scrub numbers: drag to adjust, double-click for precise text entry. */
(()=>{
  'use strict';
  const widgets=new WeakMap(),nativeValue=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value');
  let active=null,pointer=null;
  const event=(input,name,detail={})=>input.dispatchEvent(new CustomEvent(name,{bubbles:true,detail}));
  const finite=v=>v!==''&&Number.isFinite(Number(v));
  const format=v=>Number(Number(v).toFixed(6)).toString();
  function limits(widget){
    const custom=widget.options.bounds?.()||{};
    return {min:custom.min??(widget.input.min===''?-1e7:Number(widget.input.min)),max:custom.max??(widget.input.max===''?1e7:Number(widget.input.max))};
  }
  function sync(widget){
    const {input,view,host}=widget,value=input.value;
    view.textContent=finite(value)?format(value):'—';
    view.disabled=input.disabled||input.readOnly;host.dataset.readonly=String(input.readOnly);
    view.setAttribute('aria-label',input.getAttribute('aria-label')||widget.label||'数值');
    if(finite(value))view.setAttribute('aria-valuenow',value);else view.removeAttribute('aria-valuenow');
    const bounds=limits(widget);view.setAttribute('aria-valuemin',bounds.min);view.setAttribute('aria-valuemax',bounds.max);
    view.title=view.disabled?(input.title||'只读数值'):'左右或上下拖动调整 · 右/上增加，左/下减少 · Shift 精调 · Ctrl 加速 · 双击输入';
  }
  function begin(widget,kind){
    if(active?.widget===widget)return;
    finish();active={widget,kind,original:widget.input.value,last:widget.input.value};
    event(widget.input,'number-start',{kind});
  }
  function write(widget,value,typed=false){
    const {input,options}=widget,bounds=limits(widget);
    if(!Number.isFinite(value)||value<bounds.min||value>bounds.max){input.setAttribute('aria-invalid','true');return false;}
    const previous=active?.widget===widget?active.last:input.value,raw=input.value;
    input.removeAttribute('aria-invalid');widget.writing=true;
    try{
      input.value=format(value);
      if(options.set?.(value)===false){input.value=previous;input.setAttribute('aria-invalid','true');return false;}
      if(options.get){const actual=options.get();if(finite(actual))input.value=String(actual);}
      if(active?.widget===widget)active.last=input.value;
      input.dispatchEvent(new Event('input',{bubbles:true}));
      input.dispatchEvent(new Event('change',{bubbles:true}));
      if(typed)input.value=raw;
      return true;
    }finally{widget.writing=false;sync(widget);}
  }
  function finish(cancelled=false,focus=false){
    const session=active;if(!session)return;
    const {widget}=session,{input,view,host}=widget;
    if(cancelled&&finite(session.original))write(widget,Number(session.original));
    input.value=cancelled?session.original:session.last;input.removeAttribute('aria-invalid');
    active=null;host.classList.remove('number-editing','number-dragging');delete host.dataset.scrubAxis;
    if(pointer?.widget===widget){const id=pointer.id;pointer=null;if(view.hasPointerCapture(id))view.releasePointerCapture(id);}
    event(input,'number-end',{cancelled,kind:session.kind});sync(widget);
    if(focus&&view.isConnected&&!view.disabled)view.focus({preventScroll:true});
  }
  function edit(widget){
    if(widget.input.disabled||widget.input.readOnly)return;
    begin(widget,'text');widget.host.classList.add('number-editing');
    widget.input.focus({preventScroll:true});widget.input.select();
  }
  function attach(input){
    if(widgets.has(input))return widgets.get(input);
    const label=input.labels?.[0]?.textContent.trim(),host=document.createElement('span'),view=document.createElement('button');
    host.className='number-field';view.className='number-value';view.type='button';view.setAttribute('role','spinbutton');
    input.before(host);host.append(view,input);input.classList.add('number-input');input.tabIndex=-1;
    const widget={input,host,view,label,options:{},writing:false};widgets.set(input,widget);
    Object.defineProperty(input,'value',{configurable:true,get(){return nativeValue.get.call(this);},set(value){nativeValue.set.call(this,value);sync(widget);}});
    view.addEventListener('dblclick',e=>{e.preventDefault();edit(widget);});
    view.addEventListener('pointerdown',e=>{
      if(e.button!==0||view.disabled)return;finish();e.preventDefault();view.focus({preventScroll:true});
      pointer={widget,id:e.pointerId,startX:e.clientX,startY:e.clientY,lastX:e.clientX,lastY:e.clientY,moved:false,axis:null};view.setPointerCapture(e.pointerId);
    });
    view.addEventListener('pointermove',e=>{
      const drag=pointer;if(!drag||drag.widget!==widget||drag.id!==e.pointerId)return;
      if(input.disabled||input.readOnly){finish(true);pointer=null;return;}
      if(!drag.moved){
        const dx=e.clientX-drag.startX,dy=e.clientY-drag.startY;
        if(Math.max(Math.abs(dx),Math.abs(dy))<3)return;
        // Keep the initial dominant axis for the whole gesture so diagonal drift cannot reverse or double the adjustment.
        drag.axis=Math.abs(dy)>Math.abs(dx)?'y':'x';drag.moved=true;begin(widget,'drag');
        host.dataset.scrubAxis=drag.axis;host.classList.add('number-dragging');
      }
      const step=typeof widget.options.step==='function'?widget.options.step():widget.options.step??Number(input.dataset.scrubStep||input.step||1);
      const delta=drag.axis==='y'?drag.lastY-e.clientY:e.clientX-drag.lastX;drag.lastX=e.clientX;drag.lastY=e.clientY;
      if(delta===0)return;
      const bounds=limits(widget),value=Number(active.last||0)+delta*step*(e.shiftKey ? .1 : e.ctrlKey||e.metaKey ? 10 : 1);
      write(widget,Math.max(bounds.min,Math.min(bounds.max,Number(value.toFixed(6)))));
    });
    const endPointer=(e,cancelled=false)=>{
      if(!pointer||pointer.widget!==widget||pointer.id!==e.pointerId)return;
      pointer=null;if(active?.widget===widget&&active.kind==='drag')finish(cancelled);
      if(view.hasPointerCapture(e.pointerId))view.releasePointerCapture(e.pointerId);
    };
    view.addEventListener('pointerup',e=>endPointer(e));view.addEventListener('pointercancel',e=>endPointer(e,true));
    // Capture can be dropped by the desktop host before pointerup arrives.
    // Only an explicit cancel/Escape rolls back an otherwise valid edit.
    view.addEventListener('lostpointercapture',e=>endPointer(e));
    view.addEventListener('keydown',e=>{
      if(view.disabled)return;
      if(e.key==='Enter'||e.key==='F2'){e.preventDefault();e.stopPropagation();edit(widget);}
      if(e.key==='ArrowUp'||e.key==='ArrowDown'){
        e.preventDefault();e.stopPropagation();begin(widget,'key');
        const step=typeof widget.options.step==='function'?widget.options.step():widget.options.step??Number(input.dataset.scrubStep||input.step||1),b=limits(widget);
        write(widget,Math.max(b.min,Math.min(b.max,Number(input.value||0)+(e.key==='ArrowUp'?1:-1)*step*(e.shiftKey ? .1 : 1))));finish();
      }
    });
    input.addEventListener('input',()=>{if(!widget.writing&&active?.widget===widget&&finite(input.value))write(widget,Number(input.value),true);});
    input.addEventListener('change',e=>{if(!widget.writing)e.stopImmediatePropagation();});
    input.addEventListener('keydown',e=>{
      if(e.key==='Enter'){e.preventDefault();e.stopPropagation();finish(false,true);}
      if(e.key==='Escape'){e.preventDefault();e.stopPropagation();finish(true,true);}
    });
    input.addEventListener('blur',()=>{if(active?.widget===widget&&active.kind==='text')finish();});
    sync(widget);return widget;
  }
  function scan(root){if(root instanceof HTMLInputElement&&root.type==='number')attach(root);root.querySelectorAll?.('input[type=number]').forEach(attach);}
  window.BlitzNumbers={configure(input,options){const widget=attach(input);Object.assign(widget.options,options);sync(widget);return widget;},finish,
    get active(){return active?.widget.input||null;}};
  scan(document);
  new MutationObserver(records=>{for(const record of records){
    if(record.type==='childList')record.addedNodes.forEach(node=>{if(node.nodeType===1)scan(node);});
    else{const widget=widgets.get(record.target);if(widget)sync(widget);}
  }}).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['disabled','readonly','min','max','step','aria-label','title']});
  document.addEventListener('pointerdown',e=>{if(active&&!active.widget.host.contains(e.target))finish();},true);
  document.addEventListener('pointerup',e=>{if(pointer?.id===e.pointerId)finish();},true);
  document.addEventListener('pointercancel',e=>{if(pointer?.id===e.pointerId)finish(true);},true);
  document.addEventListener('keydown',e=>{if(active&&e.key==='Escape'){e.preventDefault();e.stopPropagation();finish(true,true);}},true);
  window.addEventListener('blur',()=>{finish();pointer=null;});
})();
