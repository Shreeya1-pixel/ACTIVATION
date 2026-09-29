/* AutoStack bridge node: redacted desktop notification + run completion via worker. */
module.exports = function (RED) {
  function AsNotify(config) {
    RED.nodes.createNode(this, config);
    const node = this;
    node.on('input', async (msg, send, done) => {
      try {
        const res = await fetch(`${config.workerUrl}/api/nodes/notify`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${config.workerToken}` },
          body: JSON.stringify({ run_id: msg.run_id, title: 'AutoStack run finished', redacted: true }),
        });
        if (!res.ok) throw new Error(`worker ${res.status}`);
        // Complete the run in the worker (bridge transport). A catch-node reroute carries
        // msg.error; a normal completion does not.
        const failed = Boolean(msg.error || msg._run_failed);
        await fetch(`${config.workerUrl}/api/runs/${msg.run_id}/complete`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${config.workerToken}` },
          body: JSON.stringify({ run_id: msg.run_id, status: failed ? 'failed' : 'passed',
                                 error: failed ? String(msg.error?.message || msg.error) : null }),
        });
        node.status({ fill: 'green', shape: 'dot', text: 'notified + closed run' });
        done();
      } catch (err) {
        node.status({ fill: 'red', shape: 'ring', text: String(err.message).slice(0, 32) });
        done(err);
      }
    });
  }
  RED.nodes.registerType('as-notify', AsNotify);
};
