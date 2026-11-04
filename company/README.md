# SPMS 公司版：SQLite 離線功能驗收

只使用本機 Python 與 SQLite，不連接或更新 Supabase。尚未開放內網或在公司正式資料庫匯入舊資料。
已提供共用密碼解鎖編輯，以及核准 CSV／附件的離線轉換、來源封存與副本試匯入；不是個人帳號／角色系統。
不需安裝第三方套件。目標環境：Windows 11、Python 3.13、現代瀏覽器。

本輪原版功能對照、集中修補與未完成界線見 [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)。
公司端驗收集中在整批開發後進行；不以自動測試通過宣稱已正式上線。

## 目前範圍

- `/`：環境檢查；`/repairs/`：送修新增／搜尋／編輯／刪除、每筆及全站異動紀錄、DBN、S/N 主檔、機台／板件／價格對應、年／月統計。
- 沿用原版左側導覽、狀態清單、S/N 快速搜尋、六欄送修列表、右側詳細資料及深色配色。新增管理表單以本機功能為主，尚未完成與原版逐畫面／像素一致性驗收，不能稱為外觀一模一樣。機台保養模組仍未安裝。
- 介面第二段：離線封裝原版 Logo 與 CSS；DBN／S/N 改回欄列清單、快速搜尋改回板件摘要與送修／DBN 分區、統計改回年度／月份選單及卡片／分類金額圖例、詳細資料有三階段維修時程。Model 與金額唯讀顯示，DBN 依類型隱藏不適用欄位。Logo JSON 為安裝封裝用途，不直接對外提供；只有明確 PNG 路由可讀取圖片。沒有搬入原版雲端 JS 或前端硬編碼密碼，不宣稱已完成登入權限。
- 快速搜尋以正規化後的完整 S/N 精確查詢，不混入「包含相同字串」的其他序號；狀態導覽筆數由 SQLite 實際紀錄取得。
- S/N 主檔只存 S/N、板名與 PN，命中後鎖定板名／PN；一般案件的主檔衝突阻止寫入。主檔維護支援改名及選擇是否同步歷史，先顯示影響筆數，再確認；版本或預覽後的歷史變更會阻擋。同步不重算歷史金額／Socket 快照，且須與歷史 Model 相容；任一筆失敗全部回復。改 S/N 但不同步時，有歷史引用的舊主檔會保留，避免破壞外鍵。
- 機型由機台對應取得，維修金額由板件與維修分類決定；未設定為 NULL，零元仍為 0。
- 一般編輯（描述、日期、開單等）保留案件原金額，包括 NULL 與 0，不隨新版價目默默重算。變更 Model／板名／PN／維修分類，或明確勾選「重新套用目前價目」時才重新計價；預覽顯示保留原價或目前價目。已結案案件也適用此規則，明確重計會影響歷史統計並記錄異動。補齊價目後要更新原先 NULL 案件，須勾選重新套用，再進行結案。
- 修改必須提供讀取時的版本；過期版本回傳 409，不覆蓋他人修改。
- 狀態／日期表單連動：已送修要求送修日期；取回驗證／已結案要求送修與回修日期；填回修時也必須有送修日期。日期選擇器與文字提示限制損壞≤送修≤回修，已結案時回修不可晚於原結案日。不自動填入、清空或修正歷史日期；後端仍獨立驗證。
- 送修新增／編輯儲存後直接開啟該案詳細資料；取消既有案件編輯時，重新讀取並返回詳細資料。衝突或失敗仍保留表單輸入；「重新載入此案」須先確認捨棄未儲存內容，讀取失敗不清空輸入，成功則取得最新版本與主檔鎖定。儲存／重載期間停用重複操作；過期的編輯歷史回應不會填入其他表單。
- 機台管理是預留模組（未安裝），與備品管理分開。共用 SQLite 連線與模組遷移紀錄，之後以新增遷移擴充，不重建資料庫。
- DBN：獨立新增／編輯／刪除，驗證客戶→產品→站點與機台／板件；支援 Group（連續 1–8 DUT）、Single Dut、RTE、Other。後兩者描述必填。DUT／PIN 為當時 Socket 快照，產品與 DUT 不變時保留舊快照；未有 Socket 的產品顯示「尚無對應」，不猜測 PIN。共用 PIN 僅合併每個 DUT 都存在的完全相同 token。
- Fail Log：每筆一個非空 `.txt`／`.asc`、最大 5 MB，可在新增／再次送修時一併儲存，也可從詳細資料上傳、文字檢視、下載、刪除。**附件內容直接存 SQLite BLOB**，不連 Supabase Storage；與案件／異動同一交易。上傳／刪除會遞增案件版本，避免其他編輯覆蓋。
- 新增、再次送修與詳細資料共用原版式 Fail Log 選檔按鈕，顯示檔名／大小並可清除尚未上傳的選擇；清除選擇不刪除已存附件，格式與容量仍由前後端檢查。
- 結案：只限「取回驗證」且金額已設定（0 可結案）。PASS 結案；FAIL 與下一筆待送修原子建立，分類、描述、附件獨立，日期由台北當日取得。連續送修鏈可從詳細資料查閱。已結案可編輯基本內容但不能直接重開；刪除須從最後一輪逐筆往前，確認後刪除該筆及附件並保留異動，不變更前一輪狀態。
- 統計：按年看各月／按月份看各年；首輪案件計損壞頻率及機台排行，再次送修不重複算損壞次數。各輪結案金額依結案日及維修分類加總，NULL 未設定另計，不當成零；提供長條圖及表格。現有統計沒有登入後的人員區分。
- 主檔對應維護不會自動重算或同步舊案件；S/N 的同步需從 S/N 主檔頁明確操作。價格以整數分寫入，保固只允許 NULL／0。
- 機台／板件／價格清單使用中文欄名，價格以元顯示並區分未設定與零元；逐列「修改」帶入原值並鎖定識別欄位。板件的 PN、機台的 Model 仍可修改；價格只能改該組識別下的金額。清單讀取後若主檔 token 改變，阻止開啟舊列編輯；儲存仍有後端 token 衝突保護。新增識別使用上方新增／修改表單。尚未經公司端驗收。
- **保留「機台／板件／價格對應」側欄與完整維護功能**，不因原版外觀還原而移除。支援機台、Model、板名、PN 搜尋（不分大小寫，空白分隔的條件須全部命中）；各表獨立篩選識別欄位並顯示命中／總筆數，金額不作為識別搜尋條件。清空搜尋再查詢可看全部。搜尋只影響顯示，不修改主檔、不重設價目，也不改變版本衝突 token。
- 異動紀錄提供資料類型、操作、開始／結束日期篩選及舊值／新值六欄表格；日期依台北時區、包含結束日，搜尋包含異動內容並將 `%`／`_` 視為文字。以每頁 20 個事件分頁，同一事件的變更欄位一併顯示（不同於原版每頁 10 個欄位）；新增／刪除也保留各欄細節，不隱藏來源紀錄。尚非具名人員稽核。
- 集中故障處理：快速搜尋分區顯示失敗，不把失敗當零筆；附件／送修鏈失敗仍保留基本詳情，未知狀態停用相關危險操作並提供重讀。對應表初始化失敗可重試；送出前的非同步查詢也鎖定輸入。DBN 補齊 DUT／類型／站點／PN／Model 搜尋，送修支援 PN；匯入異動可用 IMPORT 篩選。來源時間原字串保留、按實際時間點排序。
- 詳細資料的連續送修歷史逐輪顯示日期、狀態、維修分類、金額、異常類別、描述與該輪附件；標示目前案件，可點選切換，不將同 S/N 的其他獨立送修混入本鏈。只有單筆未結案時顯示「尚無連續送修紀錄」。S/N 主檔表單提供獨立唯讀 PN 預覽。此輪畫面仍未經 Windows／視覺驗收。
- 再次送修的進行中案件顯示前一輪 FAIL 提醒；有後續送修時停用刪除按鈕，後端在交易內再次檢查，須先刪最後一輪。未設定金額時保留但停用 PASS／FAIL 按鈕，提示補價後明確重新套用價目；重新計價另有儲存前確認，取消不寫入且保留表單。
- 離線匯入、SQLite 備份驗證與復原到新檔工具已提供（下方）。`legacy_import.py` 可處理本次核准的 13 份 CSV 與實體附件，保留來源欄位、來源異動、時間、金額及 PIN；公司正式匯入仍須另行確認。程式不會讀雲端取得資料。
- 使用者指定以**共用密碼解鎖編輯防誤觸**，不採個人帳號／角色管理。所有寫入有後端工作階段檢查，但異動不是具名人員稽核；這不是正式內網的身分安全方案。正式內網部署與排程／異地備份、Windows 本輪操作及視覺驗收仍未完成，不得直接開放內網作正式服務。

內附 `modules/repairs/catalog.json` 為 Git 內兩份已知來源的離線基礎對應，
來源檔名及 SHA256 記錄於 JSON；不是 Supabase 線上資料快照，也不是完整機台管理清冊。
首次安裝送修模組時才載入；重啟不覆寫主檔、價目或案件，不重算舊案價格。
正式使用前必須核對公司實際對應。

DBN 內附客戶 AB／QR／VB、Git 已知產品站點與 JAA118／GAA112／CAA100／GAA126 Socket 對應，來源檔名及 SHA256 在 `dbn_catalog.json`。只在模組 v2 安裝時載入，不是線上資料快照。Socket 原始檔的 SHA256 在產生時核對；執行服務只需離線 JSON。新增其他 Socket／產品對應須另行核對遷移，不接受任意未審核 SQL 上傳。

## 從第一階段更新（保留資料）

### 單檔安裝（須先符合公司 IT 政策）

若公司允許下載及執行此類 Python 安裝程式，可從 GitHub 儲存庫根目錄取得
`install_spms.py`，放到 `D:\Python\SPMS\install_spms.py`。不要更改副檔名來繞過安全限制；
若被封鎖，請聯絡 IT 核准交付方式。

此檔內含安裝清單中的純文字程式檔與個別 SHA256 校驗碼，不是需要額外下載內容的啟動器，
也不會執行封裝的服務、開啟／遷移資料庫、變更系統政策或防火牆。
校驗碼只供偵測損壞，不是數位簽章；請由可信任的儲存庫取得並依公司規定審核。

先停止服務，在 PowerShell 執行唯讀預覽：

```powershell
cd D:\Python\SPMS
.\.venv\Scripts\python.exe .\install_spms.py --check
```

顯示 `CHECK OK` 後才執行安裝：

```powershell
.\.venv\Scripts\python.exe .\install_spms.py
```

確認服務已停止且更新範圍正確後輸入 `INSTALL`。
安裝前把會被覆寫的舊程式備份至 `D:\Python\SPMS\spms-code-backups\<時間-唯一碼>`。
只替換清單中的程式，保留 `company\data`、`.venv` 與其他檔案；它不備份資料庫，
資料庫備份及模組升級仍在下一次啟動服務時處理。
程式檔逐一替換，發生一般寫入錯誤會嘗試回復已替換程式；斷電、強制終止或回復失敗不保證自動還原，請保持服務停止並保留備份供維護人員處理。
出現 `.spms-install.lock` 錯誤表示另有安裝執行中或上次中斷，不要直接刪鎖或資料庫重試。
既有單檔安裝流程已由使用者在 Windows 驗證；本次 v2 功能仍需 Windows 更新後驗收。

### 手動複製程式

1. 在舊版 PowerShell 按 Ctrl+C 停止，關閉其他使用這個資料庫的服務。
2. 停止後先複製整個 `company\data` 資料夾到另一個安全的本機位置保存。
3. 下載新版，將 `company` 中的程式檔與資料夾合併複製到既有位置；不要刪除舊資料夾後重放，也不要覆蓋或刪除 `company\data`、上層 `.venv`。
4. 用下方原指令啟動。首次升級會先以 SQLite backup API 備份至 `company\data\backups\before-repairs-*.sqlite3`，然後在交易內新增送修模組資料表。v1→v2 為新增資料表／索引與主檔版本欄位，不刪除／重建既有送修資料；資料庫模組版本比程式新時拒絕降版。
5. 備份失敗或結構衝突會停止啟動；請保留錯誤，不要刪資料庫重試。遷移成功後不重複備份／安裝。第一階段首次建立時間維持不變。

自動備份是本機升級保護，不是完整的異地備份／還原管理。若要還原，先停止服務並保留目前整個 data 資料夾，再請維護人員處理；不要直接用檔案覆蓋運作中的資料庫。

## Windows PowerShell 啟動

保留既有 `D:\Python\SPMS\.venv`，把本儲存庫的整個 `company` 資料夾複製到
`D:\Python\SPMS\company`。應有 `company\server.py`、`company\web\index.html` 等檔案。

在 PowerShell 執行：

```powershell
cd D:\Python\SPMS
.\.venv\Scripts\python.exe .\company\server.py
```

保持此視窗開啟，用同一台電腦的瀏覽器開啟 `http://127.0.0.1:8765`。
應看到「Python 服務正常，SQLite 已連線」。不需啟用 PowerShell 指令碼執行權限。
點「進入備品管理」，或開啟 `http://127.0.0.1:8765/repairs/`。

若埠已被使用，可執行以下指令，再開啟 `http://127.0.0.1:8766`：

```powershell
.\.venv\Scripts\python.exe .\company\server.py --port 8766
```

## 公司端驗證狀態

使用者回報基本流程、DBN／Socket、附件及第一輪 FAIL→再次送修測試完成。之後要求跳過所有公司端驗證並繼續移植，故第二輪 PASS、統計、主檔歷史同步、人工備份／復原及本次畫面一致性仍屬**未驗收**；不得將略過記為通過，也不以此宣稱正式上線。開發機自動測試照常執行，但不能取代 Windows／真實資料驗收。

## 驗收參考程序（保留供後續，不作為目前移植的前置要求）

1. 頁面顯示 SQLite 已連線及版本，結構版本為 1。
2. 按「重新檢查」仍成功。
3. 在 PowerShell 按 Ctrl+C 停止，重新執行啟動指令。
4. 重新整理頁面；首次建立時間應相同，證明不是每次建立空白資料庫。
5. 進入備品管理，使用測試 S/N 新增一筆送修，確認搜尋、金額及異常描述正確。
6. 編輯該筆並儲存，再開啟檢查異動紀錄；點視窗背景或按 Esc 不會關閉表單。
7. 在兩個瀏覽器分頁先後開啟同一筆編輯表單；第一頁儲存後，第二頁儲存應顯示衝突且保留輸入，不可覆蓋第一頁。
8. 重啟後測試紀錄仍存在。此階段不要輸入正式資料，完整移植及備份流程尚未驗收。
9. 新版開啟後預設為 S/N 快速搜尋；查詢測試 S/N，點結果應開啟右側詳細資料。點「編輯／異動」進入編輯視窗，既有鎖定與衝突保護維持不變。
10. 左側「全部送修」「待送修」等狀態可切換、搜尋及分頁，支援異常及維修分類篩選。DBN 清單、快速搜尋 DBN、S/N 維護、全站異動、對應主檔與統計可開啟。機台保養仍停用。
11. 建立測試 DBN：F45／HVDR PE、AB→JAA118→CP1、Group 1-4；應顯示共用及個別 PIN，送修清單可看到該 S/N 的 DBN 筆數。改成 Single Dut 1-2 應被阻擋；RTE／Other 描述不可空白。修改與刪除都須保留異動。
12. 送修詳細資料上傳測試 `.asc`，文字檢視與下載內容須相同；每筆限一檔。刪除後可重新上傳；舊分頁版本須衝突。新增或 FAIL 再次送修時附錯誤檔案，整筆案件／結案必須保持原樣。
13. 將測試案改為取回驗證，送修及回修日填妥；金額未設定時不允許結案。先以合約零元案驗證 FAIL→新待送修→第二輪取回驗證→PASS，兩輪描述及 Fail Log 不互相覆蓋，歷史鏈可切換；第二分頁重複結案應衝突。
14. S/N 主檔修改先確認影響筆數；先測「只改主檔」，舊案保持原樣；再測「同步歷史」，名稱／PN 及版本更新但金額與 Socket 快照保持不變。改 S/N 不同步時仍可查舊歷史。
15. 統計切換年／月並核對：兩輪維修仍只算一次損壞，結案金額依各輪計算。重啟後案件／DBN／附件／異動都須保留。對照原版截圖，Windows 縮放及實際視窗操作另行驗收。

資料庫自動建立在 `company\data\spms.sqlite3`；不要刪除或放在網路磁碟、OneDrive。
原第一階段的核心結構版本維持 1；送修模組版本另存於 `spms_module_migrations`。
SQLite 使用 WAL 模式；運作中不要只複製主資料庫檔來備份。下列備份工具使用 SQLite backup API；排程、保管及異地副本仍須依公司規範設置。

此階段僅監聽 `127.0.0.1`。不要開防火牆、轉送連接埠或改成對外開放；
共用密碼解鎖僅防誤觸，不提供個人角色或具名稽核；正式多人／內網部署尚未完成。保留本機版本衝突保護、交易、升級備份及人工備份／復原驗證。
停止時若出現錯誤，保留 PowerShell 訊息供排查，不要刪除資料庫重試。

## SQLite 備份、驗證與復原演練

在 `D:\Python\SPMS` 執行，下例輸出目錄必須先存在、檔名必須尚未存在（不可覆蓋）。輸入 `COPY` 才寫入新副本；附件也包含在資料庫內。

```powershell
.\.venv\Scripts\python.exe .\company\maintenance.py backup --output D:\Python\SPMS\spms-backup-test.sqlite3
.\.venv\Scripts\python.exe .\company\maintenance.py verify --source D:\Python\SPMS\spms-backup-test.sqlite3
.\.venv\Scripts\python.exe .\company\maintenance.py recover --source D:\Python\SPMS\spms-backup-test.sqlite3 --output D:\Python\SPMS\spms-recovered-test.sqlite3
```

`verify` 執行 integrity／foreign key 檢查並顯示案件、DBN、主檔、附件及異動筆數；僅接受本程式 v2 結構。`recover` **只建立新檔**，不會替換正式資料庫、清理 WAL 或重啟服務。正式切換須先停止服務、保留當前完整 data，核對程式版本與復原筆數／內容，再由維護人員依公司程序進行。升級前 v1 備份應用配套舊程式處理，不得混用。

## 舊資料：離線 JSON 匯入工具（先審核，不自動讀雲端）

`company/import_data.py` 接受已核對的 `spms-offline-import-v1` JSON；這個舊版格式**不直接接受 SQL dump／CSV／Storage URL，也不下載雲端附件**，僅新增本機 `IMPORT` 異動。實際 CSV 與來源異動請改用下方 `legacy_import.py`；兩者格式不可混用。

格式：

```json
{
  "format": "spms-offline-import-v1",
  "source_description": "公司核准的匯出來源與日期",
  "serial_board_mappings": [],
  "repair_records": [],
  "dbn_records": [],
  "repair_attachments": []
}
```

- 送修：`id` 與新增表單欄位（`serial_no,machine_code,description,board_part_code,failure_tag,failure_description,repair_type,current_status,is_opened,occurred_on,sent_on,returned_on`），**另須明確提供 `repair_amount`（元、最多兩位小數，可為 null）**。結案須 `closed_on`，連續鏈須 `retry_of_record_id`。所有案件 ID 接受 1–64 位英數、連字號／底線，UUID 可原樣保留。保留歷史金額，不用目前價目覆蓋。`created_at,updated_at` 可提供帶時區 ISO 字串，省略則記匯入時間。
- DBN：`id,serial_no,machine_code,board_name,board_part_code,customer_code,product_code,station_code,issue_type,dut,issue_description,socket_file_id,dut_pin_snapshot`。**須提供歷史快照物件**；沒有 PIN 時每個 DUT 明確為 null，RTE／Other 為 `{}`。不以目前 Socket 重建舊 PIN。可提供來源時間。
- 附件：`repair_record_id,filename,content_base64`，需實際離線檔案內容，不能只有 `storage_path`。維持一檔、5 MB 限制。
- 匯入前須先建立正確的機台／板件等參照資料。主檔完全相同可沿用；衝突、重複案件 ID、缺失欄位、無效日期、斷鏈／循環一律拒絕。未知欄位也會拒絕，須在審核轉換時處理，不能把原 dump 原樣當成已支援格式。
- 每批上限 100 MB；檔案內容限 UTF-8 JSON。工具會顯示來源 SHA256 與各表輸入筆數；筆數含沿用的相同主檔，不代表每筆都是新建。

先在暫存副本完整試跑（原資料庫不變）；正式寫入須停服務，加 `--apply` 並輸入 `IMPORT`，會先備份，再同一交易驗證寫入，任何錯誤整批回復：

```powershell
.\.venv\Scripts\python.exe .\company\import_data.py D:\approved-import.json
.\.venv\Scripts\python.exe .\company\import_data.py D:\approved-import.json --apply
```

匯入後逐表核對 ID／筆數、NULL 與零元、來源時間、連續送修鏈、附件 SHA256 及 PIN 快照，再另做備份。這個舊版格式的合成測試不等於公司正式移轉已完成。

## 共用密碼開啟編輯（防誤觸）

更新程式後，預設為唯讀；未設定密碼也能瀏覽，但不能寫入。在公司主機 `D:\Python\SPMS` 執行一次：

```powershell
.\.venv\Scripts\python.exe .\company\edit_access.py
```

依提示輸入兩次共用密碼；不放在命令列、不回傳給助理、不使用原前端硬編碼密碼。
設定存在 `company\data\edit-password.json`，僅存隨機 salt 與 scrypt 雜湊；更新安裝器不封裝或覆寫此檔。
更換密碼也是執行同一命令；原工作階段會失效。此設定不在 SQLite 備份內，須由 IT 另行保管或復原後重新設定。

- 頁面按「開啟編輯」並輸入密碼，才顯示新增／修改／刪除／結案／附件寫入及價格維護。
- 後端對每個寫入 API 檢查隨機 token；token 僅放頁面記憶體，不寫 cookie、網址或 localStorage。只解鎖目前分頁，重新整理後唯讀。
- 「結束編輯」撤銷 token；有未儲存表單須確認，有正在送出的操作則等完成後再結束。服務重啟、密碼變更或 8 小時到期也會失效。
- 工作階段到期的寫入不自動重送，表單保留輸入；可按表單內「重新開啟編輯」後自行確認再儲存。
- 連續錯誤五次暫停嘗試 30 秒。沒有預設密碼、個人帳號或角色，不能據此識別實際操作人員；仍只限 localhost。

## 真實 CSV／附件：一次性來源移轉包

`legacy_import.py` 僅針對已審閱的備品 CSV 欄位與規則，不執行 SQL，也不是通用 dump 或增量同步工具。
需要 13 張表：`dbn_customers,dbn_records,dbn_socket_files,dbn_valid_combinations,record_change_history,repair_attachments,repair_board_prices,repair_machine_models,repair_machines,repair_model_boards,repair_models,repair_records,serial_board_mappings`。
CSV 檔名為 `<表名>_rows.csv`；實體附件根目錄下保留 `<案件ID>/<Storage檔名>`。

準備資料包（在有核准來源的電腦執行；若已收到 `source_bundle.json` 則不用重建）：

```text
python company/legacy_import.py build --csv-directory APPROVED_CSV_FOLDER --files-directory EXTRACTED_FILES_FOLDER --output source_bundle.json --description "approved source export and date"
```

資料包含完整 CSV 與附件，**是公司資料，不是公開安裝檔**，須依公司核准方式傳送及保存；不提交 GitHub。
轉換不修改來源；每份 CSV／附件含 SHA256，所有 13 份原始 CSV 位元組會連同附件一起存入 SQLite 的同一交易與備份。

處理界線：

- 送修保留原 ID、版本、金額（含 NULL／0）、日期、送修鏈、建立／更新時間；不以現價重計。
- DBN 保留原 PIN 與 Socket ID。原類型空白且無 DUT／快照／描述的舊案存入新增的 `legacy_dbn_records`，清單／搜尋／摘要仍一併顯示，標為「未記錄類型」。不推測為 Other；只有明確補齊類型並儲存後，才原子轉為正常 DBN，保留 ID／原建立時間及來源封存。
- DBN 原 CSV 沒有版本／更新時間：本機初始版本為 1、更新時間採原建立時間；新 S/N 主檔建立時間採原更新時間，沿用的相同主檔保留本機時間。這些衍生欄位會列在核對報告，不冒充來源提供值。
- 明確標記來源日期先後例外及前輪結案晚於再次送修損壞日；原值／關聯不改。個案日期錯序時禁止 PASS／FAIL，須人工核對、明確編輯更正。一般新增／編輯仍套用原有嚴格日期驗證。
- 來源異動原操作、時間、舊值／新值保留，ID 加 `legacy-` 前綴防碰撞；畫面標示「來源歷史」，與本機 `IMPORT` 事件分開。來源已刪除案件的歷史也保留。
- 舊欄位 `repair_month/item/area/tester_id/failure_data/order_status` 等完整封存，案件詳細資料可唯讀查看原始欄位，但不是新增可編輯業務欄位。`repair_machines` 與 `repair_models` 完整 CSV 僅封存；本機選項使用實際的 `repair_machine_models`／板件／價格對應，不偽稱兩套機台表已合併。
- 不重建資料庫，不覆寫既有案件；相同基礎對應可沿用、不同值整批拒絕。公司既有測試資料不刪除。重複匯入不是同步，會拒絕並整批回復。
- additive `legacy_import` 模組 v1 升級前備份，與 repairs v2 並存。此版資料庫不可退回不支援來源封存與舊 DBN 的程式，否則會漏顯資料。

公司正式匯入步驟（集中驗收時執行，不因本機試跑成功自動匯入）：

1. 依既有更新程序安裝新版；啟動一次服務完成備份式新增遷移，再停止服務。保留 `company\data` 與 `.venv`，不要拿預覽 SQLite 替換正式檔。
2. 將核准 `source_bundle.json` 放在例如 `D:\Python\SPMS\migration\`，先對目前公司資料庫做副本預檢：

```powershell
.\.venv\Scripts\python.exe .\company\legacy_import.py import .\migration\source_bundle.json
```

3. 核對報告、來源例外及公司現有資料是否衝突。無 `--apply` 時只試匯入暫存副本，不改正式檔。確認後才執行：

```powershell
.\.venv\Scripts\python.exe .\company\legacy_import.py import .\migration\source_bundle.json --apply
```

輸入 `IMPORT` 才會先建立 `before-legacy-import-*.sqlite3` 備份並整批交易寫入。失敗整批回復，不會刪除重建。
最後用 `maintenance.py verify` 核對並另做備份，再啟動服務、設定密碼及集中驗收。
來源為手動分表匯出，不證明同一時間點快照或雲端最新完整筆數。若匯出後舊系統仍有變動，正式切換前須停止舊系統寫入、重新收齊並核對來源；不能把目前資料包當成持續同步。

## 開發測試

從儲存庫根目錄執行（使用暫存資料庫，不修改使用者資料）：

```text
python -m unittest discover -s company -p "test_*.py" -v
```

Mac 開發機可額外執行 `swift scripts/test_company_ui.swift` 檢查 JS 語法及 mock DOM 流程（導覽、精確 S/N 查詢、詳細資料／編輯、衝突保留輸入）；這不取代 Windows 瀏覽器與 CSS 視覺驗收。
該命令另執行隔離的 `scripts/company_ui_resilience_test.js`，涵蓋部分讀取失敗、起始載入恢復、取消後遲到回應、前置查詢鎖定、錯誤回應及對應維護表單保護。
另有隔離的 `scripts/company_ui_edit_access_test.js` 檢查唯讀／解鎖／鎖回、到期保留輸入、舊案類型及來源時間顯示。後端 `test_edit_access.py`／`test_legacy_import.py` 使用合成資料，不包含真實公司來源。
要重建離線基礎對應（只讀 Git 檔案、不連雲端），執行 `python scripts/build_company_catalog.py`；
這只產生封裝檔，不會更新已安裝 SQLite 的主檔，正式主檔變更須另行審閱遷移。
DBN 基礎對應：`python scripts/build_company_dbn_catalog.py`（從明確 Git SQL VALUES／Socket JSON 擷取，不執行 PostgreSQL 或連雲端）。
原版外觀資源：`python scripts/build_company_ui_assets.py`，產生 `company/web/original.css` 與純文字 `branding.json`；另以 `parity.css` 適配本機 DOM。原版 CSS 有變更時須重新產生，再重建安裝檔。資源重現測試：`python -m unittest discover -s scripts -p "test_company_ui_assets.py" -v`。

單檔安裝程式由 `python scripts/build_company_installer.py` 產生；公司版程式更新後必須重新產生。
安裝測試：`python -m unittest discover -s scripts -p "test_company_installer.py" -v`。
