// Isolated disk-only decode using the workstation's pinned replay parser.
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const [configPath] = process.argv.slice(2);
const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
const engine = path.resolve('blitzcam/web/vendor/agent');
const wasm = await import(pathToFileURL(path.join(engine, 'wotb_replay_wasm.js')));
wasm.initSync({module: fs.readFileSync(path.join(engine, 'wotb_replay_wasm_bg.wasm'))});
for (const input of config.inputs) {
  const bytes = fs.readFileSync(input.path);
  const playback = JSON.parse(wasm.parsePlayback(bytes));
  const result = JSON.parse(wasm.parseResult(bytes));
  const ai = JSON.parse(wasm.parseAiReview(bytes));
  for (const [name, data] of Object.entries({playback, result, ai})) {
    fs.writeFileSync(path.join(config.output, `${input.label}-${name}.json`), JSON.stringify(data));
  }
  console.log(JSON.stringify({label: input.label, meta: playback.meta,
    vehicleCount: playback.vehicles.length, vehicleKeys: Object.keys(playback.vehicles[0] ?? {}),
    firstVehicle: playback.vehicles[0] ? Object.fromEntries(Object.entries(playback.vehicles[0]).map(([k,v]) =>
      [k, Array.isArray(v) ? {count: v.length, first: v.slice(0,4)} : typeof v === 'object' && v !== null ? {keys: Object.keys(v)} : v])) : null,
    aiKeys: Object.keys(ai), resultKeys: Object.keys(result)}));
}
