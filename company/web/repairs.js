const byId = id => document.getElementById(id);
let catalogs, current = null, mapping = null, mappingRequest = 0, saving = false;
let page = 1, total = 0, listingRequest = 0;
let quickRequest = 0, detailRequest = 0, selectedRecord = null, serialFilter = '';
let quickSerial = '';
let editorSession = 0, editorReloading = false;
let catalogsLoading = false;
let editToken = '', editAccessBusy = false, pendingEdits = 0;
const editor = byId('editor');
const detail = byId('record-detail');
const fieldLabels = {serial_no:'S/N', machine_code:'機台', model:'機型', description:'板件名稱', board_part_code:'Part Number', failure_tag:'異常類別', failure_description:'異常描述', repair_type:'維修分類', repair_amount:'維修金額', current_status:'狀態', is_opened:'已開單', occurred_on:'損壞日期', sent_on:'送修日期', returned_on:'回修日期', attachment:'Fail Log', closed_on:'結案日期', retry_of_record_id:'前次案件'};

async function api(path, method = 'GET', body) {
  const options = {method, cache:'no-store', headers:{'X-SPMS-Request':'1'}};
  const writing = method !== 'GET' && !path.startsWith('/api/edit/');
  if (writing) requireEditMode();
  if (editToken) options.headers['X-SPMS-Edit-Token'] = editToken;
  if (body !== undefined) {options.headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(body);}
  // Writes are not automatically retried: a lost response must be checked first.
  if (writing) pendingEdits++;
  try {
    let response, data;
    try {response = await fetch(path, options);}
    catch (error) {throw new Error('本機服務連線失敗，請確認 Python 服務仍在執行：' + error.message);}
    try {data = await response.json();}
    catch {throw new Error('本機服務回應不是有效 JSON；請保留錯誤並確認服務版本。寫入結果未知時勿直接重送。');}
    if (!response.ok) {
      if (response.status === 401 && !path.startsWith('/api/edit/')) {editToken = ''; updateEditControls();}
      const error = new Error(data.error || '操作失敗'); error.status = response.status; throw error;
    }
    return data;
  } finally {if (writing) pendingEdits--;}
}

function requireEditMode() {if (!editToken || editAccessBusy) throw new Error('目前為唯讀模式或正在切換，請輸入密碼開啟編輯');}
function sourceDate(value) {
  return new Date(String(value).replace(' ', 'T').replace(/([+-]\d{2})$/, '$1:00').replace(/(\.\d{3})\d+/, '$1'));
}
function updateEditControls() {
  byId('edit-mode-state').textContent = editToken ? '編輯模式（共用密碼，非個人帳號）' : '唯讀模式';
  byId('toggle-edit').textContent = editToken ? '結束編輯' : '開啟編輯';
  for (const button of document.querySelectorAll('[data-edit-only]')) button.hidden = !editToken;
  for (const id of ['editor-unlock','operations-unlock']) byId(id).hidden = Boolean(editToken);
}
function openEditUnlock() {
  if (editAccessBusy) return;
  byId('edit-password').value = ''; byId('edit-unlock-message').textContent = '';
  if (!byId('edit-unlock').open) byId('edit-unlock').showModal();
  byId('edit-password').focus();
}
for (const id of ['editor-unlock','operations-unlock']) byId(id).addEventListener('click', openEditUnlock);
byId('toggle-edit').addEventListener('click', async () => {
  if (editAccessBusy) return;
  byId('edit-access-message').textContent = '';
  if (!editToken) {
    openEditUnlock(); return;
  }
  if (saving || editorReloading || pendingEdits || (typeof operationsSaving !== 'undefined' && operationsSaving)) {
    byId('edit-access-message').textContent = '操作正在處理，請稍候再結束編輯'; return;
  }
  if ((editor.open || byId('operations-modal').open) && !window.confirm('結束編輯並捨棄未儲存內容？')) return;
  editAccessBusy = true;
  try {await api('/api/edit/lock', 'POST', {});}
  catch (error) {byId('edit-access-message').textContent = error.message + '；本頁已鎖定。';}
  finally {
    editToken = ''; editorSession++; mappingRequest++; editor.close();
    if (typeof closeOperations === 'function') closeOperations();
    updateEditControls(); editAccessBusy = false;
  }
});
byId('edit-unlock-cancel').addEventListener('click', () => {if (!editAccessBusy) {byId('edit-password').value = ''; byId('edit-unlock').close();}});
byId('edit-unlock').addEventListener('cancel', event => {if (editAccessBusy) event.preventDefault(); else byId('edit-password').value = '';});
byId('edit-unlock-form').addEventListener('submit', async event => {
  event.preventDefault(); if (editAccessBusy) return;
  editAccessBusy = true; byId('edit-unlock-submit').disabled = true;
  const password = byId('edit-password').value; byId('edit-password').value = '';
  try {
    const result = await api('/api/edit/unlock', 'POST', {password});
    if (!result.token) throw new Error('服務未傳回編輯工作階段');
    editToken = result.token; updateEditControls(); byId('edit-unlock').close();
  } catch (error) {byId('edit-unlock-message').textContent = error.message;}
  finally {editAccessBusy = false; byId('edit-unlock-submit').disabled = false;}
});
updateEditControls();

function fillSelect(select, values, placeholder) {
  select.replaceChildren();
  if (placeholder) select.add(new Option(placeholder, ''));
  for (const value of values) select.add(new Option(value, value));
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function statusTone(status) {
  return {'已送修':'sent', '取回驗證':'verify', '結案（PASS）':'pass', '結案（FAIL）':'fail'}[status] || 'pending';
}

function statusPill(status) {
  return element('span', 'status-pill tone-' + statusTone(status), status);
}

function updateCounts(counts) {
  for (const node of document.querySelectorAll('[data-count]')) {
    node.textContent = node.dataset.count === 'all'
      ? Object.values(counts).reduce((sum, number) => sum + number, 0) : counts[node.dataset.count] || 0;
  }
}

function setView(quick, status = '') {
  if (typeof invalidateFeatureRequests === 'function') invalidateFeatureRequests();
  byId('workspace-view').hidden = true;
  for (const button of document.querySelectorAll('[data-workspace]')) button.removeAttribute('aria-current');
  byId('quick-view').hidden = !quick;
  byId('records-view').hidden = quick;
  byId('nav-quick').toggleAttribute('aria-current', quick);
  if (quick) byId('nav-quick').setAttribute('aria-current', 'page');
  for (const button of document.querySelectorAll('[data-status]')) {
    if (!quick && button.dataset.status === status) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  }
  if (!quick) {
    byId('status-filter').value = status;
    byId('view-title').textContent = status || '全部送修';
  }
}

function renderRecord(record) {
  const row = element('button', 'issue-row');
  row.type = 'button';
  row.classList.toggle('selected', selectedRecord?.id === record.id);
  const main = element('span', 'issue-main');
  const symbol = {'已送修':'↗', '取回驗證':'◎', '結案（PASS）':'✓', '結案（FAIL）':'×'}[record.current_status] || '○';
  const copy = element('span', 'item-copy');
  copy.className = 'item-copy issue-copy';
  const line = element('span', 'issue-line');
  line.append(element('strong', 'item-title issue-title', record.description), element('span', 'item-sub issue-sub', record.serial_no));
  copy.append(line, element('span', 'issue-open-status', `開單 ${record.is_opened ? 'O' : 'X'}`));
  main.append(element('span', 'state-symbol', symbol), copy);
  const tags = element('span', 'record-tags');
  const typeColor = ['板修','外修','合約','保固'].indexOf(record.repair_type);
  tags.append(element('span', 'failure-tag', record.failure_tag), element('span', 'repair-tag repair-tag-' + typeColor, record.repair_type));
  const dbn = element('span', 'dbn-link', record.dbn_count ? `DBN ${record.dbn_count}` : '—');
  if (record.dbn_count) {
    dbn.setAttribute('role', 'link'); dbn.tabIndex = 0;
    const follow = event => {event.preventDefault(); event.stopPropagation(); openWorkspace('dbn', record.serial_no);};
    dbn.addEventListener('click', follow);
    dbn.addEventListener('keydown', event => {if (event.key === 'Enter' || event.key === ' ') follow(event);});
  }
  const date = {'已送修':record.sent_on, '取回驗證':record.returned_on, '結案（PASS）':record.returned_on, '結案（FAIL）':record.returned_on}[byId('status-filter').value] || record.occurred_on;
  row.append(main, statusPill(record.current_status), tags, dbn,
    element('span', 'machine-cell', record.machine_code), element('span', 'date-cell', date));
  row.addEventListener('click', () => openDetail(record.id));
  return row;
}

function detailSection(title, fields) {
  const section = element('section', 'detail-section');
  section.append(element('h3', '', title));
  const grid = element('div', 'detail-grid');
  for (const [label, value] of fields) {
    const field = element('div', 'detail-field');
    field.append(element('label', '', label), element('span', '', value ?? '—'));
    grid.append(field);
  }
  section.append(grid);
  return section;
}

async function openDetail(id) {
  const request = ++detailRequest;
  byId('detail-message').textContent = '';
  try {
    const result = await api('/api/repairs/records/' + encodeURIComponent(id));
    if (request !== detailRequest) return;
    const record = result.data;
    selectedRecord = record;
    byId('detail-serial').textContent = record.serial_no;
    byId('detail-title').textContent = record.description;
    byId('edit-detail').disabled = !catalogs;
    const body = byId('detail-content');
    body.replaceChildren(statusPill(record.current_status));
    body.append(detailSection('板件資訊', [['機台', record.machine_code], ['Model', record.model],
      ['S/N', record.serial_no], ['Part Number', record.board_part_code], ['是否開單', record.is_opened ? 'O' : 'X']]));
    body.append(detailSection('維修資訊', [['維修分類', record.repair_type], ['維修金額', record.repair_amount == null ? '未設定' : record.repair_amount.toLocaleString('zh-TW')],
      ['損壞日期', record.occurred_on], ['送修日期', record.sent_on], ['回修日期', record.returned_on], ['結案日期', record.closed_on], ['異常類別', record.failure_tag]]));
    body.append(repairTimeline(record));
    const failure = element('section', 'detail-section');
    failure.append(element('h3', '', '異常描述'), element('div', 'detail-text', record.failure_description));
    body.append(failure);
    if (record.legacy_source) {
      const source = element('details', 'detail-section'); source.append(element('summary', '', '唯讀來源欄位（匯入當時）'));
      for (const [key, value] of Object.entries(record.legacy_source)) source.append(element('p', 'detail-text', `${key}: ${value || '（空白）'}`));
      body.append(source);
    }
    for (const warning of record.legacy_warnings || []) body.append(element('p', 'notice', '來源核對提醒（匯入時）：' + warning));
    if (!detail.open) detail.showModal();
    if (typeof renderDetailFeatures === 'function') await renderDetailFeatures(record, body, () => request === detailRequest);
    if (request !== detailRequest) return;
    if (!detail.open) detail.showModal();
  } catch (error) {
    if (request !== detailRequest) return;
    byId('detail-message').textContent = byId('message').textContent = byId('quick-message').textContent = error.message;
  }
}

byId('close-detail').addEventListener('click', () => {detailRequest++; detail.close();});
detail.addEventListener('cancel', () => {detailRequest++;});
byId('edit-detail').addEventListener('click', async () => {
  if (!editToken) {byId('detail-message').textContent = '請先開啟編輯模式'; return;}
  if (!selectedRecord) return;
  const button = byId('edit-detail');
  const id = selectedRecord.id, request = detailRequest;
  button.disabled = true;
  try {
    const result = await api('/api/repairs/records/' + encodeURIComponent(id));
    if (request !== detailRequest || !detail.open || selectedRecord?.id !== id) return;
    detailRequest++;
    detail.close();
    await openEditor(result.data);
  } catch (error) {if (request === detailRequest) byId('detail-message').textContent = error.message;}
  finally {button.disabled = false;}
});

async function searchSerial() {
  if (!catalogs) return;
  const request = ++quickRequest;
  let serial = byId('quick-query').value.trim().toUpperCase();
  if (/^[0-9]{1,8}$/.test(serial)) serial = serial.padStart(9, '0');
  if (!serial) return;
  byId('quick-query').value = serial;
  byId('quick-message').textContent = '正在查詢…';
  byId('quick-results').replaceChildren();
  try {
    const query = new URLSearchParams({serial});
    const outcomes = await Promise.allSettled([api('/api/repairs/records?' + query),
      api('/api/repairs/serial-summary?' + query), api('/api/repairs/dbn?' + query)]);
    if (request !== quickRequest) return;
    const read = (index, fallback) => outcomes[index].status === 'fulfilled' ? outcomes[index].value : {...fallback, error:outcomes[index].reason.message};
    const records = read(0, {data:[],total:0}), dbn = read(2, {data:[],total:0});
    const summary = read(1, {serial_no:serial,mapping:null,models:[],machines:[]});
    if (summary.error) {
      const known = [...records.data,...dbn.data];
      summary.models = [...new Set(known.map(row => row.model).filter(Boolean))];
      summary.machines = [...new Set(known.map(row => row.machine_code).filter(Boolean))];
    }
    quickSerial = serial;
    if (!records.error) updateCounts(records.status_counts);
    renderQuickResults(summary, records, dbn, byId('quick-results'));
    if (records.total > 20) {
      const all = element('button', 'quick-card', '目前顯示前 20 筆，前往送修清單查看全部');
      all.type = 'button';
      all.addEventListener('click', () => {serialFilter = serial; byId('query').value = ''; setView(false); page = 1; loadRecords();});
      byId('quick-results').append(all);
    }
    if (dbn.total > 20) {
      const allDbn = element('button', 'quick-card', '前往 DBN 清單查看全部'); allDbn.type = 'button';
      allDbn.addEventListener('click', () => openWorkspace('dbn', serial)); byId('quick-results').append(allDbn);
    }
    byId('quick-message').textContent = outcomes.some(row => row.status === 'rejected') ? '部分查詢失敗，以下只顯示已成功讀取的資料；不可當成完整歷史或零筆。可再按 Search 重新查詢。' : records.total || dbn.total ? '點選送修紀錄查看詳細資料。' : '此 S/N 尚無本機送修或 DBN 紀錄。';
  } catch (error) {if (request === quickRequest) byId('quick-message').textContent = error.message;}
}

byId('quick-form').addEventListener('submit', event => {event.preventDefault(); searchSerial();});
byId('quick-query').addEventListener('input', () => {
  quickRequest++; quickSerial = ''; byId('quick-results').replaceChildren();
  byId('quick-message').textContent = '輸入 S/N 後按 Search 查詢。';
});
byId('nav-quick').addEventListener('click', () => {setView(true); byId('quick-query').focus();});
for (const button of document.querySelectorAll('[data-status]')) button.addEventListener('click', () => {
  serialFilter = ''; byId('query').value = ''; setView(false, button.dataset.status); page = 1; loadRecords();
});

function updateBoards(preferred = byId('board').value) {
  const machine = catalogs.machines.find(row => row.machine_code === byId('machine').value);
  byId('model').value = machine?.model || '';
  const boards = catalogs.boards.filter(row => row.model === machine?.model &&
    (!mapping || (row.board_name === mapping.board_name && row.board_part_code === mapping.board_part_code)));
  fillSelect(byId('board'), boards.map(row => row.board_name), '請選擇板件');
  if (boards.some(row => row.board_name === preferred)) byId('board').value = preferred;
  else if (mapping && boards.length === 1) byId('board').value = boards[0].board_name;
  byId('board').disabled = Boolean(mapping);
  byId('part').value = boards.find(row => row.board_name === byId('board').value)?.board_part_code || '';
  byId('mapping-hint').textContent = mapping
    ? `S/N 已綁定 ${mapping.board_name}／${mapping.board_part_code}，板名與 PN 鎖定。${boards.length ? '' : '請選擇相容機台。'}`
    : 'S/N 未綁定時，儲存成功會建立主檔；不會默默修改其他歷史。';
  updatePricePreview();
}

function updatePricePreview() {
  const model = catalogs?.machines.find(row => row.machine_code === byId('machine').value)?.model;
  const preserve = current && !byId('reprice').checked && current.model === model && current.description === byId('board').value && current.board_part_code === byId('part').value && current.repair_type === byId('repair-type').value;
  const cents = repairPrice(model, byId('board').value, byId('part').value, byId('repair-type').value);
  const amount = preserve ? current.repair_amount : cents == null ? null : cents / 100;
  byId('repair-amount-preview').textContent = (amount == null ? '未設定' : amount.toLocaleString('zh-TW') + ' 元') + (preserve ? '（保留原金額）' : '（目前價目）');
}

function repairPrice(model, board, part, type) {
  const price = catalogs?.prices?.find(row => row.model === model && row.board_name === board && row.board_part_code === part);
  const column = {'板修':'board_repair_cents','外修':'external_repair_cents','合約':'contract_repair_cents','保固':'warranty_repair_cents'}[type];
  return price?.[column] ?? null;
}

function updateEditorDates() {
  const occurred = byId('occurred-on'), sent = byId('sent-on'), returned = byId('returned-on');
  const status = byId('record-status').value;
  const closed = ['結案（PASS）','結案（FAIL）'].includes(current?.current_status) ? current.closed_on || '' : '';
  const verified = ['取回驗證','結案（PASS）','結案（FAIL）'].includes(status);
  occurred.required = true; sent.required = verified || status === '已送修' || Boolean(returned.value); returned.required = verified;
  const earliest = values => values.filter(Boolean).sort()[0] || '9999-12-31';
  occurred.min = '0001-01-01'; occurred.max = earliest([sent.value, returned.value, closed]);
  sent.min = occurred.value || '0001-01-01'; sent.max = earliest([returned.value, closed]);
  returned.min = sent.value || occurred.value || '0001-01-01'; returned.max = closed || '9999-12-31';
  for (const input of [occurred, sent, returned]) input.setCustomValidity('');
  const errors = [];
  const invalid = (input, message) => {input.setCustomValidity(message); errors.push(message);};
  if (!occurred.value) invalid(occurred, '損壞日期必填');
  if (sent.required && !sent.value) invalid(sent, '目前狀態或回修日期需要送修日期');
  if (returned.required && !returned.value) invalid(returned, '取回驗證／已結案必須填回修日期');
  if (sent.value && occurred.value && sent.value < occurred.value) invalid(sent, '送修日期不得早於損壞日期');
  if (returned.value && sent.value && returned.value < sent.value) invalid(returned, '回修日期不得早於送修日期');
  if (closed && returned.value > closed) invalid(returned, '回修日期不得晚於結案日期');
  byId('date-hint').textContent = errors.length ? errors.join('；') : `日期順序：損壞 → 送修 → 回修${closed ? ' → 結案 ' + closed : ''}。${verified ? '目前送修／回修日期皆必填。' : sent.required ? '目前送修日期必填。' : '送修／回修日期選填。'}不會自動更改日期。`;
  return errors.length === 0;
}

async function lookupMapping() {
  const request = ++mappingRequest;
  const serial = byId('serial').value.trim().toUpperCase();
  const result = await api('/api/repairs/serial-mapping?serial=' + encodeURIComponent(serial));
  if (request !== mappingRequest) return false;
  mapping = result.data;
  if (mapping) byId('serial').value = mapping.serial_no;
  updateBoards();
  return true;
}

async function closeEditor() {
  if (saving || editorReloading) return;
  const id = current?.id;
  editorSession++; mappingRequest++; current = null;
  editor.close();
  if (id) await openDetail(id);
}
editor.addEventListener('cancel', event => event.preventDefault());
byId('close').addEventListener('click', closeEditor);
byId('cancel').addEventListener('click', closeEditor);
byId('reload-record').addEventListener('click', async () => {
  if (saving || editorReloading || !current) return;
  if (!window.confirm('重新載入會捨棄這個表單尚未儲存的內容，改讀取最新案件。確定繼續？')) return;
  const id = current.id, session = editorSession;
  editorReloading = true; mappingRequest++;
  let frozen = [...byId('record-form').elements].map(input => [input, input.disabled]);
  frozen.forEach(([input]) => {input.disabled = true;});
  for (const key of ['save','cancel','close','reload-record']) byId(key).disabled = true;
  try {
    byId('form-message').textContent = '正在重新載入最新案件…';
    const result = await api('/api/repairs/records/' + encodeURIComponent(id));
    if (session !== editorSession || !editor.open) return;
    frozen.forEach(([input, disabled]) => {input.disabled = disabled;}); frozen = [];
    await openEditor(result.data);
  } catch (error) {
    if (session === editorSession) byId('form-message').textContent = error.message + '\n重新載入失敗；原輸入已保留。';
  } finally {
    frozen.forEach(([input, disabled]) => {input.disabled = disabled;});
    editorReloading = false;
    for (const key of ['save','cancel','close','reload-record']) byId(key).disabled = false;
  }
});
byId('machine').addEventListener('change', () => updateBoards());
byId('board').addEventListener('change', () => updateBoards());
byId('repair-type').addEventListener('change', updatePricePreview);
byId('reprice').addEventListener('change', updatePricePreview);
for (const id of ['record-status','occurred-on','sent-on','returned-on']) {
  byId(id).addEventListener('change', updateEditorDates);
  if (id !== 'record-status') byId(id).addEventListener('input', updateEditorDates);
}
byId('serial').addEventListener('input', () => {mappingRequest++; mapping = null; updateBoards();});
byId('serial').addEventListener('blur', () => lookupMapping().catch(error => {byId('form-message').textContent = error.message;}));

async function openEditor(record = null) {
  requireEditMode();
  const session = ++editorSession;
  current = record;
  mapping = null;
  mappingRequest++;
  byId('record-form').reset();
  byId('reprice').checked = false;
  byId('reprice-field').hidden = !record;
  byId('reload-record').hidden = !record;
  byId('create-attachment-field').hidden = Boolean(record);
  byId('create-attachment').value = '';
  filePickerUpdates.get(byId('create-attachment'))?.();
  byId('editor-title').textContent = record ? '編輯送修' : '新增送修';
  byId('form-message').textContent = '';
  byId('history').replaceChildren();
  byId('history-section').hidden = !record;
  byId('history-section').open = false;
  fillSelect(byId('record-status'), record ? (catalogs.statuses.includes(record.current_status) ? catalogs.statuses : [record.current_status]) : ['待送修']);
  for (const [field, value] of Object.entries(record || {})) {
    const input = byId('record-form').elements.namedItem(field);
    if (!input || field === 'description' || field === 'board_part_code') continue;
    if (input.type === 'checkbox') input.checked = Boolean(value);
    else input.value = value ?? '';
  }
  if (!record) byId('occurred-on').value = new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Taipei', year:'numeric', month:'2-digit', day:'2-digit'}).format(new Date());
  updateBoards(record?.description || '');
  updateEditorDates();
  if (!editor.open) editor.showModal();
  byId('serial').focus();
  const id = record?.id;
  try {
    await lookupMapping();
    if (session !== editorSession || !editor.open) return;
    if (id) {
      const result = await api(`/api/repairs/records/${encodeURIComponent(id)}/history`);
      if (session !== editorSession || !editor.open || current?.id !== id) return;
      for (const event of result.data) {
        const item = document.createElement('li');
        const time = sourceDate(event.changed_at).toLocaleString('zh-TW', {timeZone:'Asia/Taipei', hour12:false});
        if (event.operation === 'INSERT') item.textContent = `${time} 新增 ${event.serial_no}－${event.board_name}`;
        else item.textContent = `${time} ${event.operation === 'IMPORT' ? '匯入' : '修改'}\n` + Object.entries(event.changes).map(([field, change]) => `${fieldLabels[field] || field}：${typeof change.old === 'object' && change.old !== null ? JSON.stringify(change.old) : change.old ?? '—'} → ${typeof change.new === 'object' && change.new !== null ? JSON.stringify(change.new) : change.new ?? '—'}`).join('\n');
        byId('history').append(item);
      }
    }
  } catch (error) {if (session === editorSession && editor.open) byId('form-message').textContent = error.message;}
}

byId('create').addEventListener('click', () => openEditor());
byId('record-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (saving || editorReloading) return;
  saving = true;
  for (const id of ['save', 'cancel', 'close', 'reload-record']) byId(id).disabled = true;
  byId('form-message').textContent = '正在儲存…';
  let frozen = [];
  try {
    frozen = [...byId('record-form').elements].map(input => [input, input.disabled]);
    frozen.forEach(([input]) => {input.disabled = true;});
    if (!await lookupMapping()) throw new Error('S/N 查詢已變更，請再檢查後儲存');
    frozen.forEach(([input, disabled]) => {input.disabled = disabled;});
    byId('board').disabled = Boolean(mapping);
    const datesValid = updateEditorDates();
    if (!byId('record-form').reportValidity()) throw new Error('請填妥必填欄位');
    if (!datesValid) throw new Error(byId('date-hint').textContent);
    const payload = Object.fromEntries(new FormData(byId('record-form')));
    // Disabled locked fields are deliberately omitted by FormData.
    payload.description = byId('board').value;
    payload.is_opened = byId('is-opened').checked;
    if (current) payload.reprice = byId('reprice').checked;
    if (current && payload.reprice && !window.confirm('確認重新套用目前價目？這會更新此案金額，已結案案件也會影響歷史統計。')) {
      byId('form-message').textContent = '已取消重新計價，尚未儲存；輸入內容已保留。'; return;
    }
    frozen.forEach(([input]) => {input.disabled = true;});
    if (!current && byId('create-attachment').files?.[0]) payload.attachment = await encodeFile(byId('create-attachment').files[0]);
    if (current) payload.expected_version = current.version;
    const url = '/api/repairs/records' + (current ? '/' + encodeURIComponent(current.id) : '');
    const result = await api(url, current ? 'PUT' : 'POST', payload);
    const savedId = result.data.id;
    editorSession++; mappingRequest++; current = null;
    editor.close();
    page = 1;
    await loadRecords();
    if (quickSerial) await searchSerial();
    await openDetail(savedId);
  } catch (error) {
    byId('form-message').textContent = error.message + '\n輸入內容已保留。若為連線中斷，請先查詢確認是否已儲存，避免重複新增。';
  } finally {
    for (const [input, disabled] of frozen) input.disabled = disabled;
    byId('board').disabled = Boolean(mapping);
    saving = false;
    for (const id of ['save', 'cancel', 'close', 'reload-record']) byId(id).disabled = false;
  }
});

async function loadRecords() {
  const request = ++listingRequest;
  byId('message').textContent = '正在載入…';
  byId('message').dataset.error = 'false';
  byId('previous').disabled = byId('next').disabled = true;
  try {
    const query = new URLSearchParams({q:byId('query').value, status:byId('status-filter').value, page});
    if (byId('tag-filter').value) query.set('failure_tag', byId('tag-filter').value);
    if (byId('type-filter').value) query.set('repair_type', byId('type-filter').value);
    if (serialFilter) query.set('serial', serialFilter);
    const result = await api('/api/repairs/records?' + query);
    if (request !== listingRequest) return;
    page = result.page;
    total = result.total;
    updateCounts(result.status_counts);
    byId('date-heading').textContent = {'已送修':'送修日期','取回驗證':'回修日期','結案（PASS）':'回修日期','結案（FAIL）':'回修日期'}[byId('status-filter').value] || '損壞日期';
    byId('records').replaceChildren();
    for (const record of result.data) byId('records').append(renderRecord(record));
    const first = total ? (page - 1) * 20 + 1 : 0;
    byId('message').textContent = `共${total}筆資料 顯示${first}-${Math.min(page * 20, total)}`;
    byId('page').textContent = `第 ${page} / ${Math.max(1, Math.ceil(total / 20))} 頁`;
    byId('previous').disabled = page <= 1;
    byId('next').disabled = page * 20 >= total;
  } catch (error) {
    if (request !== listingRequest) return;
    byId('records').replaceChildren();
    byId('message').textContent = error.message; byId('message').dataset.error = 'true';
  }
}

byId('search-form').addEventListener('submit', event => {event.preventDefault(); serialFilter = ''; setView(false, byId('status-filter').value); page = 1; loadRecords();});
byId('previous').addEventListener('click', () => {page--; loadRecords();});
byId('next').addEventListener('click', () => {page++; loadRecords();});
for (const id of ['tag-filter', 'type-filter']) byId(id).addEventListener('change', () => {page = 1; loadRecords();});
let searchTimer = null;
byId('query').addEventListener('input', () => {
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => {serialFilter = ''; page = 1; loadRecords();}, 220);
});

async function initializeApp() {
  if (catalogsLoading) return;
  catalogsLoading = true; byId('create').disabled = byId('reload-catalogs').disabled = true;
  byId('startup-error').hidden = true;
  try {
    catalogs = await api('/api/repairs/catalog');
    fillSelect(byId('machine'), catalogs.machines.map(row => row.machine_code), '請選擇機台');
    fillSelect(byId('failure-tag'), catalogs.failure_tags, '請選擇異常類別');
    fillSelect(byId('repair-type'), catalogs.repair_types);
    fillSelect(byId('tag-filter'), catalogs.failure_tags, '所有異常類別');
    fillSelect(byId('type-filter'), catalogs.repair_types, '所有維修分類');
    byId('create').disabled = false;
    await loadRecords();
  } catch (error) {
    byId('startup-error').hidden = false; byId('startup-message').textContent = '無法載入本機對應表：' + error.message;
    byId('message').textContent = error.message; byId('message').dataset.error = 'true';
  } finally {catalogsLoading = false; byId('reload-catalogs').disabled = false;}
}
byId('reload-catalogs').addEventListener('click', initializeApp);
initializeApp();
