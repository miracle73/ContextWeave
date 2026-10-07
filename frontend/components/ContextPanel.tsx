"use client";

import { useState } from "react";
import { api, type Source } from "@/lib/api";

export function ContextPanel({ chatId, sources, onChange }: { chatId: string; sources: Source[]; onChange: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [links, setLinks] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  const upload = async (file: File) => {
    setBusy("Extracting CV…"); setMsg(null);
    try { await api.uploadCv(chatId, file); onChange(); }
    catch (e) { setMsg((e as Error).message); }
    finally { setBusy(null); }
  };

  const addLinks = async () => {
    const items = links.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean);
    if (!items.length) return;
    const isRepo = (s: string) => /^(https?:\/\/github\.com\/)?[\w.-]+\/[\w.-]+\/?$/.test(s) && !/^https?:\/\/(?!github\.com)/.test(s);
    setBusy("Fetching & indexing…"); setMsg(null);
    try {
      const res = await api.addSources(chatId, items.filter((s) => !isRepo(s)), items.filter(isRepo));
      const failed = res.filter((r) => !r.ok);
      setMsg(failed.length ? failed.map((f) => `${f.input}: ${f.error}`).join("\n") : null);
      setLinks(""); onChange();
    } catch (e) { setMsg((e as Error).message); }
    finally { setBusy(null); }
  };

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="text-sm font-semibold text-slate-700">Candidate context <span className="font-normal text-slate-400">(this chat only)</span></h2>
      <label className="mt-3 flex cursor-pointer items-center justify-center rounded-lg border-2 border-dashed border-slate-300 p-3 text-sm text-slate-500 hover:border-indigo-400 hover:text-indigo-600">
        Upload CV (PDF / DOCX)
        <input type="file" accept=".pdf,.docx" className="hidden" disabled={!!busy}
          onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ""; }} />
      </label>
      <textarea value={links} onChange={(e) => setLinks(e.target.value)} rows={2}
        placeholder="Project URLs or GitHub repos (owner/repo), one per line"
        className="mt-3 w-full rounded-lg border border-slate-300 p-2 text-sm focus:outline-indigo-500" />
      <button onClick={addLinks} disabled={!!busy || !links.trim()}
        className="mt-2 w-full rounded-lg bg-slate-800 py-1.5 text-sm text-white disabled:opacity-40">Add sources</button>
      {busy && <p className="mt-2 text-xs text-indigo-600">{busy}</p>}
      {msg && <p className="mt-2 whitespace-pre-wrap text-xs text-red-600">{msg}</p>}
      <ul className="mt-3 space-y-1.5">
        {sources.map((s) => (
          <li key={s.id} className="flex items-center justify-between gap-2 rounded-md bg-slate-50 px-2 py-1 text-xs">
            <span className="truncate"><span className="mr-1 rounded bg-slate-200 px-1 uppercase">{s.kind}</span>{s.name}
              <span className="text-slate-400"> · {s.chunks} chunks</span></span>
            <button aria-label={`Remove ${s.name}`} className="text-slate-400 hover:text-red-600"
              onClick={async () => { await api.deleteSource(chatId, s.id); onChange(); }}>✕</button>
          </li>
        ))}
        {!sources.length && <li className="text-xs text-slate-400">No context yet — answers will flag missing evidence.</li>}
      </ul>
      <p className="mt-3 text-[11px] leading-snug text-slate-400">Uploaded files and fetched pages are treated as untrusted data; instructions inside them are ignored.</p>
    </section>
  );
}
