"use client";

import { useState } from "react";
import type { AppConfig } from "@/lib/api";
import { useInterview, type AudioSource } from "@/lib/useInterview";

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

export function InterviewPanel({ chatId, config, onSourcesChanged }: { chatId: string; config: AppConfig; onSourcesChanged: () => void }) {
  const iv = useInterview(chatId, onSourcesChanged);
  const { state: s } = iv;
  const [consent, setConsent] = useState(false);
  const [text, setText] = useState("");
  const canTab = typeof navigator !== "undefined" && !!navigator.mediaDevices?.getDisplayMedia;
  const [source, setSource] = useState<AudioSource>("mic");
  // Model and length live on the server, so every device on this chat shares them.
  const model = s.model || config.default_model;
  const length = s.length;

  const listening = iv.mic === "listening";
  const micElsewhere = !!s.micOwner && s.micOwner !== s.clientId;
  const gen = s.genStatus === "streaming" ? (s.provisional ? "provisional" : "streaming") : s.genStatus;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge label="Server" value={iv.conn} />
        <Badge label="Mic" value={micElsewhere ? "other device" : iv.mic} />
        <Badge label="Answer" value={gen === "provisional" ? "streaming" : gen} />
        <span className="text-xs text-slate-400">STT: {iv.sttProvider}</span>
        {!config.llm_configured && <span className="text-xs text-red-600">OPENROUTER_API_KEY missing on server</span>}
      </div>

      <div className="grid grid-cols-2 items-end gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm sm:flex sm:flex-wrap">
        <label className="text-xs text-slate-500">Model
          <select value={model} onChange={(e) => iv.setSettings(e.target.value, length)} className="mt-1 block w-full rounded-md border border-slate-300 px-2 py-2 text-sm text-slate-900 sm:w-auto">
            {config.models.map((m) => <option key={m}>{m}</option>)}
          </select>
        </label>
        <label className="text-xs text-slate-500">Answer length
          <select value={length} onChange={(e) => iv.setSettings(model, e.target.value)} className="mt-1 block w-full rounded-md border border-slate-300 px-2 py-2 text-sm text-slate-900 sm:w-auto">
            {config.lengths.map((l) => <option key={l}>{l}</option>)}
          </select>
        </label>
        {canTab && (
          <label className="text-xs text-slate-500">Listen to
            <select value={source} onChange={(e) => setSource(e.target.value as AudioSource)} className="mt-1 block w-full rounded-md border border-slate-300 px-2 py-2 text-sm text-slate-900 sm:w-auto">
              <option value="mic">My microphone</option>
              <option value="tab">Call tab (friend on Meet/Zoom)</option>
            </select>
          </label>
        )}
        <label className="col-span-2 flex items-start gap-2 text-xs text-slate-600 sm:max-w-xs">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-0.5" />
          Everyone in this mock interview, including anyone on the call, has consented to being recorded and transcribed.
        </label>
        <div className="col-span-2 flex gap-2 sm:ml-auto">
          {!listening ? (
            <button onClick={() => iv.startMic(source)} disabled={!consent || iv.conn !== "open" || iv.mic === "requesting" || micElsewhere}
              className="flex-1 rounded-lg bg-emerald-600 px-4 py-3 text-sm font-medium text-white disabled:opacity-40 sm:flex-none sm:py-2">
              {micElsewhere ? "Mic live on another device" : source === "tab" ? "🎧 Capture call tab" : "🎙 Start mic"}</button>
          ) : (
            <button onClick={iv.stopMic} className="flex-1 rounded-lg bg-red-600 px-4 py-3 text-sm font-medium text-white sm:flex-none sm:py-2">■ Stop</button>
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
          <p className="mt-2 min-h-20 text-base leading-relaxed sm:min-h-24 sm:text-lg" aria-live="polite">
            {s.committed}{" "}<span className="text-slate-400 italic">{s.interim}</span>
            {!s.committed && !s.interim && <span className="text-sm text-slate-400">{listening || micElsewhere ? "Listening for the interviewer…" : "Start the mic or type a question below."}</span>}
          </p>
          {s.notice && <p className="mt-2 text-xs text-slate-500">{s.notice}</p>}
          <form className="mt-4 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (text.trim() && iv.ask(text)) setText(""); }}>
            <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Type an interviewer question…"
              className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-base focus:outline-indigo-500 sm:text-sm" />
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
