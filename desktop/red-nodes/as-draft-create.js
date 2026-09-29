/* AutoStack bridge node: create the in-app follow-up draft via worker (exactly-once). */
module.exports = function (RED) {
  function AsDraftCreate(config) {
    RED.nodes.createNode(this, config);
    const node = this;
    node.on('input', async (msg, send, done) => {
      try {
        const recordKey = msg.payload && msg.payload.record_key;
        const res = await fetch(`${config.workerUrl}/api/nodes/draft-create`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${config.workerToken}` },
          body: JSON.stringify({ run_id: msg.run_id, record_key: recordKey,
                                 template_id: config.templateId || 'followup_en',
                                 destination: 'in_app' }),
        });
        if (!res.ok) throw new Error(`worker ${res.status}`);
        const data = await res.json();
        node.status({ fill: data.skipped ? 'yellow' : 'green', shape: 'dot',
                      text: data.skipped ? 'already claimed' : `draft ${recordKey}` });
        send(msg);
        done();
      } catch (err) {
        node.status({ fill: 'red', shape: 'ring', text: String(err.message).slice(0, 32) });
        done(err);
      }
    });
  }
  RED.nodes.registerType('as-draft-create', AsDraftCreate);
};
