const {chromium}=require('playwright');
const {enterFixture}=require('./ui_fixture.cjs');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');

(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const page=await browser.newPage({viewport:{width:1200,height:800}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/preview/select',r=>r.fulfill({status:400,json:{error:'合成资源生命周期测试'}}));
  try{
    await page.goto(process.argv[2]);await enterFixture(page);
    const result=await page.evaluate(async()=>{
      const T=await import('/vendor/three/build/three.module.js'),p=replayPreviewPane;
      p.initRenderer();p.resetScene();p.active=true;
      const gl=p.renderer.getContext(),buffers=new Set();
      const create=gl.createBuffer.bind(gl),remove=gl.deleteBuffer.bind(gl);
      gl.createBuffer=()=>{const b=create();buffers.add(b);return b;};
      gl.deleteBuffer=b=>{buffers.delete(b);return remove(b);};
      const readings=[];
      for(let cycle=0;cycle<12;cycle++){
        const bitmap=await createImageBitmap(new ImageData(32,32));
        const texture=new T.Texture(bitmap);texture.needsUpdate=true;
        const material=new T.MeshBasicMaterial({map:texture});
        const mesh=new T.InstancedMesh(new T.BoxGeometry(2,2,2),material,8);
        for(let i=0;i<8;i++)mesh.setMatrixAt(i,new T.Matrix4().makeTranslation(i*3,0,0));
        mesh.frustumCulled=false;p.assetsGroup.add(mesh);
        p.render();const allocated=buffers.size;
        p.resetScene();
        readings.push({cycle,allocated,buffers:buffers.size,bitmapWidth:bitmap.width,geometries:p.renderer.info.memory.geometries,textures:p.renderer.info.memory.textures});
      }
      gl.createBuffer=create;gl.deleteBuffer=remove;
      return {readings};
    });
    if(!process.env.BLITZ_RESOURCE_BASELINE){
      result.interrupted=await page.evaluate(async()=>{
        const T=await import('/vendor/three/build/three.module.js');
        const {GLTFLoader}=await import('/vendor/three/examples/jsm/loaders/GLTFLoader.js');
        const p=replayPreviewPane,original=GLTFLoader.prototype.loadAsync,readings=[];
        const scene=async()=>{
          const bitmap=await createImageBitmap(new ImageData(32,32)),tex=new T.Texture(bitmap);
          const root=new T.Group(),mesh=new T.Mesh(new T.BoxGeometry(),new T.MeshBasicMaterial({map:tex}));root.add(mesh);
          const disposed={geometry:0,material:0,texture:0};
          mesh.geometry.addEventListener('dispose',()=>disposed.geometry++);mesh.material.addEventListener('dispose',()=>disposed.material++);tex.addEventListener('dispose',()=>disposed.texture++);
          return {bitmap,root,mesh,disposed};
        };
        try{
          // Clear while the GLB is still loading; late completion must not
          // resurrect its scene or retain its decoded images.
          const pending=await scene();let finish;
          GLTFLoader.prototype.loadAsync=()=>new Promise(resolve=>finish=resolve);
          const load=p.loadScene({urls:{scenery:'delayed'}},p.generation);
          p.clear();finish({scene:pending.root});await load;
          readings.push({kind:'cancelled',width:pending.bitmap.width,...pending.disposed,children:p.assetsGroup.children.length});
          // Variant rejection removes a node from the scene before throwing.
          // It still belongs to the failed load and must be released.
          const failed=await scene();failed.mesh.userData.mdVariant='unknown';
          GLTFLoader.prototype.loadAsync=async()=>({scene:failed.root});
          p.data={playback:{meta:{map_id:21}}};let error='';
          try{await p.loadScene({urls:{scenery:'invalid'}},p.generation);}catch(e){error=e.message;}
          readings.push({kind:'failed',width:failed.bitmap.width,...failed.disposed,children:p.assetsGroup.children.length,error});
          return readings;
        }finally{GLTFLoader.prototype.loadAsync=original;p.clear();}
      });
    }
    const out=path.resolve('output/preview-resource-acceptance');fs.mkdirSync(out,{recursive:true});
    fs.writeFileSync(path.join(out,process.env.BLITZ_RESOURCE_BASELINE?'baseline.json':'result.json'),JSON.stringify({...result,errors},null,2));
    console.log(JSON.stringify(result));
    if(!process.env.BLITZ_RESOURCE_BASELINE){
      for(const row of result.readings){assert.equal(row.buffers,0,'scene reset leaked WebGL buffers');assert.equal(row.bitmapWidth,0,'scene reset retained an ImageBitmap');}
      for(const row of result.interrupted){assert.equal(row.width,0);assert.equal(row.geometry,1);assert.equal(row.material,1);assert.equal(row.texture,1);assert.equal(row.children,0);}
      assert.match(result.interrupted[1].error,/变体映射/);
      assert.deepEqual(errors,[]);
    }
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
