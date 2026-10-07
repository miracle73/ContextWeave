// Pure reducer for server events. Guards against stale data using transcript revisions and generation IDs.

export type Evidence = { id: string; source: string; score: number; snippet: string };
export type Turn = { question: string; answer: string; ts?: number };
export type GenStatus = "idle" | "streaming" | "provisional-done" | "done" | "cancelled" | "error";

export type InterviewState = {
  transcriptRevision: number;
  committed: string;
  interim: string;
  genId: string | null;
  answerRevision: number;
  provisional: boolean;
  question: string;
  kind: string;
  evidence: Evidence[];
  missingEvidence: boolean;
  answer: string;
  genStatus: GenStatus;
  history: Turn[];
  notice: string | null;
  error: string | null;
  model: string;
  length: string;
  clientId: string | null;
  micOwner: string | null;
};

export const initialState: InterviewState = {
  transcriptRevision: 0, committed: "", interim: "", genId: null, answerRevision: 0, provisional: false,
  question: "", kind: "", evidence: [], missingEvidence: false, answer: "", genStatus: "idle",
  history: [], notice: null, error: null, model: "", length: "medium", clientId: null, micOwner: null,
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type ServerMsg = { type: string; [k: string]: any };

export function reduce(s: InterviewState, m: ServerMsg): InterviewState {
  switch (m.type) {
    case "ready": { // snapshot of the chat's shared live session (other devices may already be mid-question)
      const g = m.generation;
      return {
        ...initialState, history: m.history ?? [], transcriptRevision: m.revision ?? 0, committed: m.committed ?? "",
        interim: m.interim ?? "", model: m.model ?? "", length: m.length ?? "medium", clientId: m.client_id ?? null,
        micOwner: m.mic_owner ?? null,
        ...(g ? {
          genId: g.gen_id, answerRevision: g.revision, provisional: g.provisional, question: g.question, answer: g.text,
          genStatus: g.done ? (g.provisional ? "provisional-done" : "done") : "streaming",
        } : {}),
      };
    }
    case "settings":
      return { ...s, model: m.model, length: m.length };
    case "mic":
      return { ...s, micOwner: m.owner };
    case "transcript":
      if (m.revision <= s.transcriptRevision) return s;
      return { ...s, transcriptRevision: m.revision, committed: m.committed, interim: m.interim, notice: null };
    case "answer_start":
      if (m.revision < s.answerRevision) return s; // older than what we already show
      return {
        ...s, genId: m.gen_id, answerRevision: m.revision, provisional: m.provisional, question: m.question,
        kind: m.kind, evidence: m.evidence ?? [], missingEvidence: m.missing_evidence, answer: "",
        genStatus: "streaming", error: null, notice: null,
      };
    case "token":
      if (m.gen_id !== s.genId || s.genStatus !== "streaming") return s;
      return { ...s, answer: s.answer + m.delta };
    case "answer_end": {
      if (m.gen_id !== s.genId) return s;
      if (!m.final) return { ...s, answer: m.text, genStatus: "provisional-done" };
      return {
        ...s, answer: m.text, provisional: false, genStatus: "done", committed: "", interim: "",
        history: [...s.history, { question: m.question, answer: m.text, ts: Date.now() / 1000 }],
      };
    }
    case "answer_cancelled":
      if (m.gen_id !== s.genId) return s;
      // Superseded: keep the old text visible until the replacement starts, but accept no more tokens for it.
      return m.reason === "superseded" ? { ...s, genId: null } : { ...s, genStatus: "cancelled" };
    case "no_question":
      return { ...s, committed: "", interim: "", notice: `Not treated as a question: “${m.text}”` };
    case "error":
      if (m.gen_id && m.gen_id !== s.genId) return s;
      return { ...s, error: m.message, genStatus: m.gen_id ? "error" : s.genStatus };
    default:
      return s;
  }
}
