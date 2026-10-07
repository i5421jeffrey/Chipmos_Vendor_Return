import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const SUPABASE_URL = "https://ywazcutaodqrthhighod.supabase.co";
const SUPABASE_KEY = "sb_publishable_wu8mVnxG-ifzSDB8Zl4wlg_xCRjl9k3";
const ATTACHMENT_BUCKET = "machine-maintenance-files";
const MAX_ATTACHMENT_SIZE = 5 * 1024 * 1024;
const ALLOWED_EXTENSIONS = new Set(["pdf", "png", "jpg", "jpeg", "txt", "asc"]);
const supabase = createClient(SUPABASE_URL, SUPABASE_KEY);

const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[char]));
const machineById = () => new Map(machines.map((machine) => [machine.id, machine]));

let machines = [];
let cases = [];
let events = [];
let attachments = [];
let activeView = "cases";
let statusFilter = "全部";
let selectedCaseId = null;
let selectedMachineId = null;
let editingCaseId = null;

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(`${String(value).slice(0, 10)}T00:00:00`);
  return Number.isNaN(date.valueOf())
    ? String(value)
    : new Intl.DateTimeFormat("zh-TW", { month: "numeric", day: "numeric" }).format(date);
}

function formatTimestamp(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? String(value)
    : new Intl.DateTimeFormat("zh-TW", {
      year: "numeric", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
    }).format(date);
}

function setConnectionState(state, text) {
  const badge = $("connection-state");
  badge.dataset.state = state;
  badge.textContent = text;
  $("system-note").innerHTML = state === "connected"
    ? `資料庫：Supabase<br>${machines.length ? `已載入 ${machines.length} 台機台` : "新機台清冊尚未匯入"}<br>公開存取`
    : state === "error"
      ? "資料庫：連線失敗<br>請檢查設定或遷移"
      : "資料庫：Supabase<br>讀取資料中…";
}

function showNotice(message, kind = "warning") {
  const notice = $("notice");
  notice.textContent = message;
  notice.className = `notice ${kind}`;
  notice.hidden = false;
}

function hideNotice() {
  $("notice").hidden = true;
}

function updateMachineOptions() {
  const select = $("form-machine");
  const previous = select.value;
  const options = machines.map((machine) => {
    const label = [machine.machine_code, machine.machine_name, machine.model]
      .filter(Boolean).join(" · ");
    return `<option value="${escapeHtml(machine.id)}">${escapeHtml(label)}</option>`;
  }).join("");
  select.innerHTML = `<option value="">${machines.length ? "選擇機台" : "機台清冊尚未匯入"}</option>${options}`;
  if (machines.some((machine) => machine.id === previous)) select.value = previous;
  $("new-case").disabled = machines.length === 0;

  const filter = $("model-filter");
  const selectedModel = filter.value;
  const models = [...new Set(machines.map((machine) => machine.model).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, "zh-TW"));
  filter.innerHTML = `<option value="">所有機型</option>${models.map((model) =>
    `<option value="${escapeHtml(model)}">${escapeHtml(model)}</option>`).join("")}`;
  if (models.includes(selectedModel)) filter.value = selectedModel;
}

async function loadData() {
  setConnectionState("loading", "連線中…");
  const [machineResult, caseResult] = await Promise.all([
    supabase.from("machine_maintenance_machines")
      .select("id,machine_code,machine_name,machine_serial,model,area")
      .order("machine_code", { ascending: true }),
    supabase.from("machine_maintenance_cases")
      .select("id,machine_id,fault_date,issue,description,status,priority,owner_vendor,created_at,updated_at,closed_at")
      .order("updated_at", { ascending: false }),
  ]);

  if (machineResult.error || caseResult.error) {
    machines = [];
    cases = [];
    events = [];
    attachments = [];
    setConnectionState("error", "資料庫錯誤");
    showNotice("無法讀取機台管理資料。請確認已執行 machine_maintenance_migration.sql，並檢查 Supabase 連線與權限。", "error");
    updateMachineOptions();
    render();
    return;
  }

  machines = machineResult.data || [];
  cases = caseResult.data || [];
  const ids = cases.map((item) => item.id);
  if (ids.length) {
    const [eventResult, attachmentResult] = await Promise.all([
      supabase.from("machine_maintenance_events")
        .select("id,case_id,event_type,from_status,to_status,created_at")
        .in("case_id", ids).order("created_at", { ascending: false }),
      supabase.from("machine_maintenance_attachments")
        .select("id,case_id,storage_path,filename,file_size,content_type,created_at")
        .in("case_id", ids).order("created_at", { ascending: true }),
    ]);
    events = eventResult.error ? [] : (eventResult.data || []);
    attachments = attachmentResult.error ? [] : (attachmentResult.data || []);
    if (eventResult.error || attachmentResult.error) {
      showNotice("案件已載入，但部分歷程或附件無法讀取。", "warning");
    } else {
      hideNotice();
    }
  } else {
    events = [];
    attachments = [];
    hideNotice();
  }

  if (!cases.some((item) => item.id === selectedCaseId)) selectedCaseId = cases[0]?.id || null;
  if (!machines.some((item) => item.id === selectedMachineId)) selectedMachineId = machines[0]?.id || null;
  setConnectionState("connected", "資料庫已連線");
  updateMachineOptions();
  render();
  if (machines.length === 0) {
    showNotice("機台管理資料庫已連線；新版機台清冊尚未匯入，因此目前無機台可選。請提供新版清冊後再匯入。", "warning");
  }
}

function filteredCases() {
  const query = $("search-cases").value.trim().toLocaleLowerCase();
  const model = $("model-filter").value;
  const sort = $("sort-filter").value;
  const byId = machineById();
  return cases
    .filter((item) => statusFilter === "全部" || item.status === statusFilter)
    .filter((item) => {
      const machine = byId.get(item.machine_id);
      return !model || machine?.model === model;
    })
    .filter((item) => {
      const machine = byId.get(item.machine_id);
      return [item.id, item.issue, item.description, item.owner_vendor,
        machine?.machine_code, machine?.machine_name, machine?.model]
        .join(" ").toLocaleLowerCase().includes(query);
    })
    .sort((a, b) => sort === "oldest"
      ? String(a.created_at).localeCompare(String(b.created_at))
      : String(b.updated_at).localeCompare(String(a.updated_at)));
}

function updateSummary() {
  const open = cases.filter((item) => item.status !== "已結案").length;
  const pending = cases.filter((item) => item.status === "待處理").length;
  const repairing = cases.filter((item) => item.status === "維修中").length;
  const review = cases.filter((item) => item.status === "待確認").length;
  $("metric-open").textContent = String(open);
  $("metric-pending").textContent = String(pending);
  $("metric-repairing").textContent = String(repairing);
  $("metric-review").textContent = String(review);
  $("count-all").textContent = String(cases.length);
  $("count-pending").textContent = String(pending);
  $("count-repairing").textContent = String(repairing);
  $("count-review").textContent = String(review);
  $("count-closed").textContent = String(cases.filter((item) => item.status === "已結案").length);
  $("nav-case-count").textContent = String(cases.length);
  $("nav-machine-count").textContent = String(machines.length);
}

function renderCaseList() {
  const rows = filteredCases();
  const byId = machineById();
  $("case-rows").innerHTML = rows.map((item) => {
    const machine = byId.get(item.machine_id);
    const machineLabel = machine?.machine_code || "機台資料不存在";
    return `<tr class="case-row ${selectedCaseId === item.id ? "selected" : ""}" data-id="${escapeHtml(item.id)}">
      <td><div class="case-id">${escapeHtml(item.id.slice(0, 8).toUpperCase())}</div><div class="issue-name">${escapeHtml(item.issue)}</div><div class="cell-sub">${escapeHtml(item.owner_vendor || "未指派")}</div></td>
      <td><div class="machine-code">${escapeHtml(machineLabel)}</div><div class="cell-sub">${escapeHtml(machine?.model || "—")}</div></td>
      <td><span class="status" data-status="${escapeHtml(item.status)}">${escapeHtml(item.status)}</span></td>
      <td>${formatDate(item.fault_date)}</td>
    </tr>`;
  }).join("");
  const empty = rows.length === 0;
  $("case-rows").closest("table").hidden = empty;
  $("empty-state").hidden = !empty;
  $("empty-state").textContent = cases.length === 0
    ? (machines.length ? "目前尚無維修案件。" : "尚未匯入新版機台清冊；匯入後即可建立維修案件。")
    : "沒有符合條件的維修案件。";
  $("list-meta").textContent = `${rows.length} 筆案件`;
  const latest = rows[0]?.updated_at;
  if (latest) $("list-meta").textContent += ` · 最近更新 ${formatTimestamp(latest)}`;
}

function renderMachineList() {
  const query = $("search-cases").value.trim().toLocaleLowerCase();
  const model = $("model-filter").value;
  const rows = machines.filter((machine) => (!model || machine.model === model)
    && [machine.machine_code, machine.machine_name, machine.machine_serial, machine.model, machine.area]
      .join(" ").toLocaleLowerCase().includes(query));
  $("machine-rows").innerHTML = rows.map((machine) => {
    const history = cases.filter((item) => item.machine_id === machine.id);
    const open = history.filter((item) => item.status !== "已結案").length;
    const recent = history.slice().sort((a, b) => String(b.fault_date || b.created_at)
      .localeCompare(String(a.fault_date || a.created_at)))[0];
    return `<tr class="machine-row ${selectedMachineId === machine.id ? "selected" : ""}" data-machine="${escapeHtml(machine.id)}">
      <td><div class="machine-code">${escapeHtml(machine.machine_code)}</div><div class="cell-sub">${escapeHtml(machine.machine_name || "未填機台名稱")}</div></td>
      <td>${escapeHtml(machine.model || "—")}</td><td>${open} 筆</td><td>${formatDate(recent?.fault_date)}</td>
    </tr>`;
  }).join("");
  const empty = rows.length === 0;
  $("machine-rows").closest("table").hidden = empty;
  $("empty-state").hidden = !empty;
  $("empty-state").textContent = machines.length
    ? "沒有符合條件的機台。"
    : "機台清單目前沒有資料；新版清冊匯入後會顯示於此。";
  $("list-meta").textContent = `${rows.length} 台機台`;
}

function statusEventLabel(event) {
  if (event.event_type === "created") return `建立案件 · ${event.to_status}`;
  return `進度由「${event.from_status || "—"}」更新為「${event.to_status}」`;
}

function publicAttachmentUrl(storagePath) {
  return supabase.storage.from(ATTACHMENT_BUCKET).getPublicUrl(storagePath).data.publicUrl;
}

function renderCaseDetail(item) {
  const panel = $("detail-panel");
  if (!item) {
    panel.innerHTML = `<div class="empty-state">${machines.length
      ? "選擇一筆案件以查看詳細資料。"
      : "資料庫已連線，等待新版機台清冊匯入。"}</div>`;
    return;
  }
  const machine = machineById().get(item.machine_id);
  const history = events.filter((event) => event.case_id === item.id);
  const files = attachments.filter((file) => file.case_id === item.id);
  panel.innerHTML = `<div class="detail-top"><div class="detail-idline"><span>${escapeHtml(item.id.slice(0, 8).toUpperCase())}</span><span>更新於 ${formatTimestamp(item.updated_at)}</span></div>
    <h2 class="detail-heading">${escapeHtml(item.issue)}</h2><div class="detail-status-line"><span class="status" data-status="${escapeHtml(item.status)}">${escapeHtml(item.status)}</span><span class="priority ${item.priority === "高" ? "high" : ""}">優先度：${escapeHtml(item.priority)}</span></div></div>
    <section class="detail-section"><div class="section-label">關聯機台</div><div class="machine-card"><div class="machine-icon">▦</div><div class="machine-info"><strong>${escapeHtml(machine?.machine_code || "機台資料不存在")}</strong><span>${escapeHtml([machine?.machine_name, machine?.model].filter(Boolean).join(" · ") || "—")}</span></div></div></section>
    <section class="detail-section"><div class="section-label">案件資訊</div><div class="info-grid"><div class="info-field"><label>故障日期</label><div>${formatDate(item.fault_date)}</div></div><div class="info-field"><label>負責人／廠商</label><div>${escapeHtml(item.owner_vendor || "未指派")}</div></div><div class="info-field"><label>建立時間</label><div>${formatTimestamp(item.created_at)}</div></div><div class="info-field"><label>結案時間</label><div>${formatTimestamp(item.closed_at)}</div></div></div></section>
    <section class="detail-section"><div class="section-label">問題描述</div><div class="description">${escapeHtml(item.description || "未補充問題描述")}</div></section>
    <section class="detail-section"><div class="section-label">附件</div>${files.length ? `<div class="attachment-list">${files.map((file) => `<a class="attachment-link" href="${escapeHtml(publicAttachmentUrl(file.storage_path))}" target="_blank" rel="noopener">↗ ${escapeHtml(file.filename)}</a>`).join("")}</div>` : '<div class="description">尚無附件</div>'}</section>
    <section class="detail-section"><div class="section-label">處理歷程</div>${history.length ? `<div class="timeline">${history.map((event) => `<div class="timeline-item"><div class="timeline-rail"><i class="timeline-dot"></i></div><div class="timeline-copy">${escapeHtml(statusEventLabel(event))}<time>${formatTimestamp(event.created_at)}</time></div></div>`).join("")}</div>` : '<div class="description">尚無歷程</div>'}</section>
    <div class="detail-footer"><button class="button" type="button" id="edit-case">編輯案件</button></div>`;
  $("edit-case").addEventListener("click", () => openCaseForm(item));
}

function renderMachineDetail(machine) {
  const panel = $("detail-panel");
  if (!machine) {
    panel.innerHTML = '<div class="empty-state">機台清冊匯入後，可在此查看機台資料與維修履歷。</div>';
    return;
  }
  const history = cases.filter((item) => item.machine_id === machine.id)
    .sort((a, b) => String(b.fault_date || b.created_at).localeCompare(String(a.fault_date || a.created_at)));
  const openCount = history.filter((item) => item.status !== "已結案").length;
  panel.innerHTML = `<div class="detail-top"><div class="detail-idline"><span>機台資料</span><span>${openCount} 筆未結案件</span></div><h2 class="detail-heading">${escapeHtml(machine.machine_name || machine.machine_code)}</h2></div>
    <section class="detail-section"><div class="section-label">基本資料</div><div class="info-grid"><div class="info-field"><label>機台編號</label><div>${escapeHtml(machine.machine_code)}</div></div><div class="info-field"><label>Model</label><div>${escapeHtml(machine.model || "—")}</div></div><div class="info-field"><label>機台序號</label><div>${escapeHtml(machine.machine_serial || "—")}</div></div><div class="info-field"><label>Area</label><div>${escapeHtml(machine.area || "—")}</div></div></div></section>
    <section class="detail-section"><div class="section-label">維修履歷</div>${history.length ? `<div class="timeline">${history.map((item) => `<div class="timeline-item"><div class="timeline-rail"><i class="timeline-dot"></i></div><div class="timeline-copy">${escapeHtml(item.issue)}<time>${formatDate(item.fault_date)} · ${escapeHtml(item.status)}</time></div></div>`).join("")}</div>` : '<div class="description">尚無維修案件</div>'}</section>
    <div class="detail-footer"><button class="button primary" type="button" id="new-machine-case">＋ 為此機台新增案件</button></div>`;
  $("new-machine-case").addEventListener("click", () => openCaseForm(null, machine.id));
}

function render() {
  updateSummary();
  const machineView = activeView === "machines";
  $("case-rows").closest("table").hidden = machineView;
  $("machine-rows").closest("table").hidden = !machineView;
  $("case-controls").hidden = false;
  $("status-tabs").hidden = machineView;
  $("sort-filter").hidden = machineView;
  $("search-cases").placeholder = machineView
    ? "搜尋機台編號、名稱、序號或機型…"
    : "搜尋案件、機台或故障內容…";
  $("list-title").textContent = machineView ? "所有機台" : "所有維修案件";
  if (machineView) {
    renderMachineList();
    renderMachineDetail(machines.find((machine) => machine.id === selectedMachineId));
  } else {
    const rows = filteredCases();
    if (!rows.some((item) => item.id === selectedCaseId)) selectedCaseId = rows[0]?.id || null;
    renderCaseList();
    renderCaseDetail(cases.find((item) => item.id === selectedCaseId));
  }
}

function setView(view) {
  activeView = view;
  document.querySelectorAll("[data-view]").forEach((button) => {
    if (button.classList.contains("toggle-button")) button.classList.toggle("active", button.dataset.view === view);
    else button.setAttribute("aria-current", String(button.dataset.view === view));
  });
  const machineView = view === "machines";
  $("page-title").textContent = machineView ? "機台清單" : "維修案件";
  $("breadcrumb-current").textContent = machineView ? "機台清單" : "維修案件";
  $("page-subtitle").textContent = machineView
    ? "瀏覽機台資料，並依機台查看維修履歷"
    : "集中追蹤各機台故障維修的處理進度與歷程";
  $("new-case").hidden = machineView;
  render();
}

function setStatusFilter(button) {
  statusFilter = button.dataset.statusFilter;
  document.querySelectorAll("[data-status-filter]").forEach((tab) => tab.classList.toggle("active", tab === button));
  renderCaseList();
  const selected = cases.find((item) => item.id === selectedCaseId && (statusFilter === "全部" || item.status === statusFilter));
  if (!selected) selectedCaseId = filteredCases()[0]?.id || null;
  renderCaseDetail(cases.find((item) => item.id === selectedCaseId));
  renderCaseList();
}

function openCaseForm(item = null, machineId = null) {
  if (machines.length === 0) {
    showNotice("請先匯入新版機台清冊，才能建立維修案件。", "warning");
    return;
  }
  editingCaseId = item?.id || null;
  $("case-form").reset();
  $("modal-title").textContent = item ? "編輯維修案件" : "新增維修案件";
  $("submit-case").textContent = item ? "儲存變更" : "建立案件";
  $("form-machine").value = item?.machine_id || machineId || "";
  $("form-date").value = item?.fault_date || new Date().toISOString().slice(0, 10);
  $("form-issue").value = item?.issue || "";
  $("form-description").value = item?.description || "";
  $("form-owner").value = item?.owner_vendor || "";
  $("form-priority").value = item?.priority || "一般";
  $("form-status").value = item?.status || "待處理";
  $("form-message").textContent = "";
  $("case-modal").hidden = false;
  $("form-machine").focus();
}

function closeCaseForm() {
  $("case-modal").hidden = true;
  editingCaseId = null;
}

function validateAttachment(file) {
  if (!file) return null;
  const extension = file.name.split(".").pop().toLowerCase();
  if (!ALLOWED_EXTENSIONS.has(extension)) return "附件格式僅接受 PDF、PNG、JPG、TXT 或 ASC。";
  if (file.size === 0 || file.size > MAX_ATTACHMENT_SIZE) return "附件不可為空，且單檔大小不得超過 5 MB。";
  return null;
}

async function uploadAttachment(caseId, file) {
  if (!file) return null;
  const validationError = validateAttachment(file);
  if (validationError) return validationError;
  const extension = file.name.split(".").pop().toLowerCase();
  const path = `${caseId}/${crypto.randomUUID()}.${extension}`;
  const { error: uploadError } = await supabase.storage.from(ATTACHMENT_BUCKET)
    .upload(path, file, { contentType: file.type || "application/octet-stream", upsert: false });
  if (uploadError) return `附件上傳失敗：${uploadError.message}`;
  const { error: metadataError } = await supabase.from("machine_maintenance_attachments").insert({
    case_id: caseId,
    storage_path: path,
    filename: file.name,
    file_size: file.size,
    content_type: file.type || "application/octet-stream",
  });
  if (metadataError) {
    return `附件資料登錄失敗：${metadataError.message}`;
  }
  return null;
}

async function saveCase(event) {
  event.preventDefault();
  const form = $("case-form");
  if (!form.reportValidity()) return;
  const isEditing = Boolean(editingCaseId);
  const button = $("submit-case");
  const message = $("form-message");
  const file = $("form-attachment").files?.[0] || null;
  const attachmentValidationError = validateAttachment(file);
  if (attachmentValidationError) {
    message.textContent = attachmentValidationError;
    return;
  }
  button.disabled = true;
  message.textContent = "正在儲存維修案件…";
  const payload = {
    machine_id: $("form-machine").value,
    fault_date: $("form-date").value || null,
    issue: $("form-issue").value.trim(),
    description: $("form-description").value.trim(),
    owner_vendor: $("form-owner").value.trim(),
    priority: $("form-priority").value,
    status: $("form-status").value,
  };
  let caseId = editingCaseId;
  let saveError = null;
  if (editingCaseId) {
    const { error } = await supabase.from("machine_maintenance_cases")
      .update(payload).eq("id", editingCaseId);
    saveError = error;
  } else {
    const { data, error } = await supabase.from("machine_maintenance_cases")
      .insert(payload).select("id").single();
    caseId = data?.id || null;
    saveError = error;
  }
  if (saveError || !caseId) {
    button.disabled = false;
    message.textContent = `儲存失敗：${saveError?.message || "資料庫未回傳案件編號"}`;
    return;
  }

  const attachmentError = await uploadAttachment(caseId, file);
  selectedCaseId = caseId;
  statusFilter = "全部";
  document.querySelectorAll("[data-status-filter]").forEach((tab) => tab.classList.toggle("active", tab.dataset.statusFilter === "全部"));
  setView("cases");
  await loadData();
  closeCaseForm();
  button.disabled = false;
  if (attachmentError) showNotice(`案件已儲存。${attachmentError}`, "warning");
  else showNotice(isEditing ? "維修案件已更新。" : "維修案件已建立。", "success");
}

document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
document.querySelectorAll("[data-status-filter]").forEach((button) => button.addEventListener("click", () => setStatusFilter(button)));
$("search-cases").addEventListener("input", render);
$("model-filter").addEventListener("change", render);
$("sort-filter").addEventListener("change", renderCaseList);
$("case-rows").addEventListener("click", (event) => {
  const row = event.target.closest("[data-id]");
  if (!row) return;
  selectedCaseId = row.dataset.id;
  renderCaseList();
  renderCaseDetail(cases.find((item) => item.id === selectedCaseId));
});
$("machine-rows").addEventListener("click", (event) => {
  const row = event.target.closest("[data-machine]");
  if (!row) return;
  selectedMachineId = row.dataset.machine;
  renderMachineList();
  renderMachineDetail(machines.find((item) => item.id === selectedMachineId));
});
$("new-case").addEventListener("click", () => openCaseForm());
$("close-modal").addEventListener("click", closeCaseForm);
$("cancel-modal").addEventListener("click", closeCaseForm);
$("case-modal").addEventListener("click", (event) => {
  if (event.target === $("case-modal")) closeCaseForm();
});
$("case-form").addEventListener("submit", saveCase);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !$("case-modal").hidden) closeCaseForm();
});

loadData();
