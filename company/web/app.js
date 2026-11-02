async function checkConnection() {
  const status = document.getElementById('status');
  const button = document.getElementById('refresh');
  button.disabled = true;
  status.textContent = '正在檢查…';
  status.dataset.state = '';
  for (const id of ['sqlite-version', 'schema-version', 'initialized-at', 'repairs-module']) {
    document.getElementById(id).textContent = '—';
  }
  try {
    const response = await fetch('/api/health', { cache: 'no-store', signal: AbortSignal.timeout(5000) });
    const data = await response.json();
    if (!response.ok || data.status !== 'ok') throw new Error('連線檢查失敗');
    document.getElementById('sqlite-version').textContent = data.sqlite_version;
    document.getElementById('schema-version').textContent = data.schema_version;
    document.getElementById('repairs-module').textContent = data.modules?.repairs
      ? `版本 ${data.modules.repairs}（送修基本流程）` : '未安裝';
    document.getElementById('initialized-at').textContent = data.initialized_at;
    status.textContent = 'Python 服務正常，SQLite 已連線。';
    status.dataset.state = 'ok';
  } catch {
    status.textContent = '無法連線，請確認 PowerShell 中的服務仍在執行，並查看是否有錯誤。';
    status.dataset.state = 'error';
  } finally {
    button.disabled = false;
  }
}

document.getElementById('refresh').addEventListener('click', checkConnection);
checkConnection();
