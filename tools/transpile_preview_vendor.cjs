const fs=require('node:fs');const ts=require('../research/source/typescript-5.9.3.cjs');
const src='research/source/WotbTools/frontend/src/';
for(const [source,dest] of [['replay-local/pose/vehiclePose.ts','vehiclePose.js'],['replay-local/canonical/facts.ts','facts.js'],['replay-local/canonical/hpRawState.ts','hpRawState.js'],['utils/battlePlaybackV2.ts','battlePlaybackV2.js']]){
 let input=fs.readFileSync(src+source,'utf8');let result=ts.transpileModule(input,{compilerOptions:{target:ts.ScriptTarget.ES2020,module:ts.ModuleKind.ES2020}}).outputText;
 result=result.replaceAll('../../scene/trackInterp.js','./trackInterp.js').replaceAll('../canonical/facts.js','./facts.js');
 fs.writeFileSync('blitzcam/web/vendor/wotbtools/'+dest,result);
}
for(const file of ['battleFx.js','shotPath.js','impactKind.js','tankDestroyedVisual.js']){
 const input=fs.readFileSync(src+'scene/'+file,'utf8').replaceAll("from 'three'","from '../three/build/three.module.js'");
 fs.writeFileSync('blitzcam/web/vendor/wotbtools/'+file,input);
}
