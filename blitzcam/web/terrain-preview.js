/* Asset terrain for offline previews only; never reads or controls a game camera. */
(function(root,factory){const value=factory();if(typeof module!=="undefined"&&module.exports)module.exports=value;else root.BlitzTerrain=value;})(typeof globalThis!=="undefined"?globalThis:this,function(){
  "use strict";
  class Mesh{
    constructor(data){
      const n=data.size,lo=data.bounds?.min,hi=data.bounds?.max;
      if(!Number.isInteger(n)||n<2||n>129||!Array.isArray(lo)||!Array.isArray(hi)||lo.length!==3||hi.length!==3||![...lo,...hi].every(Number.isFinite)||lo.some((v,i)=>v>=hi[i])||!Array.isArray(data.rows)||data.rows.length!==n||data.rows.some(r=>!Array.isArray(r)||r.length!==n||r.some(z=>!Number.isFinite(z)||z<lo[2]||z>hi[2])))throw new Error("地形数据格式无效。");
      this.data=data;this.n=n;this.lo=lo;this.hi=hi;this.points=[];this.faces=[];this.layer=null;this.layerKey="";
      const colors=data.colors;
      if(colors&&(!Array.isArray(colors)||colors.length!==n||colors.some(row=>!Array.isArray(row)||row.length!==n||row.some(c=>!Array.isArray(c)||c.length!==3||c.some(v=>!Number.isInteger(v)||v<0||v>255)))))throw new Error("地图颜色数据无效。");
      this.ready=Promise.resolve();this.mapImage=null;
      if(data.map_image){
        if(typeof data.map_image!=="string"||!data.map_image.startsWith("data:image/webp;base64,")||data.map_image.length>1000000)throw new Error("地图底图格式无效。");
        this.ready=new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>{this.mapImage=image;this.layerKey="";resolve();};image.onerror=()=>reject(new Error("地图底图读取失败。"));image.src=data.map_image;});
      }
      for(let y=0;y<n;y++)for(let x=0;x<n;x++)this.points.push([lo[0]+x/(n-1)*(hi[0]-lo[0]),lo[1]+y/(n-1)*(hi[1]-lo[1]),data.rows[y][x]]);
      for(let y=0;y<n-1;y++)for(let x=0;x<n-1;x++){
        const a=y*n+x,b=a+1,c=a+n,d=c+1;
        for(const ids of[[a,b,c],[b,d,c]]){
          const [p,q,r]=ids.map(i=>this.points[i]),u=q.map((v,i)=>v-p[i]),v=r.map((v,i)=>v-p[i]);
          const normal=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]],len=Math.hypot(...normal);
          const light=Math.max(0,(normal[0]*.35-normal[1]*.45+normal[2]*.82)/len),height=(p[2]+q[2]+r[2])/3;
          const tone=.55+.65*light,alt=(height-lo[2])/(hi[2]-lo[2]);
          const rgb=colors?ids.map(i=>colors[Math.floor(i/n)][i%n]).reduce((sum,c)=>sum.map((v,k)=>v+c[k]/3),[0,0,0]).map(v=>Math.round(v*(.8+.2*light))):[Math.round((64+alt*25)*tone),Math.round((83+alt*21)*tone),Math.round((70+alt*17)*tone)];
          this.faces.push({ids,center:p.map((z,i)=>(z+q[i]+r[i])/3),color:`rgb(${rgb.join(",")})`});
        }
      }
    }
    heightAt(x,y){
      if(x<this.lo[0]||x>this.hi[0]||y<this.lo[1]||y>this.hi[1])return null;
      const n=this.n,gx=(x-this.lo[0])/(this.hi[0]-this.lo[0])*(n-1),gy=(y-this.lo[1])/(this.hi[1]-this.lo[1])*(n-1),ix=Math.min(n-2,Math.floor(gx)),iy=Math.min(n-2,Math.floor(gy)),a=gx-ix,b=gy-iy,r=this.data.rows;
      return (1-b)*((1-a)*r[iy][ix]+a*r[iy][ix+1])+b*((1-a)*r[iy+1][ix]+a*r[iy+1][ix+1]);
    }
    draw(ctx,project,depth,view="3d"){
      // The terrain is static while a path plays; cache its raster until the view changes.
      const matrix=ctx.getTransform(),key=JSON.stringify([ctx.canvas.width,ctx.canvas.height,matrix.a,matrix.d,...[[0,0,0],[1,0,0],[0,1,0],[0,0,1]].map(project)]);
      if(key!==this.layerKey){
        const layer=document.createElement("canvas");layer.width=ctx.canvas.width;layer.height=ctx.canvas.height;const g=layer.getContext("2d");g.setTransform(matrix);
        if(this.mapImage&&(view==="map"||view==="xy")){
          const a=project([this.lo[0],this.lo[1],0]),b=project([this.hi[0],this.lo[1],0]),c=project([this.lo[0],this.hi[1],0]),im=this.mapImage;
          g.save();g.transform((b[0]-a[0])/im.width,(b[1]-a[1])/im.width,(c[0]-a[0])/im.height,(c[1]-a[1])/im.height,...a);g.drawImage(im,0,0);g.restore();
        }else{
        const screen=this.points.map(project),faces=[...this.faces].sort((a,b)=>depth(a.center)-depth(b.center));
        for(const f of faces){const [a,b,c]=f.ids.map(i=>screen[i]);if(Math.max(a[0],b[0],c[0])<0||Math.min(a[0],b[0],c[0])>layer.width/matrix.a||Math.max(a[1],b[1],c[1])<0||Math.min(a[1],b[1],c[1])>layer.height/matrix.d)continue;g.beginPath();g.moveTo(...a);g.lineTo(...b);g.lineTo(...c);g.closePath();g.fillStyle=g.strokeStyle=f.color;g.lineWidth=.6;g.fill();g.stroke();}
        g.strokeStyle="#b2c8ae24";g.lineWidth=.6;
        for(let i=0;i<this.n;i+=4)for(const vertical of[false,true]){g.beginPath();for(let j=0;j<this.n;j++){const p=screen[vertical?j*this.n+i:i*this.n+j];if(j)g.lineTo(...p);else g.moveTo(...p);}g.stroke();}
        }
        this.layer=layer;this.layerKey=key;
      }
      ctx.save();ctx.setTransform(1,0,0,1,0,0);ctx.drawImage(this.layer,0,0);ctx.restore();
    }
  }
  function bind(select,status,onChange){
    let sequence=0,identity=null,lastKey="";
    async function load(){
      const current=++sequence;onChange(null);status.classList.remove("error");
      if(!select.value){status.textContent="辅助网格 · 不含地图";return;}
      const automatic=select.value==="auto",map=automatic?identity?.map_id:select.value;
      if(!map){status.textContent=identity?.message||"连接回放后自动识别地图";return;}
      if(!automatic&&identity?.map_id&&identity.map_id!==map){status.textContent="所选地图与当前回放不同，请使用自动识别。";status.classList.add("error");return;}
      status.textContent="读取地图资源…首次转换可能需要几秒";
      try{
        const response=await fetch("/api/terrain/"+encodeURIComponent(map)),data=await response.json();
        if(!response.ok)throw new Error(data.error||"地形读取失败。");
        const mesh=new Mesh(data);await mesh.ready;if(current!==sequence)return;
        onChange(mesh);status.textContent=`${data.label||map} · ${automatic?(identity.state==="matched"?"回放与场景一致":"按当前场景识别"):"手动预览"} · 地图底图＋地形`;
        status.title=(identity?.replay_file||"")+"\n"+(identity?.message||"")+"\n底图含建筑图像，不含建筑三维模型；仍需画面地标核对精度。";
      }catch(error){if(current!==sequence)return;status.textContent=error.message;status.classList.add("error");status.title=error.message;}
    }
    select.addEventListener("change",load);
    return {update(value){const key=JSON.stringify([value?.state,value?.map_id,value?.replay_file,value?.message]);identity=value;if(key===lastKey)return;lastKey=key;if(select.value==="auto")load();}};
  }
  return {Mesh,bind};
});
