// Replay-clock schedule for the WotbTools battleFx renderer. Pure and seekable:
// a paused frame, a direct seek and sequential playback produce the same events.
import {pathPointsOf,legSecsOf,legEndTimes,legArcEnds} from './vendor/wotbtools/shotPath.js';
import {impactKind} from './vendor/wotbtools/impactKind.js';
import {defLifeAt} from './vendor/wotbtools/battlePlaybackV2.js';

const finite3=a=>Array.isArray(a)&&a.length===3&&a.every(Number.isFinite);
const scene=p=>[-p[0],p[1],p[2]]; // Packet coordinates use Y-up; editor cameras use Z-up.
const upper=(rows,t,key)=>{let lo=0,hi=rows.length;while(lo<hi){const m=(lo+hi)>>>1;if(key(rows[m])<=t)lo=m+1;else hi=m;}return lo;};
export const EFFECT_LIFE={muzzle:1.8,impact:1.95,burst:4.2,trail:4};
export const teamShotColor=(team,friendly)=>(team===1||team===2)&&(friendly===1||friendly===2)?(team===friendly?0x3ee08a:0xff5a45):0xf5f5f5;

export function createBattleTimeline(playback){
  const vehicles=new Map((playback.vehicles||[]).map(v=>[v.eid,v])),shots=[],events=[],deaths=[];
  let invalidShots=0,maxPathAge=EFFECT_LIFE.trail;
  for(const [index,shot] of (playback.shots||[]).entries()){
    if(!Number.isFinite(shot.t_fire)||shot.t_fire<0||!finite3(shot.from)||!finite3(shot.to)) {invalidShots++;continue;}
    const path=pathPointsOf(shot),legs=legSecsOf(shot,Math.max(1/60,Number.isFinite(shot.flight_secs)?shot.flight_secs:0));
    const duration=legs.reduce((a,b)=>a+b,0);
    if(!path.every(finite3)||!Number.isFinite(duration)||duration<=0||duration>120){invalidShots++;continue;}
    const points=path.map(scene),ends=legEndTimes(legs,shot.t_fire),arc=legArcEnds(points);
    if(!(arc.at(-1)>1e-4)){invalidShots++;continue;}
    const entry={id:index,seed:index+1,shot,points,ends,arc,start:shot.t_fire,end:ends.at(-1),
                 color:teamShotColor(vehicles.get(shot.shooter_eid)?.team,playback.meta?.friendly_team)};
    shots.push(entry);maxPathAge=Math.max(maxPathAge,duration+EFFECT_LIFE.trail);
    events.push({type:'muzzle',time:entry.start,entry});
    const kind=impactKind(shot);
    if(kind)events.push({type:'impact',kind,time:ends[0],entry});
  }
  for(const def of vehicles.values()){
    if(!Number.isFinite(def.death_t))continue;
    const times=[...new Set([def.death_t,...(def.death_times||[])].filter(t=>Number.isFinite(t)&&t>=0))].sort((a,b)=>a-b);
    for(const time of times){
      const life=defLifeAt(def,time);
      if(life?.lifeState!=='DESTROYED'||life.destroyedKnownAtSec!==time)continue;
      const event={type:'burst',time,eid:def.eid,seed:def.eid};deaths.push(event);events.push(event);
    }
  }
  shots.sort((a,b)=>a.start-b.start||a.id-b.id);events.sort((a,b)=>a.time-b.time);deaths.sort((a,b)=>a.time-b.time);
  return {shots,events,deaths,invalidShots,at(raw){
    if(!Number.isFinite(raw))return {events:[],paths:[]};
    const recent=events.slice(upper(events,raw-EFFECT_LIFE.burst,e=>e.time),upper(events,raw,e=>e.time))
      .filter(e=>raw-e.time<EFFECT_LIFE[e.type]);
    const paths=shots.slice(upper(shots,raw-maxPathAge,e=>e.start),upper(shots,raw,e=>e.start))
      .filter(s=>raw<s.end+EFFECT_LIFE.trail);
    return {events:recent,paths};
  }};
}
