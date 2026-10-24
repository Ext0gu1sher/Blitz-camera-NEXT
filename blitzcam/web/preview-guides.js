// Editor guides only. These meshes never change the evaluated shot camera.
import * as THREE from './vendor/three/build/three.module.js';
import {Line2} from './vendor/three/examples/jsm/lines/Line2.js';
import {LineGeometry} from './vendor/three/examples/jsm/lines/LineGeometry.js';
import {LineMaterial} from './vendor/three/examples/jsm/lines/LineMaterial.js';

const CYAN=0x9cf3e9,GREEN=0xd7f58c;
function fatLine(positions,color,width,opacity=1,order=110){
  const geometry=new LineGeometry().setPositions(positions);
  const material=new LineMaterial({color,linewidth:width,worldUnits:false,transparent:true,opacity,depthTest:false,depthWrite:false,toneMapped:false});
  const line=new Line2(geometry,material);line.renderOrder=order;line.frustumCulled=false;return line;
}
function dot(radius,color){const mesh=new THREE.Mesh(new THREE.SphereGeometry(radius,12,8),new THREE.MeshBasicMaterial({color,depthTest:false,depthWrite:false,toneMapped:false}));mesh.renderOrder=125;return mesh;}
function release(root){const seen=new Set();root.traverse(n=>{for(const obj of [n.geometry,...[n.material].flat()])if(obj&&!seen.has(obj)){seen.add(obj);obj.dispose();}});}
function boxSegments(min,max){
  const corners=[];for(const z of [min[2],max[2]])for(const y of [min[1],max[1]])for(const x of [min[0],max[0]])corners.push([x,y,z]);
  return [[0,1],[0,2],[1,3],[2,3],[4,5],[4,6],[5,7],[6,7],[0,4],[1,5],[2,6],[3,7]].flatMap(([a,b])=>[...corners[a],...corners[b]]);
}

export class PreviewGuides {
  constructor(){
    this.root=new THREE.Group();this.root.name='editor-guides';
    this.path=new THREE.Group();this.root.add(this.path);this.glyph=new THREE.Group();this.glyph.name='compact-camera';this.root.add(this.glyph);
    this.lines=[];this.markers=[];this.samples=[];
    // Camera-local convention: +X right, +Y up, -Z forward. A recognisable
    // body/lens replaces the render camera's kilometre-long far-plane helper.
    const housing=new THREE.Mesh(new THREE.BoxGeometry(.76,.46,.6),new THREE.MeshBasicMaterial({color:0x102e36,depthTest:false,depthWrite:false,toneMapped:false}));housing.position.z=.38;housing.renderOrder=120;this.glyph.add(housing);
    const body=new THREE.LineSegments(new THREE.BufferGeometry().setAttribute('position',new THREE.Float32BufferAttribute(boxSegments([-.38,-.23,.08],[.38,.23,.68]),3)),new THREE.LineBasicMaterial({color:CYAN,depthTest:false,depthWrite:false,transparent:true,opacity:.9,toneMapped:false}));
    body.renderOrder=123;this.glyph.add(body);
    const lens=new THREE.Mesh(new THREE.CylinderGeometry(.27,.19,.27,4,1,true),new THREE.MeshBasicMaterial({color:CYAN,depthTest:false,depthWrite:false,transparent:true,opacity:.5,side:THREE.DoubleSide,toneMapped:false}));
    lens.rotation.x=Math.PI/2;lens.rotation.z=Math.PI/4;lens.position.z=-.08;lens.renderOrder=121;this.glyph.add(lens);
    this.cone=new THREE.LineSegments(new THREE.BufferGeometry().setAttribute('position',new THREE.Float32BufferAttribute(new Float32Array(48),3)),new THREE.LineBasicMaterial({color:CYAN,transparent:true,opacity:.8,depthTest:false,depthWrite:false,toneMapped:false}));this.cone.renderOrder=122;this.glyph.add(this.cone);
    const up=new THREE.Mesh(new THREE.ConeGeometry(.10,.25,3),new THREE.MeshBasicMaterial({color:GREEN,depthTest:false,depthWrite:false,toneMapped:false}));up.position.set(0,.45,.3);up.renderOrder=124;this.glyph.add(up);
    const halo=dot(.22,0x102e36);halo.renderOrder=124;this.glyph.add(halo);this.glyph.add(dot(.12,CYAN));this.lastZoom=null;
  }
  setPath(samples){
    release(this.path);this.path.clear();this.lines=[];this.markers=[];this.progress=null;this.samples=samples||[];
    if(this.samples.length<2)return;
    const points=this.samples.flatMap(s=>[-s.position[0],s.position[2],s.position[1]]);
    // Pixel widths stay legible at every zoom and on high-DPI displays.
    for(const [color,width,opacity,order]of [[0x04191e,5,.9,110],[GREEN,6,.12,111],[GREEN,2.2,1,112]]){const line=fatLine(points,color,width,opacity,order);this.path.add(line);this.lines.push(line);}
    this.progress=fatLine(points,CYAN,2.6,1,113);this.progress.geometry.instanceCount=0;this.path.add(this.progress);this.lines.push(this.progress);
    for(const sample of [this.samples[0],this.samples.at(-1)]){const p=dot(1,GREEN);p.position.set(-sample.position[0],sample.position[2],sample.position[1]);this.markers.push(p);this.path.add(p);}
  }
  setZoom(zoom){
    if(this.lastZoom===zoom)return;this.lastZoom=zoom;
    const tangent=Math.tan(zoom*Math.PI/360),length=Math.min(1.8,1.8/Math.max(.001,tangent)),x=tangent*length,y=x*9/16,z=-length;
    const c=[[-x,-y,z],[x,-y,z],[x,y,z],[-x,y,z]],positions=[];
    for(let i=0;i<4;i++)positions.push(0,0,0,...c[i],...c[i],...c[(i+1)%4]);
    this.cone.geometry.attributes.position.array.set(positions);this.cone.geometry.attributes.position.needsUpdate=true;this.cone.geometry.computeBoundingSphere();
  }
  update(shot,observer,width,height,time,zoom){
    observer.updateMatrixWorld();
    const perPixel=p=>{const depth=-p.clone().applyMatrix4(observer.matrixWorldInverse).z;return Math.max(observer.near,depth)*2*Math.tan(observer.fov*Math.PI/360)/height;};
    this.glyph.position.copy(shot.position);this.glyph.quaternion.copy(shot.quaternion);this.glyph.scale.setScalar(perPixel(shot.position)*14);this.setZoom(zoom);
    const clip=shot.position.clone().project(observer);this.glyph.visible=clip.z>=-1&&clip.z<=1;
    for(const p of this.markers)p.scale.setScalar(perPixel(p.position)*3.5);
    for(const line of this.lines)line.material.resolution.set(width,height);
    if(this.progress){let lo=0,hi=this.samples.length;while(lo<hi){const m=(lo+hi)>>1;if(this.samples[m].time_sec<=time)lo=m+1;else hi=m;}this.progress.geometry.instanceCount=Math.max(0,lo-1);}
    return {visible:this.glyph.visible&&Math.abs(clip.x)<.95&&Math.abs(clip.y)<.95,x:(clip.x+1)*width/2,y:(1-clip.y)*height/2};
  }
  diagnostics(){return {cameraStyle:'compact-body-and-short-frustum',pathWidth:2.2,outlineWidth:5,glyphScale:this.glyph.scale.x,visible:this.root.visible,pathVisible:this.path.visible,progressSegments:this.progress?.geometry.instanceCount||0};}
}
