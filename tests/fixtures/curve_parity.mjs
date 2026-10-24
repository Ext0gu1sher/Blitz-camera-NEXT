import {readFileSync} from 'node:fs';
import {scalarTrack} from '../../blitzcam/web/curve-core.js';
const cases=JSON.parse(readFileSync(0,'utf8'));
const out=cases.map(c=>{const f=scalarTrack(c.rows,c.smooth,c.easing);return c.times.map(t=>f(t));});
process.stdout.write(JSON.stringify(out));
