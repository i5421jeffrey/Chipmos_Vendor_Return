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
const elements={};
for(const id of ['dbn-dut','dbn-dut-pins','dbn-product']) elements[id]={value:'',textContent:'',innerHTML:'',validationMessage:'',setCustomValidity(s){this.validationMessage=s;},checkValidity(){return !this.validationMessage;}};
let failure=false;
const client={from(table){assert(table==='dbn_socket_files','Socket table');return {select(){return {async eq(){return failure?{error:{message:'unavailable'}}:{data:[{id:'new-version',product_code:'JAA118',dut_count:512,dut_pins:mapping}]};}};}};}};
const controller=createDbnSockets(client,id=>elements[id],escape);
let completed=false;
(async()=>{
 await controller.load();assert(controller.ready,'Catalog ready');
 elements['dbn-product'].value='JAA118';controller.open(null);
 assert(controller.payload().dut===null,'Empty clears DUT');
 elements['dbn-dut'].value='1-2';controller.preview();
 assert(elements['dbn-dut-pins'].innerHTML.includes('PD49C1'),'Live preview');
 assert(controller.payload().dut==='1-2','DUT payload');
 elements['dbn-dut'].value='513';controller.preview();rejects(()=>controller.payload(),'Product bound guard');
 const historical={product_code:'JAA118',dut:'1',socket_file_id:'old-version',dut_pin_snapshot:{'1':['PD49C1','OLD']}};
 controller.open(historical);assert(elements['dbn-dut-pins'].innerHTML.includes('OLD'),'Preserve old snapshot');
 elements['dbn-dut'].value='2';controller.preview();assert(!elements['dbn-dut-pins'].innerHTML.includes('OLD'),'Changed DUT uses active version');
 elements['dbn-product'].value='UNKNOWN';controller.preview();assert(elements['dbn-dut-pins'].innerHTML.includes('尚無對應'),'Unknown product allowed');
 assert(controller.payload().dut==='2','Unknown product retains DUT');
 controller.open(null);assert(elements['dbn-dut'].value==='','New form reset');
 failure=true;await controller.load();assert(!controller.ready,'Load failure');
 elements['dbn-dut'].value='1';rejects(()=>controller.payload(),'Unavailable catalog blocks nonempty DUT');
 elements['dbn-dut'].value='';assert(!Object.hasOwn(controller.payload(),'dut'),'Legacy blank write compatibility');
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
""")
if let error = historyContext.exception { print(error);exit(1) }
print("History includes DUT-only edits and clearing without empty-field clutter: OK")
