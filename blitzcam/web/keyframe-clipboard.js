/* Keyframe clipboard data; no DOM, project writes, or operating-system clipboard. */
(function(root,factory){const api=factory(typeof module!=="undefined"&&module.exports?require('./preview-time.js'):root.BlitzPreviewTime);if(typeof module!=="undefined"&&module.exports)module.exports=api;else root.BlitzKeyframeClipboard=api;})(typeof globalThis!=="undefined"?globalThis:this,function(Timing){
  'use strict';
  const CHANNELS=['x','y','z','yaw','pitch','roll','zoom'],ALL=[...CHANNELS,'rate'];
  const EPS=1e-6,MIN_GAP=1e-5,TYPE='blitzcam-keyframes';
  const own=(o,k)=>Object.prototype.hasOwnProperty.call(o,k),clone=x=>JSON.parse(JSON.stringify(x));
  const fail=message=>{throw new Error(message);};
  function object(value,fields,label){
    if(!value||typeof value!=='object'||Array.isArray(value)||![Object.prototype,null].includes(Object.getPrototypeOf(value)))fail(`${label}格式无效。`);
    for(const key of Reflect.ownKeys(value)){
      const d=Object.getOwnPropertyDescriptor(value,key);
      if(typeof key!=='string'||!fields.includes(key)||!d.enumerable||!own(d,'value'))fail(`${label}包含未知字段。`);
    }
    return value;
  }
  function array(value,max,label){
    if(!Array.isArray(value)||Object.getPrototypeOf(value)!==Array.prototype||!value.length||value.length>max||Reflect.ownKeys(value).length!==value.length+1)fail(`${label}数量或格式无效。`);
    for(let i=0;i<value.length;i++){const d=Object.getOwnPropertyDescriptor(value,String(i));if(!d||!d.enumerable||!own(d,'value'))fail(`${label}数量或格式无效。`);}
    return value;
  }
  function finite(value,min,max,label){if(typeof value!=='number'||!Number.isFinite(value)||value<min||value>max)fail(`${label}无效。`);return value;}
  function ease(value,rate){
    array(value,4,'缓动手柄');if(value.length!==4)fail('缓动手柄需要四个坐标。');
    const result=value.map((v,i)=>finite(v,rate&&i%2?-1e6:0,rate&&i%2?1e6:1,'缓动手柄'));
    if(rate&&result[0]>result[2])fail('速度曲线手柄不能交叉。');return result;
  }
  function keyData(channel,key,source=false,effectiveEase){
    const rate=channel==='rate',allowed=rate?['rate','ease']:['value','ease','curve'];
    object(key,source?[...allowed,'_id','time_sec','progress']:allowed,'关键帧');
    const result=rate?{rate:finite(key.rate,.0625,1,'回放倍率')}:{value:finite(key.value,-1e7,1e7,'关键帧数值')};
    if(channel==='zoom'&&!(result.value>0&&result.value<180))fail('缩放需大于 0°、小于 180°。');
    if(channel==='pitch'&&Math.abs(result.value)>80)fail('俯仰需在 -80° 至 80° 内。');
    if(own(key,'curve')){if(key.curve!=='auto')fail('摄像机曲线模式无效。');result.curve='auto';}
    if(effectiveEase!==undefined)result.ease=ease(effectiveEase,rate);else if(own(key,'ease'))result.ease=ease(key.ease,rate);
    return result;
  }
  function checkItems(items,source){
    array(items,1464,'剪贴板关键帧');let camera=0,rate=0;
    const result=items.map(item=>{
      object(item,source?['channel','time_sec','key','effectiveEase']:['channel','offset_sec','key'],'剪贴板条目');
      if(!ALL.includes(item.channel))fail('剪贴板关键帧通道无效。');
      if(item.channel==='rate')rate++;else camera++;
      const time=finite(item[source?'time_sec':'offset_sec'],0,1e7,'关键帧时间');
      return {channel:item.channel,time,key:keyData(item.channel,item.key,source,source?item.effectiveEase:undefined)};
    });
    if(camera>1400||rate>64)fail('一次最多复制 1400 个摄像机参数点和 64 个速度点。');
    for(const channel of ALL){
      const times=result.filter(k=>k.channel===channel).map(k=>k.time).sort((a,b)=>a-b);
      if(times.some((t,i)=>i&&t-times[i-1]<MIN_GAP))fail('剪贴板中同一通道的关键帧不能重合或过近。');
    }
    return result;
  }
  function capture(items){
    const checked=checkItems(items,true).sort((a,b)=>a.time-b.time),first=checked[0].time;
    return {type:TYPE,version:1,items:checked.map(item=>({channel:item.channel,offset_sec:item.time-first,key:item.key}))};
  }
  function payloadItems(payload){
    object(payload,['type','version','items'],'关键帧剪贴板');
    if(payload.type!==TYPE||payload.version!==1)fail('剪贴板不是受支持的关键帧数据。');
    const checked=checkItems(payload.items,false);
    if(Math.min(...checked.map(item=>item.time))!==0)fail('关键帧剪贴板缺少起始时刻。');return checked;
  }
  function validateCamera(rows,channel){
    if(!Array.isArray(rows)||!rows.length||rows.length>200)fail('每条摄像机轨道需要 1–200 个关键帧。');
    for(let i=0;i<rows.length;i++){
      const k=rows[i];keyData(channel,k,true);finite(k.time_sec,0,1e7,'关键帧时间');
      if(i&&k.time_sec-rows[i-1].time_sec<MIN_GAP)fail('同一轨道的关键帧不能重合或过近。');
    }
  }
  function paste(doc,payload,playhead,nextId){
    const items=payloadItems(payload);finite(playhead,0,1e7,'粘贴时刻');
    if(!doc||!doc.tracks||!doc.speed||!['camera_only','replay'].includes(doc.mode))fail('请先打开有效的轨迹。');
    if(doc.mode==='camera_only'&&items.some(item=>item.channel==='rate'))fail('模式一不支持速度关键帧，请切换到模式二后粘贴。');
    const duration=doc.mode==='replay'?finite(doc.timeline?.duration_sec,0,3600,'回放长度'):1e7;
    const targets=items.map(item=>({...item,time:finite(playhead+item.time,0,duration,'粘贴目标时间')}));
    if(typeof nextId!=='function')fail('无法生成关键帧标识。');
    const out=clone(doc),used=new Set(),selected=[];let replaced=0;
    for(const row of [...Object.values(out.tracks),out.speed.keyframes]){
      if(!Array.isArray(row))fail('轨迹关键帧数据无效。');
      for(const k of row)if(own(k,'_id')){if(!Number.isSafeInteger(k._id)||k._id<=0||used.has(k._id))fail('轨迹关键帧标识无效。');used.add(k._id);}
    }
    const id=()=>{const value=nextId();if(!Number.isSafeInteger(value)||value<=0||used.has(value))fail('新关键帧标识无效或重复。');used.add(value);return value;};
    for(const channel of CHANNELS){
      const row=out.tracks[channel];validateCamera(row,channel);
      for(const item of targets.filter(item=>item.channel===channel)){
        const index=row.findIndex(k=>Math.abs(k.time_sec-item.time)<=EPS),key={...clone(item.key),time_sec:item.time,_id:id()};
        if(index<0)row.push(key);else{row.splice(index,1,key);replaced++;}selected.push(key._id);
      }
      row.sort((a,b)=>a.time_sec-b.time_sec);validateCamera(row,channel);
    }
    const rates=targets.filter(item=>item.channel==='rate');
    if(rates.length){
      const s=out.speed;
      if(!Timing.valid(s))fail('当前速度曲线无效，无法粘贴。');
      const range=s.mode==='curve'&&s.time_range?s.time_range:{start_sec:out.timeline.work_start_sec,end_sec:out.timeline.work_end_sec};
      const start=finite(range.start_sec,0,duration,'速度曲线起点'),end=finite(range.end_sec,0,duration,'速度曲线终点');
      if(!(end>start))fail('速度曲线时间范围无效。');
      let records;
      if(s.mode==='curve'){
        if(s.camera_clock!=='replay')fail('速度曲线需要使用对局时间。');
        records=s.keyframes.map(k=>({time:start+Timing.atShooting(end-start,s,k.progress).cameraProgress*(end-start),key:clone(k)}));
      }else{
        const rate=s.mode==='fixed'?s.rate:1;
        records=[{time:start,key:{rate,_id:id()}},{time:end,key:{rate,_id:id()}}];
      }
      for(const item of rates){
        const index=records.findIndex(r=>Math.abs(r.time-item.time)<=EPS),key={...clone(item.key),_id:id()};
        if(index<0)records.push({time:item.time,key});else{records.splice(index,1,{time:item.time,key});replaced++;}selected.push(key._id);
      }
      records.sort((a,b)=>a.time-b.time);
      if(records.length>64)fail('速度曲线最多保留 64 个点。');
      if(records.some((r,i)=>i&&r.time-records[i-1].time<MIN_GAP))fail('速度关键帧不能重合或过近。');
      s.mode='curve';s.camera_clock='replay';s.time_range={start_sec:records[0].time,end_sec:records.at(-1).time};s.keyframes=records.map(r=>r.key);
      // A copied outgoing handle may meet a different neighbour. Keep it in the
      // legal rate range before computing its segment's exact mean rate.
      for(let i=1;i<s.keyframes.length;i++){
        const a=s.keyframes[i-1],b=s.keyframes[i];
        if(a.ease&&[1,3].some(j=>{const value=a.rate+(b.rate-a.rate)*a.ease[j];return value<.0625||value>1;}))Timing.boundHandles({keyframes:[a,b]});
      }
      const segments=records.slice(1).map((b,i)=>{
        const a=records[i],mean=a.key.rate+(b.key.rate-a.key.rate)*(a.key.ease?Timing.bezierArea(a.key.ease,1):.5);
        if(!Number.isFinite(mean)||mean<.0625-1e-9||mean>1+1e-9)fail('速度曲线平均倍率无效。');
        return (b.time-a.time)/mean;
      });
      const total=segments.reduce((sum,v)=>sum+v,0);let elapsed=0;
      if(!Number.isFinite(total)||total<=0)fail('速度曲线时长无效。');
      for(let i=0;i<records.length;i++){if(i)elapsed+=segments[i-1];records[i].key.progress=i===records.length-1?1:elapsed/total;}
      if(!Timing.valid(s))fail('粘贴后的速度点过近或曲线无效，请调整粘贴位置。');
      const width=s.time_range.end_sec-s.time_range.start_sec;
      for(const r of records){const actual=s.time_range.start_sec+Timing.atShooting(width,s,r.key.progress).cameraProgress*width;if(!Number.isFinite(actual)||Math.abs(actual-r.time)>EPS)fail('速度关键帧无法准确对齐粘贴时刻。');}
    }
    return {doc:out,selected,count:targets.length,replaced};
  }
  return {capture,paste};
});
