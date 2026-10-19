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
  return selection.numbers.map(number => {
    const pins = snapshot?.[String(number)];
    return `<div class="dut-pin-line"><strong>DUT${number}</strong><span>${Array.isArray(pins) ? escape(pins.join(', ')) : '尚無對應'}</span></div>`;
  }).join('');
}

export function createDbnSockets(supabase, byId, escape) {
  const files = new Map();
  let ready = false, loadMessage = 'Socket File 載入中…', original = null;
  function preview() {
    const input = byId('dbn-dut'), output = byId('dbn-dut-pins'), product = byId('dbn-product').value;
    input.setCustomValidity('');
    try {
      const selection = parseDut(input.value), file = files.get(product);
      const same = original?.socket_file_id && selection.text === (original.dut || '') && product === original.product_code;
      if (!selection.text) { output.textContent = '填入 DUT 後自動顯示 PIN（選填）'; return; }
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
    open(record) { original = record;byId('dbn-dut').value = record?.dut || '';preview(); },
    preview,
    payload() {
      preview();
      const selection = parseDut(byId('dbn-dut').value);
      if (selection.text && !ready) throw new Error(loadMessage);
      if (!byId('dbn-dut').checkValidity()) throw new Error(byId('dbn-dut').validationMessage);
      return ready ? { dut: selection.text || null } : {};
    },
  };
}
