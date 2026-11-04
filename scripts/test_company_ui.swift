import Foundation
import JavaScriptCore

// Syntax plus isolated mock-DOM suites; real browser/Windows acceptance is separate.
for file in ["company/web/app.js", "company/web/repairs.js", "company/web/features.js"] {
    let script = try String(contentsOfFile: file, encoding: .utf8)
    let context = JSContext()!
    context.evaluateScript("if(false){\n\(script)\n}")
    if let error = context.exception { print("\(file): \(error)");exit(1) }
}
print("Company UI JavaScript syntax: OK (not a browser interaction test)")

let homeHTML = try String(contentsOfFile: "company/web/index.html", encoding: .utf8)
let homeRegex = try NSRegularExpression(pattern: "\\bid=\"([^\"]+)\"")
let homeIds = homeRegex.matches(in: homeHTML, range: NSRange(homeHTML.startIndex..., in: homeHTML)).map {
    String(homeHTML[Range($0.range(at: 1), in: homeHTML)!])
}
let homeContext = JSContext()!
let homeJSON = String(data: try JSONSerialization.data(withJSONObject: homeIds), encoding: .utf8)!
homeContext.evaluateScript("const homeIds=\(homeJSON);")
let homeTests = try String(contentsOfFile: "scripts/company_home_ui_test.js", encoding: .utf8).components(separatedBy: "// TESTS")
homeContext.evaluateScript(homeTests[0])
homeContext.evaluateScript(try String(contentsOfFile: "company/web/app.js", encoding: .utf8))
homeContext.evaluateScript(homeTests[1])
if let error = homeContext.exception { print(error);exit(1) }
if let error = homeContext.objectForKeyedSubscript("companyUiFailure"), !error.isUndefined { print(error);exit(1) }
if homeContext.objectForKeyedSubscript("companyUiDone")?.toBool() != true { print("Homepage mock tests did not complete");exit(1) }
print("SPMS homepage mock-DOM suite: OK")

let html = try String(contentsOfFile: "company/web/repairs.html", encoding: .utf8)
func values(_ pattern: String) throws -> [String] {
    let regex = try NSRegularExpression(pattern: pattern)
    return regex.matches(in: html, range: NSRange(html.startIndex..., in: html)).map {
        String(html[Range($0.range(at: 1), in: html)!])
    }
}
let ids = try values("\\bid=\"([^\"]+)\"")
if Set(ids).count != ids.count { print("Duplicate company HTML IDs");exit(1) }
let tests = try String(contentsOfFile: "scripts/company_ui_test.js", encoding: .utf8).components(separatedBy: "// TESTS")
for suite in ["normal", "resilience", "edit_access"] {
    let context = JSContext()!
    for (name, array) in [("pageIds", ids), ("pageStatuses", try values("data-status=\"([^\"]*)\"")), ("pageCounters", try values("data-count=\"([^\"]+)\"")), ("pageWorkspaces", try values("data-workspace=\"([^\"]+)\""))] {
        let json = String(data: try JSONSerialization.data(withJSONObject: array), encoding: .utf8)!
        context.evaluateScript("const \(name)=\(json);")
    }
    context.evaluateScript(tests[0])
    context.evaluateScript(try String(contentsOfFile: "company/web/repairs.js", encoding: .utf8))
    context.evaluateScript(try String(contentsOfFile: "company/web/features.js", encoding: .utf8))
    if suite != "edit_access" {context.evaluateScript("editToken='test-suite-token'; updateEditControls();")}
    let suitePath = suite == "resilience" ? "scripts/company_ui_resilience_test.js" : "scripts/company_ui_edit_access_test.js"
    context.evaluateScript(suite == "normal" ? tests[1] : try String(contentsOfFile: suitePath, encoding: .utf8))
    if let error = context.exception { print(error);exit(1) }
    if let error = context.objectForKeyedSubscript("companyUiFailure"), !error.isUndefined { print(error);exit(1) }
    if context.objectForKeyedSubscript("companyUiDone")?.toBool() != true { print("Company mock UI tests did not complete: \(suite)");exit(1) }
    print("Company UI mock-DOM \(suite) suite: OK")
}
print("Company UI mock-DOM flows: navigation, S/N, detail/edit, conflicts, DBN create, mapping preview/sync, masters, history, statistics: OK")
