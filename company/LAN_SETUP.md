# SPMS：Windows 11 內網共用

## 最新預設連接埠：8085

依使用者後續要求，預設改為 `http://10.1.121.61:8085/repairs/`；此設定取代下方舊的 8765 說明及範例。直接執行 `company/server.py` 即採用新埠；仍可用 `--port` 指定其他埠。防火牆／代理規則若仍是舊埠，須由有權限者調整；程式不自動改規則，改埠不保證解決代理限制。資料及編輯密碼不變。

使用者已確認目前電腦作主機、預計 10 人使用、IT 允許內網及防火牆設定。本文件是部署步驟，不代表已在公司操作或通過實際負載測試。

## 指定主機預設（2026-11-04 更新）

使用者已指定換機測試，預設改用 `10.1.121.61`、`10.1.121.0/24`、HTTP 8765，並選擇暫不配置 HTTPS。現在無參數啟動即使用此設定：

```powershell
cd D:\Python\SPMS
.\.venv\Scripts\python.exe .\company\server.py
```

網址為 `http://10.1.121.61:8765/repairs/`。如需只允許主機，明確加 `--host 127.0.0.1`。綁定 IP 不存在時會報錯停止，不會自動退回其他 IP 或公開監聽。請固定 IP；公司 Proxy 問題不會因此解決。指定其他 `--host` 時，仍須另指定網段及 TLS 或 `--allow-http-lan`，不沿用此主機的 HTTP 同意。以下範例為其他部署的明確設定方式。

### 搬到測試電腦（10.1.121.61）

1. 舊主機先 Ctrl+C 停止 SPMS，保留原資料夾及備份。停止後複製完整 `SPMS` 程式及 `company\data`（包括可能存在的 WAL／SHM、密碼、附件資料庫與備份）；不可在寫入中只複製 SQLite 主檔。透過公司核准方式傳送，不上傳 GitHub。
2. 新主機放到 `D:\Python\SPMS`，勿覆蓋新主機上既有的不明資料；若沒有 D 槽可用其他目錄，但須相應更改命令路徑。
3. `.venv` 不是可攜式環境。不要刪掉舊主機環境；新主機若複製了 `.venv`，先改名保留為 `.venv-from-old-host`（若該名稱已存在，先確認再處理），再用已安裝的 Python 3.13 重建：`py -3.13 -m venv .venv`。沒有 Python 時依公司允許方式安裝，不更改系統政策。不需 pip 安裝第三方套件。
4. 最新 `install_spms.py` 放在新主機 SPMS 根目錄，使用新 venv 執行，確認目標後輸入 INSTALL；安裝器保留 `company\data`。
5. 先執行 `.\.venv\Scripts\python.exe .\company\maintenance.py verify`，核對舊主機的案件／附件等筆數；失敗就停下，不重建資料庫、不重匯來源。若路徑放錯，啟動程式可能建立空資料庫，因此必須先 verify。
6. 執行 `.\.venv\Scripts\python.exe .\company\server.py`，網址應顯示 `http://10.1.121.61:8765/repairs/`。沿用搬來的編輯密碼，不需重設或重匯資料。
7. 新主機的防火牆／Proxy 仍須另行確認；換 IP 不代表限制自動解除。測試副本不要與舊主機同時接收正式寫入，兩份資料庫不會同步，也沒有自動合併功能。確定正式主機前保留舊檔，不把測試副本覆蓋回去。

## 架構與限制

- 只有主機執行一個 Python 服務；同事只開瀏覽器，**不各自安裝資料庫或開啟共享 SQLite 檔**。
- 沿用 `D:\Python\SPMS\company\data\spms.sqlite3`、附件及編輯密碼，不重新匯入。不放 OneDrive、網路磁碟或 SMB 共享目錄。
- SQLite WAL 允許多人讀取，寫入會依序交易；版本衝突要求重新載入，不會自動覆寫或重送。10 個模擬 HTTP 用戶同時改一案的測試，不等於 10 人實際業務效能驗收。
- 共用密碼僅防誤觸，無個人帳號／具名稽核；**允許的網段內未解鎖者仍能讀取紀錄和附件**。IT 必須評估網段成員與資料敏感度。
- 標準庫 HTTP server 是輕量內部服務，不是公開網站伺服器；沒有完整的連線配額、DDoS 防護、高可用或 Windows Service 管理。只用於受信任內網；不可開路由器轉送、公開 IP、外網或訪客網段。
- 只接受指定 RFC1918 IPv4 綁定、來源網段白名單及精確 Host／Origin；不接受 `0.0.0.0`，也不信任轉送來源標頭。現階段網址用該主機 IP，不另設別名／反向代理。

## 1. 主機資料（先取得，不猜網段）

在主機 PowerShell 執行：

```powershell
ipconfig
Get-NetConnectionProfile
```

取正在使用的網卡之 **IPv4 位址、子網路遮罩**；不要貼無關的 VPN／虛擬網卡。請 IT 確認允許同事連入的 CIDR 網段、固定 IP 或 DHCP 保留，以及 Domain／Private 防火牆設定檔。相同 Wi-Fi 名稱不保證可互連，VPN／VLAN／無線隔離由 IT 檢查。

下列 `192.168.10.20`、`192.168.10.0/24` 都只是範例，**必須替換**；不是所有網段都用 `/24`。

## 2. 更新及啟動（推薦 HTTPS）

停止原服務，把新版 `install_spms.py` 放到 `D:\Python\SPMS`，在該目錄執行：

```powershell
.\.venv\Scripts\python.exe .\install_spms.py --check
.\.venv\Scripts\python.exe .\install_spms.py
```

確認目標後輸入 `INSTALL`。安裝器不開防火牆、不啟動服務、不改資料或密碼；不可再匯入已匯入的來源包。網路模式要求已設定編輯密碼，若尚未設定才執行 `company\edit_access.py`。

請 IT 提供包含主機 IPv4 subjectAltName 的 PEM 憑證／私鑰、在同事電腦信任公司簽發 CA，將檔案保存在例如 `company\data\tls\`，限制私鑰 NTFS 存取權限。私鑰不得放 GitHub、公開資料夾或傳給同事；不要要求使用者略過憑證警告。

```powershell
cd D:\Python\SPMS
.\.venv\Scripts\python.exe .\company\server.py --host 192.168.10.20 --client-subnet 192.168.10.0/24 --tls-cert .\company\data\tls\server-cert.pem --tls-key .\company\data\tls\server-key.pem
```

TLS 最低 1.2；讀取憑證失敗會停止，不會自動退回 HTTP。多個核准網段可重複 `--client-subnet`。

### 暫用 HTTP 的風險與明確選項

沒有憑證時，不會預設開放明文內網。**HTTP 會明文傳送共用密碼、編輯 token、紀錄及附件**；同網路遭監聽時，密碼雜湊存檔也無法保護傳輸。只有 IT 明確接受此傳輸風險且網段可信任時，才改用：

```powershell
.\.venv\Scripts\python.exe .\company\server.py --host 192.168.10.20 --client-subnet 192.168.10.0/24 --allow-http-lan
```

未帶網路參數會採用上方指定主機預設；停用內網須明確使用 `--host 127.0.0.1`。綁定內網 IP 時，主機也須使用內網網址；`127.0.0.1` 不再是該服務的監聽位址。

## 3. 限縮防火牆（由 IT／系統管理員執行）

先看目前設定檔與既有規則。不要關閉防火牆、改安全政策或接受全網段 Python 自動放行；若已有廣泛允許 Python／8765 的規則，請 IT 審查限縮，新增窄規則不會抵消舊的廣泛規則。

管理員 PowerShell，先填真實核准值：

```powershell
$ServerIP = '192.168.10.20'
$ClientSubnet = '192.168.10.0/24'
$Python = 'D:\Python\SPMS\.venv\Scripts\python.exe'
New-NetFirewallRule -DisplayName 'SPMS TCP 8765' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -LocalAddress $ServerIP -RemoteAddress $ClientSubnet -Program $Python -Profile Domain,Private
```

若 Windows 將公司網路列為 Public，先請 IT 確認，不自行改網路類型或新增 Public 全開規則。若使用不同 port，服務參數、網址與防火牆必須一致。

## 4. 同事連線與集中檢查

同事不需安裝 Python，使用 Edge／Chrome：

```text
HTTPS：https://192.168.10.20:8765/repairs/
HTTP（僅經風險確認）：http://192.168.10.20:8765/repairs/
```

PowerShell 可先檢查 TCP（不寫資料）：

```powershell
Test-NetConnection 192.168.10.20 -Port 8765
```

集中確認項目：第二台電腦能查詢、附件可讀、預設唯讀、解鎖後正常儲存、兩台同改一案會出現衝突而非覆寫；10 人同時查詢／儲存與實際網路延遲仍未驗證。確認非核准網段不能連入。不用真實案件製造無法回復的測試異動。

連不上：先看主機服務視窗／IP 是否變動、網卡及網段、Domain／Private 設定檔、防火牆與 VLAN。403 通常要確認網址的 IP／port、Host／Origin 是否一致；不要以放行任意 Host／CORS 解決。

## 5. 持續運作與備份

- 主機插電、由 IT 設定不休眠及系統更新維護時段；關閉終端會停止目前手動啟動的服務。
- 自動啟動可由 IT 在工作排程器建立開機工作：程式指定 venv 的 `python.exe`，引數使用上面核准的完整啟動參數，開始位置 `D:\Python\SPMS`。使用能讀寫 data／備份、讀取私鑰的專用低權限本機身分；不要以管理員執行網站。設定「不要啟動新的執行個體」及失敗重啟，延遲啟動以等待網卡，保留錯誤記錄。不要另開第二個手動服務。這些工作不會由安裝器自動建立。
- 使用 `maintenance.py backup` 的 SQLite backup API，包含已提交 WAL 與附件。排程／異地副本與保留天數由 IT 管理；密碼設定與 TLS 私鑰在 SQLite 外，須另行保管。不可在運作中只複製 SQLite 主檔。
- 資料匯入、更新或復原前先停服務；復原只能到新檔核對，不覆蓋運作中資料庫。不因網路錯誤刪除／重建資料庫。

停用內網：Ctrl+C 停服務，由 IT 停用 `SPMS TCP 8765` 規則；以現有 venv Python 執行 `company/server.py --host 127.0.0.1`，即只允許本機。若工作排程器已啟用，須同步停用或修改該工作，避免自動重新開放。
