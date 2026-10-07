# ContextWeave — real-time mock interview coach

Next.js + Tailwind frontend, FastAPI + WebSocket backend, OpenRouter streaming LLM, Deepgram (or browser) live transcription.
For **consent-based mock interviews** only.

## Setup

```bash
# backend
cd backend
python -m venv .venv
.venv/Scripts/activate        # Windows  (macOS/Linux: source .venv/bin/activate)
pip install -r requirements-dev.txt
cp .env.example .env          # fill OPENROUTER_API_KEY (+ DEEPGRAM_API_KEY)
uvicorn app.main:app --reload --port 8000

# frontend (new terminal)
cd frontend
npm install
cp .env.example .env.local
npm run dev                   # http://localhost:3000
```

Tests: `cd backend && pytest` · `cd frontend && npm test`

## How it works

1. **Per-chat context** – each chat owns its own BM25 index, sources and history (`store.py`, `index.py`). CVs (PDF/DOCX), URLs (SSRF-guarded, public IPs only) and GitHub repos (metadata, README, tree, manifests) are extracted, chunked and indexed into that chat only.
2. **Realtime loop** (`session.py`) – every transcript update bumps a `revision`. Interim text is sent immediately; once ≥5 words, a debounce (700 ms) schedules a **provisional** answer. New meaningful text cancels the running generation (`answer_cancelled`) and starts a new one with a new `gen_id`. Only the active generation may emit tokens; the client also drops tokens whose `gen_id` isn't current and transcripts with older revisions.
3. **Final transcript** (Deepgram `speech_final`/`UtteranceEnd`, browser silence timer, or Stop) triggers a **final** answer for the full question. If a completed provisional answer already covers the identical text it is promoted without another API call.
4. **Agent** (`agent.py`) – detect question → classify (behavioural/technical/project/general) → follow-up detection → retrieve evidence → grounded prompt (first person, STAR for behavioural, “⚠ Missing evidence” instead of invention). Retrieved content is wrapped in `<untrusted_context>` with angle brackets neutralised.
5. **Cost control** – min-word threshold, debounce, min new words, max 3 provisional answers per utterance, 1.5 s gap, 20 generations/min per session, OpenRouter 429/402/401 surfaced to UI.

API keys stay in `backend/.env`; the browser never sees them (audio is proxied to Deepgram by the backend).

## Transcription notes / limitations

- **Deepgram** (`STT_PROVIDER=deepgram`): `wss://api.deepgram.com/v1/listen` with `interim_results`, `endpointing=400`, `utterance_end_ms=1200`, `vad_events`. Browser sends 250 ms WebM/Opus chunks; Deepgram detects the container. If the WebSocket reconnects mid-recording the mic is stopped (container header lost) – press Start again. Accuracy drops with cross-talk/far-field audio; speaker diarization isn't used, so the mic should capture the interviewer.
- **Browser** (`STT_PROVIDER=browser`, default without a Deepgram key): Web Speech API (Chrome/Edge only), audio goes to the browser vendor's service, sessions auto-restart after silence, end-of-utterance is a 1.4 s silence heuristic.
- To add a provider implement the `Transcriber` protocol in `backend/app/stt.py` (`start/send_audio/stop` calling `on_event(text, is_final, utterance_end)`).

## Other limitations

- Storage is in-memory (restart clears chats). Swap `ChatStore` for a DB for persistence.
- JS-rendered pages and scanned (image-only) PDFs yield little text.
- Cancelling closes the OpenRouter HTTP stream; whether upstream billing stops depends on the underlying provider.
