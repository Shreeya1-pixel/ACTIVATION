let opened = null;
const result = document.querySelector('#result');
function report(action, outcome, record, text) {
  Object.assign(result.dataset, {action, outcome, record: record || ''});
  result.textContent = text;
}
document.querySelector('#client').addEventListener('change', () => {
  opened = null;
  report('', 'ambiguous', '', 'Open the selected record first.');
});
document.querySelector('#open').addEventListener('click', () => {
  opened = document.querySelector('#client').value;
  document.querySelector('#record').textContent = `${opened}: invented client, ${opened.toLowerCase()}@example.invalid`;
  report('record_opened', 'success', opened, `Opened ${opened}.`);
});
document.querySelector('#save').addEventListener('click', () => {
  const text = document.querySelector('#draft').value.trim();
  if (!opened || !text || text.length > 2000) return report('draft_saved', 'ambiguous', opened, 'Open a record and enter a draft of 1–2,000 characters.');
  try {
    localStorage.setItem(`autostack-sample-draft:${opened}`, text);
    report('draft_saved', 'success', opened, `Draft saved for ${opened}. It has not been sent.`);
  } catch {
    report('draft_saved', 'ambiguous', opened, 'Storage failed; no successful save recorded.');
  }
});
document.querySelector('#reset').addEventListener('click', () => {
  for (const id of ['C001', 'C002', 'C003']) localStorage.removeItem(`autostack-sample-draft:${id}`);
  report('', 'success', '', 'Sample drafts deleted. Clear extension events separately.');
});
