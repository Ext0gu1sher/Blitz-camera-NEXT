/* Draft-only editing; bindings take effect only after a successful save. */
(() => {
  const C=window.BlitzControls,$=id=>document.getElementById(id);
  let capture=null,suppressMenuUntil=0;
  const captureHost=active=>window.chrome?.webview?.postMessage({command:'shortcut-capture',active});
  C.cancelCapture=()=>{if(capture){capture.button.classList.remove('recording');capture.button.textContent=C.label(capture.get());capture=null;captureHost(false);}};
  C.capture=(button,action,get,set,message)=>{
    C.cancelCapture();capture={button,action,get,set,message};button.classList.add('recording');button.textContent='请按键…';
    captureHost(true);
    message(action.mouse?'按下要绑定的鼠标键；Esc 取消。':'按下按键或组合键；Backspace 清空，Esc 取消。');
  };
  function accept(key){
    const c=capture,error=c.action.global?C.globalError(key):C.bindingError(key,c.action);
    if(error){c.message(error,true);return;}
    C.cancelCapture();c.set(key);
  }
  document.addEventListener('keydown',e=>{
    if(!capture)return;e.preventDefault();e.stopImmediatePropagation();
    if(e.code==='Escape'){const c=capture;C.cancelCapture();c.message('已取消录入。');return;}
    if(e.repeat||/^(Control|Shift|Alt|Meta)/.test(e.code))return;
    if(capture.action.mouse){capture.message('请按鼠标键，或按 Esc 取消。');return;}
    if(e.code==='Backspace'||e.code==='Delete'){accept(null);return;}
    accept(C.chord(e)||'Meta');
  },true);
  document.addEventListener('pointerdown',e=>{
    if(!capture)return;
    if(capture.action.mouse){e.preventDefault();e.stopImmediatePropagation();suppressMenuUntil=performance.now()+1000;accept('Mouse'+e.button);}
    else if(e.target!==capture.button)C.cancelCapture();
  },true);
  document.addEventListener('contextmenu',e=>{if(performance.now()<suppressMenuUntil||e.target.closest('.binding-button'))e.preventDefault();});
  window.addEventListener('blur',C.cancelCapture);
  C.createSettings=onChange=>{
    let draft=null,locked=true;
    const api={
      get value(){return structuredClone(draft);},
      get errors(){return draft?C.errors(draft):[];},
      message(text,error=false){$('controlsResult').textContent=text;$('controlsResult').classList.toggle('error',error);},
      load(config){C.cancelCapture();draft=structuredClone(config||C.defaults());api.render();api.message('');},
      reset(){api.load(C.defaults());api.message('已恢复默认，保存后生效。');onChange();},
      lock(value){locked=value;$('controlsFields').disabled=value;$('controlsDefault').disabled=value;},
      render(){
        const root=$('bindingGroups');root.replaceChildren();
        for(const group of [...new Set(C.schema.actions.map(a=>a.group))]){
          const section=document.createElement(group==='飞行速度'?'details':'section');section.className='binding-group';
          const heading=document.createElement(group==='飞行速度'?'summary':'h3');heading.textContent=group;section.append(heading);
          for(const a of C.schema.actions.filter(a=>a.group===group)){
            const row=document.createElement('div');row.className='binding-row';row.dataset.bindingRow=a.id;
            const label=document.createElement('span');label.textContent=a.label;
            const button=document.createElement('button');button.type='button';button.className='binding-button';button.dataset.binding=a.id;button.textContent=C.label(draft.bindings[a.id]);button.setAttribute('aria-label',a.label+'快捷键');
            const reset=document.createElement('button');reset.type='button';reset.className='binding-reset';reset.textContent='默认';reset.setAttribute('aria-label','恢复'+a.label+'默认按键');
            const clear=document.createElement('button');clear.type='button';clear.className='binding-reset';clear.textContent='清空';clear.setAttribute('aria-label','清空'+a.label+'快捷键');
            const set=key=>{draft.bindings[a.id]=key;button.textContent=C.label(key);api.validate();onChange();};
            button.onclick=()=>C.capture(button,a,()=>draft.bindings[a.id],set,api.message);reset.onclick=()=>set(a.key);clear.onclick=()=>set(null);
            row.append(label,button,reset,clear);section.append(row);
          }
          root.append(section);
        }
        const tuning=$('controlTuning');tuning.replaceChildren();
        for(const t of C.schema.tuning){
          const row=document.createElement('label');row.className='tuning-row';const name=document.createElement('span');name.textContent=t.label;
          const input=document.createElement('input');input.type='number';input.min=t.min;input.max=t.max;input.step=t.step;input.value=draft.tuning[t.id];input.dataset.tuning=t.id;input.setAttribute('aria-label',t.label);
          input.oninput=()=>{draft.tuning[t.id]=input.value===''?NaN:Number(input.value);api.validate();onChange();};
          const unit=document.createElement('span');unit.textContent=t.unit;row.append(name,input,unit);tuning.append(row);
        }
        api.lock(locked);api.validate();
      },
      validate(){const errors=api.errors;document.querySelectorAll('[data-binding-row]').forEach(row=>row.classList.toggle('conflict',errors.some(e=>e.ids.includes(row.dataset.bindingRow))));api.message(errors.map(e=>e.text).join(' '),!!errors.length);return errors;}
    };return api;
  };
})();
