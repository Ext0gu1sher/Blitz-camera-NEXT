/* Offline editor view snapshots. No game camera or playback API is used. */
(function(root,factory){const api=factory();if(typeof module!=="undefined"&&module.exports)module.exports=api;else root.BlitzEditorSession=api;})(typeof globalThis!=="undefined"?globalThis:this,function(){
  'use strict';
  const finite=Number.isFinite, clamp=(n,a,b)=>Math.max(a,Math.min(b,n));
  const array=(v,n)=>Array.isArray(v)&&v.length===n&&v.every(finite);
  const pose=v=>v&&array(v.position,3)&&['yaw','pitch','roll','zoom'].every(k=>finite(v[k]))&&v.zoom>0&&v.zoom<180;
  const clone=v=>JSON.parse(JSON.stringify(v));
  function capturePreview(pane){
    if(pane?.status!=='ready'||!pane.observer||!pane.orbit)return null;
    return {view:pane.view,observer:{position:pane.observer.position.toArray(),quaternion:pane.observer.quaternion.toArray(),target:pane.orbit.target.toArray(),fov:pane.observer.fov},override:pose(pane.override)?clone(pane.override):null,flight_speed:pane.flightSpeed};
  }
  function restorePreview(pane,value){
    if(pane?.status!=='ready'||!pane.observer||!pane.orbit||!value)return false;
    const o=value.observer;
    pane.stopFlight();
    if(o&&array(o.position,3)&&array(o.quaternion,4)&&array(o.target,3)&&finite(o.fov)&&o.fov>0&&o.fov<180){
      pane.orbit.target.fromArray(o.target);pane.observer.position.fromArray(o.position);pane.observer.quaternion.fromArray(o.quaternion).normalize();pane.observer.fov=o.fov;pane.observer.updateProjectionMatrix();pane.orbit.update();
    }
    pane.override=pose(value.override)?clone(value.override):null;
    if(finite(value.flight_speed))pane.flightSpeed=clamp(Math.round(value.flight_speed),1,9);
    pane.setView(value.view==='camera'?'camera':'observer');pane.render();return true;
  }
  function captureTimeline(editor,time){
    if(!editor?.doc)return null;
    return {scale:editor.scale,scroll_left:editor.scroll.scrollLeft,scroll_top:editor.scroll.scrollTop,axis:editor.axis,fps:editor.fps,snap:editor.snap,playhead:time,horizon:editor.horizon};
  }
  function restoreTimeline(editor,value){
    if(!editor?.doc||!value)return false;
    if(finite(value.scale))editor.scale=clamp(value.scale,.000001,2000);
    editor.axis=editor.free()?'shooting':value.axis==='shooting'?'shooting':'replay';
    if([24,30,60].includes(value.fps))editor.fps=value.fps;
    if(typeof value.snap==='boolean')editor.snap=value.snap;
    if(editor.free()&&finite(value.horizon))editor.horizon=Math.max(editor.horizon||30,value.horizon);
    editor.pendingFit=false;editor.root.querySelector('[data-option=axis]').value=editor.axis;editor.root.querySelector('[data-option=fps]').value=editor.fps;
    editor.root.querySelector('[data-action=snap]').setAttribute('aria-pressed',String(editor.snap));
    editor.render();
    if(finite(value.scroll_left))editor.scroll.scrollLeft=Math.max(0,value.scroll_left);
    if(finite(value.scroll_top))editor.scroll.scrollTop=Math.max(0,value.scroll_top);
    editor.labels.scrollTop=editor.scroll.scrollTop;editor.render();return true;
  }
  function readLocal(storage,path){try{const v=JSON.parse(storage.getItem('blitz-editor-session:'+path));return v?.schema_version===1?v:null;}catch{return null;}}
  function writeLocal(storage,path,value){try{storage.setItem('blitz-editor-session:'+path,JSON.stringify(value));}catch{}}
  function newest(server,local){if(!local)return server;if(!server)return local;return Number(local.saved_at)>Number(server.saved_at)?local:server;}
  return {capturePreview,restorePreview,captureTimeline,restoreTimeline,readLocal,writeLocal,newest};
});
