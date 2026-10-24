// Per-segment cubic-bezier easing. Mirrors channels.ScalarTrack exactly; the
// Python implementation and this module must stay numerically identical.
export function bezierXY(s,[x1,y1,x2,y2]){
  const m=1-s;
  return [3*m*m*s*x1+3*m*s*s*x2+s*s*s,3*m*m*s*y1+3*m*s*s*y2+s*s*s];
}

export function bezierEase(u, ctrl){
  const [x1,y1,x2,y2]=ctrl;
  const bez=(t,p1,p2)=>{const m=1-t;return 3*m*m*t*p1+3*m*t*t*p2+t*t*t;};
  const dbez=(t,p1,p2)=>{const m=1-t;return 3*m*m*p1+6*m*t*(p2-p1)+3*t*t*(1-p2);};
  let s=u;
  for(let i=0;i<8;i++){
    const err=bez(s,x1,x2)-u;
    if(Math.abs(err)<=1e-6)break;
    const d=dbez(s,x1,x2);
    if(Math.abs(d)<1e-9)break;
    s-=err/d;
  }
  if(Math.abs(bez(s,x1,x2)-u)>1e-9){
    let lo=0,hi=1;s=u;
    for(let i=0;i<60;i++){
      const err=bez(s,x1,x2)-u;
      if(Math.abs(err)<=1e-9)break;
      if(err<0)lo=s;else hi=s;
      s=(lo+hi)/2;
    }
  }
  return bez(s,y1,y2);
}

function monotoneTangents(rows){
  const times=rows.map(k=>k.time_sec),v=rows.map(k=>k.value),n=v.length;
  const h=times.slice(1).map((t,i)=>t-times[i]),d=h.map((s,i)=>(v[i+1]-v[i])/s);
  const endpoint=(h0,h1,d0,d1)=>{let m=((2*h0+h1)*d0-h0*d1)/(h0+h1);if(m*d0<=0)return 0;if(d0*d1<=0&&Math.abs(m)>3*Math.abs(d0))return 3*d0;return m;};
  const m=n===1?[0]:n===2?[d[0],d[0]]:[endpoint(h[0],h[1],d[0],d[1])];
  if(n>2){for(let i=1;i<n-1;i++){const a=d[i-1],b=d[i],w1=2*h[i]+h[i-1],w2=h[i]+2*h[i-1];m.push(a*b<=0?0:(w1+w2)/(w1/a+w2/b));}m.push(endpoint(h.at(-1),h.at(-2),d.at(-1),d.at(-2)));}
  return {times,v,n,h,d,m};
}

function bezierSlope([x1,y1,x2,y2],end=false){
  if(end)[x1,y1,x2,y2]=[1-x2,1-y2,1-x1,1-y1];
  if(x1>0)return y1/x1;if(y1>0)return Infinity;if(x2>0)return y2/x2;
  return y2>0?Infinity:1;
}

// Mirrors ScalarTrack._automatic_curves. Shared slopes are in value/second,
// so unequal key spacing and independently keyed rotation/FOV stay continuous.
export function automaticCurves(rows,smooth=false,easing='linear',math=null){
  if(!rows?.length)return [];
  const {n,d,m}=math||monotoneTangents(rows),active=rows.slice(0,-1).map(k=>k.curve==='auto');
  const curves=Array(n-1).fill(null);if(!active.some(Boolean))return curves;
  const controls=rows.slice(0,-1).map(k=>k.ease||[1/3,0,2/3,1]),slopes=[...m];
  const legacySlope=(i,end)=>Array.isArray(rows[i].ease)?d[i]*bezierSlope(rows[i].ease,end)
    :(smooth?m[i+Number(end)]:d[i])*({linear:[1,1],ease_in:[0,2],ease_out:[2,0],ease_in_out:[0,0]}[easing]||[1,1])[Number(end)];
  for(let k=0;k<n;k++){
    const left=k>0&&active[k-1],right=k<n-1&&active[k];if(left===right)continue;
    const segment=left?k-1:k,end=!!left,neighbor=left?k:k-1;
    const velocity=neighbor>=0&&neighbor<n-1?legacySlope(neighbor,!end):d[segment]*Math.min(3,bezierSlope(controls[segment],end));
    slopes[k]=Number.isFinite(velocity)&&velocity*d[segment]>=0?velocity:0;
  }
  for(let i=0;i<n-1;i++){
    if(!active[i])continue;
    const [x1,,x2]=controls[i];let left=x1>0?x1:1/3,right=x2<1?1-x2:1/3;
    const a=d[i]?slopes[i]/d[i]:0,b=d[i]?slopes[i+1]/d[i]:0;
    if(a>0)left=Math.min(left,1/a);if(b>0)right=Math.min(right,1/b);
    curves[i]=[left,Math.min(1,left*a),1-right,Math.max(0,1-right*b)];
  }
  return curves;
}

export function applyCurveTemplate(targets,ctrl,continuous=true){
  for(const key of targets){
    if(ctrl)key.ease=[...ctrl];else delete key.ease;
    if(continuous)key.curve='auto';else delete key.curve;
  }
}

function guideSample(u,[x1,y1,x2,y2]){
  const bez=(s,a,b)=>3*(1-s)**2*s*a+3*(1-s)*s*s*b+s*s*s;
  if(u<=0)return [0,y1/x1];if(u>=1)return [1,(1-y2)/(1-x2)];
  let lo=0,hi=1;
  for(let i=0;i<48;i++){const s=(lo+hi)/2;if(bez(s,x1,x2)<u)lo=s;else hi=s;}
  const s=(lo+hi)/2,derivative=(a,b)=>3*(1-s)**2*a+6*(1-s)*s*(b-a)+3*s*s*(1-b),dx=derivative(x1,x2);
  return [bez(s,y1,y2),dx>1e-12?derivative(y1,y2)/dx:0];
}

// Physical acceleration solve: mirrors camera_smoothing._accelerations.
// Ordered quintic controls bound the entire curve, including between samples.
function smoothAccelerations(h,delta,velocity){
  const n=velocity.length,diag=Array(n).fill(0),rhs=Array(n).fill(0),off=Array(n-1).fill(0);
  const lower=Array(n).fill(-Infinity),upper=Array(n).fill(Infinity),signs=[],limits=[];
  for(let i=0;i<n-1;i++){
    const span=h[i],v0=velocity[i],v1=velocity[i+1];
    diag[i]+=9/span;diag[i+1]+=9/span;off[i]=-3/span;
    rhs[i]+=(60*delta[i]-span*(36*v0+24*v1))/span**3;
    rhs[i+1]+=(-60*delta[i]+span*(24*v0+36*v1))/span**3;
    const sign=delta[i]>=0?1:-1;signs.push(sign);
    limits.push(Math.max(0,20*Math.abs(delta[i])/span**2-8*sign*(v0+v1)/span));
    if(sign>0){lower[i]=Math.max(lower[i],-4*v0/span);upper[i+1]=Math.min(upper[i+1],4*v1/span);}
    else{upper[i]=Math.min(upper[i],-4*v0/span);lower[i+1]=Math.max(lower[i+1],4*v1/span);}
    if(delta[i]===0)lower[i]=upper[i]=lower[i+1]=upper[i+1]=0;
  }
  lower[0]=upper[0]=lower[n-1]=upper[n-1]=0;
  const a=[0,...off],b=[...diag],c=[...off,0],target=[...rhs];
  for(let i=0;i<n;i++)if(lower[i]===0&&upper[i]===0){a[i]=c[i]=target[i]=0;b[i]=1;}
  for(let i=1;i<n;i++){const factor=a[i]/b[i-1];b[i]-=factor*c[i-1];target[i]-=factor*target[i-1];}
  target[n-1]/=b[n-1];
  for(let i=n-2;i>=0;i--)target[i]=(target[i]-c[i]*target[i+1])/b[i];
  let scale=1;
  for(let i=0;i<n;i++){
    if(target[i]>upper[i])scale=Math.min(scale,upper[i]/target[i]);
    if(target[i]<lower[i])scale=Math.min(scale,lower[i]/target[i]);
  }
  for(let i=0;i<n-1;i++){const difference=signs[i]*(target[i]-target[i+1]);if(difference>limits[i])scale=Math.min(scale,limits[i]/difference);}
  const result=target.map(value=>value*Math.max(0,scale));
  for(let sweep=0;sweep<64;sweep++){
    let change=0;
    for(let step=1;step<n-1;step++){
      const i=sweep%2===0?step:n-1-step;let lo=lower[i],hi=upper[i];
      if(signs[i-1]>0)lo=Math.max(lo,result[i-1]-limits[i-1]);else hi=Math.min(hi,result[i-1]+limits[i-1]);
      if(signs[i]>0)hi=Math.min(hi,result[i+1]+limits[i]);else lo=Math.max(lo,result[i+1]-limits[i]);
      let value=(rhs[i]-off[i-1]*result[i-1]-off[i]*result[i+1])/diag[i];
      value=Math.max(lo,Math.min(hi,value));change=Math.max(change,Math.abs(value-result[i])/(1+Math.abs(value)));result[i]=value;
    }
    if(change<1e-10)break;
  }
  return result;
}

// C2 interpolation for consecutive automatic spans. Template samples are
// internal guides only: authored timestamps/values and serialized data stay put.
export function cameraSmoothCurves(rows,guides){
  const result=Array(guides.length).fill(null);
  let start=0;
  while(start<guides.length){
    if(!guides[start]){start++;continue;}
    let end=start+1;while(end<guides.length&&guides[end])end++;
    const times=[],values=[],velocity=[],owners=[];
    for(let i=start;i<end;i++){
      const t0=rows[i].time_sec,t1=rows[i+1].time_sec,p0=rows[i].value,p1=rows[i+1].value,steps=rows[i].ease?4:1;
      for(let j=0;j<=steps;j++){
        if(j===0&&times.length)continue;
        const u=j/steps,[y,slope]=guideSample(u,guides[i]);
        times.push(j===steps?t1:t0+(t1-t0)*u);values.push(j===steps?p1:p0+(p1-p0)*y);velocity.push((p1-p0)/(t1-t0)*slope);
        if(times.length>1)owners.push(i);
      }
    }
    const h=times.slice(1).map((t,i)=>t-times[i]),delta=values.slice(1).map((v,i)=>v-values[i]);
    for(let i=0;i<h.length;i++){
      if(delta[i]===0){velocity[i]=velocity[i+1]=0;continue;}
      const sign=delta[i]>0?1:-1;
      velocity[i]=sign*Math.max(0,sign*velocity[i]);velocity[i+1]=sign*Math.max(0,sign*velocity[i+1]);
      const total=Math.abs(velocity[i])+Math.abs(velocity[i+1]),cap=2.5*Math.abs(delta[i])/h[i];
      if(total>cap){const factor=cap/total;velocity[i]*=factor;velocity[i+1]*=factor;}
    }
    const acceleration=smoothAccelerations(h,delta,velocity);
    owners.forEach((i,j)=>{
      const span=h[j],dp=delta[j],v0=velocity[j]*span,v1=velocity[j+1]*span,a0=acceleration[j]*span**2,a1=acceleration[j+1]*span**2;
      const controls=[0,v0/5,2*v0/5+a0/20,dp-2*v1/5+a1/20,dp-v1/5,dp];
      (result[i]??=[]).push([times[j],span,values[j],controls]);
    });
    start=end;
  }
  return result;
}

export function sampleSmoothCurve(pieces,time){
  let piece=pieces[0];for(const candidate of pieces.slice(1)){if(time<candidate[0])break;piece=candidate;}
  const [start,span,value,b]=piece,u=Math.max(0,Math.min(1,(time-start)/span)),m=1-u;
  return value+5*m**4*u*b[1]+10*m**3*u*u*b[2]+10*m*m*u**3*b[3]+5*m*u**4*b[4]+u**5*b[5];
}

export function scalarTrack(rows,smooth=false,easing='linear'){
  if(!rows?.length)return ()=>NaN;
  const math=monotoneTangents(rows),{times,v,n,h,m}=math,curves=cameraSmoothCurves(rows,automaticCurves(rows,smooth,easing,math));
  return t=>{
    if(t<=times[0]||n===1)return v[0];if(t>=times.at(-1))return v.at(-1);
    let lo=0,hi=n-1;while(hi-lo>1){const k=(lo+hi)>>1;if(times[k]<=t)lo=k;else hi=k;}
    const a=rows[lo];
    let u=(t-times[lo])/h[lo];
    if(curves[lo])return sampleSmoothCurve(curves[lo],t);
    if(Array.isArray(a.ease))return v[lo]+(v[lo+1]-v[lo])*bezierEase(u,a.ease);
    if(easing==='ease_in')u=u*u;else if(easing==='ease_out')u=1-(1-u)**2;else if(easing==='ease_in_out')u=u*u*(3-2*u);
    return smooth?(2*u**3-3*u*u+1)*v[lo]+(u**3-2*u*u+u)*m[lo]*h[lo]+(-2*u**3+3*u*u)*v[lo+1]+(u**3-u*u)*m[lo+1]*h[lo]:v[lo]+(v[lo+1]-v[lo])*u;
  };
}
