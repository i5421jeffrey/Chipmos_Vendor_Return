# SPMS Flask／Waitress 離線套件

僅供 **Windows x64、標準 CPython 3.13**（非 32 位元、ARM64 或 free-threaded）使用。
Flask 3.1.3、Waitress 3.0.2 及七個相依套件從 PyPI 下載；建置時以 PyPI release JSON 比對各 wheel 的 SHA256。上游授權文件保留在各 wheel 的 dist-info 目錄。

這不是 SPMS 網站更新，不包含公司資料、密碼或 `.venv`，不會自動將網站改成 Flask／Waitress。

## 公司端只需一個檔案

從 GitHub Raw 下載根目錄的 `install_spms_dependencies.py`，放到 `D:\Python\SPMS`。不要誤用原本的 `install_spms.py`；兩者用途不同。經公司核准方式搬入及使用，不修改 Proxy／憑證或安全政策。

先停止 SPMS，在 CMD 執行：

```cmd
cd /d D:\Python\SPMS
.\.venv\Scripts\python.exe -c "import sys,platform,struct; print(sys.version); print(platform.machine(),struct.calcsize('P')*8)"
.\.venv\Scripts\python.exe .\install_spms_dependencies.py --check
.\.venv\Scripts\python.exe .\install_spms_dependencies.py
```

確認目標是 SPMS 的 `.venv`，輸入 `INSTALL` 才安裝；使用 pip 的 `--no-index`、本機 wheel 及完整版本／SHA256 鎖定，不會下載套件或查版本。不需要管理員權限。現有的這九個套件若版本不同可能被替換，無整批回復保證；失敗時保留訊息，不反覆重建環境。原始資料庫與編輯密碼不改。

最後會載入 Flask／Waitress 並顯示版本。這不表示公司網路、Proxy 或網站服務切換已測試。

## 重現建置（開發端）

wheel 檔案與單檔安裝程式皆保留上游內容。使用 Python 執行：

```text
python scripts/build_spms_dependencies.py --verify-pypi
python -m unittest discover -s scripts -p "test_spms_dependencies.py" -v
```

實際 Windows 安裝尚待現場驗證；macOS 的建置／模擬測試不是 Windows 安裝驗收。
