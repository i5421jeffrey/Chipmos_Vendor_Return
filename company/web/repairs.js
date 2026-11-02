const byId = id => document.getElementById(id);
let catalogs, current = null, mapping = null, mappingRequest = 0, saving = false;
let page = 1, total = 0, listingRequest = 0;
let quickRequest = 0, detailRequest = 0, selectedRecord = null, serialFilter = '';
let quickSerial = '';
const editor = byId('editor');
const detail = byId('record-detail');
const fieldLabels = {serial_no:'S/N', machine_code:'機台', model:'機型', description:'板件名稱', board_part_code:'Part Number', failure_tag:'異常類別', failure_description:'異常描述', repair_type:'維修分類', repair_amount:'維修金額', current_status:'狀態', is_opened:'已開單', occurred_on:'損壞日期', sent_on:'送修日期', returned_on:'回修日期'};

async function api(path, method = 'GET', body) {
  const options = {method, cache:'no-store', headers:{'X-SPMS-Request':'1'}};
  if (body !== undefined) {options.headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(body);}
  // Writes are not automatically retried: a lost response must be checked first.
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '操作失敗');
  return data;
}

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
  copy.append(element('strong', 'item-title', record.description),
    element('span', 'item-sub', `${record.serial_no} · 開單 ${record.is_opened ? 'O' : 'X'}`));
  main.append(element('span', 'state-symbol', symbol), copy);
  const tags = element('span', 'record-tags');
  tags.append(element('span', 'failure-tag', record.failure_tag), element('span', 'repair-tag', record.repair_type));
  row.append(main, statusPill(record.current_status), tags, element('span', 'dbn-pending', '尚未移植'),
    element('span', 'machine-cell', record.machine_code), element('span', 'date-cell', record.occurred_on));
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
    byId('edit-detail').disabled = !catalogs?.statuses.includes(record.current_status);
    const body = byId('detail-content');
    body.replaceChildren(statusPill(record.current_status));
    body.append(detailSection('板件資訊', [['機台', record.machine_code], ['Model', record.model],
      ['S/N', record.serial_no], ['Part Number', record.board_part_code], ['是否開單', record.is_opened ? 'O' : 'X']]));
    body.append(detailSection('維修資訊', [['維修分類', record.repair_type], ['維修金額', record.repair_amount == null ? '未設定' : record.repair_amount.toLocaleString('zh-TW')],
      ['損壞日期', record.occurred_on], ['送修日期', record.sent_on], ['回修日期', record.returned_on], ['異常類別', record.failure_tag]]));
    const failure = element('section', 'detail-section');
    failure.append(element('h3', '', '異常描述'), element('div', 'detail-text', record.failure_description));
    body.append(failure, element('p', 'detail-note', '附件、結案／再次送修及跨案件連續送修歷史尚未移植。本筆新增／修改紀錄可從「編輯／異動」查看。'));
    if (!detail.open) detail.showModal();
  } catch (error) {
    if (request !== detailRequest) return;
    byId('message').textContent = byId('quick-message').textContent = error.message;
  }
}

byId('close-detail').addEventListener('click', () => {detailRequest++; detail.close();});
byId('edit-detail').addEventListener('click', async () => {
  if (!selectedRecord) return;
  const button = byId('edit-detail');
  button.disabled = true;
  try {
    const result = await api('/api/repairs/records/' + encodeURIComponent(selectedRecord.id));
    detail.close();
    await openEditor(result.data);
  } catch (error) {byId('detail-message').textContent = error.message;}
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
    const [records, master] = await Promise.all([api('/api/repairs/records?' + query),
      api('/api/repairs/serial-mapping?' + query)]);
    if (request !== quickRequest) return;
    quickSerial = serial;
    updateCounts(records.status_counts);
    const summary = element('section', 'quick-summary');
    summary.append(element('h2', '', master.data?.board_name || records.data[0]?.description || '尚無板件主檔'),
      element('p', 'serial-text', serial), element('p', '', `共 ${records.total} 筆送修紀錄 · Part Number：${master.data?.board_part_code || '未記錄'}`));
    byId('quick-results').append(summary);
    for (const record of records.data) {
      const card = element('button', 'quick-card');
      card.type = 'button';
      card.append(element('strong', '', `${record.description} · ${record.current_status}`),
        element('span', '', `${record.machine_code} · ${record.occurred_on} · ${record.failure_tag}`),
        element('span', '', record.failure_description));
      card.addEventListener('click', () => openDetail(record.id));
      byId('quick-results').append(card);
    }
    if (records.total > 20) {
      const all = element('button', 'quick-card', '目前顯示前 20 筆，前往送修清單查看全部');
      all.type = 'button';
      all.addEventListener('click', () => {serialFilter = serial; byId('query').value = ''; setView(false); page = 1; loadRecords();});
      byId('quick-results').append(all);
    }
    byId('quick-message').textContent = records.total ? '點選紀錄查看詳細資料。' : '此 S/N 尚無本機送修紀錄。';
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

function closeEditor() {if (!saving) editor.close();}
editor.addEventListener('cancel', event => event.preventDefault());
byId('close').addEventListener('click', closeEditor);
byId('cancel').addEventListener('click', closeEditor);
byId('machine').addEventListener('change', () => updateBoards());
byId('board').addEventListener('change', () => updateBoards());
byId('serial').addEventListener('input', () => {mappingRequest++; mapping = null; updateBoards();});
byId('serial').addEventListener('blur', () => lookupMapping().catch(error => {byId('form-message').textContent = error.message;}));

async function openEditor(record = null) {
  current = record;
  mapping = null;
  mappingRequest++;
  byId('record-form').reset();
  byId('editor-title').textContent = record ? '編輯送修' : '新增送修';
  byId('form-message').textContent = '';
  byId('history').replaceChildren();
  byId('history-section').hidden = !record;
  byId('history-section').open = false;
  fillSelect(byId('record-status'), record ? catalogs.statuses : ['待送修']);
  for (const [field, value] of Object.entries(record || {})) {
    const input = byId('record-form').elements.namedItem(field);
    if (!input || field === 'description' || field === 'board_part_code') continue;
    if (input.type === 'checkbox') input.checked = Boolean(value);
    else input.value = value ?? '';
  }
  if (!record) byId('occurred-on').value = new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Taipei', year:'numeric', month:'2-digit', day:'2-digit'}).format(new Date());
  updateBoards(record?.description || '');
  editor.showModal();
  byId('serial').focus();
  const id = record?.id;
  try {
    await lookupMapping();
    if (id) {
      const result = await api(`/api/repairs/records/${encodeURIComponent(id)}/history`);
      if (current?.id !== id) return;
      for (const event of result.data) {
        const item = document.createElement('li');
        const time = new Date(event.changed_at).toLocaleString('zh-TW', {timeZone:'Asia/Taipei', hour12:false});
        if (event.operation === 'INSERT') item.textContent = `${time} 新增 ${event.serial_no}－${event.board_name}`;
        else item.textContent = `${time} 修改\n` + Object.entries(event.changes).map(([field, change]) => `${fieldLabels[field] || field}：${change.old ?? '—'} → ${change.new ?? '—'}`).join('\n');
        byId('history').append(item);
      }
    }
  } catch (error) {byId('form-message').textContent = error.message;}
}

byId('create').addEventListener('click', () => openEditor());
byId('record-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (saving) return;
  saving = true;
  for (const id of ['save', 'cancel', 'close']) byId(id).disabled = true;
  byId('form-message').textContent = '正在儲存…';
  let frozen = [];
  try {
    if (!await lookupMapping()) throw new Error('S/N 查詢已變更，請再檢查後儲存');
    if (!byId('record-form').reportValidity()) throw new Error('請填妥必填欄位');
    const payload = Object.fromEntries(new FormData(byId('record-form')));
    // Disabled locked fields are deliberately omitted by FormData.
    payload.description = byId('board').value;
    payload.is_opened = byId('is-opened').checked;
    if (current) payload.expected_version = current.version;
    frozen = [...byId('record-form').elements].map(input => [input, input.disabled]);
    for (const [input] of frozen) input.disabled = true;
    const url = '/api/repairs/records' + (current ? '/' + encodeURIComponent(current.id) : '');
    await api(url, current ? 'PUT' : 'POST', payload);
    editor.close();
    page = 1;
    await loadRecords();
    if (quickSerial) await searchSerial();
  } catch (error) {
    byId('form-message').textContent = error.message + '\n輸入內容已保留。若為連線中斷，請先查詢確認是否已儲存，避免重複新增。';
  } finally {
    for (const [input, disabled] of frozen) input.disabled = disabled;
    saving = false;
    for (const id of ['save', 'cancel', 'close']) byId(id).disabled = false;
  }
});

async function loadRecords() {
  const request = ++listingRequest;
  byId('message').textContent = '正在載入…';
  byId('message').dataset.error = 'false';
  byId('previous').disabled = byId('next').disabled = true;
  try {
    const query = new URLSearchParams({q:byId('query').value, status:byId('status-filter').value, page});
    if (serialFilter) query.set('serial', serialFilter);
    const result = await api('/api/repairs/records?' + query);
    if (request !== listingRequest) return;
    page = result.page;
    total = result.total;
    updateCounts(result.status_counts);
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

(async () => {
  try {
    catalogs = await api('/api/repairs/catalog');
    fillSelect(byId('machine'), catalogs.machines.map(row => row.machine_code), '請選擇機台');
    fillSelect(byId('failure-tag'), catalogs.failure_tags, '請選擇異常類別');
    fillSelect(byId('repair-type'), catalogs.repair_types);
    byId('create').disabled = false;
    await loadRecords();
  } catch (error) {byId('message').textContent = error.message; byId('message').dataset.error = 'true';}
})();
