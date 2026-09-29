/* AutoStack bridge node: read tracking table + filter due rows (thin proxy to worker).
 * Output 1: ONE message per due row, parts-stamped so a downstream auto-join reassembles
 *           exactly the rows of this run: {run_id, payload:{run_id, record_key, ClientID}}.
 * Output 2: empty-due bypass — the original message, so the flow can close the run without
 *           a split/join pair (auto-join never fires on zero parts).
 */
module.exports = function (RED) {
  function AsReadDue(config) {
    RED.nodes.createNode(this, config);
    const node = this;
    node.on('input', async (msg, send, done) => {
      try {
        const runId = msg.run_id || (msg.payload && msg.payload.run_id);
        const res = await fetch(`${config.workerUrl}/api/nodes/read-due`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${config.workerToken}` },
          body: JSON.stringify({ run_id: runId }),
        });
        if (!res.ok) throw new Error(`worker ${res.status}`);
        const data = await res.json();
        if (!data.due.length) {
          node.status({ fill: 'yellow', shape: 'dot', text: 'no due rows' });
          send([null, msg]); // bypass: nothing to join — close the run via output 2
          done();
          return;
        }
        // parts.id is scoped per run+trigger so concurrent runs never cross-join.
        const partsId = `due:${runId}`;
        const msgs = data.due.map((row) => ({
          run_id: runId,
          payload: { run_id: runId, record_key: `sample:${row.ClientID}`, ClientID: row.ClientID },
          parts: { id: partsId, type: 'array', count: data.due.length },
        }));
        node.status({ fill: 'green', shape: 'dot', text: `due=${data.due.length}` });
        send([msgs, null]);
        done();
      } catch (err) {
        node.status({ fill: 'red', shape: 'ring', text: String(err.message).slice(0, 32) });
        done(err);
      }
    });
  }
  RED.nodes.registerType('as-read-due', AsReadDue);
};
