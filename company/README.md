# SPMS 公司版：第一階段

只驗證本機 Python 網站與 SQLite 連線。不連接 Supabase，不含業務功能或舊資料。
不需安裝第三方套件。目標環境：Windows 11、Python 3.13、現代瀏覽器。

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

若埠已被使用，可執行以下指令，再開啟 `http://127.0.0.1:8766`：

```powershell
.\.venv\Scripts\python.exe .\company\server.py --port 8766
```

## 驗收

1. 頁面顯示 SQLite 已連線及版本，結構版本為 1。
2. 按「重新檢查」仍成功。
3. 在 PowerShell 按 Ctrl+C 停止，重新執行啟動指令。
4. 重新整理頁面；首次建立時間應相同，證明不是每次建立空白資料庫。

資料庫自動建立在 `company\data\spms.sqlite3`；不要刪除或放在網路磁碟、OneDrive。
目前只有技術用的結構版本資料表，尚未建立維修業務資料表。
SQLite 使用 WAL 模式；運作中不要只複製主資料庫檔來備份。正式備份流程於後續階段加入。

此階段僅監聽 `127.0.0.1`。不要開防火牆、轉送連接埠或改成對外開放；
登入、權限、多人編輯控制、備份及內網部署尚未完成。
停止時若出現錯誤，保留 PowerShell 訊息供排查，不要刪除資料庫重試。

## 開發測試

從儲存庫根目錄執行（使用暫存資料庫，不修改使用者資料）：

```text
python -m unittest discover -s company -p "test_*.py" -v
```
