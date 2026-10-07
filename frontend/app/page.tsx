"use client";

import { useCallback, useEffect, useState } from "react";
import { ContextPanel } from "@/components/ContextPanel";
import { InterviewPanel } from "@/components/InterviewPanel";
import { api, type AppConfig, type ChatDetail, type ChatSummary } from "@/lib/api";

export default function Home() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [chats, setChats] = useState<ChatSummary[]>([]);
  const [active, setActive] = useState<ChatDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [menu, setMenu] = useState(false);

  const refreshChats = useCallback(() => api.chats().then(setChats), []);
  const refreshActive = useCallback((id: string) => api.chat(id).then(setActive).catch(() => setActive(null)), []);

  useEffect(() => {
    Promise.all([api.config().then(setConfig), refreshChats()])
      .catch(() => setError("Cannot reach the backend. Is it running on NEXT_PUBLIC_API_URL?"));
  }, [refreshChats]);

  const newChat = async () => {
    const title = prompt("Name this practice interview", "Mock interview");
    if (title === null) return;
    const c = await api.createChat(title);
    await refreshChats();
    setActive(c); setMenu(false);
  };

  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className={`${menu ? "block" : "hidden"} border-b border-slate-200 bg-white p-4 md:block md:w-64 md:border-r md:border-b-0`}>
        <button onClick={newChat} disabled={!config} className="w-full rounded-lg bg-indigo-600 py-2 text-sm font-medium text-white disabled:opacity-40">+ New practice chat</button>
        <ul className="mt-4 space-y-1">
          {chats.map((c) => (
            <li key={c.id} className="group flex items-center">
              <button onClick={() => { refreshActive(c.id); setMenu(false); }}
                className={`flex-1 truncate rounded-md px-2 py-1.5 text-left text-sm ${active?.id === c.id ? "bg-indigo-50 text-indigo-700" : "hover:bg-slate-100"}`}>{c.title}</button>
              <button aria-label={`Delete ${c.title}`} className="px-1 text-slate-300 hover:text-red-600"
                onClick={async () => { await api.deleteChat(c.id); if (active?.id === c.id) setActive(null); refreshChats(); }}>✕</button>
            </li>
          ))}
        </ul>
      </aside>

      <main className="flex-1 p-4 md:p-6">
        <header className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold">ContextWeave <span className="text-sm font-normal text-slate-400">mock interview coach</span></h1>
            <p className="text-xs text-slate-500">For consent-based practice only. Answers are grounded in your own CV and projects.</p>
          </div>
          <button className="rounded-md border border-slate-300 px-3 py-1.5 text-sm md:hidden" onClick={() => setMenu((m) => !m)}>Chats</button>
        </header>
        {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
        {config && active ? (
          <div className="grid gap-4 xl:grid-cols-[300px_1fr]">
            <ContextPanel chatId={active.id} sources={active.sources} onChange={() => refreshActive(active.id)} />
            <InterviewPanel key={active.id} chatId={active.id} config={config} onAnswered={() => {}} />
          </div>
        ) : (
          !error && (
            <div className="mt-20 text-center text-slate-500">
              <p className="text-lg">Create or pick a practice chat to begin.</p>
              <p className="mt-1 text-sm">Each chat keeps its own CV, projects and history.</p>
            </div>
          )
        )}
      </main>
    </div>
  );
}
