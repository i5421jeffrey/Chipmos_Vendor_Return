/* This password only gates the UI; it is not authentication or API authorization. */
(() => {
  const storageKey = "spms-edit-mode-v1";
  const adminPassword = "14561456";
  let enabled = false;
  try { enabled = sessionStorage.getItem(storageKey) === "on"; } catch {}

  const root = document.documentElement;
  const mount = document.getElementById("spms-mode-controls");
  if (!mount) return;
  mount.innerHTML = '<span class="spms-mode-label" id="spms-mode-label"></span><button class="spms-mode-button" id="spms-mode-toggle" type="button"></button><span class="spms-mode-message" id="spms-mode-message" role="status" aria-live="polite"></span>';
  const button = document.getElementById("spms-mode-toggle");
  const label = document.getElementById("spms-mode-label");
  const message = document.getElementById("spms-mode-message");
  const dialog = document.createElement("dialog");
  dialog.className = "spms-mode-dialog";
  dialog.setAttribute("aria-labelledby", "spms-password-title");
  dialog.innerHTML = '<form id="spms-password-form"><h2 id="spms-password-title">開啟編輯模式</h2><label for="spms-admin-password">管理員密碼</label><input id="spms-admin-password" type="password" autocomplete="off" required aria-describedby="spms-password-error"><div class="spms-mode-error" id="spms-password-error" role="alert"></div><div class="spms-mode-dialog-actions"><button class="spms-mode-button" id="spms-password-cancel" type="button">取消</button><button class="spms-mode-button" type="submit">開啟編輯模式</button></div></form>';
  document.body.append(dialog);
  const input = document.getElementById("spms-admin-password");
  const error = document.getElementById("spms-password-error");

  function applyMode() {
    root.dataset.spmsEditMode = enabled ? "on" : "off";
    label.textContent = enabled ? "編輯模式" : "閱讀模式";
    button.textContent = enabled ? "關閉編輯模式" : "開啟編輯模式";
    button.setAttribute("aria-pressed", String(enabled));
  }
  function setMode(value) {
    enabled = value;
    try {
      if (enabled) sessionStorage.setItem(storageKey, "on");
      else sessionStorage.removeItem(storageKey);
    } catch {
      message.textContent = "此瀏覽器無法保留模式，切換頁面後可能需要重新輸入密碼。";
    }
    applyMode();
    document.dispatchEvent(new CustomEvent("spms-edit-mode-change", { detail: { enabled } }));
  }
  function writeInProgress() {
    return ["submit-create", "submit-dbn", "submit-serial-map", "submit-retry", "finish-edit", "delete-record", "delete-file"].some(id => {
      const control = document.getElementById(id);
      return control?.disabled && control.getClientRects().length > 0;
    });
  }
  button.addEventListener("click", () => {
    message.textContent = "";
    if (enabled) {
      if (writeInProgress()) { message.textContent = "請等待目前操作完成，再關閉編輯模式。"; return; }
      setMode(false);
    } else {
      error.textContent = "";
      input.value = "";
      dialog.showModal();
      input.focus();
    }
  });
  document.getElementById("spms-password-form").addEventListener("submit", event => {
    event.preventDefault();
    if (input.value !== adminPassword) {
      error.textContent = "密碼錯誤，請重新輸入。";
      input.value = "";
      input.focus();
      return;
    }
    input.value = "";
    dialog.close();
    setMode(true);
  });
  document.getElementById("spms-password-cancel").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => { input.value = ""; error.textContent = ""; });

  // Also prevent normal UI events reaching the app while in reading mode.
  const writeControls = '#open-create,#open-dbn,#open-serial-map,#edit-record,#resolve-pass,#resolve-fail,#upload-file,#delete-file,#delete-record,#finish-edit,[data-dbn-action],[data-serial-map-action]';
  const writeForms = '#create-form,#dbn-form,#serial-map-form,#retry-form,#edit-record-form';
  const fileInputs = '#new-file-input,#retry-file-input,#file-input';
  function blockWrite(event, selector) {
    if (!enabled && event.target instanceof Element && event.target.closest(selector)) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }
  document.addEventListener("click", event => blockWrite(event, writeControls), true);
  document.addEventListener("submit", event => blockWrite(event, writeForms), true);
  document.addEventListener("change", event => blockWrite(event, fileInputs), true);
  // Back/forward navigation can restore an old page from the browser cache.
  window.addEventListener("pageshow", () => {
    let restored = enabled;
    try { restored = sessionStorage.getItem(storageKey) === "on"; } catch {}
    if (restored !== enabled) {
      enabled = restored;
      applyMode();
      document.dispatchEvent(new CustomEvent("spms-edit-mode-change", { detail: { enabled } }));
    }
    input.value = "";
  });
  applyMode();
})();
