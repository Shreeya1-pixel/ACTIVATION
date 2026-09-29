// Plain-language reading of a detected pattern, derived only from its evidence
// (file name, step actions, changed column names).
const KIND_RULES = [
  [/status/i, 'Status update'],
  [/check|verif|valid/i, 'Verification check'],
  [/amount|pay|aed|net|total|price|hours/i, 'Amounts / calculation'],
  [/request|follow|remind|email|notif/i, 'Follow-up'],
  [/date|week|month|due/i, 'Date tracking'],
];

function parseStep(step) {
  const m = /^row\.(added|updated|removed)(?:\[(.*)\])?$/.exec(step || '');
  if (!m) return { action: step, fields: [] };
  return { action: m[1], fields: m[2] ? m[2].split(',').map(f => f.trim()).filter(Boolean) : [] };
}

function stepSentence(step) {
  const { action, fields } = parseStep(step);
  if (action === 'added') return 'adds a new row';
  if (action === 'removed') return 'deletes a row';
  if (!fields.length) return 'edits the row';
  return `${fields.length >= 3 ? 'fills in' : 'updates'} ${fields.join(', ')}`;
}

export function describePattern(c) {
  const steps = (c.evidence && c.evidence.steps) || (c.pattern && c.pattern.sequence) || [];
  const resource = (c.pattern && c.pattern.resource) || '';
  const file = resource.split('/').pop().replace(/^sample_/, '').replace(/[_-]+/g, ' ').trim();
  const kinds = [];
  const parsed = steps.map(parseStep);
  if (parsed.some(p => p.action === 'added' || p.fields.length >= 3)) kinds.push('Data entry');
  const allFields = parsed.flatMap(p => p.fields).join(' ');
  KIND_RULES.forEach(([re, label]) => { if (re.test(allFields) && !kinds.includes(label)) kinds.push(label); });
  const records = Object.keys((c.evidence && c.evidence.per_client) || {}).map(k => k.split(':').pop());
  return {
    title: `Excel workflow · ${file ? file[0].toUpperCase() + file.slice(1) : 'spreadsheet'}`,
    kinds: kinds.length ? kinds : ['Repeated edits'],
    steps: steps.map(stepSentence),
    records,
    instances: c.occurrences || (c.evidence && c.evidence.instances) || 0,
    distinct: (c.evidence && c.evidence.distinct_clients) || records.length,
    file,
  };
}

export function whyNotSuggested(d) {
  if (d.distinct < 2) return `only on one record (${d.records[0] || 'one row'}), so it looks like a one-off fix, not a routine`;
  if (d.instances < 3) return `only ${d.instances} time(s), and a routine needs at least 3`;
  return 'below the detection rule';
}

