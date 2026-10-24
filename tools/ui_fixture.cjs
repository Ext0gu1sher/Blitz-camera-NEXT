// Metadata-only replay fixtures cannot build a 3D scene. Use the normal
// failure-page entry button; production replay rendering has its own acceptance.
exports.enterFixture=async page=>{
 await page.waitForFunction(()=>document.body.dataset.appReady==='true'||(
  state.loaded&&startupSamples.ready&&replayPreviewPane?.status==='error'&&
  document.getElementById('appSplash').dataset.failed==='true'&&!document.getElementById('startupContinue').hidden));
 if(await page.evaluate(()=>document.body.dataset.appReady!=='true'))await page.locator('#startupContinue').click();
 await page.waitForFunction(()=>document.body.dataset.appReady==='true'&&!pendingEditorRestore);
};
