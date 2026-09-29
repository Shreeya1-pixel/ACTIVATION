async function refresh() {
  const {events = []} = await chrome.storage.local.get('events');
  document.querySelector('#events').textContent = JSON.stringify(events, null, 2);
}
document.querySelector('#refresh').addEventListener('click', refresh);
document.querySelector('#clear').addEventListener('click', async () => {
  await chrome.storage.local.remove('events');
  await refresh();
});
refresh();
