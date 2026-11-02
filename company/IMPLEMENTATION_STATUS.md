# 備品管理：本機功能整批對照與交付界線

本文件記錄目前**開發交付範圍**，不是公司驗收簽核，也不代表已完成真實舊資料移轉或正式上線。
依使用者要求，先集中完成開發與自動測試，再統一安排公司端驗收；略過的檢查仍是未驗收。

## 已實作的原版操作對照

原版依據為儲存庫的 `docs/repairs/index.html`、`history.html`、`dbn-socket.js`、`repair-pricing.js`；
沒有讀取 Supabase 線上資料。下表表示功能已有本機實作與開發測試，不表示畫面逐像素一致。

| 功能 | 原版參考 | 本機實作／測試依據 |
| --- | --- | --- |
| 狀態導覽、查詢、標籤／分類篩選 | `renderNav`、`render` | `web/repairs.js`、`service.list_records`；版本、搜尋與 HTTP 測試 |
| S/N 快速搜尋、送修／DBN 分區及摘要 | `renderQuickSearch`、`searchQuickSerial` | `serial_summary`、`renderQuickResults`；精確 S/N、跨分頁摘要及部分失敗測試 |
| 新增／編輯、日期、開單、計價 | `createRecord`、`saveRecordEdits` | `service.save_record`；日期／版本衝突、原金額快照、重新計價測試 |
| 詳細資料、時程、連續維修歷史 | `renderDetail`、`historyMarkup`、`repairTimeline` | `operations.chain`、`renderRepairChain`；逐輪內容／附件及切換測試 |
| PASS／FAIL 及再次送修 | `finishVerification`、`createRetry` | `operations.resolve`；單一交易、重複結案衝突及失敗回復測試 |
| Fail Log 上傳、預覽、下載、刪除 | `loadAttachment`、`uploadAttachment` | SQLite BLOB、SHA256；格式／容量、交易、HTTP 位元組與備份測試 |
| DBN 客戶／產品／站點、DUT／PIN | `renderDbnList`、`openDbnModal`、`dbn-socket.js` | `operations.save_dbn`；級聯、範圍、歷史 PIN 快照及共用 PIN 測試 |
| S/N 主檔、影響預覽、明確歷史同步 | `saveSerialMapping` | `preview_mapping`、`save_mapping`；token、改 S/N、相容性及整批回復測試 |
| 全站／單案異動 | `history.html` | 舊值／新值、類型／操作／台北日期篩選；本機 IMPORT 可獨立查詢 |
| 年／月損壞頻率、分類金額、機台排行 | `renderStatistics` | `operations.statistics`；首輪計次、各輪結案金額、NULL／0 與排序測試 |
| **機台／板件／價格對應（指定保留）** | 公司版擴充，不因原版還原移除 | 搜尋、中文清單、元單位、逐列編輯、主檔 token 及不改寫歷史測試 |
| 離線安裝、遷移、備份與匯入工具 | 公司 Windows／SQLite 需求 | `database.py`、`maintenance.py`、`import_data.py`；暫存資料庫及獨立安裝後測試 |

## 本輪集中修補的例外流程

- 快速搜尋的送修、DBN、板件摘要分開處理失敗；已讀取的資料仍顯示，失敗不當成零筆或完整歷史。
- 基本案件先顯示；附件或送修鏈失敗不遮蔽基本資料。未知附件狀態不提供空附件上傳；未知送修鏈停用結案／刪除，提供重新讀取。
- 初始對應表載入失敗在預設頁顯示原因及重讀按鈕，不要求重裝或刪資料。
- 送修／DBN 等表單在非同步前置查詢時鎖定輸入；失敗保留內容並恢復原先欄位鎖定。取消導覽後的舊回應不會重新彈出表單。
- 非 JSON 回應／斷線有明確訊息，不自動重送寫入。
- DBN 搜尋補齊原版 DUT／類型及本機 PN／Model／站點；送修可搜尋 PN；萬用字元當成文字。
- 不同時區格式的來源時間保留原字串，但清單以時間點排序，不以字串誤判先後。
- 新增對應表單不把上一組價格默默帶入新 PN，也不覆蓋明確手改的 PN；保固及金額範圍在前後端檢查。

## 刻意保留的差異與未完成事項

1. **操作實作不等於像素還原**：編輯使用本機 dialog，清單採伺服器每頁 20 筆；快速搜尋提供轉往完整清單。異動每頁為 20 個事件，單一事件欄位一併顯示，與原版每頁 10 個欄位不同。
2. 原版 CSS／Logo 已離線封裝；本輪桌面瀏覽器未連線，沒有執行真實瀏覽器、CSS、Windows 縮放及視覺驗收。mock DOM 不取代這些檢查。
3. 原版 UI-only 硬編碼密碼沒有搬成「登入」。**真正登入、角色、具名稽核仍未實作**，須先決定公司帳號來源與權限規則。
4. **真實舊資料仍未移轉**：缺核准匯出檔及實體附件。現有工具只接受 README 的審核 JSON；原始 SQL／CSV、來源異動、舊欄位如 `repair_month`／`item`／`area`／`tester_id`／`failure_data`／`order_status` 沒有通用轉換器。未知欄位拒絕，不默默丟棄。需原樣保留來源檔，取得真實資料後再決定轉換及核對。
5. **正式內網、服務啟動管理、排程／異地備份仍未部署**。只監聽 localhost；不可自行改綁定位址或開防火牆作正式服務。需 IT 核准與主機設定。
6. 機台保養模組仍僅預留，不在目前備品優先範圍。
7. 第二輪 PASS、統計、主檔同步、人工復原及本輪畫面仍未通過公司驗收；使用者要求最後統一驗收，不將開發自動測試當作代替。

## 自動檢查與交付

命令及 Windows 安裝／保留資料步驟見 `README.md`。所有開發測試使用暫存資料，不改動公司正式資料。

- 後端／HTTP／升級／備份／離線匯入：`python -m unittest discover -s company -p "test_*.py" -v`
- UI 正常／故障恢復兩個隔離的 mock-DOM 套件：`swift scripts/test_company_ui.swift`
- 原版資源重現、離線頁面資源、保留對應維護入口：`python -m unittest discover -s scripts -p "test_company_ui_assets.py" -v`
- 重建：`python scripts/build_company_installer.py`
- 安裝器、回復、資料／venv 保護及脫離原始碼安裝後後端測試：`python -m unittest discover -s scripts -p "test_company_installer.py" -v`

安裝檔不封裝／覆寫 `company/data` 或 `.venv`，也不自動啟動服務、匯入真實舊資料或開放內網。
