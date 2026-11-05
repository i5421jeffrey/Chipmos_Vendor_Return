# Flask＋Waitress 連線對照測試

這是可退回的 HTTP 測試入口，不替換 `server.py`、不將正式資料搬到另一套架構。
Flask＋Waitress 負責 HTTP／WSGI，透過傳輸介面呼叫既有 `Handler` 的路由、欄位驗證與業務函式；不是在背後另啟一個原 HTTP server，也不額外使用 Proxy 轉接。介面、API、SQLite 與交易規則不重寫。

## 公司端

1. 先用 `install_spms_dependencies.py` 完成 Windows x64 CPython 3.13 的離線依賴安裝（Flask 3.1.3／Waitress 3.0.2），使用的 Python 必須是 SPMS `.venv`。只有測試版需要這些套件，原服務不需要。
2. 停止 SPMS，確認沒有另一個服務使用 8082。把最新 `install_spms.py` 放到 `D:\Python\SPMS`，以現有 venv 執行、確認目標並輸入 `INSTALL`。安裝器只更新程式，不啟動網站、不改 data／密碼／venv，也不安裝第三方套件。
3. 在 CMD：

```cmd
cd /d D:\Python\SPMS
.\.venv\Scripts\python.exe .\company\flask_server.py
```

或雙擊 `company\start_flask_test.cmd`。此 CMD 不會自動關閉其他程序／視窗或調整系統設定。

4. 保持視窗開啟，用**同一個瀏覽器**分別比較：

```text
主機：http://127.0.0.1:8082/repairs/
內網：http://10.1.121.135:8082/repairs/
```

預設監聽 `0.0.0.0:8082`；0.0.0.0 不是瀏覽器網址。支援原本的 `--host`、`--port`、`--client-subnet` 與 HTTP 同意規則；本版只測 HTTP，若填 TLS 憑證會停止並提示使用原服務，不會假裝使用 HTTPS。

## 資料隔離

- 每次啟動都以 SQLite backup API 從既有 `company\data\spms.sqlite3` 建立全新 `company\data\flask-tests\<隨機ID>\spms.sqlite3`，包含附件與已提交 WAL，並驗證完整性；不執行原始來源匯入。
- 編輯密碼設定複製到同一測試資料夾，因此密碼沿用，但 token 與工作階段獨立。測試目錄含真實資料與密碼雜湊，依正式資料的保管規則處理，絕不可上傳 GitHub。
- 所有測試寫入只發生在副本，**不回寫、不合併正式資料**。重新啟動會建立另一個新副本，前次測試內容保留在舊副本但不再載入。
- 原資料庫缺失、未設定密碼或副本驗證失敗時停止，不偷偷建立空白正式資料庫。若原結構需要升級，只對副本執行備份式新增遷移。
- 正式服務與測試版不應同時開啟；保持相同 port 可避免不小心連錯。測試副本不作正式主資料庫，不得拿它覆蓋原資料庫。測試檔不自動刪除，可由維護人員在停止服務後依公司保管規則處理指定的測試目錄。

## 保留的限制與診斷

- 來源仍只允許 loopback 及核准網段，預設 `10.1.121.0/24`。不因使用 Waitress 就取消來源檢查。非核准來源會收到 403 並記錄 `SOURCE_DENIED`。
- Host 只允許 `10.1.121.135:<port>`、`127.0.0.1:<port>`、`localhost:<port>`；其他 Host 收到 403 並記錄 `HOST_DENIED`。指定單一 IP 監聽則沿用該 IP 的規則。
- 同源、編輯 token、大小限制、附件格式、版本衝突、交易與倒序刪除保護均沿用既有程式。沒有跨域全開或接受任意 Host。
- 不信任 `X-Forwarded-For`／`X-Forwarded-Host`／`X-Forwarded-Proto`，Waitress 清除未信任的代理標頭，不使用 ProxyFix。伺服器看到的來源可能是公司 Proxy 的 IP，拒絕原因必須據此核對，不自行將未知來源加入白名單。
- CMD 與副本旁的 `connections.jsonl` 記錄時間、事件、來源 IP、Host、方法、路徑、狀態碼。`WRITE_REJECTED` 表示寫入驗證或業務拒絕，畫面回應提供錯誤；不記錄請求 body、query、密碼、token、cookie、附件內容。
- 日誌可能含案件 ID／公司 IP，分享前審核，不上傳公開儲存庫。每次啟動會列出測試副本、筆數與日誌路徑。
- Waitress 以 10 個工作執行緒提供 HTTP，仍只適用核准內網；未實作長期服務管理或高可用。HTTP 仍是明文，不改 Proxy／防火牆、不保證解除 Proxy 登入。

若仍出現 Proxy 視窗，請一起提供該時刻的 CMD 訊息：`SOURCE_DENIED` 表示來源限制，`HOST_DENIED` 表示網址 Host 不符；若沒有任何新紀錄，只能表示此應用尚未記錄到請求，還可能是 Proxy 驗證、TCP／HTTP 解析前拒絕或其他網路問題，不能直接認定某一原因。

## 回到原服務

Ctrl+C 停止測試版後：

```cmd
.\.venv\Scripts\python.exe .\company\server.py
```

原服務使用原資料及原密碼，沒有需要反向匯入的步驟。

## 自動測試界線

`test_flask_server.py` 包含副本隔離、API／頁面／HEAD、附件位元組、來源／Host／Origin、編輯鎖、日誌去敏及真實 Waitress loopback 十個並發修改測試。安裝 Flask／Waitress 的開發 venv 才能執行 Flask 測試；無依賴時只執行副本測試並明確 skip Flask 部分。macOS loopback／Flask test client 不等於公司 Windows 瀏覽器、Proxy、防火牆或真實使用驗收。
