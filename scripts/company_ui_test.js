// Test doubles for DOM/control flow, not a browser or CSS rendering test.
class TestNode {
  constructor(tag = 'div') {
    this.tag = tag; this.children = []; this.listeners = {}; this.dataset = {};
    this.attributes = {}; this.value = ''; this.disabled = false; this.checked = false;
    this.hidden = false; this.open = false; this.type = ''; this.className = '';
    this._text = ''; this.classList = {toggle(){}};
  }
  set textContent(text) {this._text = String(text); this.children = [];}
  set value(value) {this._value = value; if (this.type === 'file' && value === '') this.files = [];}
  get value() {return this._value;}
  get textContent() {return this._text + this.children.map(child => child.textContent).join('');}
  set innerHTML(value) {throw Error('User data must not be rendered with innerHTML');}
  append(...nodes) {
    for (const node of nodes) {
      if (node.parentNode) {const index = node.parentNode.children.indexOf(node); if (index >= 0) node.parentNode.children.splice(index, 1);}
      node.parentNode = this; this.children.push(node);
    }
  }
  replaceChildren(...nodes) {this.children = nodes; this._text = ''; if (this.tag === 'select') this.value = '';}
  add(option) {this.children.push(option); if (this.children.length === 1) this.value = option.value;}
  addEventListener(type, handler) {(this.listeners[type] ||= []).push(handler);}
  setAttribute(name, value) {this.attributes[name] = value;}
  removeAttribute(name) {delete this.attributes[name];}
  toggleAttribute(name, on) {if (on) this.attributes[name] = ''; else delete this.attributes[name];}
  showModal() {this.open = true;}
  close() {this.open = false;}
  focus() {}
  click() {this.clicks = (this.clicks || 0) + 1;}
  reportValidity() {return true;}
  setCustomValidity(message) {this.validationMessage = message;}
  get elements() {
    if (this._elements) return this._elements;
    const result = [];
    function walk(node) {for (const child of node.children) {if (['input','select','textarea','button'].includes(child.tag)) result.push(child); walk(child);}}
    walk(this); return result;
  }
  set elements(value) {this._elements = value;}
}
class Option extends TestNode {
  constructor(text, value) {super('option'); this.textContent = text; this.value = value;}
}
class URLSearchParams {
  constructor(values) {this.values = {...values};}
  set(key, value) {this.values[key] = value;}
  toString() {return Object.entries(this.values).map(([key, value]) => encodeURIComponent(key) + '=' + encodeURIComponent(value)).join('&');}
}
const nodes = Object.fromEntries(pageIds.map(id => [id, new TestNode()]));
nodes['operations-form'].append(nodes['operations-fields']);
for (const id of ['machine','board','failure-tag','repair-type','record-status','status-filter']) nodes[id].tag = 'select';
nodes['is-opened'].type = 'checkbox';
nodes['records-view'].hidden = true;
const fields = {serial_no:'serial', machine_code:'machine', description:'board', board_part_code:'part', failure_tag:'failure-tag', failure_description:'failure-description', repair_type:'repair-type', current_status:'record-status', is_opened:'is-opened', occurred_on:'occurred-on', sent_on:'sent-on', returned_on:'returned-on'};
for (const [name, id] of Object.entries(fields)) nodes[id].name = name;
nodes['record-form'].elements = Object.values(fields).map(id => nodes[id]);
nodes['record-form'].elements.namedItem = name => nodes[fields[name]];
nodes['record-form'].reset = () => {for (const input of nodes['record-form'].elements) {input.value = ''; input.checked = false;}};
class FormData {
  constructor(form) {this.values = form.elements.filter(input => !input.disabled && (input.type !== 'checkbox' || input.checked)).map(input => [input.name, input.type === 'checkbox' ? 'on' : input.value]);}
  [Symbol.iterator]() {return this.values[Symbol.iterator]();}
}
const navigation = pageStatuses.map(status => {const node = new TestNode('button'); node.dataset.status = status; return node;});
const counters = pageCounters.map(count => {const node = new TestNode(); node.dataset.count = count; return node;});
const workspaces = pageWorkspaces.map(kind => {const node = new TestNode('button'); node.dataset.workspace = kind; return node;});
const window = {confirm:()=>true};
const document = {
  getElementById(id) {if (!nodes[id]) throw Error('HTML is missing id: ' + id); return nodes[id];},
  createElement(tag) {return new TestNode(tag);},
  createElementNS(ns, tag) {return new TestNode(tag);},
  querySelectorAll(selector) {
    if (selector === '[data-status]') return navigation;
    if (selector === '[data-count]') return counters;
    if (selector === '[data-workspace]') return workspaces;
    throw Error('Unmocked selector: ' + selector);
  }
};
const testRecord = {id:'record-1', serial_no:'002850948', machine_code:'F45', model:'T5377S', description:'HVDR PE', board_part_code:'BPR-030837', failure_tag:'RTE', failure_description:'<script>not markup</script>', repair_type:'板修', repair_amount:0, current_status:'待送修', is_opened:false, occurred_on:'2026-11-02', sent_on:null, returned_on:null, version:1};
const testDbn = {id:'dbn-1',serial_no:'002850948',machine_code:'F45',model:'T5377S',board_name:'HVDR PE',board_part_code:'BPR-030837',customer_code:'AB',product_code:'JAA118',station_code:'CP1',issue_type:'Group',dut:'1-2',dut_pin_snapshot:{'1':['COMMON','ONE'], '2':['COMMON','TWO']},socket_file_id:'socket-1',created_at:'2026-11-02T00:00:00Z',version:1};
const requests = [];
let featureChain = null;
let recordWritesSucceed = false, recordReadFails = false, liveRecord = {...testRecord};
let recordReadGate = null;
async function fetch(path, options = {}) {
  requests.push({path:String(path), options});
  let data;
  if (options.method === 'PUT') {
    if (recordWritesSucceed && String(path).startsWith('/api/repairs/records/')) {
      liveRecord = {...liveRecord,...JSON.parse(options.body),version:liveRecord.version + 1};
      return {ok:true,json:async()=>({data:{...liveRecord}})};
    }
    return {ok:false, json:async()=>({error:'此紀錄已被其他人修改'})};
  }
  if (options.method === 'POST' && path === '/api/repairs/records') {
    liveRecord = {...testRecord,...JSON.parse(options.body),id:'created-1'};
    return {ok:true,json:async()=>({data:{...liveRecord}})};
  }
  if (options.method === 'POST' && path === '/api/repairs/dbn') return {ok:true,json:async()=>({data:{id:'new-dbn'}})};
  if (options.method === 'POST' && path === '/api/repairs/mappings/impact') return {ok:true,json:async()=>({repair_count:1,dbn_count:0,token:'impact-token'})};
  if (options.method === 'POST' && path === '/api/repairs/mappings') return {ok:true,json:async()=>({data:{serial_no:'002850948'}})};
  if (options.method === 'POST' && path === '/api/repairs/masters') return {ok:true,json:async()=>({data:{}})};
  if (String(path) === '/api/repairs/catalog') data = {machines:[{machine_code:'F45', model:'T5377S'}], boards:[{model:'T5377S', board_name:'HVDR PE', board_part_code:'BPR-030837'}], statuses:['待送修','已送修','取回驗證'], repair_types:['板修','合約'], failure_tags:['RTE']};
  else if (String(path).includes('/serial-mapping')) data = {data:{serial_no:'002850948', board_name:'HVDR PE', board_part_code:'BPR-030837'}};
  else if (String(path).includes('/serial-summary')) data = {serial_no:'002850948',mapping:{board_name:'HVDR PE',board_part_code:'BPR-030837'},models:['T5377S'],machines:['F45']};
  else if (String(path).includes('/history')) data = {data:[{operation:'INSERT', source_table:'repair_records', changes:{description:{old:null,new:'HVDR PE'}}, changed_at:'2026-11-02T00:00:00Z', serial_no:testRecord.serial_no, board_name:testRecord.description}],total:1,page:1};
  else if (String(path).includes('/attachment')) data = {data:null};
  else if (String(path).includes('/chain')) data = {data:featureChain || [{...testRecord,attachment:null}]};
  else if (String(path).includes('/dbn/catalog')) data = {customers:['AB','VB'],combinations:[{customer_code:'AB',product_code:'JAA118',station_code:'CP1'}],sockets:[]};
  else if (String(path).startsWith('/api/repairs/dbn?')) data = {data:[{...testDbn}], total:1, page:1, page_size:20};
  else if (String(path).startsWith('/api/repairs/mappings?')) data = {data:[{serial_no:'002850948',board_name:'HVDR PE',board_part_code:'BPR-030837',version:1}],total:1,page:1,page_size:20};
  else if (String(path).startsWith('/api/repairs/statistics?')) data = {frequency:{'2026-11':1},amounts_cents:{'2026-11':{'板修':0,'外修':0,'合約':0,'保固':0}},ranking:[{machine:'F45',count:1}],missing_amounts:0};
  else if (String(path).startsWith('/api/repairs/masters')) data = {machines:[{machine_code:'F45',model:'T5377S'}],boards:[{model:'T5377S',board_name:'HVDR PE',board_part_code:'BPR-030837'}],prices:[{model:'T5377S',board_name:'HVDR PE',board_part_code:'BPR-030837',board_repair_cents:0}],token:'master-token'};
  else if (String(path).startsWith('/api/repairs/records?')) data = {data:[{...testRecord}], total:1, page:1, page_size:20, status_counts:{'待送修':1}};
  else if (String(path).endsWith('/record-1') || String(path).endsWith('/created-1')) {
    if (recordReadGate) await recordReadGate;
    if (recordReadFails) throw Error('模擬讀取失敗');
    data = {data:{...liveRecord}};
  }
  else if (String(path).endsWith('/retry-2')) data = {data:{...testRecord,id:'retry-2'}};
  else throw Error('Unexpected API path: ' + path);
  return {ok:true, json:async()=>data};
}
function assert(ok, message) {if (!ok) throw Error(message);}

// TESTS
(async () => {
  // Let the bootstrap's immediate mocked promises finish first.
  for (let i = 0; i < 10; i++) await Promise.resolve();
  assert(catalogs && !nodes.create.disabled, 'Catalog loads without cloud SDK');
  const selectedFile = new TestNode('input'); selectedFile.type = 'file';
  const pickerContainer = new TestNode(), picker = mountFilePicker(selectedFile, pickerContainer);
  assert(selectedFile.hidden && picker.textContent.includes('尚未選擇檔案'), 'Shared picker replaces native file appearance without uploading');
  picker.children[0].listeners.click[0]();
  assert(selectedFile.clicks === 1, 'Picker opens the native file selection dialog');
  selectedFile.files = [{name:'<log>.asc',size:1024}]; selectedFile.listeners.change[0]();
  assert(picker.textContent.includes('<log>.asc · 1 KB') && !picker.children[2].hidden, 'Picker displays untrusted filename as text and file size');
  picker.children[2].listeners.click[0]();
  assert(!selectedFile.files.length && picker.children[2].hidden && picker.textContent.includes('尚未選擇檔案'), 'Clearing selection resets only the local input');
  assert(navigation.length === 6 && counters.length === 6, 'All status navigation entries exist');
  assert(nodes.records.children.length === 1, 'Original-style list renders');
  assert(nodes.records.children[0].children.length === 6, 'List retains original six-column structure');
  assert(nodes.records.children[0].textContent.includes('開單 X'), 'Serial/open-status subtitle');
  assert(counters.find(node => node.dataset.count === 'all').textContent === '1', 'Navigation counts reflect database');
  setView(false, '待送修');
  assert(nodes['quick-view'].hidden && !nodes['records-view'].hidden, 'Status view toggles correctly');
  assert(navigation.find(node => node.dataset.status === '待送修').attributes['aria-current'] === 'page', 'Active navigation state');
  nodes['quick-query'].value = '2850948';
  await searchSerial();
  assert(nodes['quick-query'].value === '002850948', 'Quick query normalizes serial');
  assert(requests.some(request => request.path === '/api/repairs/records?serial=002850948'), 'Quick search uses exact-serial endpoint');
  assert(nodes['quick-results'].textContent.includes('<script>not markup</script>'), 'Failure text remains plain text');
  assert(nodes['quick-results'].children[0].className === 'quick-board-summary', 'Quick search restores original board summary');
  assert(nodes['quick-results'].children.filter(node => node.className === 'quick-result-section').length === 2, 'Quick results have separate repair and DBN sections');
  await openDetail(testRecord.id);
  featureChain = [{...testRecord,current_status:'結案（FAIL）'}, {...testRecord,id:'retry-2',retry_of_record_id:testRecord.id,current_status:'取回驗證',repair_amount:null}];
  const featureContainer = new TestNode();
  await renderDetailFeatures(featureChain[1], featureContainer, () => true);
  assert(featureContainer.textContent.includes('上次維修未完成'), 'Active retries visibly warn of preceding FAIL');
  const resolveSection = featureContainer.children.find(node => node.textContent.includes('驗證結果'));
  assert(resolveSection.children.filter(node => node.tag === 'button').every(node => node.disabled), 'Unset price blocks both verification outcomes');
  assert(featureContainer.children.find(node => node.textContent === '刪除此筆送修').disabled, 'Retry chains visibly disable unsupported deletion');
  const staleContainer = new TestNode();
  await renderDetailFeatures(featureChain[1], staleContainer, () => false);
  assert(!staleContainer.children.length, 'Late detail feature responses cannot populate a different record');
  featureChain = null;
  assert(nodes['record-detail'].open, 'Right-side detail opens');
  assert(nodes['detail-content'].textContent.includes('0'), 'Zero price is not replaced by unset');
  assert(nodes['detail-content'].textContent.includes('維修時程'), 'Original repair timeline appears');
  assert(nodes['detail-content'].textContent.includes('尚無連續送修紀錄'), 'Single open repair is not presented as a retry history');
  const chain = renderRepairChain(testRecord, [
    {...testRecord,current_status:'結案（FAIL）',attachment:{id:'log/1',filename:'<log>.asc'}},
    {...testRecord,id:'retry-2',repair_amount:null,failure_description:'<script>second round</script>',attachment:null}
  ]);
  assert(chain.textContent.includes('第 1 輪') && chain.textContent.includes('第 2 輪'), 'History shows each repair round');
  assert(chain.textContent.includes('金額 0 元') && chain.textContent.includes('金額 未設定'), 'Round history distinguishes zero and unset amounts');
  assert(chain.textContent.includes('<script>second round</script>') && chain.textContent.includes('本次未附 Fail Log'), 'Round descriptions and missing attachments remain independent');
  const entries = chain.children[1].children;
  assert(entries[0].children[0].attributes['aria-current'] === 'true', 'Currently viewed repair is marked');
  assert(entries[0].children[1].children[1].href.includes('log%2F1'), 'Round attachment IDs are encoded');
  await entries[1].children[0].listeners.click[0]();
  assert(requests.some(request => request.path === '/api/repairs/records/retry-2'), 'Selecting a round requests that record, not all serial matches');
  assert(selectedRecord.id === 'retry-2', 'Selecting a round opens its details successfully');
  await openDetail(testRecord.id);
  await nodes['edit-detail'].listeners.click[0]();
  assert(!nodes['record-detail'].open && nodes.editor.open, 'Detail transitions to edit dialog');
  assert(nodes.board.disabled && nodes.part.value === 'BPR-030837', 'Serial mapping locks board and PN');
  const dateInputs = [nodes['occurred-on'],nodes['sent-on'],nodes['returned-on']];
  const originalDates = dateInputs.map(input => input.value);
  nodes['record-status'].value = '已送修';
  assert(!updateEditorDates() && nodes['sent-on'].required && !nodes['returned-on'].required, 'Sent status requires only sent date');
  const beforeInvalidDates = requests.filter(request => request.options.method === 'PUT').length;
  await nodes['record-form'].listeners.submit[0]({preventDefault(){}});
  assert(requests.filter(request => request.options.method === 'PUT').length === beforeInvalidDates && nodes.editor.open, 'Missing required dates do not send writes or discard form');
  assert(dateInputs.map(input => input.value).join('|') === originalDates.join('|'), 'Changing status never invents or clears dates');
  nodes['sent-on'].value = '2026-11-02'; assert(updateEditorDates(), 'Same-day sending is valid');
  nodes['record-status'].value = '取回驗證'; assert(!updateEditorDates() && nodes['returned-on'].required, 'Verification requires return date');
  nodes['returned-on'].value = '2026-11-01';
  assert(!updateEditorDates() && nodes['returned-on'].min === '2026-11-02', 'Return date cannot precede sent date');
  nodes['returned-on'].value = '2026-11-02'; assert(updateEditorDates(), 'Same-day return is valid');
  current = {...testRecord,current_status:'結案（PASS）',closed_on:'2026-11-02'}; nodes['record-status'].value = '結案（PASS）';
  nodes['returned-on'].value = '2026-11-03';
  assert(!updateEditorDates() && nodes['returned-on'].max === '2026-11-02', 'Closed record return is bounded by original closing date');
  current = testRecord; nodes['record-status'].value = testRecord.current_status;
  dateInputs.forEach((input,index) => {input.value = originalDates[index];});
  assert(updateEditorDates() && !nodes['sent-on'].required && !nodes['returned-on'].required && nodes['returned-on'].max === '9999-12-31', 'Switching back clears stale validation and closed-date limits');
  assert(nodes['repair-amount-preview'].textContent.includes('0 元（保留原金額）'), 'Edit preview keeps recorded zero even without current price');
  nodes.reprice.checked = true; nodes.reprice.listeners.change[0]();
  assert(nodes['repair-amount-preview'].textContent.includes('未設定（目前價目）'), 'Explicit reprice switches to current catalog preview');
  const beforeCancel = requests.filter(request => request.options.method === 'PUT').length;
  window.confirm = () => false;
  await nodes['record-form'].listeners.submit[0]({preventDefault(){}});
  assert(requests.filter(request => request.options.method === 'PUT').length === beforeCancel && nodes.editor.open && !saving, 'Cancelling reprice preserves form and sends no write');
  window.confirm = () => true;
  nodes.reprice.checked = false; nodes.reprice.listeners.change[0]();
  let cancelled = false;
  nodes.editor.listeners.cancel[0]({preventDefault(){cancelled=true;}});
  assert(cancelled && nodes.editor.open, 'Escape cannot discard edit');
  nodes['failure-description'].value = '保留未儲存描述';
  await nodes['record-form'].listeners.submit[0]({preventDefault(){}});
  assert(nodes.editor.open && nodes['failure-description'].value === '保留未儲存描述', 'Conflict preserves entered data');
  assert(nodes['form-message'].textContent.includes('此紀錄已被其他人修改'), 'Conflict is shown');
  assert(!nodes.save.disabled && nodes.board.disabled, 'Controls recover and mapped board stays locked');
  const editWrite = requests.find(request => request.options.method === 'PUT' && request.path.endsWith('/record-1'));
  assert(JSON.parse(editWrite.options.body).reprice === false, 'Ordinary edit does not implicitly request repricing');
  nodes.editor.close();
  await openWorkspace('dbn');
  assert(!nodes['workspace-view'].hidden && nodes['records-view'].hidden, 'DBN workspace opens');
  const dbnRow = nodes['workspace-content'].children.find(node => node.className === 'dbn-row');
  assert(dbnRow?.children.length === 8, 'DBN uses original column layout');
  assert(dbnRow.textContent.includes('共用PIN:'), 'Common PIN uses original grouped presentation');
  await openWorkspace('mappings');
  assert(nodes['workspace-content'].textContent.includes('BPR-030837'), 'S/N master list renders');
  await openWorkspace('history');
  assert(nodes['workspace-content'].textContent.includes('送修／新增'), 'Global audit list uses localized operation labels');
  assert(nodes['workspace-content'].textContent.includes('舊值') && nodes['workspace-content'].textContent.includes('新值'), 'Audit restores before/after columns');
  assert(!nodes['history-filters'].hidden, 'History filters appear only in history workspace');
  nodes['history-source'].value = 'dbn_records'; nodes['history-operation'].value = 'UPDATE'; nodes['history-start'].value = '2026-11-02';
  await loadWorkspace();
  assert(requests.some(request => request.path.includes('source=dbn_records') && request.path.includes('operation=UPDATE') && request.path.includes('start=2026-11-02')), 'History filters reach local API');
  const auditContainer = new TestNode();
  renderHistory([{source_table:'dbn_records',operation:'UPDATE',changed_at:'2026-11-02T00:00:00Z',changes:{is_opened:{old:false,new:true},repair_amount:{old:null,new:0},dut_pin_snapshot:{old:null,new:{'1':null}},issue_description:{old:'',new:'<script>text</script>'}}}], auditContainer);
  assert(auditContainer.textContent.includes('未開單') && auditContainer.textContent.includes('已開單'), 'History formats booleans');
  assert(auditContainer.textContent.includes('尚無對應') && auditContainer.textContent.includes('<script>text</script>'), 'History safely renders missing PINs and untrusted text');
  await openWorkspace('statistics');
  assert(nodes['history-filters'].hidden, 'Other workspaces hide history filters');
  assert(nodes['workspace-content'].textContent.includes('F45'), 'Statistics chart/table/ranking render');
  assert(nodes['workspace-content'].children[0].className === 'stats-grid', 'Statistics uses original card structure');
  await setStatisticsMode('month');
  assert(nodes['stats-year'].hidden && !nodes['stats-month'].hidden, 'Original month/year controls switch');
  assert(requests.some(request => request.path.includes('statistics?') && request.path.includes('mode=month')), 'Month control uses local statistics endpoint');
  await openWorkspace('masters');
  assert(workspaces.some(button => button.dataset.workspace === 'masters' && button.attributes['aria-current'] === 'page'), 'Requested machine/board/price navigation remains active and available');
  assert(!nodes['workspace-search'].hidden && nodes['workspace-actions'].children.length === 3, 'Master search and all three maintenance entry points remain available');
  assert(nodes['workspace-content'].textContent.includes('HVDR PE'), 'Reference and price tables render');
  assert(nodes['workspace-content'].textContent.includes('0 元') && nodes['workspace-content'].textContent.includes('未設定'), 'Price list distinguishes zero and unset in yuan');
  assert(!nodes['workspace-content'].textContent.includes('board_repair_cents'), 'Master list uses human-readable columns');
  const masterSnapshot = JSON.stringify(masterData);
  nodes['workspace-query'].value = 't5377s hvdr';
  await nodes['workspace-search'].listeners.submit[0]({preventDefault(){}});
  assert(nodes['workspace-message'].textContent.includes('顯示 2 筆'), 'Multi-term case-insensitive search matches board and price identities independently');
  assert(JSON.stringify(masterData) === masterSnapshot, 'Search retains the complete snapshot and concurrency token');
  nodes['workspace-query'].value = 'F45'; await loadWorkspace();
  assert(nodes['workspace-message'].textContent.includes('顯示 1 筆'), 'Machine code search finds machine mapping');
  nodes['workspace-query'].value = '%_'; await loadWorkspace();
  assert(nodes['workspace-message'].textContent.includes('顯示 0 筆') && nodes['workspace-content'].textContent.includes('沒有符合搜尋條件'), 'Search treats wildcard characters literally and explains no matches');
  nodes['workspace-query'].value = 'bpr-030837'; await loadWorkspace();
  assert(nodes['workspace-message'].textContent.includes('顯示 2 筆'), 'PN search retains board and price editing rows');
  const filteredPriceRow = nodes['workspace-content'].children[2].children[1].children[0].children[1].children[0];
  await filteredPriceRow.children[filteredPriceRow.children.length-1].children[0].listeners.click[0]();
  assert(nodes['operations-title'].textContent === '修改價格', 'Filtered row opens the original price editor');
  operationsDialog.close();
  nodes['workspace-query'].value = ''; await loadWorkspace();
  assert(nodes['workspace-message'].textContent.includes('顯示 3 筆'), 'Clearing search restores all mapping groups');
  await editMaster('price', masterData.prices[0]);
  let masterInputs = Object.fromEntries(nodes['operations-fields'].elements.map(input => [input.dataset.field,input]));
  assert(masterInputs.model.readOnly && masterInputs.board_name.readOnly && masterInputs.board_part_code.readOnly, 'Row price edit locks identity');
  assert(masterInputs.board_repair_cents.value === '0.00' && masterInputs.external_repair_cents.value === '', 'Price form preserves zero versus unset');
  masterInputs.board_repair_cents.value = '12.34';
  await nodes['operations-form'].listeners.submit[0]({preventDefault(){}});
  const priceWrite = requests.find(request => request.path === '/api/repairs/masters' && request.options.method === 'POST');
  const pricePayload = JSON.parse(priceWrite.options.body);
  assert(pricePayload.value.board_repair_cents === 1234 && pricePayload.value.external_repair_cents === null, 'Price editing sends integer cents and NULL');
  assert(pricePayload.expected_token === 'master-token', 'Master editing retains token conflict protection');
  await editMaster('machine', masterData.machines[0]);
  masterInputs = Object.fromEntries(nodes['operations-fields'].elements.map(input => [input.dataset.field,input]));
  assert(masterInputs.machine_code.readOnly && !masterInputs.model.readOnly, 'Machine editor locks code but permits Model changes');
  await editMaster('board', masterData.boards[0]);
  masterInputs = Object.fromEntries(nodes['operations-fields'].elements.map(input => [input.dataset.field,input]));
  assert(masterInputs.model.readOnly && masterInputs.board_name.readOnly && !masterInputs.board_part_code.readOnly, 'Board editor permits PN change without changing its key');
  masterInputs.board_part_code.value = 'NEW-PN';
  for (const handler of masterInputs.board_part_code.listeners.change || []) handler();
  assert(masterInputs.board_part_code.value === 'NEW-PN', 'Autofill does not erase explicitly edited PN');
  masterData.token = 'stale-token';
  let staleBlocked = false;
  try {await editMaster('price', masterData.prices[0]);} catch (error) {staleBlocked = error.message.includes('主檔已變更');}
  assert(staleBlocked, 'Stale list rows cannot silently overwrite newer master values');
  masterData.token = 'master-token';
  operationsDialog.close();
  await editDbn();
  assert(nodes['operations-modal'].open, 'DBN create dialog opens');
  const dbnInputs = Object.fromEntries(nodes['operations-fields'].elements.map(input => [input.dataset.field, input]));
  dbnInputs.serial.value = '2850948'; dbnInputs.machine.value = 'F45';
  dbnInputs.machine.listeners.change[0](); dbnInputs.board.value = 'HVDR PE'; dbnInputs.board.listeners.change[0]();
  assert(dbnInputs.model.value === 'T5377S', 'DBN Model display follows machine selection');
  dbnInputs.customer.value = 'AB'; dbnInputs.customer.listeners.change[0]();
  dbnInputs.product.value = 'JAA118'; dbnInputs.product.listeners.change[0](); dbnInputs.station.value = 'CP1';
  dbnInputs.kind.value = 'RTE'; dbnInputs.kind.listeners.change[0](); dbnInputs.description.value = 'DBN test';
  assert(fieldContainers.get(dbnInputs.dut).hidden && !fieldContainers.get(dbnInputs.description).hidden, 'DBN form shows only relevant issue fields');
  await nodes['operations-form'].listeners.submit[0]({preventDefault(){}});
  const dbnWrite = requests.find(request => request.path === '/api/repairs/dbn' && request.options.method === 'POST');
  assert(dbnWrite && JSON.parse(dbnWrite.options.body).board_part_code === 'BPR-030837', 'DBN form submits local validated context');
  assert(!nodes['operations-modal'].open, 'Successful DBN write closes dialog');
  await editMapping({serial_no:'002850948',board_name:'HVDR PE',board_part_code:'BPR-030837',version:1});
  const mappingFields = nodes['operations-fields'].elements;
  const partPreview = mappingFields.find(input => input.readOnly);
  assert(partPreview?.value === 'BPR-030837', 'S/N master shows independent readonly Part Number');
  const boardSelect = mappingFields.find(input => input.tag === 'select');
  boardSelect.value = ''; boardSelect.listeners.change[0]();
  assert(partPreview.value === '', 'Clearing board clears PN preview');
  boardSelect.value = JSON.stringify(['HVDR PE','BPR-030837']); boardSelect.listeners.change[0]();
  await nodes['operations-form'].listeners.submit[0]({preventDefault(){}});
  const mappingWrite = requests.find(request => request.path === '/api/repairs/mappings' && request.options.method === 'POST');
  assert(mappingWrite && JSON.parse(mappingWrite.options.body).impact_token === 'impact-token', 'S/N write uses preview token');
  assert(JSON.parse(mappingWrite.options.body).sync_history === true, 'History synchronization is explicitly confirmed');
  operationsDialog.close();
  await openDetail(testRecord.id);
  await nodes['edit-detail'].listeners.click[0]();
  nodes['failure-description'].value = '尚未儲存的內容';
  const beforeReload = requests.length;
  window.confirm = () => false;
  await nodes['reload-record'].listeners.click[0]();
  assert(requests.length === beforeReload && nodes['failure-description'].value === '尚未儲存的內容', 'Declining reload preserves input without reading or writing');
  window.confirm = () => true; recordReadFails = true;
  await nodes['reload-record'].listeners.click[0]();
  assert(nodes.editor.open && nodes['failure-description'].value === '尚未儲存的內容' && !editorReloading && !nodes.save.disabled, 'Failed reload preserves input and restores controls');
  recordReadFails = false; liveRecord = {...testRecord,version:2,failure_description:'其他分頁已更新'};
  await nodes['reload-record'].listeners.click[0]();
  assert(current.version === 2 && nodes['failure-description'].value === '其他分頁已更新', 'Confirmed reload uses newest record/version');
  assert(nodes.board.disabled, 'Reload preserves mapped-board lock');
  let releaseRead;
  recordReadGate = new Promise(resolve => {releaseRead = resolve;});
  const pendingReload = nodes['reload-record'].listeners.click[0]();
  assert(editorReloading && nodes.save.disabled && nodes.cancel.disabled, 'Reload locks write and close controls during its request');
  const duringReload = requests.length;
  await nodes['record-form'].listeners.submit[0]({preventDefault(){}});
  await closeEditor();
  assert(requests.length === duringReload && nodes.editor.open, 'Concurrent submit/cancel cannot interrupt reload');
  recordReadGate = null; releaseRead(); await pendingReload;
  await nodes.cancel.listeners.click[0]();
  assert(!nodes.editor.open && nodes['record-detail'].open && selectedRecord.version === 2, 'Cancelling edit returns to freshly read record details');
  await nodes['edit-detail'].listeners.click[0]();
  nodes['failure-description'].value = '成功更新後返回詳細資料'; recordWritesSucceed = true;
  await nodes['record-form'].listeners.submit[0]({preventDefault(){}});
  assert(!nodes.editor.open && nodes['record-detail'].open && selectedRecord.version === 3 && selectedRecord.failure_description === '成功更新後返回詳細資料', 'Successful edit returns to updated details');
  nodes['record-detail'].close();
  await openEditor();
  assert(nodes['reload-record'].hidden, 'New records do not offer reload of an existing case');
  nodes.machine.value = 'F45'; updateBoards(); nodes.board.value = 'HVDR PE'; updateBoards();
  nodes.serial.value = testRecord.serial_no; nodes['repair-type'].value = '板修'; nodes['failure-tag'].value = 'RTE'; nodes['failure-description'].value = '新增後查看';
  await nodes['record-form'].listeners.submit[0]({preventDefault(){}});
  assert(!nodes.editor.open && nodes['record-detail'].open && selectedRecord.id === 'created-1', 'Successful creation opens the newly saved record details');
  nodes['record-detail'].close();
  setView(true);
  assert(nodes['workspace-view'].hidden && !nodes['quick-view'].hidden, 'Navigation leaves management workspace');
  assert(requests.every(request => request.path.startsWith('/api/')), 'All UI data requests are local');
  globalThis.companyUiDone = true;
})().catch(error => {globalThis.companyUiFailure = String(error) + '\n' + (error.stack || '');});
