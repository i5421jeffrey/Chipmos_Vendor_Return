const amountColumns = {
  '板修': 'board_repair_amount',
  '外修': 'external_repair_amount',
  '合約': 'contract_repair_amount',
  '保固': 'warranty_repair_amount',
};

// NULL/blank means unset; never substitute 1, 0, or another Model's price.
export function resolveRepairPrice(prices, type, model, boardName, partNumber) {
  const column = amountColumns[type];
  if (!column || !model || !boardName || !partNumber) return null;
  const row = prices.find(price => price.model === model
    && price.board_name === boardName && price.board_part_code === partNumber);
  const raw = row?.[column];
  if (raw === null || raw === undefined || raw === '' || typeof raw === 'boolean') return null;
  const amount = Number(raw);
  return Number.isFinite(amount) && amount >= 0 ? amount : null;
}
