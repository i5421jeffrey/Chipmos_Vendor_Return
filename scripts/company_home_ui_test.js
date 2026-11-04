// Minimal homepage DOM, independent from the repair workspace test doubles.
const homeNodes = Object.fromEntries(homeIds.map(id => [id,{textContent:'',disabled:false,dataset:{},listeners:{},addEventListener(name,handler){this.listeners[name]=handler;}}]));
const document = {getElementById(id){if (!homeNodes[id]) throw Error('Missing homepage element: '+id); return homeNodes[id];}};
const AbortSignal = {timeout(){return {};}};
let homeMode='ok', homeRequests=0;
async function fetch(path) {
  if (path!=='/api/health') throw Error('Unexpected homepage request');
  homeRequests++;
  if (homeMode==='offline') throw Error('network detail not for display');
  return {ok:homeMode!=='error',json:async()=>{
    if (homeMode==='invalid') throw Error('invalid JSON');
    return {status:homeMode==='ok'?'ok':'error',database:'SQLite',sqlite_version:'internal-version',initialized_at:'internal-time',modules:{repairs:2}};
  }};
}
function homeAssert(value,message){if(!value) throw Error(message);}
// TESTS
(async()=>{
  for(let i=0;i<8;i++) await Promise.resolve();
  homeAssert(homeNodes.status.textContent==='連線正常。' && homeNodes.status.dataset.state==='ok','Homepage status loads without removed diagnostic elements');
  for(const mode of ['offline','error','invalid']) {
    homeMode=mode; const before=homeRequests;
    await homeNodes.refresh.listeners.click();
    homeAssert(homeNodes.status.textContent==='暫時無法連線，請稍後重新檢查。' && homeNodes.status.dataset.state==='error','Homepage failure stays user-friendly');
    homeAssert(homeRequests===before+1 && !homeNodes.refresh.disabled,'Failure does not auto-retry or leave refresh disabled');
  }
  homeMode='ok'; await homeNodes.refresh.listeners.click();
  homeAssert(homeNodes.status.dataset.state==='ok','Homepage recovers after retry');
  homeAssert(!/SQLite|Python|本機|公司版|移植|離線|驗收|internal-/.test(Object.values(homeNodes).map(node=>node.textContent).join('')),'Homepage never renders technical health metadata');
  globalThis.companyUiDone=true;
})().catch(error=>{globalThis.companyUiFailure=String(error)+'\n'+(error.stack||'');});
