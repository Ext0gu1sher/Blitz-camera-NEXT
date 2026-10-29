/* Application input map, shared by the editor, preview and settings page. */
(() => {
  const C=window.BlitzControls={schema:null,config:null,error:''};
  const codePattern=/^(?:Key[A-Z]|Digit[0-9]|Numpad[0-9]|F(?:[1-9]|1[0-2])|Arrow(?:Left|Right|Up|Down)|Home|End|PageUp|PageDown|Insert|Tab|Backquote|Minus|Equal|BracketLeft|BracketRight|Backslash|Semicolon|Quote|Comma|Period|Slash)$/;
  C.chord=e=>e.metaKey?null:[e.ctrlKey?'Ctrl':null,e.altKey?'Alt':null,e.shiftKey?'Shift':null,e.code].filter(Boolean).join('+');
  C.label=key=>key?key.split('+').map(k=>({ArrowLeft:'←',ArrowRight:'→',ArrowUp:'↑',ArrowDown:'↓',Mouse0:'鼠标左键',Mouse1:'鼠标中键',Mouse2:'鼠标右键',Mouse3:'鼠标侧键 1',Mouse4:'鼠标侧键 2',Backquote:'`',Minus:'−',Equal:'=',BracketLeft:'[',BracketRight:']',Backslash:'\\',Semicolon:';',Quote:"'",Comma:',',Period:'.',Slash:'/'}[k]||k.replace(/^Key|^Digit/,'').replace(/^Numpad/,'小键盘 '))).join('+'):'未绑定';
  C.defaults=()=>({bindings:Object.fromEntries(C.schema.actions.map(a=>[a.id,a.key])),tuning:Object.fromEntries(C.schema.tuning.map(t=>[t.id,t.value]))});
  C.bindingError=(key,action)=>{
    if(key==null)return '';
    if(action.mouse)return /^Mouse[0-4]$/.test(key)?'':'请按鼠标按键。';
    const parts=key.split('+'),code=parts.pop(),mods=parts;
    if(mods.join('+')!==['Ctrl','Alt','Shift'].filter(m=>mods.includes(m)).join('+')||!codePattern.test(code))return '请选择字母、数字、方向键、功能键或组合键；空格和 Esc 保持固定。';
    if((code==='Tab'&&(action.id!=='exitFlight'||mods.length))||(['F5','F11','F12'].includes(code)&&!mods.length)||(mods.includes('Ctrl')&&!mods.includes('Alt')&&'SZYACVXRLWTNPF'.split('').map(c=>'Key'+c).includes(code))||(mods.includes('Alt')&&['Tab','F4'].includes(code)))return '此按键保留给通用操作，请换一个。';
    return '';
  };
  C.errors=config=>{
    const errors=[];
    for(const [i,a] of C.schema.actions.entries()){
      const key=config.bindings[a.id],error=C.bindingError(key,a);
      if(error)errors.push({ids:[a.id],text:a.label+'：'+error});
      for(const b of C.schema.actions.slice(0,i))if(key&&key===config.bindings[b.id]&&a.scopes.some(s=>b.scopes.includes(s)))errors.push({ids:[a.id,b.id],text:`“${a.label}”与“${b.label}”都绑定了 ${C.label(key)}。`});
    }
    for(const t of C.schema.tuning){const n=config.tuning[t.id];if(!Number.isFinite(n)||n<t.min||n>t.max)errors.push({ids:[t.id],text:`${t.label}需为 ${t.min}–${t.max} ${t.unit}。`});}
    return errors;
  };
  let pending;
  C.apply=config=>{
    if(!C.schema){pending=config;return;}
    const defaults=C.defaults(),next={bindings:{...defaults.bindings,...config?.bindings},tuning:{...defaults.tuning,...config?.tuning}};
    if(JSON.stringify(next)===JSON.stringify(C.config))return;
    C.config=next;C.refreshHints();window.dispatchEvent(new Event('blitz-controls-changed'));
  };
  C.key=id=>C.config?.bindings[id]??null;
  C.matches=(id,e)=>!!C.key(id)&&C.key(id)===C.chord(e);
  C.held=(id,keys)=>!!C.key(id)&&keys.has(C.key(id));
  C.value=(id,fallback)=>C.config?.tuning[id]??fallback;
  C.release=(keys,code)=>{
    if(/^(Control|Alt|Shift|Meta)/.test(code)){keys.clear();return;}
    for(const key of keys)if(key.split('+').at(-1)===code)keys.delete(key);
  };
  C.hint=id=>C.label(C.key(id));
  C.refreshHints=()=>{
    const h=C.hint;
    const speeds=Array.from({length:9},(_,i)=>h('speed'+(i+1))),speedHint=speeds.every((key,i)=>key===String(i+1))?'1–9':speeds.join('/');
    const lines=[`${h('forward')}/${h('backward')}/${h('left')}/${h('right')} 移动 · ${h('up')}/${h('down')} 升降 · ${speedHint} 调速 · 滚轮缩放`,
      `空格 播放/暂停 · ${h('seekBack')}/${h('seekForward')} 长按加速 · ${h('rear')} 回到主角后方（按住跟随）`,
      `${h('rollLeft')}/${h('rollRight')} 逆/顺时针横滚 · ${[C.key('exitFlightMouse'),C.key('exitFlight')].filter(Boolean).map(C.label).concat('Esc').join(' / ')} 退出`];
    document.querySelectorAll('[data-flight-hint]').forEach((el,i)=>el.textContent=lines[i]);
    const fly=document.getElementById('previewFly');if(fly)fly.title=`自由飞行（${h('enterFlight')}） · ${lines.join(' · ')} · 调速：${Array.from({length:9},(_,i)=>h('speed'+(i+1))).join(' / ')}`;
    const record=document.getElementById('previewRecord');if(record)record.title=`记录当前预览机位为关键帧（${h('recordPreview')}）`;
    for(const [action,id,text] of [['snap','snap','吸附'],['workStart','workStart','设置起点'],['workEnd','workEnd','设置终点']])document.querySelectorAll(`[data-action="${id}"]`).forEach(el=>el.title=`${text} ${h(action)}`);
  };
  C.globalKey=key=>/^F\d+$/.test(key||'')?'Ctrl+Alt+'+key:key;
  C.globalError=key=>!key?'全局快捷键不能为空。':C.bindingError(key,{id:'global'})||(!/^(Ctrl|Alt)\+/.test(key)?'全局快捷键需包含 Ctrl 或 Alt。':'')||(key.endsWith('+F12')?'F12 由系统保留，请换一个。':'');
  C.ready=fetch('/control-schema.json').then(r=>{if(!r.ok)throw Error('无法读取快捷键配置。');return r.json();}).then(schema=>{C.schema=schema;C.apply(pending);}).catch(e=>{C.error=e.message;});
})();
