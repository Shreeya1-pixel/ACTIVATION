const fixtureUrl = 'http://127.0.0.1:4174/office.html';
const actions = {
  record_opened: ['sample_browser', 'sample-client-page'],
  draft_saved: ['sample_draft_editor', 'sample-draft-store'],
};
let queue = Promise.resolve();
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== chrome.runtime.id || sender.url !== fixtureUrl || sender.frameId !== 0 ||
      !message || typeof message !== 'object' || Object.keys(message).sort().join(',') !== 'action,captured_at,record' ||
      typeof message.action !== 'string' || !Object.hasOwn(actions, message.action) ||
      typeof message.record !== 'string' || !/^C[0-9]{3}$/.test(message.record) ||
      typeof message.captured_at !== 'string' || !Number.isFinite(Date.parse(message.captured_at))) {
    respond({accepted: false});
    return false;
  }
  queue = queue.then(async () => {
    const {events = []} = await chrome.storage.local.get('events');
    // Stop when full; do not silently discard evidence. Synthetic data only, no production storage claims.
    if (events.length >= 100) return respond({accepted: false, reason: 'fixture_queue_full'});
    const [source, resource] = actions[message.action];
    events.push({schema_version: 1, source_version: 'phase1-0.1.0', event_id: crypto.randomUUID(), captured_at: message.captured_at,
      processed_at: new Date().toISOString(), source, action: message.action, resource,
      record_key: `sample:${message.record}`, changed_fields: [], outcome: 'success', synthetic: true});
    await chrome.storage.local.set({events});
    respond({accepted: true});
  }).catch(() => respond({accepted: false, reason: 'storage_error'}));
  return true;
});
