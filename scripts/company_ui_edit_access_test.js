// Isolated access-mode behavior; no real browser or company password involved.
(async () => {
  for (let index=0; index<12; index++) await Promise.resolve();
  assert(!editToken && nodes.create.hidden && nodes['edit-detail'].hidden, 'Fresh page is readonly without persisted token');
  const before = requests.length;
  let denied=false;
  try {await api('/api/repairs/records','POST',{});} catch(error) {denied=error.message.includes('唯讀');}
  assert(denied && requests.length===before,'Readonly write is rejected before fetch');
  await openWorkspace('dbn');
  assert(nodes['workspace-actions'].children.every(button=>button.hidden),'Readonly workspace hides create buttons');
  await openDetail(testRecord.id);
  assert(nodes['record-detail'].open,'Readonly record detail stays available');
  const deletion=nodes['detail-content'].children.find(node=>node.textContent==='刪除此筆送修');
  assert(deletion.hidden,'Readonly detail hides delete');
  nodes['record-detail'].close();
  await nodes['toggle-edit'].listeners.click[0]();
  assert(nodes['edit-unlock'].open,'Unlock prompts for shared password');
  nodes['edit-password'].value='synthetic-only';
  await nodes['edit-unlock-form'].listeners.submit[0]({preventDefault(){}});
  assert(editToken && !nodes.create.hidden && !nodes['edit-unlock'].open && nodes['edit-password'].value==='','Unlock clears password and enables controls');
  assert(!nodes['workspace-actions'].children[0].hidden,'Already-rendered actions unlock too');
  await api('/api/repairs/dbn','POST',{});
  assert(requests.at(-1).options.headers['X-SPMS-Edit-Token']==='mock-edit-token','Mutations carry memory-only token');
  let release; gatePrefixes.set('/api/repairs/dbn',new Promise(resolve=>{release=resolve;}));
  const pending=api('/api/repairs/dbn','POST',{});
  await nodes['toggle-edit'].listeners.click[0]();
  assert(editToken && nodes['edit-access-message'].textContent.includes('正在處理'),'Cannot revoke a session in the middle of an in-flight write');
  gatePrefixes.clear(); release(); await pending;
  await nodes['toggle-edit'].listeners.click[0]();
  assert(!editToken && nodes.create.hidden && deletion.hidden,'Explicit lock clears token and hides write actions');
  assert(requests.at(-1).path==='/api/edit/lock','Explicit lock also revokes server token');
  await nodes['toggle-edit'].listeners.click[0](); nodes['edit-password'].value='synthetic-only';
  await nodes['edit-unlock-form'].listeners.submit[0]({preventDefault(){}});
  faultPrefixes.set('/api/repairs/records','UNAUTHORIZED');
  try {await api('/api/repairs/records','POST',{});} catch(error) {}
  assert(!editToken && nodes.create.hidden,'Expired server session returns page to readonly without retry');
  faultPrefixes.clear();
  nodes['failure-description'].value='unsaved preserved input';
  nodes['editor-unlock'].listeners.click[0](); nodes['edit-password'].value='synthetic-only';
  await nodes['edit-unlock-form'].listeners.submit[0]({preventDefault(){}});
  assert(editToken && nodes['failure-description'].value==='unsaved preserved input','Re-unlock after expiry preserves unsaved form contents');
  const legacyRow=renderDbnRow({...testDbn,issue_type:null,dut:null,dut_pin_snapshot:{},legacy_incomplete:1});
  assert(legacyRow.textContent.includes('未記錄類型') && !legacyRow.textContent.includes('共用PIN:'),'Untyped historical DBN never invents issue type or PIN');
  assert(!Number.isNaN(sourceDate('2026-10-08 03:04:30.647708+00').getTime()),'Source PostgreSQL timestamp renders across browsers');
  const history=new TestNode(); renderHistory([{id:'legacy-example',source_table:'repair_records',operation:'UPDATE',changed_at:'2026-10-08 03:04:30.647708+00',changes:{description:{old:'old',new:'new'}}}],history);
  assert(history.textContent.includes('來源歷史'),'Source history is distinct from local import events');
  globalThis.companyUiDone=true;
})().catch(error=>{globalThis.companyUiFailure=String(error)+'\n'+(error.stack||'');});
