/* Local-only feature workspaces. Untrusted values are always text, never HTML. */
let workspace = '', workspacePage = 1, workspaceSerial = '', workspaceRequest = 0;
let operationsSaving = false, operationsSubmit = null, masterData = null;
let statisticsMode = 'year', statisticsYear = String(new Date().getFullYear()), statisticsMonth = String(new Date().getMonth() + 1).padStart(2, '0');
const fieldContainers = new WeakMap();
const filePickerUpdates = new WeakMap();
const workspaceTitles = {dbn:'DBN 紀錄', mappings:'S/N 主檔維護', history:'全站異動紀錄', statistics:'統計資料', masters:'機台／板件／價格對應'};
const operationsDialog = byId('operations-modal');
const descriptions = {dbn:'DBN 紀錄獨立於送修案件；DUT／PIN 保存當時快照。', mappings:'主檔只保存 S/N、板名與 PN；歷史同步須先預覽及確認，不重算金額。', history:'本機異動紀錄；尚未登入，這不是具名操作人員稽核。', statistics:'首輪損壞頻率與機台排行；依結案日期加總各輪已知金額。', masters:'修改只影響後續選擇與儲存，不自動改寫既有案件、S/N 或價格快照。'};

function action(label, handler, className = 'button') {
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

function mountFilePicker(input, container) {
  input.hidden = true;
  const picker = element('div', 'upload-picker'), name = element('div', 'upload-file-name');
  const choose = element('button', 'button primary upload-trigger', '↑ 選擇 Fail Log'); choose.type = 'button';
  choose.addEventListener('click', () => input.click());
  const clear = element('button', 'button', '清除選擇'); clear.type = 'button';
  const update = () => {
    const file = input.files?.[0];
    name.textContent = file ? `${file.name} · ${(file.size / 1024).toLocaleString('zh-TW', {maximumFractionDigits:1})} KB` : '尚未選擇檔案';
    clear.hidden = !file;
  };
  clear.addEventListener('click', () => {input.value = ''; update();});
  input.addEventListener('change', update); filePickerUpdates.set(input, update);
  picker.append(choose, name, clear); container.append(picker); update();
  return picker;
}
mountFilePicker(byId('create-attachment'), byId('create-attachment-field'));

function openOperations(title, submit) {
  byId('operations-title').textContent = title;
  byId('operations-fields').replaceChildren(); byId('operations-message').textContent = '';
  operationsSubmit = submit;
  if (!operationsDialog.open) operationsDialog.showModal();
}

function formField(label, kind = 'text', value = '', choices = null) {
  const wrapper = element(kind === 'file' ? 'div' : 'label', kind === 'textarea' || kind === 'file' ? 'wide' : '', label);
  const input = element(kind === 'select' ? 'select' : kind === 'textarea' ? 'textarea' : 'input');
  if (kind !== 'select' && kind !== 'textarea') input.type = kind;
  if (kind === 'select') fillSelect(input, choices || [], '請選擇');
  input.value = value ?? ''; input.required = !['file', 'checkbox'].includes(kind);
  if (kind === 'text') input.maxLength = 200;
  if (kind === 'textarea') input.maxLength = 10000;
  if (kind === 'file') input.accept = '.txt,.asc';
  wrapper.append(input); byId('operations-fields').append(wrapper);
  if (kind === 'file') {input.setAttribute('aria-label', label); mountFilePicker(input, wrapper);}
  fieldContainers.set(input, wrapper);
  return input;
}

function closeOperations() {if (!operationsSaving) operationsDialog.close();}
byId('operations-close').addEventListener('click', closeOperations);
byId('operations-cancel').addEventListener('click', closeOperations);
operationsDialog.addEventListener('cancel', event => event.preventDefault());
byId('operations-form').addEventListener('submit', async event => {
  event.preventDefault(); if (operationsSaving || !operationsSubmit) return;
  if (!byId('operations-form').reportValidity()) return;
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
  byId('history-filters').hidden = kind !== 'history';
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
byId('ranking-sort').addEventListener('change', loadWorkspace);
for (let month = 1; month <= 12; month++) byId('stats-month').add(new Option(`${month} 月`, String(month).padStart(2, '0')));
byId('stats-month').value = statisticsMonth;
byId('stats-year').add(new Option(statisticsYear, statisticsYear));
byId('stats-year').addEventListener('change', () => {statisticsYear = byId('stats-year').value; loadWorkspace();});
byId('stats-month').addEventListener('change', () => {statisticsMonth = byId('stats-month').value; loadWorkspace();});
function setStatisticsMode(mode) {
  statisticsMode = mode;
  byId('stats-mode-year').setAttribute('aria-pressed', String(mode === 'year'));
  byId('stats-mode-month').setAttribute('aria-pressed', String(mode === 'month'));
  byId('stats-year').hidden = mode !== 'year'; byId('stats-month').hidden = mode !== 'month';
  return loadWorkspace();
}
byId('stats-mode-year').addEventListener('click', () => setStatisticsMode('year'));
byId('stats-mode-month').addEventListener('click', () => setStatisticsMode('month'));

async function loadWorkspace() {
  const request = ++workspaceRequest, kind = workspace;
  byId('workspace-message').textContent = '正在載入…';
  byId('workspace-previous').disabled = byId('workspace-next').disabled = true;
  try {
    const query = new URLSearchParams({q:byId('workspace-query').value, page:workspacePage});
    if (workspaceSerial) query.set('serial', workspaceSerial);
    if (kind === 'history') for (const key of ['source','operation','start','end']) query.set(key, byId('history-' + key).value);
    if (kind === 'statistics') {query.set('mode', statisticsMode); query.set('period', statisticsMode === 'year' ? statisticsYear : statisticsMonth);}
    const result = await api('/api/repairs/' + kind + '?' + query);
    if (request !== workspaceRequest || kind !== workspace) return;
    const content = byId('workspace-content'); content.replaceChildren();
    if (kind === 'statistics') {renderStatistics(result, content); return;}
    if (kind === 'masters') {
      masterData = result;
      renderMasters(result, content);
      byId('workspace-message').textContent = '主檔不自動改寫歷史案件。'; return;
    }
    workspacePage = result.page;
    if (kind === 'dbn') content.append(workspaceHeading(['S/N','板件名稱','機台','客戶','產品','站點','紀錄日期','操作'], 'dbn-heading'));
    if (kind === 'mappings') content.append(workspaceHeading(['S/N','板件名稱','Part Number','操作'], 'serial-map-heading'));
    if (kind === 'history') renderHistory(result.data, content);
    for (const row of result.data) {
      if (kind === 'dbn') content.append(renderDbnRow(row));
      else if (kind === 'mappings') {
        const card = element('div', 'serial-map-row');
        const actions = element('span', 'serial-map-actions'); actions.dataset.label = '操作'; actions.append(action('修改', () => editMapping(row)));
        card.append(labeledCell('S/N', row.serial_no, 'serial-map-serial'), labeledCell('板件名稱', row.board_name), labeledCell('Part Number', row.board_part_code), actions);
        content.append(card);
      }
    }
    if (!result.total) content.append(element('p', 'serial-map-empty', '沒有符合條件的紀錄。'));
    byId('workspace-message').textContent = `${workspaceSerial ? 'S/N ' + workspaceSerial + ' · ' : ''}共 ${result.total} 筆${kind === 'history' ? '異動事件（每頁最多 20 事件，展開各變更欄位）' : ''}`;
    byId('workspace-page').textContent = `第 ${result.page}／${Math.max(1, Math.ceil(result.total / 20))} 頁`;
    byId('workspace-previous').disabled = result.page <= 1;
    byId('workspace-next').disabled = result.page * 20 >= result.total;
  } catch (error) {
    if (request !== workspaceRequest) return;
    byId('workspace-content').replaceChildren(); byId('workspace-message').textContent = error.message;
  }
}

function renderHistory(events, container) {
  const sources = {repair_records:'送修',dbn_records:'DBN',serial_board_mappings:'S/N 對應',repair_machine_models:'機台對應',repair_model_boards:'板件對應',repair_board_prices:'價格',repair_attachments:'附件'};
  const operations = {INSERT:'新增',UPDATE:'修改',DELETE:'刪除'};
  const labels = {...fieldLabels,board_name:'板件名稱',customer_code:'客戶',product_code:'產品',station_code:'站點',issue_type:'DBN 類型',issue_description:'異常描述',dut:'DUT',socket_file_id:'Socket File 版本',dut_pin_snapshot:'PIN',board_repair_cents:'板修金額（分）',external_repair_cents:'外修金額（分）',contract_repair_cents:'合約金額（分）',warranty_repair_cents:'保固金額（分）'};
  function value(field, data) {
    if (data == null) return '—';
    if (data === '') return '（空白）';
    if (field === 'is_opened') return data ? '已開單' : '未開單';
    if (field === 'dut_pin_snapshot') return Object.entries(data).map(([dut,pins]) => `DUT${dut}: ${Array.isArray(pins) ? pins.join(', ') : '尚無對應'}`).join('\n') || '（空白）';
    return typeof data === 'object' ? JSON.stringify(data) : String(data);
  }
  const rows = [];
  for (const event of events) {
    const identity = `${event.serial_no || '—'}－${event.board_name || '—'}`;
    const prefix = [new Date(event.changed_at).toLocaleString('zh-TW', {timeZone:'Asia/Taipei'}), `${sources[event.source_table] || event.source_table}／${operations[event.operation] || event.operation}`, identity];
    const changes = Object.entries(event.changes || {}).filter(([field]) => !['id','version','created_at','updated_at','source_system','source_record_id'].includes(field));
    for (const [field, change] of changes) rows.push([...prefix, labels[field] || field, value(field, change.old), value(field, change.new)]);
    if (!changes.length) rows.push([...prefix, '—', '—', '—']);
  }
  const result = table(['時間','類型／操作','S/N－板件名稱','變更欄位','舊值','新值'], rows);
  result.className = 'table-wrap history-table'; container.append(result);
}

function pinDetails(record) {
  const result = element('details', 'pin-details dbn-pin-details');
  result.append(element('summary', '', `DUT ${record.dut} · PIN`));
  const snapshot = record.dut_pin_snapshot || {}, rows = Object.entries(snapshot).map(([dut, pins]) => [dut, Array.isArray(pins) ? [...new Set(pins)] : null]);
  const common = rows.length > 1 && rows.every(([, pins]) => pins?.length)
    ? rows[0][1].filter(pin => rows.every(([, pins]) => pins.includes(pin))) : [];
  function pinLine(label, content, shared = false) {
    const line = element('div', 'dut-pin-line' + (shared ? ' dut-pin-common' : ''));
    line.append(element('strong', '', label), element('span', '', content)); return line;
  }
  if (common.length) result.append(pinLine('共用PIN:', [...new Set(common)].join(', '), true));
  for (const [dut, pins] of rows) {
    const remaining = pins?.filter(pin => !common.includes(pin));
    result.append(pinLine(`DUT${dut}:`, pins ? (remaining.length ? remaining.join(', ') : '無額外 PIN') : '尚無對應'));
  }
  if (!record.socket_file_id) result.append(element('p', 'hint', '此產品沒有 Socket 對應；不推測 PIN。'));
  return result;
}

function workspaceHeading(labels, className) {
  const row = element('div', 'list-heading ' + className);
  for (const label of labels) row.append(element('span', '', label)); return row;
}

function labeledCell(label, value, className = '') {
  const cell = element('span', className, value ?? '—'); cell.dataset.label = label; return cell;
}

function renderDbnRow(record) {
  const row = element('div', 'dbn-row'), board = labeledCell('板件名稱', record.board_name);
  board.append(element('div', 'dbn-issue-type', record.issue_type));
  if (record.dut) board.append(pinDetails(record));
  if (record.issue_description) board.append(element('p', 'detail-text', record.issue_description));
  const controls = labeledCell('操作', '', 'dbn-actions');
  const edit = () => controls.replaceChildren(action('修改內容', () => editDbn(record), 'button primary'), action('刪除', async () => {
    if (!window.confirm(`永久刪除這筆 DBN（${record.serial_no}）？送修案件不受影響。`)) return;
    await api('/api/repairs/dbn/' + encodeURIComponent(record.id), 'DELETE', {expected_version:record.version}); await refreshFeatures();
  }, 'button danger'), action('取消', reset));
  const reset = () => controls.replaceChildren(action('編輯', edit)); reset();
  row.append(labeledCell('S/N', record.serial_no, 'dbn-serial'), board, labeledCell('機台', record.machine_code),
    labeledCell('客戶', record.customer_code), labeledCell('產品', record.product_code || '-'), labeledCell('站點', record.station_code || '-'),
    labeledCell('紀錄日期', new Date(record.created_at).toLocaleDateString('zh-TW', {timeZone:'Asia/Taipei'}), 'dbn-date'), controls);
  return row;
}

function repairTimeline(record) {
  const section = element('section', 'detail-section'); section.append(element('h3', '', '維修時程'));
  const timeline = element('div', 'repair-timeline');
  const stages = [['損壞', record.occurred_on], ['送修', record.sent_on], ['回修', record.returned_on]];
  stages.forEach(([label, date], index) => {
    if (index) {
      const before = stages[index - 1][1], days = before && date ? Math.round((Date.parse(date) - Date.parse(before)) / 86400000) + ' 天' : '—';
      const link = element('div', 'timeline-link'); link.append(element('span', 'timeline-days', days)); timeline.append(link);
    }
    const step = element('div', 'timeline-step');
    step.append(element('span', 'timeline-dot'), element('div', 'timeline-label', label), element('div', 'timeline-date', date || '未記錄')); timeline.append(step);
  });
  section.append(timeline); return section;
}

function renderQuickResults(summary, records, dbn, container) {
  const board = element('section', 'quick-board-summary'), heading = element('div', 'quick-summary-heading'), title = element('div');
  title.append(element('h2', 'quick-summary-title', summary.mapping?.board_name || records.data[0]?.description || dbn.data[0]?.board_name || '—'), element('div', 'quick-summary-serial', 'S/N ' + summary.serial_no));
  heading.append(title, element('div', 'quick-summary-count', `${records.total} 筆送修 · ${dbn.total} 筆 DBN`)); board.append(heading);
  const grid = element('div', 'quick-summary-grid');
  for (const [label, value] of [['Part Number',summary.mapping?.board_part_code || '—'], ['Model',summary.models.join('、') || '—'], ['機台',summary.machines.join('、') || '—'], ['板件資料',summary.mapping ? '已關聯' : '—']]) {
    const field = element('div', 'quick-summary-field'); field.append(element('label', '', label), element('div', '', value)); grid.append(field);
  }
  board.append(grid); container.append(board);
  function group(title, result) {
    const section = element('section', 'quick-result-section'), head = element('div', 'quick-section-heading'), list = element('div', 'quick-result-list');
    head.append(element('h2', '', title), element('span', 'quick-section-count', `${result.total} 筆${result.total > 20 ? '（目前顯示前 20 筆）' : ''}`));
    if (!result.total) list.append(element('p', 'quick-empty', `沒有此 S/N 的${title}。`));
    section.append(head, list); container.append(section); return list;
  }
  const repairList = group('送修紀錄', records);
  for (const row of records.data) {
    const card = element('article', 'quick-record-card'), top = element('div', 'quick-record-top');
    top.append(statusPill(row.current_status), element('span', 'failure-tag-pill', `${row.repair_type} · ${row.repair_amount == null ? '金額未填' : row.repair_amount.toLocaleString('zh-TW') + ' 元'}`),
      element('span', 'failure-tag-pill', row.failure_tag), element('span', 'quick-record-date', `損壞 ${row.occurred_on}${row.sent_on ? ' · 送修 ' + row.sent_on : ''}${row.returned_on ? ' · 回修 ' + row.returned_on : ''}`));
    const meta = element('div', 'quick-record-meta'); meta.append(element('span', '', row.machine_code), element('span', '', row.model), element('span', '', row.is_opened ? '已開單' : '未開單'));
    const controls = element('div', 'quick-record-actions'); controls.append(action('查看送修詳情', () => openDetail(row.id)));
    card.append(top, meta, element('div', 'quick-record-description', row.failure_description), controls); repairList.append(card);
  }
  const dbnList = group('DBN 紀錄', dbn);
  for (const row of dbn.data) {
    const card = element('article', 'quick-record-card');
    card.append(element('div', 'quick-record-date', new Date(row.created_at).toLocaleString('zh-TW', {timeZone:'Asia/Taipei'})),
      element('div', 'quick-record-meta', `機台：${row.machine_code} · ${row.model}`),
      element('div', 'quick-dbn-tags', `客戶：${row.customer_code} · 產品：${row.product_code || '-'} · 站點：${row.station_code || '-'}`), element('p', '', row.issue_type));
    if (row.dut) card.append(pinDetails(row)); if (row.issue_description) card.append(element('p', 'detail-text', row.issue_description)); dbnList.append(card);
  }
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
  inputs.model = formField('Model'); inputs.model.readOnly = true; inputs.model.required = false;
  const order = ['machine','model','board','part','serial','customer','product','station','kind','dut','description'];
  for (const key of order) {inputs[key].dataset.field = key; byId('operations-fields').append(fieldContainers.get(inputs[key]));}
  inputs.serial.maxLength = 64; inputs.part.readOnly = true;
  const mappingHint = element('p', 'wide hint'); byId('operations-fields').append(mappingHint);
  const preview = element('div', 'wide hint'); byId('operations-fields').append(preview);
  function boards(preferred = inputs.board.value) {
    const model = catalogs.machines.find(row => row.machine_code === inputs.machine.value)?.model;
    inputs.model.value = model || '';
    const choices = catalogs.boards.filter(row => row.model === model && (!localMapping || (row.board_name === localMapping.board_name && row.board_part_code === localMapping.board_part_code)));
    fillSelect(inputs.board, choices.map(row => row.board_name), '請選擇板件');
    inputs.board.value = choices.some(row => row.board_name === preferred) ? preferred : localMapping ? choices[0]?.board_name || '' : '';
    inputs.board.disabled = Boolean(localMapping);
    inputs.part.value = choices.find(row => row.board_name === inputs.board.value)?.board_part_code || '';
    mappingHint.textContent = localMapping ? `S/N 已鎖定 ${localMapping.board_name}／${localMapping.board_part_code}，請選相容機台。` : '輸入 S/N 後查詢主檔；新增 DBN 不會建立送修案件。';
  }
  function products() {
    fillSelect(inputs.product, [...new Set(dbnCatalog.combinations.filter(row => row.customer_code === inputs.customer.value).map(row => row.product_code))], '請選擇產品');
    inputs.product.required = dbnCatalog.combinations.some(row => row.customer_code === inputs.customer.value);
    inputs.product.disabled = !inputs.product.required;
    stations();
  }
  function stations() {
    const choices = dbnCatalog.combinations.filter(row => row.customer_code === inputs.customer.value && row.product_code === inputs.product.value).map(row => row.station_code);
    fillSelect(inputs.station, choices, '請選擇站點'); inputs.station.required = inputs.product.required;
    inputs.station.disabled = !choices.length;
    issue();
  }
  function issue() {
    const usesDut = ['Group', 'Single Dut'].includes(inputs.kind.value);
    const usesDescription = ['RTE', 'Other'].includes(inputs.kind.value);
    inputs.dut.required = usesDut; inputs.dut.disabled = !usesDut;
    inputs.description.required = usesDescription; inputs.description.disabled = !usesDescription;
    fieldContainers.get(inputs.dut).hidden = !usesDut;
    fieldContainers.get(inputs.description).hidden = !usesDescription;
    preview.hidden = !usesDut;
    preview.replaceChildren();
    if (!usesDut || !inputs.dut.value) return;
    const match = /^(\d{1,4})(?:\s*-\s*(\d{1,4}))?$/.exec(inputs.dut.value.trim());
    if (!match) {preview.textContent = 'DUT 格式錯誤'; return;}
    const first = Number(match[1]), last = Number(match[2] || match[1]);
    const socket = dbnCatalog.sockets.find(row => row.product_code === inputs.product.value);
    if (first < 1 || last < first || last > 2048 || last - first > 7 || (inputs.kind.value === 'Single Dut' && match[2])) {preview.textContent = 'Single Dut 限單一編號；Group 限連續 1–8 個 DUT'; return;}
    const canonical = first === last ? String(first) : `${first}-${last}`;
    const same = record && record.product_code === inputs.product.value && record.dut === canonical;
    if (!same && socket && last > socket.dut_count) {preview.textContent = 'DUT 超出此 Socket File 範圍'; return;}
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
  let number, board, part;
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
  board = formField('板件名稱', 'select');
  board.replaceChildren(new Option('請選板件', ''));
  for (const [key, row] of pairs) board.add(new Option(`${row.board_name} — ${row.board_part_code}`, key));
  if (record) board.value = JSON.stringify([record.board_name, record.board_part_code]);
  board.disabled = !pairs.length;
  part = formField('Part Number'); part.readOnly = true; part.required = false;
  const preview = () => {
    const selected = pairs.find(([key]) => key === board.value);
    part.value = selected?.[1].board_part_code || '';
    part.placeholder = '選擇板件後自動帶入';
  };
  board.addEventListener('change', preview); preview(); number.focus();
}

function renderMasters(result, container) {
  const groups = [
    ['machines','machine','機台／機型', [['machine_code','機台'],['model','Model']]],
    ['boards','board','板件對應', [['model','Model'],['board_name','板件名稱'],['board_part_code','Part Number']]],
    ['prices','price','價格（元；未設定不等於零元）', [['model','Model'],['board_name','板件名稱'],['board_part_code','Part Number'],['board_repair_cents','板修'],['external_repair_cents','外修'],['contract_repair_cents','合約'],['warranty_repair_cents','保固']]]
  ];
  for (const [key, kind, title, columns] of groups) {
    const section = element('section', 'master-section'); section.append(element('h2', '', title));
    const wrapper = element('div', 'table-wrap'), grid = element('table'), head = element('thead'), header = element('tr'), body = element('tbody');
    for (const label of [...columns.map(([,label]) => label), '操作']) header.append(element('th', '', label));
    head.append(header); grid.append(head, body);
    for (const record of result[key]) {
      const row = element('tr');
      for (const [field] of columns) {
        const value = record[field];
        row.append(element('td', '', field.endsWith('_cents') ? (value == null ? '未設定' : (value / 100).toLocaleString('zh-TW', {maximumFractionDigits:2}) + ' 元') : value));
      }
      const controls = element('td'); controls.append(action('修改', () => editMaster(kind, record))); row.append(controls); body.append(row);
    }
    wrapper.append(grid); section.append(wrapper);
    if (!result[key].length) section.append(element('p', 'hint', '尚無對應資料，可使用上方按鈕新增。'));
    container.append(section);
  }
}

async function editMaster(kind, record = null) {
  const original = await api('/api/repairs/masters');
  if (record && original.token !== masterData?.token) throw new Error('主檔已變更，請重新查詢清單再修改');
  const fields = {};
  openOperations((record ? '修改' : '新增／修改') + {machine:'機台對應', board:'板件對應', price:'價格'}[kind], async freeze => {
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
  if (!record) for (const key of ['machine_code', 'model', 'board_name', 'board_part_code']) fields[key]?.addEventListener('change', autofill);
  for (const [key, input] of Object.entries(fields)) {
    input.dataset.field = key;
    if (record) input.value = key.endsWith('_cents') ? (record[key] == null ? '' : (record[key] / 100).toFixed(2)) : record[key] ?? '';
    // Row edits must keep their original identity; use the add form for new keys.
    if (record) input.readOnly = kind === 'machine' ? key === 'machine_code' : ['model','board_name'].includes(key) || (kind === 'price' && key === 'board_part_code');
  }
  const hint = element('p', 'wide hint', '修改只影響後續選擇與儲存；不改寫歷史案件、S/N 主檔、金額或 PIN 快照。');
  byId('operations-fields').append(hint);
}

async function renderDetailFeatures(record, container, stillCurrent) {
  const [meta, chainResult] = await Promise.all([api(`/api/repairs/records/${encodeURIComponent(record.id)}/attachment`), api(`/api/repairs/records/${encodeURIComponent(record.id)}/chain`)]);
  if (!stillCurrent()) return;
  const previousAttempt = chainResult.data.find(row => row.id === record.retry_of_record_id);
  if (previousAttempt?.current_status === '結案（FAIL）' && !['結案（PASS）','結案（FAIL）'].includes(record.current_status)) {
    container.append(element('p', 'notice retry-warning', '上次維修未完成（前一輪結案結果為 FAIL）；本輪仍待處理。'));
  }
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
    picker.setAttribute('aria-label', '選擇此案 Fail Log');
    fileSection.append(picker); mountFilePicker(picker, fileSection);
    fileSection.append(action('上傳 Fail Log', async () => {
      if (!picker.files?.[0]) throw new Error('請先選擇檔案');
      const attachment = await encodeFile(picker.files[0]);
      await api(`/api/repairs/records/${encodeURIComponent(record.id)}/attachment`, 'POST', {expected_version:record.version, attachment});
      await openDetail(record.id);
    }));
  }
  container.append(fileSection);
  container.append(renderRepairChain(record, chainResult.data), action('查看此 S/N 的 DBN', () => {detail.close(); return openWorkspace('dbn', record.serial_no);}));
  if (record.current_status === '取回驗證') {
    const resolve = element('section', 'detail-section'); resolve.append(element('h3', '', '驗證結果'));
    const passButton = action('PASS・成功維修', async () => {
      if (!window.confirm('確認 PASS 結案？')) return;
      await api(`/api/repairs/records/${encodeURIComponent(record.id)}/resolve`, 'POST', {expected_version:record.version, passed:true});
      await refreshFeatures(); await openDetail(record.id);
    });
    const failButton = action('FAIL・建立下一筆維修', () => retryRepair(record), 'button danger');
    passButton.disabled = failButton.disabled = record.repair_amount == null;
    resolve.append(passButton, failButton);
    if (record.repair_amount == null) resolve.append(element('p', 'hint', '金額未設定，請先補齊價格，在編輯案件時勾選「重新套用目前價目」並儲存，再結案。'));
    container.append(resolve);
  }
  const deleteButton = action('刪除此筆送修', async () => {
    if (!window.confirm(`永久刪除 ${record.serial_no} 的這筆送修及附件？連續送修鏈不允許刪除。`)) return;
    await api('/api/repairs/records/' + encodeURIComponent(record.id), 'DELETE', {expected_version:record.version});
    detail.close(); selectedRecord = null; await refreshFeatures();
  }, 'button danger');
  deleteButton.disabled = chainResult.data.length > 1;
  container.append(deleteButton);
  if (deleteButton.disabled) container.append(element('p', 'hint', '此案屬於連續送修鏈，不能單獨刪除，以保留各輪追溯關係。'));
}

function renderRepairChain(record, rows) {
  const section = element('section', 'detail-section');
  section.append(element('h3', '', `連續送修紀錄（${record.serial_no}）`));
  if (rows.length < 2 && !rows.some(row => ['結案（PASS）','結案（FAIL）'].includes(row.current_status))) {
    section.append(element('p', 'history-empty', '尚無連續送修紀錄')); return section;
  }
  const list = element('div', 'history-list');
  for (const [index, row] of rows.entries()) {
    const entry = element('div', 'history-entry'), button = action('', () => openDetail(row.id), 'history-item');
    button.setAttribute('aria-label', `查看第 ${index + 1} 輪送修，${row.current_status}`);
    if (row.id === record.id) button.setAttribute('aria-current', 'true');
    const date = element('span', '', row.occurred_on || '未記錄'); date.title = '損壞日期';
    const pill = statusPill(row.current_status);
    const amount = row.repair_amount == null ? '未設定' : row.repair_amount.toLocaleString('zh-TW') + ' 元';
    const summary = `第 ${index + 1} 輪 · ${row.description || '送修案件'} · ${row.repair_type} · 金額 ${amount} · ${row.failure_tag || '未分類'}`;
    const description = element('span', 'history-description', summary); description.title = summary;
    button.append(date, pill, description);
    const content = element('div', 'history-entry-detail');
    content.append(element('div', 'history-failure-description', '異常描述：' + (row.failure_description || '未提供')));
    if (row.attachment) {
      const link = element('a', 'history-log-link', 'Fail Log：' + row.attachment.filename);
      link.href = '/api/repairs/attachments/' + encodeURIComponent(row.attachment.id) + '?download=1'; content.append(link);
    } else content.append(element('div', 'history-empty', '本次未附 Fail Log'));
    entry.append(button, content); list.append(entry);
  }
  section.append(list); return section;
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
  const amount = formField('金額（依目前本機價目）'); amount.readOnly = true; amount.required = false;
  function previewAmount() {
    const cents = repairPrice(record.model, record.description, record.board_part_code, type.value);
    amount.value = cents == null ? '未設定' : (cents/100).toLocaleString('zh-TW') + ' 元';
  }
  type.addEventListener('change', previewAmount); previewAmount();
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
  const svg = svgNode('svg', {viewBox:'0 0 920 286', role:'img', 'aria-label':amounts ? '各維修分類結案金額' : '故障頻率'});
  const entries = Object.entries(groups), rawMaximum = Math.max(0, ...entries.map(([, value]) => amounts ? Object.values(value).reduce((sum, amount) => sum + amount, 0) : value));
  const maximum = amounts ? Math.max(100, rawMaximum) : Math.max(4, Math.ceil(rawMaximum / 4) * 4);
  const slot = 840 / Math.max(1, entries.length), width = Math.min(48, slot * .6), colors = ['#8b8df8','#50c5d2','#e3b341','#65c98a'];
  for (let index = 0; index <= 4; index++) {
    const value = maximum * index / 4, y = 230 - index * 50;
    svg.append(svgNode('line', {x1:60, y1:y, x2:906, y2:y, class:'stats-gridline'}),
      svgNode('text', {x:52, y:y + 4, 'text-anchor':'end', class:'stats-axis'}, (amounts ? value / 100 : value).toLocaleString('zh-TW', {maximumFractionDigits:2})));
  }
  entries.forEach(([key, values], index) => {
    let stacked = 0;
    const pairs = amounts ? Object.entries(values) : [['次數', values]];
    pairs.forEach(([label, value], color) => {
      const height = value / maximum * 200;
      const rect = svgNode('rect', {x:60 + index * slot + (slot-width)/2, y:230 - stacked - height, width, height, fill:colors[color], class:'stats-bar'});
      rect.append(svgNode('title', {}, `${key} ${label}：${amounts ? value / 100 : value}`)); svg.append(rect); stacked += height;
      if (!amounts && value) svg.append(svgNode('text', {x:60 + index*slot + slot/2, y:Math.max(25, 225 - height), 'text-anchor':'middle', class:'stats-axis'}, value));
    });
    svg.append(svgNode('text', {x:60 + index * slot + slot/2, y:272, 'text-anchor':'middle', class:'stats-axis'}, statisticsMode === 'year' ? Number(key.slice(5)) + '月' : key.slice(0,4)));
  });
  const wrapper = element('div', 'stats-chart'); wrapper.append(svg); return wrapper;
}

function renderStatistics(result, container) {
  const labels = ['板修', '外修', '合約', '保固'];
  const total = Object.values(result.frequency).reduce((sum, value) => sum + value, 0);
  const amount = Object.values(result.amounts_cents).reduce((sum, row) => sum + Object.values(row).reduce((a, b) => a + b, 0), 0);
  byId('workspace-message').textContent = `損壞 ${total} 次 · 已知結案金額 ${(amount / 100).toLocaleString('zh-TW')} 元 · 金額未設定 ${result.missing_amounts} 筆（不視為零元）`;
  const years = [...new Set([statisticsYear, ...(result.years || [])])].sort().reverse();
  fillSelect(byId('stats-year'), years); byId('stats-year').value = statisticsYear;
  function card(title, description, value) {
    const section = element('section', 'stats-card'), head = element('div', 'stats-card-head'), copy = element('div');
    copy.append(element('h2', '', title), element('div', 'stats-card-subtitle', description)); head.append(copy, element('div', 'stats-total', value)); section.append(head); return section;
  }
  const grid = element('div', 'stats-grid');
  const frequencyCard = card('故障發生頻率', '依損壞日期；同一段連續維修只計一次', `${total} 次`);
  frequencyCard.append(chart(result.frequency));
  const frequencyTable = element('details', 'stats-data'); frequencyTable.append(element('summary', '', '查看統計明細'), table(['期間','首輪損壞次數'], Object.entries(result.frequency))); frequencyCard.append(frequencyTable);
  const amountCard = card('維修金額', '依結案日期；每筆案件皆計入，包含 FAIL', (amount / 100).toLocaleString('zh-TW') + ' 元');
  amountCard.append(chart(result.amounts_cents, true));
  const legend = element('div', 'stats-legend');
  for (const [index, label] of labels.entries()) {
    const sum = Object.values(result.amounts_cents).reduce((sum, values) => sum + values[label], 0), entry = element('div', 'stats-legend-item');
    const name = element('div', 'stats-legend-label'); name.append(element('span', 'stats-swatch repair-color-' + index), element('span', '', label));
    entry.append(name, element('div', 'stats-legend-value', (sum/100).toLocaleString('zh-TW')), element('div', 'stats-legend-share', (amount ? sum/amount*100 : 0).toFixed(1) + '%')); legend.append(entry);
  }
  amountCard.append(legend);
  const amountsTable = element('details', 'stats-data'); amountsTable.append(element('summary', '', '查看金額明細'), table(['期間', ...labels], Object.entries(result.amounts_cents).map(([period, amounts]) => [period, ...labels.map(label => (amounts[label] / 100).toLocaleString('zh-TW'))]))); amountCard.append(amountsTable);
  grid.append(frequencyCard, amountCard); container.append(grid);
  const ranking = byId('ranking-sort').value === 'asc' ? [...result.ranking].sort((a,b) => a.count - b.count || a.machine.localeCompare(b.machine)) : result.ranking;
  let rank = 0, last = null;
  const rankingCard = card('機台損壞次數排名', '依損壞日期；同一段連續維修只計一次', `共 ${ranking.length} 台機台`);
  rankingCard.className = 'stats-card machine-ranking';
  rankingCard.append(table(['排名','機台','次數'], ranking.map((row, index) => {if (row.count !== last) rank = index + 1; last = row.count; return [rank, row.machine, row.count];}))); container.append(rankingCard);
}
