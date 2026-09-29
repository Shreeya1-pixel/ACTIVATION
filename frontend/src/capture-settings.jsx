// Capture settings: which folder the watcher reads, and per file the ID column and the
// columns that matter. Only column names come back from the worker — never cell values.
import React, { useEffect, useState } from 'react';
import { api } from './api.js';

export function CaptureSettings({ onChanged }) {
  const [open, setOpen] = useState(false);
  const [preview, setPreview] = useState(null);
  const [folder, setFolder] = useState('');
  const [files, setFiles] = useState({});
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  const refresh = async () => {
    try {
      const [cfg, pv] = await Promise.all([api.captureConfig(), api.capturePreview()]);
      setFolder(cfg.custom_folder ? cfg.folder : '');
      setFiles(cfg.files || {});
      setPreview(pv);
    } catch (e) {
      setMsg({ kind: 'warn', text: `Could not read capture settings: ${e.message}` });
    }
  };

  useEffect(() => { if (open) refresh(); }, [open]);

  const setFile = (name, patch) => setFiles(prev => ({ ...prev, [name]: { ...(prev[name] || {}), ...patch } }));

  const toggleColumn = (name, header, idCol, col) => {
    const current = (files[name] && files[name].columns) || header.filter(h => h !== idCol);
    const next = current.includes(col) ? current.filter(c => c !== col) : [...current, col];
    setFile(name, { columns: next });
  };

  const save = async (resetFolder = false) => {
    setBusy(true);
    setMsg(null);
    try {
      const body = { folder: resetFolder ? '' : folder, files };
      let promoted = false;
      try {
        await api.setCaptureConfig(body);
      } catch (e) {
        if (!/may not perform/.test(e.message)) throw e;
        await api.teamSelfRole('owner');  // allowed only in solo workspaces; otherwise throws
        await api.setCaptureConfig(body);
        promoted = true;
      }
      setMsg({ kind: 'ok', text: `${promoted ? 'Switched you to owner (solo workspace). ' : ''}Saved. The next poll uses these settings (first read of a file is its baseline).` });
      await refresh();
      if (onChanged) onChanged();
    } catch (e) {
      setMsg({ kind: 'warn', text: e.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card" style={{ marginBottom: 14, padding: 14 }}>
      <button className="btn-outline" onClick={() => setOpen(o => !o)}>
        {open ? 'Hide capture settings' : 'Capture settings: folder, ID column, columns that matter'}
      </button>
      {open && (
        <div style={{ marginTop: 12 }}>
          <label style={{ display: 'block', marginBottom: 8 }}>Watched folder (absolute path; leave blank for the built-in sample folder)
            <input style={{ width: '100%' }} value={folder} placeholder={preview ? preview.folder : ''}
                   onChange={e => setFolder(e.target.value)} />
          </label>
          <p className="muted" style={{ margin: '4px 0 10px' }}>
            Reading now: <code>{preview ? preview.folder : '…'}</code>{preview && !preview.exists ? ' (does not exist)' : ''}.
            CSV and XLSX files are read; only column names and record IDs are recorded.
          </p>
          {preview && preview.files.length === 0 && <p className="muted">No CSV or XLSX files in this folder yet.</p>}
          {preview && preview.files.map(f => {
            const idCol = (files[f.file] && files[f.file].id_column) || f.id_column_in_use || f.suggested_id_column || '';
            const tracked = (files[f.file] && files[f.file].columns) || (f.header || []).filter(h => h !== idCol);
            return (
              <div key={f.file} style={{ borderTop: '1px solid #e5e7eb', padding: '10px 0' }}>
                <b>{f.file}</b>{' '}
                {f.ok
                  ? <span className="muted">{f.records} records{f.rows_without_id ? `, ${f.rows_without_id} without an ID skipped` : ''}{f.blank_rows ? `, ${f.blank_rows} blank rows` : ''}</span>
                  : <span style={{ color: '#b45309' }}>cannot read: {f.error}</span>}
                {f.header && (
                  <div style={{ marginTop: 6 }}>
                    <label>ID column{' '}
                      <select value={idCol} onChange={e => setFile(f.file, { id_column: e.target.value, columns: null })}>
                        {f.header.map(h => <option key={h} value={h}>{h}{h === f.suggested_id_column ? ' (suggested)' : ''}</option>)}
                      </select>
                    </label>
                    <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                      <span className="muted">Columns that matter:</span>
                      {f.header.filter(h => h !== idCol).map(h => (
                        <label key={h} style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
                          <input type="checkbox" checked={tracked.includes(h)}
                                 onChange={() => toggleColumn(f.file, f.header, idCol, h)} />{h}
                        </label>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button className="btn-primary" disabled={busy} onClick={() => save(false)}>Save settings</button>
            <button className="btn-outline" disabled={busy} onClick={() => save(true)}>Use built-in sample folder</button>
            <button className="btn-outline" disabled={busy} onClick={refresh}>Refresh</button>
          </div>
          {msg && <p style={{ marginTop: 8, color: msg.kind === 'ok' ? '#047857' : '#b45309' }}>{msg.text}</p>}
        </div>
      )}
    </div>
  );
}
