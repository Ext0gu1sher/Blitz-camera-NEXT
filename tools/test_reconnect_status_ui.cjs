const {chromium}=require('playwright'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const out=path.resolve('output/reconnect-status-acceptance');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const page=await browser.newPage({viewport:{width:830,height:66}}),errors=[],checks=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(()=>{window.chrome.webview={postMessage:()=>{},addEventListener:()=>{}};});
 const healthy=()=>page.waitForFunction(()=>model.data?.connection.state==='connected'&&model.data?.replay_launch.state==='launched'&&!document.getElementById('statusLine').classList.contains('launch-error'));
 try{
  await page.goto(process.argv[2]+'/overlay?panel=connection');
  await page.waitForFunction(()=>document.getElementById('statusLine').textContent.includes('回放对象已改变'));
  assert.equal(await page.locator('#statusLine').evaluate(el=>el.classList.contains('launch-error')),true);
  await page.locator('#connectToggle').click();await healthy();
  assert.equal(await page.evaluate(()=>model.data.replay_launch.verified),true);
  assert.ok(!(await page.locator('#statusLine').textContent()).includes('已失去核对'));checks.push('successful source recheck clears stale invalidation text and red style');
  await page.locator('#connectToggle').click();await page.waitForFunction(()=>model.data?.connection.state==='disconnected');
  assert.equal(await page.locator('#statusLine').evaluate(el=>el.classList.contains('launch-error')),false);checks.push('manual disconnect does not resurrect old error');
  await page.locator('#connectToggle').click();await healthy();await page.waitForTimeout(1100);
  assert.equal(await page.evaluate(()=>model.data.replay_launch.verified),true);
  assert.ok(!(await page.locator('#statusLine').textContent()).includes('回放对象已改变'));checks.push('reconnect and subsequent polling retain healthy status');
  await page.screenshot({path:path.join(out,'reconnected.png'),omitBackground:true});
  assert.deepEqual(errors,[]);const result={passed:true,checks,errors};fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }catch(error){await page.screenshot({path:path.join(out,'failure.png')}).catch(()=>{});throw error;}
 finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
