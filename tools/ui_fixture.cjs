// Metadata-only replay fixtures cannot build a 3D scene. Use the normal
// failure-page entry button; production replay rendering has its own acceptance.
exports.enterFixture=async page=>{
 await page.waitForFunction(()=>document.body.dataset.appReady==='true'||(
  state.loaded&&startupSamples.ready&&replayPreviewPane?.status==='error'&&
  document.getElementById('appSplash').dataset.failed==='true'&&!document.getElementById('startupContinue').hidden));
 if(await page.evaluate(()=>document.body.dataset.appReady!=='true'))await page.locator('#startupContinue').click();
 await page.waitForFunction(()=>document.body.dataset.appReady==='true'&&!pendingEditorRestore);
};

// Seed a curve for interaction tests without depending on a production shortcut.
exports.setSpeedCurveFixture=async page=>page.evaluate(()=>sequenceEditor.changeSpeed({
 ...sequenceEditor.data().speed,mode:'curve',time_range:null,
 keyframes:[{progress:0,rate:1},{progress:.25,rate:.25},{progress:.75,rate:.25},{progress:1,rate:1}],
}));
