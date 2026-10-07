import { describe, expect, it } from "vitest";
import { initialState, reduce, type ServerMsg } from "./interviewState";

const run = (msgs: ServerMsg[]) => msgs.reduce(reduce, initialState);

describe("interview reducer", () => {
  it("ignores out-of-order transcript revisions", () => {
    const s = run([
      { type: "transcript", revision: 2, committed: "", interim: "tell me about" },
      { type: "transcript", revision: 1, committed: "", interim: "tell" },
    ]);
    expect(s.interim).toBe("tell me about");
  });

  it("drops tokens from cancelled / superseded generations", () => {
    const s = run([
      { type: "answer_start", gen_id: "g1", revision: 3, provisional: true, question: "q", kind: "general" },
      { type: "token", gen_id: "g1", delta: "old " },
      { type: "answer_cancelled", gen_id: "g1", reason: "superseded" },
      { type: "answer_start", gen_id: "g2", revision: 5, provisional: false, question: "q full", kind: "general" },
      { type: "token", gen_id: "g1", delta: "STALE" },
      { type: "token", gen_id: "g2", delta: "new" },
    ]);
    expect(s.answer).toBe("new");
    expect(s.genId).toBe("g2");
  });

  it("rejects an answer_start older than the shown one", () => {
    const s = run([
      { type: "answer_start", gen_id: "g2", revision: 5, provisional: false, question: "new", kind: "x" },
      { type: "answer_start", gen_id: "g1", revision: 3, provisional: true, question: "old", kind: "x" },
    ]);
    expect(s.genId).toBe("g2");
  });

  it("final answer_end appends history and clears transcript", () => {
    const s = run([
      { type: "transcript", revision: 1, committed: "Why Go?", interim: "" },
      { type: "answer_start", gen_id: "g1", revision: 1, provisional: false, question: "Why Go?", kind: "technical" },
      { type: "token", gen_id: "g1", delta: "Because" },
      { type: "answer_end", gen_id: "g1", final: true, text: "Because", question: "Why Go?" },
    ]);
    expect(s.history).toHaveLength(1);
    expect(s.genStatus).toBe("done");
    expect(s.committed).toBe("");
  });
});
