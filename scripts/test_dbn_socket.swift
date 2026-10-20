import Foundation
import JavaScriptCore

// Run from the repository root: swift scripts/test_dbn_socket.swift
let context = JSContext()!
let module = try String(contentsOfFile: "docs/repairs/dbn-socket.js", encoding: .utf8)
context.evaluateScript(module.replacingOccurrences(of: "export function", with: "function"))
context.evaluateScript("""
function assert(condition, label) { if (!condition) throw Error(label); }
function rejects(fn, label) { let failed=false;try { fn(); } catch (_) { failed=true; }assert(failed,label); }
assert(parseDut('').numbers.length===0,'Optional DUT');
assert(parseDut(' 0021 - 0028 ').text==='21-28','Normalize DUT whitespace and zero padding');
assert(parseDut('1001-1008').numbers.length===8,'Eight DUTs');
assert(parseDut('39').numbers[0]===39,'Single DUT');
for(const value of ['0','8-1','1,2','1-2049','1.5','1-','abc'])rejects(()=>parseDut(value),value);
rejects(()=>parseDut('513',512),'Product maximum');
const mapping={'1':['PPS137','PD1-7C1','PD49C1','PD31C1'],'2':['pd51A7','P51A7']};
const escape=s=>String(s).replace(/</g,'&lt;');
const html=socketPinsMarkup('1-2',mapping,escape);
assert(html.includes('PD49C1, PD31C1'),'Original exception spelling');
assert(html.includes('pd51A7, P51A7'),'No case normalization or deduplication');
assert(!html.includes('P49C1'),'No prefix correction');
assert(socketPinsMarkup('3',{},escape).includes('尚無對應'),'Missing mapping');
assert(socketPinsMarkup('1',{'1':['<img>']},escape).includes('&lt;img>'),'Escapes customer content');
const sharedMapping={'1':['PPS126','PD2H6','P105H5','PPS126'],'2':['PPS126','PD2H6','P106H5'],'3':['PPS126','PD4H6','P107H5']};
const beforeShared=JSON.stringify(sharedMapping);
const sharedHtml=socketPinsMarkup('1-2',sharedMapping,escape);
assert(sharedHtml.includes('<strong>共用PIN:</strong><span>PPS126, PD2H6</span>'),'Common PIN header');
assert(sharedHtml.includes('class="dut-pin-line dut-pin-common"'),'Common PIN row has a separate wrapping style');
assert(sharedHtml.includes('<strong>DUT1:</strong><span>P105H5</span>'),'First DUT only unique remainder');
assert(sharedHtml.includes('<strong>DUT2:</strong><span>P106H5</span>'),'Second DUT only unique remainder');
assert(sharedHtml.split('PPS126').length===2,'Shared PIN appears once');
assert(JSON.stringify(sharedMapping)===beforeShared,'Display never changes stored snapshot');
const partialHtml=socketPinsMarkup('1-3',sharedMapping,escape);
assert(partialHtml.includes('<strong>共用PIN:</strong><span>PPS126</span>'),'Intersection of all selected DUTs');
assert(partialHtml.split('PD2H6').length===3,'Partially shared PIN retains DUT association');
const singleHtml=socketPinsMarkup('1',sharedMapping,escape);
assert(!singleHtml.includes('共用PIN:')&&singleHtml.includes('PPS126, PD2H6, P105H5'),'Single DUT deduplicates without common header');
assert(!socketPinsMarkup('1-4',sharedMapping,escape).includes('共用PIN:'),'Missing DUT prevents common grouping');
assert(!socketPinsMarkup('1-2',{'1':['P1A1'],'2':[]},escape).includes('共用PIN:'),'Empty DUT prevents common grouping');
assert(socketPinsMarkup('1-2',{'1':['P1A1'],'2':['P1A1']},escape).split('無額外 PIN').length===3,'Identical mappings retain both DUT labels');
assert(!socketPinsMarkup('1-2',{'1':['pd1A1'],'2':['PD1A1']},escape).includes('共用PIN:'),'Exact case-sensitive token comparison');
assert(socketPinsMarkup('1-2',{'1':['<img>'],'2':['<img>']},escape).includes('&lt;img>'),'Common PIN content is escaped');
const splitMapping={};
for(let n=297;n<=304;n++)splitMapping[n]=['PD2H6',n<=300?'PPS126':'PPS61',n<=300?'PD114H5':'PD116H5',`P${n-192}H5`];
const splitHtml=socketPinsMarkup('297-304',splitMapping,escape);
assert(splitHtml.includes('<strong>共用PIN:</strong><span>PD2H6</span>'),'Only all-DUT intersection appears in common header');
assert(splitHtml.includes('<strong>DUT297:</strong><span>PPS126, PD114H5, P105H5</span>'),'First DUT retains subgroup pins');
assert(splitHtml.includes('<strong>DUT301:</strong><span>PPS61, PD116H5, P109H5</span>'),'Second subgroup retains its own pins');
assert(splitHtml.split('PPS126').length===5&&splitHtml.split('PPS61').length===5,'Subgroup PPS remains on each DUT');
const noncontiguous=socketPinsMarkup('1-3',{'1':['PPS1'],'2':['PPS2'],'3':['PPS1']},escape);
assert(!noncontiguous.includes('共用PIN:')&&noncontiguous.split('PPS1').length===3,'Partial noncontiguous sharing stays per DUT');
const elements={};
for(const id of ['dbn-dut','dbn-dut-pins','dbn-product','dbn-issue-type','dbn-issue-description','dbn-dut-field','dbn-pin-field','dbn-description-field']) elements[id]={value:'',textContent:'',innerHTML:'',validationMessage:'',setCustomValidity(s){this.validationMessage=s;},checkValidity(){return !this.validationMessage;}};
for(const type of ['','Unknown'])rejects(()=>validateDbnIssue(type,'1','text'),'Mandatory known type');
for(const dut of ['','1,2','1-9','9-1'])rejects(()=>validateDbnIssue('Group',dut,''),'Group rules');
for(const dut of ['1-1','1-2',''])rejects(()=>validateDbnIssue('Single Dut',dut,''),'Single rules');
assert(validateDbnIssue('Group','1-4','old').dut==='1-4','Group four');
assert(validateDbnIssue('Group','1-8','old').issue_description===null,'Group clears description');
assert(validateDbnIssue('Group','39','').dut==='39','Group one');
for(const type of ['RTE','Other']){
 rejects(()=>validateDbnIssue(type,'1',' \\n '),'Description required');
 assert(validateDbnIssue(type,'invalid',' fail\\ninfo ').dut===null,'Description type clears DUT');
 assert(validateDbnIssue(type,'',' fail ').issue_description==='fail','Trim description');
}
let failure=false;
const client={from(table){assert(table==='dbn_socket_files','Socket table');return {select(){return {async eq(){return failure?{error:{message:'unavailable'}}:{data:[{id:'new-version',product_code:'JAA118',dut_count:512,dut_pins:mapping}]};}};}};}};
const controller=createDbnSockets(client,id=>elements[id],escape);
let completed=false;
(async()=>{
 await controller.load();assert(controller.ready,'Catalog ready');
 elements['dbn-product'].value='JAA118';controller.open(null);
  rejects(()=>controller.payload(),'Must classify new record');
  elements['dbn-issue-type'].value='Group';
 elements['dbn-dut'].value='1-2';controller.preview();
 assert(elements['dbn-dut-pins'].innerHTML.includes('PD49C1'),'Live preview');
 assert(controller.payload().dut==='1-2','DUT payload');
 elements['dbn-dut'].value='513';controller.preview();rejects(()=>controller.payload(),'Product bound guard');
  const historical={product_code:'JAA118',issue_type:'Single Dut',dut:'1',socket_file_id:'old-version',dut_pin_snapshot:{'1':['PD49C1','OLD']}};
 controller.open(historical);assert(elements['dbn-dut-pins'].innerHTML.includes('OLD'),'Preserve old snapshot');
 elements['dbn-dut'].value='2';controller.preview();assert(!elements['dbn-dut-pins'].innerHTML.includes('OLD'),'Changed DUT uses active version');
 elements['dbn-product'].value='UNKNOWN';controller.preview();assert(elements['dbn-dut-pins'].innerHTML.includes('尚無對應'),'Unknown product allowed');
 assert(controller.payload().dut==='2','Unknown product retains DUT');
 controller.open(null);assert(elements['dbn-dut'].value==='','New form reset');
 failure=true;await controller.load();assert(!controller.ready,'Load failure');
 elements['dbn-dut'].value='1';rejects(()=>controller.payload(),'Unavailable catalog blocks nonempty DUT');
  elements['dbn-issue-type'].value='Other';elements['dbn-issue-description'].value='fail';
  assert(controller.payload().dut===null,'Other works without socket catalog');
  assert(elements['dbn-dut'].disabled&&!elements['dbn-issue-description'].disabled,'Conditional fields');
  controller.open({dut:'1-8'});assert(elements['dbn-issue-type'].value==='','Never guess legacy type');
  rejects(()=>controller.payload(),'Legacy edit needs classification');
 completed=true;
})().catch(error=>{globalThis.testFailure=String(error.stack||error);});
""")
if let error = context.exception { print(error);exit(1) }
if let error = context.objectForKeyedSubscript("testFailure"), !error.isUndefined { print(error);exit(1) }
if context.evaluateScript("completed")?.toBool() != true { print("Async tests did not finish");exit(1) }

for file in ["docs/repairs/index.html", "docs/repairs/history.html"] {
    let html = try String(contentsOfFile: file, encoding: .utf8)
    let regex = try NSRegularExpression(pattern: "(?s)<script type=\"module\">(.*?)</script>")
    let match = regex.firstMatch(in: html, range: NSRange(html.startIndex..., in: html))!
    let script = String(html[Range(match.range(at: 1), in: html)!])
        .replacingOccurrences(of: "(?m)^\\s*import[^\\n]*\\n", with: "", options: .regularExpression)
    let syntax = JSContext()!
    syntax.evaluateScript("if(false){\n\(script)\n}")
    if let error = syntax.exception { print("\(file): \(error)");exit(1) }
}
print("DUT parsing, raw PIN display, snapshots, form guards, async catalog failure and page syntax: OK")
let history = try String(contentsOfFile: "docs/repairs/history.html", encoding: .utf8)
let historyStart = history.range(of: "  function displayChanges(event){")!.lowerBound
let historyEnd = history.range(of: "  async function load(){")!.lowerBound
let historyContext = JSContext()!
historyContext.evaluateScript(String(history[historyStart..<historyEnd]))
historyContext.evaluateScript("""
const changed={source_table:'dbn_records',operation:'UPDATE',changes:{dut:{old:null,new:'1'},dut_pin_snapshot:{old:{},new:{'1':['PD49C1']}}}};
const rows=displayChanges(changed);
if(rows.length!==2||rows[0][0]!=='dut')throw Error('DUT-only edits were hidden');
const blank={source_table:'dbn_records',operation:'INSERT',changes:{dut:{old:null,new:null},dut_pin_snapshot:{old:null,new:{}}}};
if(displayChanges(blank).length!==1)throw Error('Blank optional fields clutter history');
const cleared={source_table:'dbn_records',operation:'UPDATE',changes:{dut:{old:'1',new:null}}};
if(displayChanges(cleared).length!==1)throw Error('Clearing DUT hidden');
for(const source of ['repair_records','dbn_records','serial_board_mappings']){
 const inserted={source_table:source,operation:'INSERT',serial_no:'002850948',board_name:'TP68 CPU',changes:{serial_no:{old:null,new:'002850948'},board_name:{old:null,new:'TP68 CPU'},repair_amount:{old:null,new:33800},dut:{old:null,new:'1'},dut_pin_snapshot:{old:null,new:{'1':['PD49C1']}}}};
 const original=JSON.stringify(inserted),summary=displayChanges(inserted);
 if(summary.length!==1||summary[0][0]!=='serial_no'||summary[0][1].new!=='002850948')throw Error('Insert must collapse to one serial-number summary');
 if(eventIdentity(inserted)!=='002850948－TP68 CPU')throw Error('Insert identity must retain board name');
 if(JSON.stringify(inserted)!==original)throw Error('Insert summary changed stored event');
}
if(eventIdentity({operation:'INSERT',changes:{serial_no:{new:'001234567'},board_name:{new:'HVDR PE'}}})!=='001234567－HVDR PE')throw Error('Recorded serial/board fallback missing');
if(eventIdentity({operation:'INSERT',changes:{serial_no:{new:'001234567'},description:{new:'TP68 CPU'}}})!=='001234567－TP68 CPU')throw Error('Recorded repair description fallback missing');
if(eventIdentity({operation:'INSERT'})!=='—－—')throw Error('Missing serial/board must not be guessed');
const repairEdit={source_table:'repair_records',operation:'UPDATE',serial_no:'002850948',board_name:'TP68 CPU',changes:{repair_amount:{old:1,new:2},machine_code:{old:'F22',new:'F23'}}};
if(displayChanges(repairEdit).length!==2||displayChanges(repairEdit)[0][1].old!==1)throw Error('Update details changed');
if(eventIdentity(repairEdit)!=='002850948－TP68 CPU')throw Error('Update identity changed');
""")
if let error = historyContext.exception { print(error);exit(1) }
print("History includes DUT-only edits and clearing without empty-field clutter: OK")
let formPage = try String(contentsOfFile: "docs/repairs/index.html", encoding: .utf8)
let guardStart = formPage.range(of: "    function protectEditingForms(event){")!.lowerBound
let guardEnd = formPage.range(of: "    byId(\"quick-search-form\").addEventListener")!.lowerBound
let guardContext = JSContext()!
guardContext.evaluateScript("""
const modalIds=['create-modal','retry-modal','dbn-modal','serial-map-modal'];
const elements=Object.fromEntries(modalIds.map(id=>[id,{hidden:true,value:'unsaved input'}]));
const byId=id=>elements[id];
let editingRecordId=null;
const listeners={};
const document={addEventListener(type,handler,capture){if(!capture)throw Error('Guard must run in capture phase');listeners[type]=handler;}};
function dispatch(type,id,key){
 const event={type,target:{id},key,stopped:false,prevented:false,stopImmediatePropagation(){this.stopped=true;},preventDefault(){this.prevented=true;}};
 listeners[type](event);return event;
}
function assert(ok,label){if(!ok)throw Error(label);}
""")
guardContext.evaluateScript(String(formPage[guardStart..<guardEnd]))
guardContext.evaluateScript("""
for(const id of modalIds){
 elements[id].hidden=false;
 assert(dispatch('click',id).stopped,'Backdrop must not dismiss '+id);
 assert(dispatch('keydown','input','Escape').prevented,'Escape must not dismiss '+id);
 assert(elements[id].value==='unsaved input'&&!elements[id].hidden,'Unsaved form state preserved');
 elements[id].hidden=true;
}
for(const id of ['close-create','cancel-create','close-retry','cancel-retry','close-dbn','cancel-dbn','close-serial-map','cancel-serial-map','submit-button','dbn-serial'])assert(!dispatch('click',id).stopped,'Explicit button/input must remain usable: '+id);
assert(!dispatch('keydown','input','Enter').stopped,'Enter submission remains usable');
assert(!dispatch('keydown','input','Escape').stopped,'No open form leaves Escape alone');
assert(!dispatch('click','detail-backdrop').stopped,'Read-only detail can still close');
editingRecordId='record-id';
assert(dispatch('click','detail-backdrop').stopped,'Editing detail protected');
assert(dispatch('keydown','input','Escape').stopped,'Editing detail Escape protected');
assert(!dispatch('click','close-detail').stopped,'Explicit detail close remains usable');
""")
if let error = guardContext.exception { print(error);exit(1) }
print("Form background/Escape dismissal blocked; explicit controls and unsaved values preserved: OK")
