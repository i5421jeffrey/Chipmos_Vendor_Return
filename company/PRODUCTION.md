# SPMS 正式啟動（2026-11-16）

## 最新來源設定（2026-11-19，優先於下方歷史說明）

使用者明確核准開放所有連入網段。`production_server.py`／`start_spms.cmd` 無參數啟動現在預設允許**所有能到達現有 IPv4 listener 的來源**，不再檢查來源網段；Host 白名單、同源檢查、編輯密碼／token、資料與啟動備份不變。Host 仍限 `10.1.121.135:<port>`、`127.0.0.1:<port>`、`localhost:<port>`，不是任意網址皆可使用。

**任何可連到此服務且使用允許 Host 的人都可以讀取 SPMS 資料；共用編輯密碼只保護修改，不保護讀取。** 包括透過共用 Proxy 轉送的使用者。HTTP 仍明文，不代表已增加個人認證、HTTPS 或解除 Proxy 登入；不調整公司防火牆／Proxy，不開 IPv6 listener、不建立對外轉發。若公司已有其他轉發規則，也可能影響實際可達範圍，需由 IT 管理。

啟動時會顯示 `SOURCE ACCESS: ALL IPv4 sources (no source-IP allowlist).` 與讀取風險提示。健康檢查的 access 為 `all-ipv4-sources`，不再誤標為 allowlist。可明確指定同一模式：

```cmd
.\.venv\Scripts\python.exe .\company\production_server.py --allow-all-sources
```

退回先前兩個核准網段（加 loopback）：

```cmd
.\.venv\Scripts\python.exe .\company\production_server.py --restrict-sources
```

也可用重複 `--client-subnet` 指定限制清單，這會停用預設全來源模式。`--allow-all-sources` 不可與 `--client-subnet` 或 `--restrict-sources` 混用。明確指定 `--host` 不自動繼承全來源模式／HTTP 同意：自訂 LAN bind 仍需指定來源模式及 `--allow-http-lan`。`--host 127.0.0.1` 仍維持僅 loopback 綁定。`server.py` 與隔離測試入口不提供此全來源選項、預設行為不變。

使用者在 Flask＋Waitress 測試連線成功後，核准正式使用原 SQLite 資料庫與密碼，允許 `10.1.121.0/24` 及 `192.168.120.0/24`。預設仍是 HTTP、`0.0.0.0:8082`，精確 Host 白名單不變，不調整 Proxy／防火牆。若後者包含共用 Proxy，其他經它轉送的使用者也可能讀取資料；來源白名單不是個人登入。所有修改仍需編輯解鎖及同源驗證。

## 更新及啟動

1. 在所有 SPMS 視窗按 Ctrl+C 停止服務。原服務和測試版都不能與正式版同時執行。
2. 從 GitHub Raw 下載最新 `install_spms.py` 到 `D:\Python\SPMS`，覆蓋舊安裝檔，執行：

```cmd
cd /d D:\Python\SPMS
.\.venv\Scripts\python.exe .\install_spms.py
```

確認目標並輸入 `INSTALL`。保留 data、密碼與 .venv；不重新匯入資料。已安裝的 Flask 3.1.3／Waitress 3.0.2 繼續使用。

3. 正式啟動：

```cmd
.\.venv\Scripts\python.exe .\company\production_server.py
```

也可以雙擊 `company\start_spms.cmd`；它不殺程序、不建立 Windows 服務／排程、不改系統政策。保持視窗開啟，主機不可休眠。

4. 開啟 `http://10.1.121.135:8082/repairs/`。啟動畫面必須顯示 `LIVE DATABASE: D:\Python\SPMS\company\data\spms.sqlite3`，不得是 flask-tests 路徑。

## 資料及備份

- `production_server.py` 直接使用既有 `company/data/spms.sqlite3` 與旁邊的 `edit-password.json`，每次啟動不建立替代主資料庫，不合併任何測試副本。正式寫入會保留到下次啟動。
- 缺失資料庫、未配置密碼、備份／完整性檢查失敗時停止，不建立空白庫、不退回其他資料庫。依賴缺失時不切換框架。
- 每次啟動先以 SQLite backup API 建立並驗證 `company/data/backups/flask-startup/<隨機ID>/spms.sqlite3`，完成後才執行既有新增式 migration（如需要）。備份涵蓋已提交 WAL 與附件，不包含密碼檔；密碼檔須另依公司規則保管。
- 這是啟動備份，不代替定期與異機備份；目前不自動刪除備份，請監控磁碟容量。備份／測試檔與正式資料都不得上傳 GitHub。
- 不把舊測試 SQLite 覆蓋正式資料庫。測試中新增的資料不會自動進入正式系統。
- 連線來源／Host／狀態及拒絕分類只輸出至 CMD；不額外產生無上限的正式日誌檔，不記 body、query、密碼與 token。HTTP 仍為明文。

## 保留入口及回退

- `flask_server.py` 仍是隔離測試版，預設來源網段仍為舊測試設定；不得用它當正式入口。
- `server.py` 原標準庫服務保留。如需退回，先 Ctrl+C 停止正式入口，再用同一正式資料庫啟動：

```cmd
.\.venv\Scripts\python.exe .\company\server.py --client-subnet 10.1.121.0/24 --client-subnet 192.168.120.0/24
```

回退只切換 HTTP 框架，不還原或搬移資料。兩者不可同時使用。

自動測試使用合成暫存資料驗證正式路徑、持續寫入、備份、拒絕規則與不合併測試副本。使用者已回報測試版的內網連線成功；正式 Windows 啟動／實際多人負載、定期備份與開機常駐仍未驗證，不因新增入口就宣稱已完成。
