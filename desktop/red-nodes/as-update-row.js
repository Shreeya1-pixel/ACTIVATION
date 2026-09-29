/* AutoStack bridge node: apply the row status update via worker (claims effect key first). */
module.exports = function (RED) {
  function AsUpdateRow(config) {
    RED.nodes.createNode(this, config);
    const node = this;
    node.on('input', async (msg, send, done) => {
      try {
        const recordKey = msg.payload && msg.payload.record_key;
        const res = await fetch(`${config.workerUrl}/api/nodes/update-row`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${config.workerToken}` },
          body: JSON.stringify({ run_id: msg.run_id, record_key: recordKey }),
        });
        if (!res.ok) throw new Error(`worker ${res.status}`);
        const data = await res.json();
        if (data.skipped) {
          node.status({ fill: 'yellow', shape: 'dot', text: 'already claimed' });
        } else {
          node.status({ fill: 'green', shape: 'dot', text: `updated ${recordKey}` });
        }
        send(msg);
        done();
      } catch (err) {
        node.status({ fill: 'red', shape: 'ring', text: String(err.message).slice(0, 32) });
        done(err);
      }
    });
  }
  RED.nodes.registerType('as-update-row', AsUpdateRow);
};
