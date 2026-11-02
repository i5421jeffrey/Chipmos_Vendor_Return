/* Local-only feature workspaces. Untrusted values are always text, never HTML. */
let workspace = '', workspacePage = 1, workspaceSerial = '', workspaceRequest = 0;
let operationsSaving = false, operationsSubmit = null, masterData = null;
const workspaceTitles = {dbn:'DBN 紀錄', mappings:'S/N 主檔維護', history:'全站異動紀錄', statistics:'統計資料', masters:'機台／板件／價格對應'};
const operationsDialog = byId('operations-modal');
const descriptions = {dbn:'DBN 紀錄獨立於送修案件；DUT／PIN 保存當時快照。', mappings:'主檔只保存 S/N、板名與 PN；歷史同步須先預覽及確認，不重算金額。', history:'本機異動紀錄；尚未登入，這不是具名操作人員稽核。', statistics:'首輪損壞頻率與機台排行；依結案日期加總各輪已知金額。', masters:'修改只影響後續選擇與儲存，不自動改寫既有案件、S/N 或價格快照。'};

function action(label, handler, className = '') {
  const button = element('button', className, label); button.type = 'button';
  button.addEventListener('click', async () => {
    if (button.disabled) return;
    button.disabled = true;
    try {await handler();}
    catch (error) {byId('workspace-message').textContent = byId('detail-message').textContent = error.message;}
    finally {button.disabled = false;}
  });
  return button;
}

async function encodeFile(file) {
  if (!/\.(txt|asc)$/i.test(file.name) || !file.size || file.size > 5 * 1024 * 1024) throw new Error('附件僅接受非空 .txt／.asc，最大 5 MB');
  const encoded = await new Promise((resolve, reject) => {
    const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]);
    reader.onerror = () => reject(new Error('檔案讀取失敗')); reader.readAsDataURL(file);
  });
  return {filename:file.name, content_base64:encoded};
}

function openOperations(title, submit) {
  byId('operations-title').textContent = title;
  byId('operations-fields').replaceChildren(); byId('operations-message').textContent = '';
  operationsSubmit = submit;
  if (!operationsDialog.open) operationsDialog.showModal();
}

function formField(label, kind = 'text', value = '', choices = null) {
  const wrapper = element('label', kind === 'textarea' || kind === 'file' ? 'wide' : '', label);
  const input = element(kind === 'select' ? 'select' : kind === 'textarea' ? 'textarea' : 'input');
  if (kind !== 'select' && kind !== 'textarea') input.type = kind;
  if (kind === 'select') fillSelect(input, choices || [], '請選擇');
  input.value = value ?? ''; input.required = !['file', 'checkbox'].includes(kind);
  if (kind === 'text') input.maxLength = 200;
  if (kind === 'textarea') input.maxLength = 10000;
  if (kind === 'file') input.accept = '.txt,.asc';
  wrapper.append(input); byId('operations-fields').append(wrapper);
  return input;
}

function closeOperations() {if (!operationsSaving) operationsDialog.close();}
byId('operations-close').addEventListener('click', closeOperations);
byId('operations-cancel').addEventListener('click', closeOperations);
operationsDialog.addEventListener('cancel', event => event.preventDefault());
byId('operations-form').addEventListener('submit', async event => {
  event.preventDefault(); if (operationsSaving || !operationsSubmit) return;
  operationsSaving = true;
  const inputs = [...byId('operations-form').elements];
  const disabled = inputs.map(input => input.disabled);
  // Build the payload first; disable the form while its confirmed write runs.
  let freeze = () => inputs.forEach(input => {input.disabled = true;});
  try {
    byId('operations-message').textContent = '正在處理…';
    await operationsSubmit(freeze);
  } catch (error) {
    byId('operations-message').textContent = error.message + '\n輸入已保留；連線中斷時請先查詢是否成功，勿直接重複新增。';
  } finally {
    inputs.forEach((input, index) => {input.disabled = disabled[index];}); operationsSaving = false;
  }
});

function openWorkspace(kind, number = '') {
  workspace = kind; workspaceSerial = number; workspacePage = 1;
  setView(false); byId('records-view').hidden = true; byId('workspace-view').hidden = false;
  for (const button of document.querySelectorAll('[data-status]')) button.removeAttribute('aria-current');
  for (const button of document.querySelectorAll('[data-workspace]')) {
    if (button.dataset.workspace === kind) button.setAttribute('aria-current', 'page');
  }
  byId('workspace-title').textContent = workspaceTitles[kind];
  byId('workspace-description').textContent = descriptions[kind];
  byId('workspace-query').value = ''; byId('workspace-actions').replaceChildren();
  byId('workspace-search').hidden = ['statistics', 'masters'].includes(kind);
  byId('stats-controls').hidden = kind !== 'statistics';
  byId('workspace-pager').hidden = ['statistics', 'masters'].includes(kind);
  if (kind === 'dbn') byId('workspace-actions').append(action('＋ 新增 DBN', () => editDbn()));
  if (kind === 'mappings') byId('workspace-actions').append(action('＋ 新增 S/N 對應', () => editMapping()));
  if (kind === 'masters') for (const [key, label] of [['machine','機台'], ['board','板件'], ['price','價格']]) {
    byId('workspace-actions').append(action('新增／修改' + label, () => editMaster(key)));
  }
  return loadWorkspace();
}

for (const button of document.querySelectorAll('[data-workspace]')) button.addEventListener('click', () => openWorkspace(button.dataset.workspace));
byId('workspace-search').addEventListener('submit', event => {event.preventDefault(); workspaceSerial = ''; workspacePage = 1; loadWorkspace();});
byId('workspace-previous').addEventListener('click', () => {workspacePage--; loadWorkspace();});
byId('workspace-next').addEventListener('click', () => {workspacePage++; loadWorkspace();});
byId('stats-load').addEventListener('click', loadWorkspace);
byId('ranking-sort').addEventListener('change', loadWorkspace);
byId('stats-period').value = String(new Date().getFullYear());
byId('stats-mode').addEventListener('change', () => {byId('stats-period').value = byId('stats-mode').value === 'year' ? String(new Date().getFullYear()) : String(new Date().getMonth() + 1).padStart(2, '0');});

async function loadWorkspace() {
  const request = ++workspaceRequest, kind = workspace;
  byId('workspace-message').textContent = '正在載入…';
  byId('workspace-previous').disabled = byId('workspace-next').disabled = true;
  try {
    const query = new URLSearchParams({q:byId('workspace-query').value, page:workspacePage});
    if (workspaceSerial) query.set('serial', workspaceSerial);
    if (kind === 'statistics') {query.set('mode', byId('stats-mode').value); query.set('period', byId('stats-period').value);}
    const result = await api('/api/repairs/' + kind + '?' + query);
    if (request !== workspaceRequest || kind !== workspace) return;
    const content = byId('workspace-content'); content.replaceChildren();
    if (kind === 'statistics') {renderStatistics(result, content); return;}
    if (kind === 'masters') {
      masterData = result;
      for (const [key, title] of [['machines','機台／機型'], ['boards','板件對應'], ['prices','價格（單位：分，NULL＝未設定）']]) {
        content.append(element('h2', '', title), table(Object.keys(result[key][0] || {}), result[key].map(row => Object.values(row).map(value => value ?? 'NULL'))));
      }
      byId('workspace-message').textContent = '主檔不自動改寫歷史案件。'; return;
    }
    workspacePage = result.page;
    for (const row of result.data) {
      if (kind === 'dbn') content.append(renderDbnCard(row));
      else if (kind === 'mappings') {
        const card = element('section', 'quick-summary');
        card.append(element('strong', '', row.serial_no), element('p', '', `${row.board_name} · ${row.board_part_code}`), action('修改', () => editMapping(row)));
        content.append(card);
      } else {
        const card = element('section', 'quick-summary');
        card.append(element('strong', '', `${row.operation} · ${row.source_table} · ${row.serial_no || '—'}`),
          element('p', '', new Date(row.changed_at).toLocaleString('zh-TW', {timeZone:'Asia/Taipei'})),
          element('pre', 'detail-text', Object.entries(row.changes).map(([key, change]) => `${fieldLabels[key] || key}：${JSON.stringify(change.old) ?? '—'} → ${JSON.stringify(change.new) ?? '—'}`).join('\n')));
        content.append(card);
      }
    }
    byId('workspace-message').textContent = `${workspaceSerial ? 'S/N ' + workspaceSerial + ' · ' : ''}共 ${result.total} 筆`;
    byId('workspace-page').textContent = `第 ${result.page}／${Math.max(1, Math.ceil(result.total / 20))} 頁`;
    byId('workspace-previous').disabled = result.page <= 1;
    byId('workspace-next').disabled = result.page * 20 >= result.total;
  } catch (error) {
    if (request !== workspaceRequest) return;
    byId('workspace-content').replaceChildren(); byId('workspace-message').textContent = error.message;
  }
}

function pinDetails(record) {
  const result = element('details', 'pin-details');
  result.append(element('summary', '', `DUT ${record.dut} · PIN`));
  const snapshot = record.dut_pin_snapshot || {}, rows = Object.entries(snapshot).map(([dut, pins]) => [dut, Array.isArray(pins) ? [...new Set(pins)] : null]);
  const common = rows.length > 1 && rows.every(([, pins]) => pins?.length)
    ? rows[0][1].filter(pin => rows.every(([, pins]) => pins.includes(pin))) : [];
  if (common.length) result.append(element('p', 'detail-text', '共用 PIN：' + [...new Set(common)].join(', ')));
  for (const [dut, pins] of rows) {
    const remaining = pins?.filter(pin => !common.includes(pin));
    result.append(element('p', 'detail-text', `DUT${dut}：${pins ? (remaining.length ? remaining.join(', ') : '無額外 PIN') : '尚無對應'}`));
  }
  if (!record.socket_file_id) result.append(element('p', 'hint', '此產品沒有 Socket 對應；不推測 PIN。'));
  return result;
}

function renderDbnCard(record) {
  const card = element('section', 'quick-summary');
  card.append(element('strong', '', `${record.serial_no} · ${record.board_name}`),
    element('p', '', `${record.machine_code} · ${record.customer_code}／${record.product_code || '—'}／${record.station_code || '—'} · ${record.issue_type}`),
    element('p', 'hint', new Date(record.created_at).toLocaleString('zh-TW', {timeZone:'Asia/Taipei'})));
  if (record.dut) card.append(pinDetails(record));
  if (record.issue_description) card.append(element('p', 'detail-text', record.issue_description));
  const actions = element('div', 'actions');
  actions.append(action('編輯', () => editDbn(record)), action('刪除', async () => {
    if (!window.confirm(`永久刪除這筆 DBN（${record.serial_no}）？送修案件不受影響。`)) return;
    await api('/api/repairs/dbn/' + encodeURIComponent(record.id), 'DELETE', {expected_version:record.version});
    await refreshFeatures();
  }));
  card.append(actions); return card;
}

async function refreshFeatures() {
  await loadRecords();
  if (workspace && !byId('workspace-view').hidden) await loadWorkspace();
  if (quickSerial) await searchSerial();
}

async function editDbn(record = null) {
  const dbnCatalog = await api('/api/repairs/dbn/catalog');
  if (!catalogs) throw new Error('機台對應尚未載入');
  let inputs, localMapping = null, lookupRequest = 0;
  openOperations(record ? '編輯 DBN 紀錄' : '新增 DBN 紀錄', async freeze => {
    const number = inputs.serial.value.trim();
    const master = (await api('/api/repairs/serial-mapping?serial=' + encodeURIComponent(number))).data;
    if (master && (master.board_name !== inputs.board.value || master.board_part_code !== inputs.part.value)) throw new Error('S/N 主檔與板件衝突，請先重新查詢／選擇相容機台');
    const payload = {serial_no:number, machine_code:inputs.machine.value, board_name:inputs.board.value, board_part_code:inputs.part.value,
      customer_code:inputs.customer.value, product_code:inputs.product.value || null, station_code:inputs.station.value || null,
      issue_type:inputs.kind.value, dut:inputs.dut.value, issue_description:inputs.description.value};
    if (record) payload.expected_version = record.version;
    freeze(); await api('/api/repairs/dbn' + (record ? '/' + encodeURIComponent(record.id) : ''), record ? 'PUT' : 'POST', payload);
    operationsDialog.close(); await refreshFeatures();
  });
  inputs = {
    serial:formField('S/N', 'text', record?.serial_no), machine:formField('機台', 'select', record?.machine_code, catalogs.machines.map(row => row.machine_code)),
    board:formField('板件名稱', 'select'), part:formField('Part Number'),
    customer:formField('客戶', 'select', record?.customer_code, dbnCatalog.customers), product:formField('產品', 'select'), station:formField('站點', 'select'),
    kind:formField('DBN 類型', 'select', record?.issue_type, ['Group','Single Dut','RTE','Other']),
    dut:formField('DUT（單一編號或連續範圍）', 'text', record?.dut), description:formField('異常描述（RTE／Other 必填）', 'textarea', record?.issue_description)
  };
  inputs.serial.maxLength = 64; inputs.part.readOnly = true;
  const preview = element('div', 'wide hint'); byId('operations-fields').append(preview);
  function boards(preferred = inputs.board.value) {
    const model = catalogs.machines.find(row => row.machine_code === inputs.machine.value)?.model;
    const choices = catalogs.boards.filter(row => row.model === model && (!localMapping || (row.board_name === localMapping.board_name && row.board_part_code === localMapping.board_part_code)));
    fillSelect(inputs.board, choices.map(row => row.board_name), '請選擇板件');
    inputs.board.value = choices.some(row => row.board_name === preferred) ? preferred : localMapping ? choices[0]?.board_name || '' : '';
    inputs.board.disabled = Boolean(localMapping);
    inputs.part.value = choices.find(row => row.board_name === inputs.board.value)?.board_part_code || '';
    if (localMapping) preview.textContent = `S/N 已鎖定 ${localMapping.board_name}／${localMapping.board_part_code}，請選相容機台。`;
  }
  function products() {
    fillSelect(inputs.product, [...new Set(dbnCatalog.combinations.filter(row => row.customer_code === inputs.customer.value).map(row => row.product_code))], '請選擇產品');
    inputs.product.required = dbnCatalog.combinations.some(row => row.customer_code === inputs.customer.value);
    stations();
  }
  function stations() {
    const choices = dbnCatalog.combinations.filter(row => row.customer_code === inputs.customer.value && row.product_code === inputs.product.value).map(row => row.station_code);
    fillSelect(inputs.station, choices, '請選擇站點'); inputs.station.required = inputs.product.required;
    issue();
  }
  function issue() {
    const usesDut = ['Group', 'Single Dut'].includes(inputs.kind.value);
    inputs.dut.required = usesDut; inputs.dut.disabled = !usesDut;
    inputs.description.required = !usesDut; inputs.description.disabled = usesDut;
    preview.replaceChildren();
    if (!usesDut || !inputs.dut.value) return;
    const match = /^(\d{1,4})(?:\s*-\s*(\d{1,4}))?$/.exec(inputs.dut.value.trim());
    if (!match) {preview.textContent = 'DUT 格式錯誤'; return;}
    const first = Number(match[1]), last = Number(match[2] || match[1]);
    const socket = dbnCatalog.sockets.find(row => row.product_code === inputs.product.value);
    if (first < 1 || last < first || last > 2048 || last - first > 7 || (inputs.kind.value === 'Single Dut' && match[2])) {preview.textContent = 'Single Dut 限單一編號；Group 限連續 1–8 個 DUT'; return;}
    const canonical = first === last ? String(first) : `${first}-${last}`;
    const same = record && record.product_code === inputs.product.value && record.dut === canonical;
    const snapshot = same ? record.dut_pin_snapshot : Object.fromEntries(Array.from({length:last-first+1}, (_, index) => [String(first+index), socket?.dut_pins[String(first+index)] || null]));
    preview.append(pinDetails({dut:canonical, socket_file_id:same ? record.socket_file_id : socket?.id, dut_pin_snapshot:snapshot}));
  }
  inputs.machine.addEventListener('change', () => boards()); inputs.board.addEventListener('change', () => boards());
  inputs.customer.addEventListener('change', products); inputs.product.addEventListener('change', stations);
  inputs.kind.addEventListener('change', issue); inputs.dut.addEventListener('input', issue);
  inputs.serial.addEventListener('input', () => {lookupRequest++; localMapping = null; inputs.board.disabled = false; boards();});
  async function lookup() {
    const request = ++lookupRequest, number = inputs.serial.value;
    const result = await api('/api/repairs/serial-mapping?serial=' + encodeURIComponent(number));
    if (request !== lookupRequest) return;
    localMapping = result.data; if (localMapping) inputs.serial.value = localMapping.serial_no; boards();
  }
  inputs.serial.addEventListener('blur', () => lookup().catch(error => {byId('operations-message').textContent = error.message;}));
  boards(record?.board_name); products(); inputs.product.value = record?.product_code || ''; stations(); inputs.station.value = record?.station_code || ''; issue();
  if (record) await lookup();
}

async function editMapping(record = null) {
  if (!catalogs) throw new Error('板件對應尚未載入');
  let number, board;
  const pairs = [...new Map(catalogs.boards.map(row => [JSON.stringify([row.board_name, row.board_part_code]), row])).entries()];
  openOperations(record ? '修改 S/N 對應' : '新增 S/N 對應', async freeze => {
    if (!board.value) throw new Error('請選板件');
    const [board_name, board_part_code] = JSON.parse(board.value);
    const values = {previous_serial_no:record?.serial_no || null, serial_no:number.value, board_name, board_part_code};
    freeze();
    const impact = await api('/api/repairs/mappings/impact', 'POST', values);
    let sync = false;
    if (impact.repair_count || impact.dbn_count) {
      sync = window.confirm(`影響 ${impact.repair_count} 筆送修、${impact.dbn_count} 筆 DBN。\n確定＝同步歷史；取消＝只更新主檔。歷史金額與 Socket 快照均不重算。`);
      if (!sync && !window.confirm('確定只更新主檔，保留所有歷史原樣？更改 S/N 時，有歷史引用的舊主檔也會保留。')) {byId('operations-message').textContent = '已取消，未寫入。'; return;}
    } else if (!window.confirm('確認儲存此 S/N 主檔對應？')) {byId('operations-message').textContent = '已取消，未寫入。'; return;}
    await api('/api/repairs/mappings', 'POST', {...values, expected_version:record?.version ?? null, sync_history:sync, impact_token:impact.token});
    operationsDialog.close(); await refreshFeatures();
  });
  number = formField('S/N', 'text', record?.serial_no); number.maxLength = 64;
  board = formField('板件名稱／Part Number', 'select');
  board.replaceChildren(new Option('請選板件', ''));
  for (const [key, row] of pairs) board.add(new Option(`${row.board_name} — ${row.board_part_code}`, key));
  if (record) board.value = JSON.stringify([record.board_name, record.board_part_code]);
}

async function editMaster(kind) {
  const original = await api('/api/repairs/masters');
  const fields = {};
  openOperations('新增／修改' + {machine:'機台對應', board:'板件對應', price:'價格'}[kind], async freeze => {
    const value = Object.fromEntries(Object.entries(fields).map(([key, input]) => [key, input.value.trim()]));
    if (kind === 'price') for (const key of ['board_repair_cents','external_repair_cents','contract_repair_cents','warranty_repair_cents']) {
      const entered = value[key];
      if (entered && !/^\d+(?:\.\d{1,2})?$/.test(entered)) throw new Error('金額最多兩位小數，不可負數');
      const [units, cents = ''] = entered.split('.'); value[key] = entered ? Number(units) * 100 + Number(cents.padEnd(2, '0')) : null;
    }
    if (!window.confirm('確認儲存對應？不會自動更新其他主檔／歷史案件或金額。')) {byId('operations-message').textContent = '已取消，未寫入。'; return;}
    freeze(); await api('/api/repairs/masters', 'POST', {kind, value, expected_token:original.token});
    catalogs = await api('/api/repairs/catalog');
    fillSelect(byId('machine'), catalogs.machines.map(row => row.machine_code), '請選機台');
    operationsDialog.close(); await refreshFeatures();
  });
  if (kind === 'machine') fields.machine_code = formField('機台編號');
  fields.model = formField('Model');
  if (kind !== 'machine') {fields.board_name = formField('板件名稱'); fields.board_part_code = formField('Part Number');}
  if (kind === 'price') for (const [key, label] of [['board_repair_cents','板修'], ['external_repair_cents','外修'], ['contract_repair_cents','合約'], ['warranty_repair_cents','保固']]) {
    fields[key] = formField(label + '金額（元；空白＝未設定）'); fields[key].required = false;
  }
  function autofill() {
    if (kind === 'machine') {
      const row = original.machines.find(row => row.machine_code === fields.machine_code.value); if (row) fields.model.value = row.model;
    } else {
      const row = (kind === 'price' ? original.prices : original.boards).find(row => row.model === fields.model.value && row.board_name === fields.board_name.value && (kind !== 'price' || row.board_part_code === fields.board_part_code.value));
      if (!row) return;
      fields.board_part_code.value = row.board_part_code;
      if (kind === 'price') for (const key of ['board_repair_cents','external_repair_cents','contract_repair_cents','warranty_repair_cents']) fields[key].value = row[key] == null ? '' : (row[key] / 100).toFixed(2);
    }
  }
  for (const key of ['machine_code', 'model', 'board_name', 'board_part_code']) fields[key]?.addEventListener('change', autofill);
}

async function renderDetailFeatures(record, container, stillCurrent) {
  const [meta, chainResult] = await Promise.all([api(`/api/repairs/records/${encodeURIComponent(record.id)}/attachment`), api(`/api/repairs/records/${encodeURIComponent(record.id)}/chain`)]);
  if (!stillCurrent()) return;
  const fileSection = element('section', 'detail-section'); fileSection.append(element('h3', '', 'Fail Log'));
  if (meta.data) {
    fileSection.append(element('p', '', `${meta.data.filename} · ${meta.data.file_size} bytes`));
    const link = element('a', '', '下載'); link.href = '/api/repairs/attachments/' + encodeURIComponent(meta.data.id) + '?download=1';
    const preview = element('pre', 'file-preview'); preview.hidden = true;
    fileSection.append(action('檢視文字', async () => {
      const response = await fetch('/api/repairs/attachments/' + encodeURIComponent(meta.data.id), {cache:'no-store'});
      if (!response.ok) throw new Error('附件讀取失敗'); preview.textContent = await response.text(); preview.hidden = false;
    }), link, action('刪除附件', async () => {
      if (!window.confirm('永久刪除這筆附件？')) return;
      await api('/api/repairs/attachments/' + encodeURIComponent(meta.data.id), 'DELETE', {expected_version:record.version});
      await openDetail(record.id);
    }), preview);
  } else {
    fileSection.append(element('p', 'hint', '尚無附件。非空 .txt／.asc，最大 5 MB。'));
    const picker = element('input'); picker.type = 'file'; picker.accept = '.txt,.asc';
    fileSection.append(picker, action('上傳 Fail Log', async () => {
      if (!picker.files?.[0]) throw new Error('請先選擇檔案');
      const attachment = await encodeFile(picker.files[0]);
      await api(`/api/repairs/records/${encodeURIComponent(record.id)}/attachment`, 'POST', {expected_version:record.version, attachment});
      await openDetail(record.id);
    }));
  }
  container.append(fileSection);
  const history = element('section', 'detail-section'); history.append(element('h3', '', '連續送修紀錄'));
  for (const row of chainResult.data) {
    history.append(action(`${row.occurred_on} · ${row.current_status} · ${row.repair_type} · ${row.repair_amount ?? '未設定'}`, () => openDetail(row.id), 'quick-card'), element('p', 'detail-text', row.failure_description));
    if (row.attachment) {
      const link = element('a', '', row.attachment.filename); link.href = '/api/repairs/attachments/' + encodeURIComponent(row.attachment.id) + '?download=1'; history.append(link);
    }
  }
  container.append(history, action('查看此 S/N 的 DBN', () => {detail.close(); return openWorkspace('dbn', record.serial_no);}));
  if (record.current_status === '取回驗證') {
    const resolve = element('section', 'detail-section'); resolve.append(element('h3', '', '驗證結果'));
    if (record.repair_amount == null) resolve.append(element('p', 'hint', '金額未設定，請先補齊價格並編輯案件，再結案。'));
    else resolve.append(action('PASS・成功維修', async () => {
      if (!window.confirm('確認 PASS 結案？')) return;
      await api(`/api/repairs/records/${encodeURIComponent(record.id)}/resolve`, 'POST', {expected_version:record.version, passed:true});
      await refreshFeatures(); await openDetail(record.id);
    }), action('FAIL・建立下一筆維修', () => retryRepair(record)));
    container.append(resolve);
  }
  container.append(action('刪除此筆送修', async () => {
    if (!window.confirm(`永久刪除 ${record.serial_no} 的這筆送修及附件？連續送修鏈不允許刪除。`)) return;
    await api('/api/repairs/records/' + encodeURIComponent(record.id), 'DELETE', {expected_version:record.version});
    detail.close(); selectedRecord = null; await refreshFeatures();
  }));
}

function retryRepair(record) {
  let type, description, file;
  openOperations('FAIL 並建立再次送修', async freeze => {
    const payload = {expected_version:record.version, passed:false, repair_type:type.value, failure_description:description.value};
    if (file.files?.[0]) payload.attachment = await encodeFile(file.files[0]);
    if (!window.confirm('確認原案 FAIL 結案並建立下一筆待送修？舊描述與 Fail Log 不會被覆蓋。')) {byId('operations-message').textContent = '已取消，未寫入。'; return;}
    freeze(); const result = await api(`/api/repairs/records/${encodeURIComponent(record.id)}/resolve`, 'POST', payload);
    operationsDialog.close(); await refreshFeatures(); await openDetail(result.retry.id);
  });
  type = formField('下一筆維修分類', 'select', record.repair_type, catalogs.repair_types);
  description = formField('本次異常描述', 'textarea'); file = formField('本次 Fail Log（不自動複製前一筆）', 'file');
}

function table(headings, rows) {
  const wrapper = element('div', 'table-wrap'), result = element('table');
  const head = element('thead'), header = element('tr');
  for (const name of headings) header.append(element('th', '', name)); head.append(header); result.append(head);
  const body = element('tbody');
  for (const values of rows) {const row = element('tr'); for (const value of values) row.append(element('td', '', value)); body.append(row);}
  result.append(body); wrapper.append(result); return wrapper;
}

function chart(groups, amounts = false) {
  const ns = 'http://www.w3.org/2000/svg';
  function svgNode(tag, attributes, label) {
    const node = document.createElementNS(ns, tag); for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
    if (label !== undefined) node.textContent = label; return node;
  }
  const svg = svgNode('svg', {viewBox:'0 0 920 270', role:'img', 'aria-label':amounts ? '各維修分類結案金額' : '故障頻率', class:'stats-chart'});
  const entries = Object.entries(groups), maximum = Math.max(1, ...entries.map(([, value]) => amounts ? Object.values(value).reduce((sum, amount) => sum + amount, 0) : value));
  const slot = 840 / Math.max(1, entries.length), width = Math.min(48, slot * .6), colors = ['#8b8df8','#d7906c','#78bcba','#a2bf7c'];
  entries.forEach(([key, values], index) => {
    let stacked = 0;
    const pairs = amounts ? Object.entries(values) : [['次數', values]];
    pairs.forEach(([label, value], color) => {
      const height = value / maximum * 200;
      const rect = svgNode('rect', {x:60 + index * slot, y:220 - stacked - height, width, height, fill:colors[color]});
      rect.append(svgNode('title', {}, `${key} ${label}：${amounts ? value / 100 : value}`)); svg.append(rect); stacked += height;
    });
    svg.append(svgNode('text', {x:60 + index * slot, y:250, fill:'#929398', 'font-size':10}, key));
  });
  return svg;
}

function renderStatistics(result, container) {
  const labels = ['板修', '外修', '合約', '保固'];
  const total = Object.values(result.frequency).reduce((sum, value) => sum + value, 0);
  const amount = Object.values(result.amounts_cents).reduce((sum, row) => sum + Object.values(row).reduce((a, b) => a + b, 0), 0);
  byId('workspace-message').textContent = `損壞 ${total} 次 · 已知結案金額 ${(amount / 100).toLocaleString('zh-TW')} 元 · 金額未設定 ${result.missing_amounts} 筆（不視為零元）`;
  container.append(element('h2', '', '故障發生頻率'), chart(result.frequency), table(['期間','首輪損壞次數'], Object.entries(result.frequency)));
  container.append(element('h2', '', '結案金額'), chart(result.amounts_cents, true), table(['期間', ...labels], Object.entries(result.amounts_cents).map(([period, amounts]) => [period, ...labels.map(label => (amounts[label] / 100).toLocaleString('zh-TW'))])));
  const ranking = byId('ranking-sort').value === 'asc' ? [...result.ranking].sort((a,b) => a.count - b.count || a.machine.localeCompare(b.machine)) : result.ranking;
  let rank = 0, last = null;
  container.append(element('h2', '', '機台損壞排行'), table(['排名','機台','次數'], ranking.map((row, index) => {if (row.count !== last) rank = index + 1; last = row.count; return [rank, row.machine, row.count];})));
}
