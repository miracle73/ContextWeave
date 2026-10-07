"use client";

import { useCallback, useEffect, useState } from "react";
import { ContextPanel } from "@/components/ContextPanel";
import { InterviewPanel } from "@/components/InterviewPanel";
import { api, WS_URL, type AppConfig, type ChatDetail, type ChatSummary } from "@/lib/api";

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

  // Lobby socket: chats created or deleted on another device show up here immediately.
  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout>;
    let stopped = false;
    const connect = () => {
      ws = new WebSocket(`${WS_URL}/ws/lobby`);
      ws.onmessage = (e) => {
        if (JSON.parse(e.data).type !== "chats_changed") return;
        api.chats().then((list) => {
          setChats(list);
          setActive((a) => (a && !list.some((c) => c.id === a.id) ? null : a));
        });
      };
      ws.onopen = () => { refreshChats().catch(() => {}); };
      ws.onclose = () => { if (!stopped) timer = setTimeout(connect, 3000); };
    };
    connect();
    return () => { stopped = true; clearTimeout(timer); ws?.close(); };
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
      {menu && <div className="fixed inset-0 z-30 bg-black/30 md:hidden" onClick={() => setMenu(false)} />}
      <aside className={`${menu ? "translate-x-0" : "-translate-x-full"} fixed inset-y-0 left-0 z-40 w-72 overflow-y-auto border-r border-slate-200 bg-white p-4 transition-transform md:static md:w-64 md:translate-x-0`}>
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

      <main className="min-w-0 flex-1 p-3 sm:p-4 md:p-6">
        <header className="mb-4 flex items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold sm:text-xl">ContextWeave <span className="hidden text-sm font-normal text-slate-400 sm:inline">mock interview coach</span></h1>
            {active && <p className="truncate text-sm text-indigo-700 md:hidden">{active.title}</p>}
            <p className="text-xs text-slate-500">For consent-based practice only. Answers are grounded in your own CV and projects.</p>
          </div>
          <button className="shrink-0 rounded-md border border-slate-300 px-3 py-2 text-sm md:hidden" onClick={() => setMenu((m) => !m)}>☰ Chats</button>
        </header>
        {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
        {config && active ? (
          <div className="grid gap-4 xl:grid-cols-[300px_1fr]">
            <div className="order-2 xl:order-1">
              <ContextPanel chatId={active.id} sources={active.sources} onChange={() => refreshActive(active.id)} />
            </div>
            <div className="order-1 min-w-0 xl:order-2">
              <InterviewPanel key={active.id} chatId={active.id} config={config} onSourcesChanged={() => refreshActive(active.id)} />
            </div>
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
