export function parseDut(value, maximum = 2048) {
  const text = String(value ?? '').trim().replace(/\s*-\s*/g, '-');
  if (!text) return { text: '', numbers: [] };
  if (!/^\d{1,4}(?:-\d{1,4})?$/.test(text)) throw new Error('DUT 請輸入單一編號或連續範圍，例如 39、21-28');
  const parts = text.split('-').map(Number), first = parts[0], last = parts[1] ?? first;
  if (first < 1 || last < first || last > maximum) throw new Error(`DUT 須介於 1–${maximum}，結束編號不得小於起始編號`);
  return { text: first === last ? String(first) : `${first}-${last}`, numbers: Array.from({ length: last - first + 1 }, (_, i) => first + i) };
}

export function socketPinsMarkup(dut, snapshot, escape) {
  if (!dut) return '';
  const selection = parseDut(dut);
  const rows = selection.numbers.map(number => {
    const pins = snapshot?.[String(number)];
    return { number, pins: Array.isArray(pins) ? [...new Set(pins)] : null };
  });
  // Group exact tokens by their DUT membership, including partial sharing.
  const membership = new Map(), groups = new Map(), shared = new Set();
  for (const { number, pins } of rows) for (const pin of pins || []) {
    if (!membership.has(pin)) membership.set(pin, []);
    membership.get(pin).push(number);
  }
  for (const [pin, numbers] of membership) {
    if (numbers.length < 2) continue;
    shared.add(pin);
    const key = numbers.join(',');
    if (!groups.has(key)) groups.set(key, { numbers, pins: [] });
    groups.get(key).pins.push(pin);
  }
  function dutLabel(numbers) {
    const ranges = [];
    for (let i = 0; i < numbers.length; i++) {
      const first = numbers[i];
      while (numbers[i + 1] === numbers[i] + 1) i++;
      ranges.push(first === numbers[i] ? `DUT${first}` : `DUT${first}-${numbers[i]}`);
    }
    return ranges.join(', ');
  }
  const header = [...groups.values()]
    .sort((a, b) => Number(b.numbers.length === rows.length) - Number(a.numbers.length === rows.length))
    .map(({ numbers, pins }) => {
      const scope = numbers.length === rows.length ? '' : `${dutLabel(numbers)}：`;
      return `<div class="dut-pin-line"><strong>共用PIN:</strong><span>${escape(scope + pins.join(', '))}</span></div>`;
    }).join('');
  return header + rows.map(({ number, pins }) => {
    const remaining = pins?.filter(pin => !shared.has(pin));
    return `<div class="dut-pin-line"><strong>DUT${number}:</strong><span>${pins ? (remaining.length ? escape(remaining.join(', ')) : '無額外 PIN') : '尚無對應'}</span></div>`;
  }).join('');
}

export function validateDbnIssue(type, dut, description) {
  if (!['Group', 'Single Dut', 'RTE', 'Other'].includes(type)) throw new Error('請選擇 DBN 類型');
  if (type === 'RTE' || type === 'Other') {
    const text = String(description ?? '').trim();
    if (!text) throw new Error('異常描述：此欄位必填');
    return { issue_type: type, dut: null, issue_description: text };
  }
  const selection = parseDut(dut);
  if (!selection.numbers.length) throw new Error('DUT：此欄位必填');
  if (type === 'Single Dut' && (selection.numbers.length !== 1 || String(dut).includes('-'))) throw new Error('Single Dut 請填寫單一 DUT 編號');
  if (type === 'Group' && selection.numbers.length > 8) throw new Error('Group 僅接受連續 1–8 個 DUT');
  return { issue_type: type, dut: selection.text, issue_description: null };
}

export function createDbnSockets(supabase, byId, escape) {
  const files = new Map();
  let ready = false, loadMessage = 'Socket File 載入中…', original = null;
  function preview() {
    const input = byId('dbn-dut'), output = byId('dbn-dut-pins'), product = byId('dbn-product').value;
    const type = byId('dbn-issue-type').value, usesDut = type === 'Group' || type === 'Single Dut', usesDescription = type === 'RTE' || type === 'Other';
    byId('dbn-dut-field').hidden = !usesDut;
    byId('dbn-pin-field').hidden = !usesDut;
    byId('dbn-description-field').hidden = !usesDescription;
    input.required = usesDut;input.disabled = !usesDut;
    byId('dbn-issue-description').required = usesDescription;
    byId('dbn-issue-description').disabled = !usesDescription;
    input.placeholder = type === 'Single Dut' ? '例如：39' : '例如：1-4、1-8、21-28';
    input.setCustomValidity('');
    if (!usesDut) { output.textContent = '';return; }
    try {
      const selection = parseDut(input.value), file = files.get(product);
      if (selection.text) validateDbnIssue(type, input.value, '');
      const same = original?.socket_file_id && selection.text === (original.dut || '') && product === original.product_code;
      if (!selection.text) { output.textContent = '填入 DUT 後自動顯示 PIN'; return; }
      if (!ready) { output.textContent = loadMessage; return; }
      if (file && !same) parseDut(selection.text, file.dut_count);
      output.innerHTML = socketPinsMarkup(selection.text, same ? original.dut_pin_snapshot : file?.dut_pins, escape);
    } catch (error) { input.setCustomValidity(error.message); output.textContent = error.message; }
  }
  return {
    get ready() { return ready; },
    async load() {
      try {
        const { data, error } = await supabase.from('dbn_socket_files').select('id,product_code,source_filename,dut_count,dut_pins').eq('is_active', true);
        if (error) throw error;
        files.clear();for (const file of data || []) files.set(file.product_code, file);
        ready = true;loadMessage = '';
      } catch (error) { ready = false;loadMessage = `Socket File 尚未就緒，請先執行 DUT 與 Socket File 遷移：${error.message}`; }
      preview();
    },
    open(record) {
      original = record;byId('dbn-dut').value = record?.dut || '';
      byId('dbn-issue-type').value = record?.issue_type || '';
      byId('dbn-issue-description').value = record?.issue_description || '';preview();
    },
    preview,
    payload() {
      preview();
      const issue = validateDbnIssue(byId('dbn-issue-type').value, byId('dbn-dut').value, byId('dbn-issue-description').value);
      if (issue.dut && !ready) throw new Error(loadMessage);
      if (!byId('dbn-dut').checkValidity()) throw new Error(byId('dbn-dut').validationMessage);
      return issue;
    },
  };
}
