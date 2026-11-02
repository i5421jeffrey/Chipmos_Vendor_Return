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
