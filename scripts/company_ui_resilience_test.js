// Additional isolated mock-DOM suite. Not a visual/browser acceptance test.
(async () => {
  for (let index = 0; index < 12; index++) await Promise.resolve();
  faultPrefixes.set('/api/repairs/catalog', 'catalog offline');
  await initializeApp();
  assert(!nodes['startup-error'].hidden && nodes.create.disabled, 'Startup failure is visible from the default quick view');
  faultPrefixes.clear(); await nodes['reload-catalogs'].listeners.click[0]();
  assert(nodes['startup-error'].hidden && !nodes.create.disabled, 'Startup can recover without losing page state');

  nodes['quick-query'].value = testRecord.serial_no;
  faultPrefixes.set('/api/repairs/dbn?', 'DBN offline'); await searchSerial();
  assert(nodes['quick-results'].textContent.includes('<script>not markup</script>') && nodes['quick-results'].textContent.includes('DBN 讀取失敗'), 'DBN outage preserves repair results');
  assert(!nodes['quick-results'].textContent.includes('沒有此 S/N 的DBN'), 'Failed DBN query is not reported as no history');
  faultPrefixes.clear(); faultPrefixes.set('/api/repairs/records?', 'repairs offline'); await searchSerial();
  assert(nodes['quick-results'].textContent.includes('送修讀取失敗') && nodes['quick-results'].textContent.includes('共用PIN:'), 'Repair outage preserves DBN results');
  faultPrefixes.clear(); faultPrefixes.set('/api/repairs/serial-summary', 'summary offline'); await searchSerial();
  assert(nodes['quick-results'].textContent.includes('板件摘要讀取失敗') && nodes['quick-results'].textContent.includes('F45'), 'Failed summary falls back only to available result identities with a warning');
  faultPrefixes.set('/api/repairs/records?', 'repairs offline'); faultPrefixes.set('/api/repairs/dbn?', 'DBN offline'); await searchSerial();
  assert(nodes['quick-message'].textContent.includes('不可當成完整歷史或零筆'), 'Total query outage never masquerades as zero records');
  faultPrefixes.clear();

  await editMaster('board');
  let masterInputs = Object.fromEntries(nodes['operations-fields'].elements.map(input => [input.dataset.field,input]));
  masterInputs.model.value = 'T5377S'; masterInputs.board_name.value = 'HVDR PE'; masterInputs.board_name.listeners.change[0]();
  masterInputs.board_part_code.value = 'EXPLICIT-NEW-PN';
  for (const handler of masterInputs.board_part_code.listeners.change || []) handler();
  assert(masterInputs.board_part_code.value === 'EXPLICIT-NEW-PN', 'Add/update board form does not erase an intentionally changed PN');
  closeOperations();
  await editMaster('price');
  masterInputs = Object.fromEntries(nodes['operations-fields'].elements.map(input => [input.dataset.field,input]));
  masterInputs.model.value = 'T5377S'; masterInputs.board_name.value = 'HVDR PE'; masterInputs.board_part_code.value = 'BPR-030837';
  masterInputs.board_part_code.listeners.change[0]();
  assert(masterInputs.board_repair_cents.value === '0.00', 'Known price identity autofills exact recorded price');
  masterInputs.board_part_code.value = 'OTHER-PN'; masterInputs.board_part_code.listeners.change[0]();
  assert(masterInputs.board_repair_cents.value === '', 'Changing price identity cannot silently carry old amounts into a different PN');
  masterInputs.board_part_code.value = 'BPR-030837'; masterInputs.warranty_repair_cents.value = '1';
  const beforePrice = requests.filter(request => request.path === '/api/repairs/masters' && request.options.method === 'POST').length;
  await nodes['operations-form'].listeners.submit[0]({preventDefault(){}});
  assert(nodes['operations-message'].textContent.includes('保固金額只能') && requests.filter(request => request.path === '/api/repairs/masters' && request.options.method === 'POST').length === beforePrice, 'Invalid warranty price is rejected before any write');
  closeOperations();

  faultPrefixes.set('/api/repairs/records/record-1/attachment', 'attachment offline'); await openDetail(testRecord.id);
  assert(nodes['record-detail'].open && nodes['detail-content'].textContent.includes('板件資訊'), 'Attachment outage does not hide known record details');
  assert(nodes['detail-content'].textContent.includes('不能當成沒有附件') && !nodes['detail-content'].textContent.includes('上傳 Fail Log'), 'Unknown attachment state does not expose an empty-file uploader');
  assert(nodes['detail-content'].children.find(node => node.textContent === '刪除此筆送修').disabled, 'Unknown attachment state blocks deletion');
  faultPrefixes.clear(); faultPrefixes.set('/api/repairs/records/record-1/chain', 'chain offline');
  const target = new TestNode(); await renderDetailFeatures({...testRecord,current_status:'取回驗證'}, target, () => true);
  const resolve = target.children.find(node => node.textContent.includes('驗證結果'));
  assert(resolve.children.filter(node => node.tag === 'button').every(node => node.disabled), 'Unreadable chain blocks verification writes');
  assert(target.textContent.includes('重新讀取詳細資料') && !target.textContent.includes('尚無連續送修紀錄'), 'Unreadable chain offers retry instead of empty-chain claims');
  faultPrefixes.clear(); nodes['record-detail'].close();

  function hold(prefix) {
    let release; const promise = new Promise(resolve => {release = resolve;}); gatePrefixes.set(prefix, promise);
    return () => {gatePrefixes.delete(prefix); release();};
  }
  let release = hold('/api/repairs/dbn/catalog');
  const openingDbn = editDbn(); setView(true); release(); await openingDbn;
  assert(!operationsDialog.open, 'A late DBN catalog response cannot open a dialog after navigation');
  release = hold('/api/repairs/masters');
  const openingMaster = editMaster('machine'); setView(true); release(); await openingMaster;
  assert(!operationsDialog.open, 'A late master response cannot reopen a canceled navigation');

  await editDbn();
  const inputs = Object.fromEntries(nodes['operations-fields'].elements.map(input => [input.dataset.field,input]));
  inputs.machine.value = 'F45'; inputs.machine.listeners.change[0](); inputs.board.value = 'HVDR PE'; inputs.board.listeners.change[0]();
  inputs.serial.value = testRecord.serial_no; inputs.customer.value = 'AB'; inputs.customer.listeners.change[0]();
  inputs.product.value = 'JAA118'; inputs.product.listeners.change[0](); inputs.station.value = 'CP1';
  inputs.kind.value = 'RTE'; inputs.kind.listeners.change[0](); inputs.description.value = 'DBN preflight freeze';
  inputs.kind.value = 'Single Dut'; inputs.dut.value = '1-2'; inputs.kind.listeners.change[0]();
  assert(inputs.dut.validationMessage.includes('Single Dut 限單一編號'), 'Invalid DUT preview also marks the native field invalid');
  inputs.kind.value = 'RTE'; inputs.kind.listeners.change[0]();
  assert(inputs.dut.validationMessage === '' && inputs.dut.disabled, 'Switching issue type clears irrelevant DUT validation');
  release = hold('/api/repairs/serial-mapping');
  const savingDbn = nodes['operations-form'].listeners.submit[0]({preventDefault(){}});
  assert(operationsSaving && nodes['operations-form'].elements.every(input => input.disabled), 'DBN inputs lock before asynchronous serial lookup');
  closeOperations(); assert(operationsDialog.open, 'Closing cannot interrupt a pending DBN write');
  release(); await savingDbn;
  assert(!operationsDialog.open && !operationsSaving, 'DBN controls recover after confirmed write');

  await openEditor(testRecord); nodes['failure-description'].value = 'repair preflight freeze';
  release = hold('/api/repairs/serial-mapping');
  const savingRepair = nodes['record-form'].listeners.submit[0]({preventDefault(){}});
  assert(saving && nodes['record-form'].elements.every(input => input.disabled), 'Repair inputs lock before serial preflight');
  release(); await savingRepair;
  assert(nodes.editor.open && !saving && nodes.board.disabled && nodes['failure-description'].value === 'repair preflight freeze', 'Conflict restores editable inputs and preserves the mapped lock');
  await closeEditor(); nodes['record-detail'].close();

  await openDetail(testRecord.id); release = hold('/api/repairs/records/record-1');
  const pendingEdit = nodes['edit-detail'].listeners.click[0]();
  nodes['close-detail'].listeners.click[0](); release(); await pendingEdit;
  assert(!nodes.editor.open && !nodes['record-detail'].open, 'Closed details cannot be reopened by a late edit lookup');

  faultPrefixes.set('/api/repairs/catalog', 'INVALID_JSON');
  const before = requests.length; let message = '';
  try {await api('/api/repairs/catalog');} catch (error) {message = error.message;}
  assert(message.includes('服務回應異常') && message.includes('避免重複操作') && requests.length === before + 1, 'Invalid service responses keep the no-retry warning without exposing implementation details');
  faultPrefixes.clear();
  assert(requests.every(request => request.path.startsWith('/api/')), 'Failure and recovery paths remain local-only');
  const rankingContainer = new TestNode();
  renderStatistics({frequency:{},amounts_cents:{},years:['2026'],missing_amounts:0,ranking:[{machine:'F10',count:1},{machine:'F2',count:1}]}, rankingContainer);
  assert(rankingContainer.textContent.indexOf('F2') < rankingContainer.textContent.indexOf('F10'), 'Tied machine rankings use original-style numeric code ordering');
  globalThis.companyUiDone = true;
})().catch(error => {globalThis.companyUiFailure = String(error) + '\n' + (error.stack || '');});
