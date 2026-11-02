const byId = id => document.getElementById(id);
let catalogs, current = null, mapping = null, mappingRequest = 0, saving = false;
let page = 1, total = 0, listingRequest = 0;
const editor = byId('editor');
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
    const result = await api('/api/repairs/records?' + query);
    if (request !== listingRequest) return;
    page = result.page;
    total = result.total;
    byId('records').replaceChildren();
    for (const record of result.data) {
      const tr = document.createElement('tr');
      const texts = [`${record.serial_no}－${record.description}`, `${record.machine_code}／${record.model}`, record.current_status,
        record.failure_tag, `${record.repair_type}／${record.repair_amount == null ? '未設定' : record.repair_amount.toLocaleString('zh-TW')}`, record.occurred_on];
      for (const text of texts) {const td = document.createElement('td'); td.textContent = text; tr.append(td);}
      const info = document.createElement('small'); info.textContent = record.failure_description; tr.firstChild.append(info);
      const action = document.createElement('td'), button = document.createElement('button');
      button.textContent = '編輯／異動'; button.type = 'button';
      button.disabled = !catalogs.statuses.includes(record.current_status);
      button.addEventListener('click', async () => {
        button.disabled = true;
        try {const result = await api('/api/repairs/records/' + encodeURIComponent(record.id)); await openEditor(result.data);}
        catch (error) {byId('message').textContent = error.message;}
        finally {button.disabled = false;}
      });
      action.append(button); tr.append(action); byId('records').append(tr);
    }
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

byId('search-form').addEventListener('submit', event => {event.preventDefault(); page = 1; loadRecords();});
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
