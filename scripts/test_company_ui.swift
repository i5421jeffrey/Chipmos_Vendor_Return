import Foundation
import JavaScriptCore

// Syntax smoke test only; actual browser/Windows acceptance is still required.
for file in ["company/web/app.js", "company/web/repairs.js"] {
    let script = try String(contentsOfFile: file, encoding: .utf8)
    let context = JSContext()!
    context.evaluateScript("if(false){\n\(script)\n}")
    if let error = context.exception { print("\(file): \(error)");exit(1) }
}
print("Company UI JavaScript syntax: OK (not a browser interaction test)")

let html = try String(contentsOfFile: "company/web/repairs.html", encoding: .utf8)
func values(_ pattern: String) throws -> [String] {
    let regex = try NSRegularExpression(pattern: pattern)
    return regex.matches(in: html, range: NSRange(html.startIndex..., in: html)).map {
        String(html[Range($0.range(at: 1), in: html)!])
    }
}
let ids = try values("\\bid=\"([^\"]+)\"")
if Set(ids).count != ids.count { print("Duplicate company HTML IDs");exit(1) }
let context = JSContext()!
for (name, array) in [("pageIds", ids), ("pageStatuses", try values("data-status=\"([^\"]*)\"")), ("pageCounters", try values("data-count=\"([^\"]+)\""))] {
    let json = String(data: try JSONSerialization.data(withJSONObject: array), encoding: .utf8)!
    context.evaluateScript("const \(name)=\(json);")
}
let tests = try String(contentsOfFile: "scripts/company_ui_test.js", encoding: .utf8).components(separatedBy: "// TESTS")
context.evaluateScript(tests[0])
context.evaluateScript(try String(contentsOfFile: "company/web/repairs.js", encoding: .utf8))
context.evaluateScript(tests[1])
if let error = context.exception { print(error);exit(1) }
if let error = context.objectForKeyedSubscript("companyUiFailure"), !error.isUndefined { print(error);exit(1) }
if context.objectForKeyedSubscript("companyUiDone")?.toBool() != true { print("Company mock UI tests did not complete");exit(1) }
print("Company UI mock-DOM flows: navigation, exact S/N search, detail/edit, conflict preservation: OK")
