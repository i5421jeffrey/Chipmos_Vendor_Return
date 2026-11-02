# SPMS 公司版：分段移植驗證

只使用本機 Python 與 SQLite，不連接或更新 Supabase。尚未開放內網或匯入舊資料。
不需安裝第三方套件。目標環境：Windows 11、Python 3.13、現代瀏覽器。

## 目前範圍

- `/`：環境檢查；`/repairs/`：備品管理的送修新增／查詢／編輯、每筆異動紀錄。
- 介面第一段還原：沿用原版左側導覽、狀態清單、S/N 快速搜尋、六欄送修列表、右側詳細資料及編輯視窗結構與配色。這不是完整原版的像素／功能一致性驗收；未移植功能停用並標示，不顯示假資料。
- 快速搜尋以正規化後的完整 S/N 精確查詢，不混入「包含相同字串」的其他序號；狀態導覽筆數由 SQLite 實際紀錄取得。
- S/N 主檔只存 S/N、板名與 PN，命中後鎖定板名／PN；衝突阻止寫入，不自動同步其他歷史。
- 機型由機台對應取得，維修金額由板件與維修分類決定；未設定為 NULL，零元仍為 0。
- 修改必須提供讀取時的版本；過期版本回傳 409，不覆蓋他人修改。
- 機台管理是預留模組（未安裝），與備品管理分開。共用 SQLite 連線與模組遷移紀錄，之後以新增遷移擴充，不重建資料庫。
- 尚未移植：DBN／Socket、附件、結案／再次送修、完整 S/N 主檔維護與歷史同步、全站異動紀錄頁、統計、舊資料匯入、登入權限與內網部署。驗證資料不代表正式資料已搬移。

內附 `modules/repairs/catalog.json` 為 Git 內兩份已知來源的離線基礎對應，
來源檔名及 SHA256 記錄於 JSON；不是 Supabase 線上資料快照，也不是完整機台管理清冊。
首次安裝送修模組時才載入；重啟不覆寫主檔、價目或案件，不重算舊案價格。
正式使用前必須核對公司實際對應。

## 從第一階段更新（保留資料）

### 單檔安裝（須先符合公司 IT 政策）

若公司允許下載及執行此類 Python 安裝程式，可從 GitHub 儲存庫根目錄取得
`install_spms.py`，放到 `D:\Python\SPMS\install_spms.py`。不要更改副檔名來繞過安全限制；
若被封鎖，請聯絡 IT 核准交付方式。

此檔內含 17 個純文字程式檔與個別 SHA256 校驗碼，不是需要額外下載內容的啟動器，
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
此安裝方式尚需 Windows 實機驗收。

### 手動複製程式

1. 在舊版 PowerShell 按 Ctrl+C 停止，關閉其他使用這個資料庫的服務。
2. 停止後先複製整個 `company\data` 資料夾到另一個安全的本機位置保存。
3. 下載新版，將 `company` 中的程式檔與資料夾合併複製到既有位置；不要刪除舊資料夾後重放，也不要覆蓋或刪除 `company\data`、上層 `.venv`。
4. 用下方原指令啟動。首次升級會先以 SQLite backup API 備份至 `company\data\backups\before-repairs-*.sqlite3`，然後在交易內新增送修模組資料表。
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

## 驗收

1. 頁面顯示 SQLite 已連線及版本，結構版本為 1。
2. 按「重新檢查」仍成功。
3. 在 PowerShell 按 Ctrl+C 停止，重新執行啟動指令。
4. 重新整理頁面；首次建立時間應相同，證明不是每次建立空白資料庫。
5. 進入備品管理，使用測試 S/N 新增一筆送修，確認搜尋、金額及異常描述正確。
6. 編輯該筆並儲存，再開啟檢查異動紀錄；點視窗背景或按 Esc 不會關閉表單。
7. 在兩個瀏覽器分頁先後開啟同一筆編輯表單；第一頁儲存後，第二頁儲存應顯示衝突且保留輸入，不可覆蓋第一頁。
8. 重啟後測試紀錄仍存在。此階段不要輸入正式資料，完整移植及備份流程尚未驗收。
9. 新版開啟後預設為 S/N 快速搜尋；查詢測試 S/N，點結果應開啟右側詳細資料。點「編輯／異動」進入編輯視窗，既有鎖定與衝突保護維持不變。
10. 左側「全部送修」「待送修」等狀態可切換、搜尋及分頁；DBN 等未移植功能停用。請截圖對照原版，Windows 的顯示縮放及實際視窗操作仍需實機驗收。

資料庫自動建立在 `company\data\spms.sqlite3`；不要刪除或放在網路磁碟、OneDrive。
原第一階段的核心結構版本維持 1；送修模組版本另存於 `spms_module_migrations`。
SQLite 使用 WAL 模式；運作中不要只複製主資料庫檔來備份。正式備份流程於後續階段加入。

此階段僅監聽 `127.0.0.1`。不要開防火牆、轉送連接埠或改成對外開放；
登入、權限、完整多人協作、正式備份還原及內網部署尚未完成；目前僅有基本版本衝突檢查與升級備份。
停止時若出現錯誤，保留 PowerShell 訊息供排查，不要刪除資料庫重試。

## 開發測試

從儲存庫根目錄執行（使用暫存資料庫，不修改使用者資料）：

```text
python -m unittest discover -s company -p "test_*.py" -v
```

Mac 開發機可額外執行 `swift scripts/test_company_ui.swift` 檢查 JS 語法及 mock DOM 流程（導覽、精確 S/N 查詢、詳細資料／編輯、衝突保留輸入）；這不取代 Windows 瀏覽器與 CSS 視覺驗收。
要重建離線基礎對應（只讀 Git 檔案、不連雲端），執行 `python scripts/build_company_catalog.py`；
這只產生封裝檔，不會更新已安裝 SQLite 的主檔，正式主檔變更須另行審閱遷移。

單檔安裝程式由 `python scripts/build_company_installer.py` 產生；公司版程式更新後必須重新產生。
安裝測試：`python -m unittest discover -s scripts -p "test_company_installer.py" -v`。
