// Test doubles for DOM/control flow, not a browser or CSS rendering test.
class TestNode {
  constructor(tag = 'div') {
    this.tag = tag; this.children = []; this.listeners = {}; this.dataset = {};
    this.attributes = {}; this.value = ''; this.disabled = false; this.checked = false;
    this.hidden = false; this.open = false; this.type = ''; this.className = '';
    this._text = ''; this.classList = {toggle(){}};
  }
  set textContent(text) {this._text = String(text); this.children = [];}
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
  reportValidity() {return true;}
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
async function fetch(path, options = {}) {
  requests.push({path:String(path), options});
  let data;
  if (options.method === 'PUT') return {ok:false, json:async()=>({error:'此紀錄已被其他人修改'})};
  if (options.method === 'POST' && path === '/api/repairs/dbn') return {ok:true,json:async()=>({data:{id:'new-dbn'}})};
  if (options.method === 'POST' && path === '/api/repairs/mappings/impact') return {ok:true,json:async()=>({repair_count:1,dbn_count:0,token:'impact-token'})};
  if (options.method === 'POST' && path === '/api/repairs/mappings') return {ok:true,json:async()=>({data:{serial_no:'002850948'}})};
  if (String(path) === '/api/repairs/catalog') data = {machines:[{machine_code:'F45', model:'T5377S'}], boards:[{model:'T5377S', board_name:'HVDR PE', board_part_code:'BPR-030837'}], statuses:['待送修','已送修','取回驗證'], repair_types:['板修','合約'], failure_tags:['RTE']};
  else if (String(path).includes('/serial-mapping')) data = {data:{serial_no:'002850948', board_name:'HVDR PE', board_part_code:'BPR-030837'}};
  else if (String(path).includes('/serial-summary')) data = {serial_no:'002850948',mapping:{board_name:'HVDR PE',board_part_code:'BPR-030837'},models:['T5377S'],machines:['F45']};
  else if (String(path).includes('/history')) data = {data:[{operation:'INSERT', source_table:'repair_records', changes:{description:{old:null,new:'HVDR PE'}}, changed_at:'2026-11-02T00:00:00Z', serial_no:testRecord.serial_no, board_name:testRecord.description}],total:1,page:1};
  else if (String(path).includes('/attachment')) data = {data:null};
  else if (String(path).includes('/chain')) data = {data:[{...testRecord,attachment:null}]};
  else if (String(path).includes('/dbn/catalog')) data = {customers:['AB','VB'],combinations:[{customer_code:'AB',product_code:'JAA118',station_code:'CP1'}],sockets:[]};
  else if (String(path).startsWith('/api/repairs/dbn?')) data = {data:[{...testDbn}], total:1, page:1, page_size:20};
  else if (String(path).startsWith('/api/repairs/mappings?')) data = {data:[{serial_no:'002850948',board_name:'HVDR PE',board_part_code:'BPR-030837',version:1}],total:1,page:1,page_size:20};
  else if (String(path).startsWith('/api/repairs/statistics?')) data = {frequency:{'2026-11':1},amounts_cents:{'2026-11':{'板修':0,'外修':0,'合約':0,'保固':0}},ranking:[{machine:'F45',count:1}],missing_amounts:0};
  else if (String(path).startsWith('/api/repairs/masters')) data = {machines:[{machine_code:'F45',model:'T5377S'}],boards:[{model:'T5377S',board_name:'HVDR PE',board_part_code:'BPR-030837'}],prices:[{model:'T5377S',board_name:'HVDR PE',board_part_code:'BPR-030837',board_repair_cents:0}],token:'master-token'};
  else if (String(path).startsWith('/api/repairs/records?')) data = {data:[{...testRecord}], total:1, page:1, page_size:20, status_counts:{'待送修':1}};
  else if (String(path).endsWith('/record-1')) data = {data:{...testRecord}};
  else throw Error('Unexpected API path: ' + path);
  return {ok:true, json:async()=>data};
}
function assert(ok, message) {if (!ok) throw Error(message);}

// TESTS
(async () => {
  // Let the bootstrap's immediate mocked promises finish first.
  for (let i = 0; i < 10; i++) await Promise.resolve();
  assert(catalogs && !nodes.create.disabled, 'Catalog loads without cloud SDK');
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
  assert(nodes['record-detail'].open, 'Right-side detail opens');
  assert(nodes['detail-content'].textContent.includes('0'), 'Zero price is not replaced by unset');
  assert(nodes['detail-content'].textContent.includes('維修時程'), 'Original repair timeline appears');
  await nodes['edit-detail'].listeners.click[0]();
  assert(!nodes['record-detail'].open && nodes.editor.open, 'Detail transitions to edit dialog');
  assert(nodes.board.disabled && nodes.part.value === 'BPR-030837', 'Serial mapping locks board and PN');
  let cancelled = false;
  nodes.editor.listeners.cancel[0]({preventDefault(){cancelled=true;}});
  assert(cancelled && nodes.editor.open, 'Escape cannot discard edit');
  nodes['failure-description'].value = '保留未儲存描述';
  await nodes['record-form'].listeners.submit[0]({preventDefault(){}});
  assert(nodes.editor.open && nodes['failure-description'].value === '保留未儲存描述', 'Conflict preserves entered data');
  assert(nodes['form-message'].textContent.includes('此紀錄已被其他人修改'), 'Conflict is shown');
  assert(!nodes.save.disabled && nodes.board.disabled, 'Controls recover and mapped board stays locked');
  nodes.editor.close();
  await openWorkspace('dbn');
  assert(!nodes['workspace-view'].hidden && nodes['records-view'].hidden, 'DBN workspace opens');
  const dbnRow = nodes['workspace-content'].children.find(node => node.className === 'dbn-row');
  assert(dbnRow?.children.length === 8, 'DBN uses original column layout');
  assert(dbnRow.textContent.includes('共用PIN:'), 'Common PIN uses original grouped presentation');
  await openWorkspace('mappings');
  assert(nodes['workspace-content'].textContent.includes('BPR-030837'), 'S/N master list renders');
  await openWorkspace('history');
  assert(nodes['workspace-content'].textContent.includes('INSERT'), 'Global audit list renders');
  await openWorkspace('statistics');
  assert(nodes['workspace-content'].textContent.includes('F45'), 'Statistics chart/table/ranking render');
  assert(nodes['workspace-content'].children[0].className === 'stats-grid', 'Statistics uses original card structure');
  await setStatisticsMode('month');
  assert(nodes['stats-year'].hidden && !nodes['stats-month'].hidden, 'Original month/year controls switch');
  assert(requests.some(request => request.path.includes('statistics?') && request.path.includes('mode=month')), 'Month control uses local statistics endpoint');
  await openWorkspace('masters');
  assert(nodes['workspace-content'].textContent.includes('HVDR PE'), 'Reference and price tables render');
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
  await nodes['operations-form'].listeners.submit[0]({preventDefault(){}});
  const mappingWrite = requests.find(request => request.path === '/api/repairs/mappings' && request.options.method === 'POST');
  assert(mappingWrite && JSON.parse(mappingWrite.options.body).impact_token === 'impact-token', 'S/N write uses preview token');
  assert(JSON.parse(mappingWrite.options.body).sync_history === true, 'History synchronization is explicitly confirmed');
  setView(true);
  assert(nodes['workspace-view'].hidden && !nodes['quick-view'].hidden, 'Navigation leaves management workspace');
  assert(requests.every(request => request.path.startsWith('/api/')), 'All UI data requests are local');
  globalThis.companyUiDone = true;
})().catch(error => {globalThis.companyUiFailure = String(error.stack || error);});
