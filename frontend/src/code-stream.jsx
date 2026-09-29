// CodeStream — editor-style replay of the generation + self-repair attempts the
// worker actually produced. Code, verdicts and feedback all come from the
// /api/artifacts/generate response; only the typing speed is presentational.
import React, { useEffect, useRef, useState } from 'react';

const LINE_MS = 55;
const PAUSE_MS = 1400;

function verdict(a) {
  if (!a.problems || a.problems.length === 0) return 'passed';
  return 'failed';
}

export function CodeStream({ attempts, provider }) {
  const [active, setActive] = useState(0);
  const [shown, setShown] = useState(0);
  const [phase, setPhase] = useState('typing');
  const [runId, setRunId] = useState(0);
  const bodyRef = useRef(null);

  const list = attempts || [];
  const cur = list[active];
  const lines = cur ? (cur.code || '').split('\n') : [];

  useEffect(() => { setActive(0); setShown(0); setPhase('typing'); }, [attempts, runId]);

  useEffect(() => {
    if (!cur) return undefined;
    if (phase === 'typing') {
      if (shown >= lines.length) {
        const t = setTimeout(() => setPhase('testing'), 350);
        return () => clearTimeout(t);
      }
      const t = setTimeout(() => setShown(n => n + 1), LINE_MS);
      return () => clearTimeout(t);
    }
    if (phase === 'testing') {
      const t = setTimeout(() => setPhase('verdict'), 900);
      return () => clearTimeout(t);
    }
    if (phase === 'verdict' && active < list.length - 1) {
      const t = setTimeout(() => { setActive(a => a + 1); setShown(0); setPhase('typing'); }, PAUSE_MS);
      return () => clearTimeout(t);
    }
    return undefined;
  }, [cur, phase, shown, lines.length, active, list.length]);

  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
  }, [shown]);

  if (!cur) return null;
  const v = verdict(cur);
  const author = cur.seeded
    ? 'deliberately broken draft (demo)'
    : provider === 'gemini' ? 'Gemini' : 'offline generator (no LLM call)';

  return (
    <div className="codestream">
      <div className="codestream-tabs">
        {list.map((a, i) => (
          <button key={a.attempt} className={`codestream-tab ${i === active ? 'active' : ''} ${i < active || (i === active && phase === 'verdict') ? verdict(a) : ''}`}
                  onClick={() => { setActive(i); setShown((a.code || '').split('\n').length); setPhase('verdict'); }}>
            automation_v{a.version || a.attempt}.py
          </button>
        ))}
        <span className="codestream-author">writing: {author}</span>
        <button className="codestream-replay" onClick={() => setRunId(r => r + 1)}>Replay</button>
      </div>
      <div className="codestream-body" ref={bodyRef}>
        {lines.slice(0, shown).map((ln, i) => (
          <div key={i} className="codestream-line">
            <span className="codestream-ln">{i + 1}</span>
            <span>{ln || ' '}</span>
          </div>
        ))}
        {phase === 'typing' && <span className="codestream-caret" />}
      </div>
      <div className={`codestream-status ${phase === 'verdict' ? v : 'run'}`}>
        {phase === 'typing' && `Attempt ${cur.attempt}: writing code…`}
        {phase === 'testing' && `Attempt ${cur.attempt}: static safety check + sandbox test against the plan's expected results…`}
        {phase === 'verdict' && v === 'passed' && `Attempt ${cur.attempt}: PASSED. Safe code, correct results.`}
        {phase === 'verdict' && v === 'failed' && (
          <>
            <div>Attempt {cur.attempt}: FAILED</div>
            {cur.problems.slice(0, 3).map((p, i) => <div key={i} className="codestream-problem">{p}</div>)}
            {active < list.length - 1 && <div className="codestream-feedback">↳ sent back to the AI as repair feedback</div>}
          </>
        )}
      </div>
    </div>
  );
}
