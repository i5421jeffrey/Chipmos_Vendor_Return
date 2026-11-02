# SPMS 公司版：分段移植驗證

只使用本機 Python 與 SQLite，不連接或更新 Supabase。尚未開放內網或匯入舊資料。
不需安裝第三方套件。目標環境：Windows 11、Python 3.13、現代瀏覽器。

## 目前範圍

- `/`：環境檢查；`/repairs/`：備品管理的送修新增／查詢／編輯、每筆異動紀錄。
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

Mac 開發機可額外執行 `swift scripts/test_company_ui.swift` 檢查 JS 語法；這不取代 Windows 瀏覽器互動驗收。
要重建離線基礎對應（只讀 Git 檔案、不連雲端），執行 `python scripts/build_company_catalog.py`；
這只產生封裝檔，不會更新已安裝 SQLite 的主檔，正式主檔變更須另行審閱遷移。
