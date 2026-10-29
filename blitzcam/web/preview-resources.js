// A load owns its resources even before they enter the visible scene. Late
// asynchronous results are released immediately after that load is cancelled.
export class PreviewResources {
  constructor(){
    this.resources=new Set();this.images=new Set();this.released=new WeakSet();this.closed=false;
  }
  own(resource){
    if(!resource||typeof resource.dispose!=='function'||this.released.has(resource))return resource;
    if(this.closed){this.released.add(resource);resource.dispose();}
    else this.resources.add(resource);
    return resource;
  }
  texture(value){
    if(Array.isArray(value)){value.forEach(v=>this.texture(v));return value;}
    if(!value?.isTexture)return value;
    this.own(value);
    for(const image of [value.source?.data??value.image].flat()){
      if(!image||typeof image.close!=='function'||this.released.has(image))continue;
      if(this.closed){this.released.add(image);image.close();}
      else this.images.add(image);
    }
    return value;
  }
  track(root){
    root?.traverse(n=>{
      // InstancedMesh owns GPU buffers independently of its geometry.
      if(n.isInstancedMesh)this.own(n);
      this.own(n.geometry);
      for(const material of [n.material].flat()){
        if(!material)continue;
        this.own(material);
        Object.values(material).forEach(v=>this.texture(v));
        Object.values(material.uniforms||{}).forEach(u=>this.texture(u.value));
      }
    });
    return root;
  }
  dispose(){
    if(this.closed)return;
    this.closed=true;
    for(const resource of this.resources){this.released.add(resource);resource.dispose();}
    // Texture.dispose releases the GPU texture, not its decoded ImageBitmap.
    // Shared images must stay alive until every material in this load is done.
    for(const image of this.images){this.released.add(image);image.close();}
    this.resources.clear();this.images.clear();
  }
}
