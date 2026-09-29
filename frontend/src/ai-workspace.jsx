// AIWorkspace — IDE-style replay of the real pipeline. Every terminal line and every
// file comes from worker responses (files are the ones written to disk under
// automations/); only the pacing is presentational.
import React, { useEffect, useMemo, useRef, useState } from 'react';

export const STAGES = [
  ['identify', 'Identify'], ['plan', 'Plan'], ['generate', 'Generate'], ['sandbox', 'Test & repair'],
  ['approve', 'Approve'], ['dryrun', 'Dry run'], ['live', 'Live'],
];
const STAGE_OF = { repair: 'sandbox', test: 'sandbox', undo: 'live' };
const LINE_MS = 22;
const EVENT_MS = 240;

const PY_KW = /\b(def|return|for|in|if|elif|else|continue|not|is|None|and|or|True|False|import|from|as|while|break|pass)\b/g;

function highlight(line, lang) {
  if (lang === 'diff') {
    const cls = line.startsWith('+') ? 'ws-add' : line.startsWith('-') ? 'ws-del' : line.startsWith('@@') ? 'ws-hunk' : '';
    return <span className={cls}>{line || ' '}</span>;
  }
  const parts = [];
  const re = lang === 'json'
    ? /("(?:[^"\\]|\\.)*")(\s*:)?|(-?\b\d+(?:\.\d+)?\b)|\b(true|false|null)\b/g
    : /(#.*$)|('(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")|(\b\d+\b)|(\b(?:def|return|for|in|if|elif|else|continue|not|is|None|and|or|True|False|import|from|as|while|break|pass)\b)/g;
  let last = 0;
  let m;
  while ((m = re.exec(line)) !== null) {
    if (m.index > last) parts.push(line.slice(last, m.index));
    if (lang === 'json') {
      if (m[1]) parts.push(<span key={m.index} className={m[2] ? 'ws-key' : 'ws-str'}>{m[1]}</span>, m[2] || '');
      else if (m[3]) parts.push(<span key={m.index} className="ws-num">{m[3]}</span>);
      else parts.push(<span key={m.index} className="ws-kw">{m[4]}</span>);
    } else if (m[1]) parts.push(<span key={m.index} className="ws-com">{m[1]}</span>);
    else if (m[2]) parts.push(<span key={m.index} className="ws-str">{m[2]}</span>);
    else if (m[3]) parts.push(<span key={m.index} className="ws-num">{m[3]}</span>);
    else parts.push(<span key={m.index} className={m[4] === 'def' ? 'ws-def' : 'ws-kw'}>{m[4]}</span>);
    last = m.index + m[0].length;
  }
  if (last < line.length) parts.push(line.slice(last));
  return parts.length ? parts : ' ';
}

function langOf(name) {
  if (name.endsWith('.py')) return 'py';
  if (name.endsWith('.json')) return 'json';
  if (name.endsWith('.diff')) return 'diff';
  return 'txt';
}

function FileIcon({ name }) {
  const l = langOf(name);
  const color = l === 'py' ? '#60a5fa' : l === 'json' ? '#fbbf24' : l === 'diff' ? '#34d399' : '#94a3b8';
  return <span className="ws-ficon" style={{ color }}>{l === 'py' ? 'py' : l === 'json' ? '{}' : l === 'diff' ? '±' : '•'}</span>;
}

export function AIWorkspace({ events, folder, model, onIdle }) {
  const [played, setPlayed] = useState(0);
  const [termLines, setTermLines] = useState([]);
  const [files, setFiles] = useState([]);
  const [active, setActive] = useState(null);
  const [typed, setTyped] = useState(0);
  const [typing, setTyping] = useState(null);
  const termRef = useRef(null);
  const codeRef = useRef(null);

  const busy = played < events.length || typing !== null;

  useEffect(() => {
    if (typing !== null) return undefined;
    if (played >= events.length) { if (onIdle) onIdle(); return undefined; }
    const ev = events[played];
    const t = setTimeout(() => {
      if (ev.text) setTermLines(prev => [...prev, { ...ev, ts: new Date().toLocaleTimeString('en-GB', { hour12: false }) }]);
      if (ev.file) {
        setFiles(prev => {
          const existing = prev.find(f => f.name === ev.file.name);
          if (existing) return prev.map(f => (f.name === ev.file.name ? { ...ev.file, status: 'M' } : f));
          return [...prev, { ...ev.file, status: 'A' }];
        });
        setActive(ev.file.name);
        setTyped(0);
        setTyping(ev.file.name);
      }
      setPlayed(p => p + 1);
    }, ev.delay ?? EVENT_MS);
    return () => clearTimeout(t);
  }, [played, events, typing, onIdle]);

  const activeFile = files.find(f => f.name === active);
  const lines = activeFile ? activeFile.content.split('\n') : [];

  useEffect(() => {
    if (typing === null || !activeFile) return undefined;
    if (typed >= lines.length) { setTyping(null); return undefined; }
    const step = lines.length > 60 ? 3 : 1;
    const t = setTimeout(() => setTyped(n => Math.min(lines.length, n + step)), LINE_MS);
    return () => clearTimeout(t);
  }, [typing, typed, lines.length, activeFile]);

  useEffect(() => { if (termRef.current) termRef.current.scrollTop = termRef.current.scrollHeight; }, [termLines]);
  useEffect(() => { if (codeRef.current && typing) codeRef.current.scrollTop = codeRef.current.scrollHeight; }, [typed, typing]);

  const reached = useMemo(() => {
    const seen = new Set();
    let failing = false;
    termLines.forEach(l => {
      const st = STAGE_OF[l.tag] || l.tag;
      seen.add(st);
      if (st === 'sandbox') failing = l.kind === 'fail' ? true : l.kind === 'ok' ? false : failing;
    });
    const order = STAGES.map(s => s[0]);
    const current = order.filter(s => seen.has(s)).pop();
    return { seen, current, failing };
  }, [termLines]);

  const shownLines = typing === active ? lines.slice(0, typed) : lines;

  return (
    <div className={`ws ${busy ? 'ws-busy' : ''}`}>
      <div className="ws-title">
        <div className="term-dots"><i /><i /><i /></div>
        <span className="ws-title-text">autostack · {folder || 'automation'}</span>
        <span className="ws-chip">{model}</span>
        <span className={`ws-state ${busy ? 'run' : ''}`}>{busy ? '● working' : '✓ idle'}</span>
      </div>

      <div className="ws-pipe">
        {STAGES.map(([id, label], i) => {
          const done = reached.seen.has(id) && id !== reached.current;
          const cur = id === reached.current;
          const fail = cur && id === 'sandbox' && reached.failing;
          return (
            <React.Fragment key={id}>
              {i > 0 && <span className={`ws-pipe-link ${reached.seen.has(id) ? 'on' : ''}`} />}
              <span className={`ws-pipe-step ${done ? 'done' : ''} ${cur ? (fail ? 'fail' : 'cur') : ''}`}>
                <span className="ws-pipe-dot">{done ? '✓' : fail ? '!' : i + 1}</span>{label}
              </span>
            </React.Fragment>
          );
        })}
      </div>

      <div className="ws-body">
        <div className="ws-explorer">
          <div className="ws-ex-head">EXPLORER</div>
          <div className="ws-ex-folder">▾ {folder || 'automation'}</div>
          {files.length === 0 && <div className="ws-ex-empty">no files yet</div>}
          {files.map(f => (
            <button key={f.name} className={`ws-ex-file ${f.name === active ? 'active' : ''} ${f.status === 'A' ? 'new' : ''}`}
                    onClick={() => { if (!typing) setActive(f.name); }}>
              <FileIcon name={f.name} /> <span className="ws-ex-name">{f.name}</span>
              <span className={`ws-git ${f.status}`}>{f.status === 'A' ? '+' : 'M'}</span>
            </button>
          ))}
        </div>

        <div className="ws-editor">
          <div className="ws-tabs">
            {files.map(f => (
              <span key={f.name} className={`ws-tab ${f.name === active ? 'active' : ''}`} onClick={() => { if (!typing) setActive(f.name); }}>
                <FileIcon name={f.name} /> {f.name}
              </span>
            ))}
          </div>
          <div className="ws-code" ref={codeRef}>
            {!activeFile && <div className="ws-empty">Files AutoStack writes will open here.</div>}
            {activeFile && shownLines.map((ln, i) => (
              <div key={i} className="ws-line">
                <span className="ws-ln">{i + 1}</span>
                <span className="ws-src">{highlight(ln, langOf(activeFile.name))}</span>
              </div>
            ))}
            {typing === active && activeFile && <span className="ws-caret" />}
          </div>
        </div>
      </div>

      <div className="ws-term" ref={termRef}>
        {termLines.map((l, i) => (
          <div key={i} className={`ws-tl ${l.kind || ''}`}>
            <span className="ws-ts">{l.ts}</span>
            <span className={`ws-tag t-${STAGE_OF[l.tag] || l.tag}`}>[{l.tag}]</span>
            <span>{l.text}</span>
          </div>
        ))}
        {busy && <div className="ws-tl dim"><span className="ws-caret small" /></div>}
      </div>

      <div className="ws-status">
        <span>⎇ {folder || 'automation'}</span>
        <span>sandbox: isolated subprocess</span>
        <span>network: blocked</span>
        <span>files: {files.length}</span>
        <span className="ws-status-right">{activeFile ? `${langOf(activeFile.name).toUpperCase()} · ${activeFile.lines} lines · UTF-8` : 'ready'}</span>
      </div>
    </div>
  );
}
