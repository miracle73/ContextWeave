"use client";

import { useEffect, useState } from "react";
import type { AppConfig } from "@/lib/api";
import { useInterview } from "@/lib/useInterview";

const dot: Record<string, string> = {
  open: "bg-emerald-500", listening: "bg-emerald-500 animate-pulse", streaming: "bg-indigo-500 animate-pulse",
  connecting: "bg-amber-400", reconnecting: "bg-amber-400 animate-pulse", requesting: "bg-amber-400",
  closed: "bg-red-500", error: "bg-red-500", denied: "bg-red-500", unsupported: "bg-red-500",
};

function Badge({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs">
      <span className={`h-2 w-2 rounded-full ${dot[value] ?? "bg-slate-300"}`} />
      <span className="text-slate-500">{label}:</span> {value}
    </span>
  );
}

export function InterviewPanel({ chatId, config, onAnswered }: { chatId: string; config: AppConfig; onAnswered: () => void }) {
  const iv = useInterview(chatId);
  const { state: s } = iv;
  const [model, setModel] = useState(config.default_model);
  const [length, setLength] = useState("medium");
  const [consent, setConsent] = useState(false);
  const [text, setText] = useState("");

  useEffect(() => { if (iv.conn === "open") iv.setSettings(model, length); }, [iv.conn, model, length]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (s.genStatus === "done") onAnswered(); }, [s.history.length]); // eslint-disable-line react-hooks/exhaustive-deps

  const listening = iv.mic === "listening";
  const gen = s.genStatus === "streaming" ? (s.provisional ? "provisional" : "streaming") : s.genStatus;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge label="Server" value={iv.conn} />
        <Badge label="Mic" value={iv.mic} />
        <Badge label="Answer" value={gen === "provisional" ? "streaming" : gen} />
        <span className="text-xs text-slate-400">STT: {iv.sttProvider}</span>
        {!config.llm_configured && <span className="text-xs text-red-600">OPENROUTER_API_KEY missing on server</span>}
      </div>

      <div className="flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <label className="text-xs text-slate-500">Model
          <select value={model} onChange={(e) => setModel(e.target.value)} className="mt-1 block rounded-md border border-slate-300 px-2 py-1.5 text-sm text-slate-900">
            {config.models.map((m) => <option key={m}>{m}</option>)}
          </select>
        </label>
        <label className="text-xs text-slate-500">Answer length
          <select value={length} onChange={(e) => setLength(e.target.value)} className="mt-1 block rounded-md border border-slate-300 px-2 py-1.5 text-sm text-slate-900">
            {config.lengths.map((l) => <option key={l}>{l}</option>)}
          </select>
        </label>
        <label className="flex max-w-xs items-start gap-2 text-xs text-slate-600">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-0.5" />
          Everyone in this mock interview has consented to being recorded and transcribed.
        </label>
        <div className="ml-auto flex gap-2">
          {!listening ? (
            <button onClick={iv.startMic} disabled={!consent || iv.conn !== "open" || iv.mic === "requesting"}
              className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-40">🎙 Start mic</button>
          ) : (
            <button onClick={iv.stopMic} className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white">■ Stop</button>
          )}
          {s.genStatus === "streaming" && (
            <button onClick={iv.cancel} className="rounded-lg border border-slate-300 px-3 py-2 text-sm">Cancel</button>
          )}
        </div>
      </div>
      {iv.micError && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{iv.micError}</p>}
      {s.error && <p role="alert" className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">{s.error}</p>}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h3 className="text-sm font-semibold text-slate-700">Live transcript</h3>
          <p className="mt-2 min-h-24 text-lg leading-relaxed" aria-live="polite">
            {s.committed}{" "}<span className="text-slate-400 italic">{s.interim}</span>
            {!s.committed && !s.interim && <span className="text-sm text-slate-400">{listening ? "Listening for the interviewer…" : "Start the mic or type a question below."}</span>}
          </p>
          {s.notice && <p className="mt-2 text-xs text-slate-500">{s.notice}</p>}
          <form className="mt-4 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim() && iv.ask(text)) setText(""); }}>
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Type an interviewer question…"
              className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-indigo-500" />
            <button disabled={iv.conn !== "open"} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm text-white disabled:opacity-40">Ask</button>
          </form>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-700">Suggested answer</h3>
            <div className="flex gap-1 text-[11px]">
              {s.kind && <span className="rounded bg-slate-100 px-1.5 py-0.5">{s.kind}</span>}
              {s.genStatus !== "idle" && s.provisional && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-amber-800">provisional</span>}
              {s.missingEvidence && <span className="rounded bg-red-100 px-1.5 py-0.5 text-red-700">weak evidence</span>}
            </div>
          </div>
          {s.question && <p className="mt-2 text-xs text-slate-500">Q: {s.question}</p>}
          <p className={`mt-2 min-h-24 whitespace-pre-wrap leading-relaxed ${s.genStatus === "cancelled" ? "opacity-50" : ""}`} aria-live="polite">
            {s.answer || (s.genStatus === "streaming" ? <span className="text-slate-400">Retrieving evidence and drafting…</span> : <span className="text-sm text-slate-400">Answers stream here.</span>)}
            {s.genStatus === "streaming" && <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-indigo-500 align-middle" />}
          </p>
          {s.evidence.length > 0 && (
            <details className="mt-3 text-xs text-slate-500">
              <summary className="cursor-pointer">Evidence used ({s.evidence.length})</summary>
              <ul className="mt-1 space-y-1">{s.evidence.map((e) => <li key={e.id}><b>{e.id}</b> {e.source}: {e.snippet}…</li>)}</ul>
            </details>
          )}
        </section>
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-700">Chat history</h3>
        <ol className="mt-2 space-y-3">
          {[...s.history].reverse().map((t, i) => (
            <li key={i} className="border-l-2 border-indigo-200 pl-3 text-sm">
              <p className="font-medium">{t.question}</p>
              <p className="mt-1 whitespace-pre-wrap text-slate-600">{t.answer}</p>
            </li>
          ))}
          {!s.history.length && <li className="text-xs text-slate-400">No answered questions yet.</li>}
        </ol>
      </section>
    </div>
  );
}
