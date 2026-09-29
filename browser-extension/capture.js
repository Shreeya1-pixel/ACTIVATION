// The manifest's match pattern cannot constrain ports; check the complete URL here and in the worker.
(() => {
  const fixtureUrl = 'http://127.0.0.1:4174/office.html';
  if (location.href !== fixtureUrl || window.top !== window) return;
  document.addEventListener('click', (event) => {
    if (!event.isTrusted || location.href !== fixtureUrl) return;
    const button = event.target.closest('button[data-action]');
    if (!button || !['record_opened', 'draft_saved'].includes(button.dataset.action)) return;
    // Fixture handlers run on the button before this document listener. Success is a connector signal,
    // not authorization: an untrusted page can change its DOM. Phase 3 must corroborate per connector.
    const signal = document.querySelector('#result');
    if (!signal || signal.dataset.action !== button.dataset.action || signal.dataset.outcome !== 'success') return;
    const record = signal.dataset.record;
    if (!/^C[0-9]{3}$/.test(record || '')) return;
    chrome.runtime.sendMessage({action: button.dataset.action, record, captured_at: new Date().toISOString()})
      .catch(() => { /* Closing/unloading a proof tab may disconnect the worker. No guessed event. */ });
  });
})();
