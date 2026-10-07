export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const WS_URL = API_URL.replace(/^http/, "ws");

export type Source = { id: string; kind: string; name: string; chars: number; chunks: number };
export type ChatSummary = { id: string; title: string; created: number };
export type ChatDetail = ChatSummary & { sources: Source[]; history: { question: string; answer: string }[] };
export type AppConfig = { models: string[]; default_model: string; lengths: string[]; stt_provider: string; llm_configured: boolean };

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API_URL}${path}`, init);
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed (${r.status})`);
  }
  return r.json();
}

const json = (body: unknown): RequestInit => ({
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

export const api = {
  config: () => req<AppConfig>("/api/config"),
  chats: () => req<ChatSummary[]>("/api/chats"),
  chat: (id: string) => req<ChatDetail>(`/api/chats/${id}`),
  createChat: (title: string) => req<ChatDetail>("/api/chats", json({ title })),
  deleteChat: (id: string) => req(`/api/chats/${id}`, { method: "DELETE" }),
  uploadCv: (id: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<Source>(`/api/chats/${id}/cv`, { method: "POST", body: fd });
  },
  addSources: (id: string, urls: string[], repos: string[]) =>
    req<{ input: string; ok: boolean; error?: string }[]>(`/api/chats/${id}/sources`, json({ urls, repos })),
  deleteSource: (id: string, sid: string) => req(`/api/chats/${id}/sources/${sid}`, { method: "DELETE" }),
};
