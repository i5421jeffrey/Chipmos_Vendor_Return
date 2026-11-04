async function checkConnection() {
  const status = document.getElementById('status');
  const button = document.getElementById('refresh');
  button.disabled = true;
  status.textContent = '正在檢查…';
  status.dataset.state = '';
  try {
    const response = await fetch('/api/health', { cache: 'no-store', signal: AbortSignal.timeout(5000) });
    const data = await response.json();
    if (!response.ok || data.status !== 'ok') throw new Error('連線檢查失敗');
    status.textContent = '連線正常。';
    status.dataset.state = 'ok';
  } catch {
    status.textContent = '暫時無法連線，請稍後重新檢查。';
    status.dataset.state = 'error';
  } finally {
    button.disabled = false;
  }
}

document.getElementById('refresh').addEventListener('click', checkConnection);
checkConnection();
