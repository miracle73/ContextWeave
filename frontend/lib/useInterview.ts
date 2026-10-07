"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { WS_URL } from "./api";
import { initialState, reduce } from "./interviewState";

export type ConnState = "connecting" | "open" | "reconnecting" | "closed";
export type AudioSource = "mic" | "tab";
export type MicState = "idle" | "requesting" | "listening" | "denied" | "error" | "unsupported";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type SpeechRec = any;

/** WebSocket session with auto-reconnect, microphone capture and two replaceable STT paths:
 *  - "deepgram": raw audio chunks are streamed to the backend (key stays server-side)
 *  - "browser":  Web Speech API produces interim/final transcripts locally, sent as text */
export function useInterview(chatId: string, onSourcesChanged?: () => void) {
  const [state, dispatch] = useReducer(reduce, initialState);
  const [conn, setConn] = useState<ConnState>("connecting");
  const [mic, setMic] = useState<MicState>("idle");
  const [micError, setMicError] = useState<string | null>(null);
  const [sttProvider, setSttProvider] = useState("browser");
  const ws = useRef<WebSocket | null>(null);
  const retry = useRef(0);
  const closedByUs = useRef(false);
  const media = useRef<{ stream?: MediaStream; rec?: MediaRecorder; speech?: SpeechRec; silence?: ReturnType<typeof setTimeout> }>({});
  const listening = useRef(false);
  const onSources = useRef(onSourcesChanged);
  onSources.current = onSourcesChanged;

  const send = useCallback((msg: object | Blob) => {
    const s = ws.current;
    if (s?.readyState !== WebSocket.OPEN) return false;
    s.send(msg instanceof Blob ? msg : JSON.stringify(msg));
    return true;
  }, []);

  const stopMic = useCallback((notify = true) => {
    listening.current = false;
    const m = media.current;
    if (m.silence) clearTimeout(m.silence);
    try { m.rec?.state !== "inactive" && m.rec?.stop(); } catch { /* already stopped */ }
    try { m.speech?.stop(); } catch { /* already stopped */ }
    m.stream?.getTracks().forEach((t) => t.stop());
    media.current = {};
    setMic((s) => (s === "listening" || s === "requesting" ? "idle" : s));
    if (notify) send({ type: "stop_audio" });
  }, [send]);

  useEffect(() => {
    closedByUs.current = false;
    let timer: ReturnType<typeof setTimeout>;
    const connect = () => {
      setConn(retry.current ? "reconnecting" : "connecting");
      const s = new WebSocket(`${WS_URL}/ws/${chatId}`);
      ws.current = s;
      s.onopen = () => { retry.current = 0; setConn("open"); };
      s.onmessage = (e) => {
        const m = JSON.parse(e.data);
        if (m.type === "ready") setSttProvider(m.stt_provider);
        if (m.type === "sources_changed") onSources.current?.();
        if (m.type === "stt_status" && m.state === "error") { setMicError(m.message); stopMic(false); setMic("error"); }
        dispatch(m);
      };
      s.onclose = (e) => {
        if (listening.current) stopMic(false); // audio container headers are lost across reconnects
        if (closedByUs.current || e.code === 4404) { setConn("closed"); return; }
        retry.current += 1;
        setConn("reconnecting");
        timer = setTimeout(connect, Math.min(10_000, 500 * 2 ** retry.current));
      };
    };
    connect();
    const ping = setInterval(() => send({ type: "ping" }), 25_000);
    return () => {
      closedByUs.current = true;
      clearTimeout(timer);
      clearInterval(ping);
      stopMic(false);
      ws.current?.close();
    };
  }, [chatId, send, stopMic]);

  const startMic = useCallback(async (source: AudioSource = "mic") => {
    setMicError(null);
    if (!navigator.mediaDevices?.getUserMedia) { setMic("unsupported"); setMicError("Microphone not available in this browser."); return; }
    if (source === "tab" && sttProvider !== "deepgram") {
      setMic("error");
      setMicError("Call-tab audio needs server-side transcription: set STT_PROVIDER=deepgram and DEEPGRAM_API_KEY on the backend.");
      return;
    }
    setMic("requesting");
    try {
      if (source === "mic" && sttProvider === "browser") {
        const SR = (window as SpeechRec).SpeechRecognition ?? (window as SpeechRec).webkitSpeechRecognition;
        if (!SR) { setMic("unsupported"); setMicError("Browser speech recognition unsupported (use Chrome/Edge) or configure Deepgram."); return; }
        // Ask permission explicitly so denial is reported clearly.
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        stream.getTracks().forEach((t) => t.stop());
        const rec = new SR();
        rec.continuous = true; rec.interimResults = true; rec.lang = "en-US";
        const armSilence = () => {
          if (media.current.silence) clearTimeout(media.current.silence);
          media.current.silence = setTimeout(() => send({ type: "utterance_end" }), 1400);
        };
        rec.onresult = (ev: SpeechRec) => {
          let interim = "";
          for (let i = ev.resultIndex; i < ev.results.length; i++) {
            const r = ev.results[i];
            if (r.isFinal) send({ type: "transcript", text: r[0].transcript, is_final: true });
            else interim += r[0].transcript;
          }
          if (interim) send({ type: "transcript", text: interim, is_final: false });
          armSilence();
        };
        rec.onerror = (e: SpeechRec) => {
          if (e.error === "not-allowed") { setMic("denied"); setMicError("Microphone permission denied."); listening.current = false; }
          else if (e.error !== "no-speech" && e.error !== "aborted") setMicError(`Speech recognition error: ${e.error}`);
        };
        rec.onend = () => { if (listening.current) try { rec.start(); } catch { /* restarting */ } };
        // Claim the shared mic for this device; the server ignores transcripts from non-owners.
        if (!send({ type: "start_audio" })) throw new Error("Not connected to the server");
        media.current.speech = rec;
        listening.current = true;
        rec.start();
      } else {
        let stream: MediaStream;
        if (source === "tab") {
          // Chrome requires video in the picker; we keep only the shared tab's audio (the friend on the call).
          const shared = await navigator.mediaDevices.getDisplayMedia({
            video: true, audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false },
            // @ts-expect-error Chrome-only picker hints
            preferCurrentTab: false, selfBrowserSurface: "exclude", systemAudio: "include",
          });
          shared.getVideoTracks().forEach((t) => t.stop());
          const audio = shared.getAudioTracks();
          if (!audio.length) throw new DOMException("No audio shared. Pick the call's tab and turn on \"Share tab audio\".", "NoAudio");
          audio[0].onended = () => stopMic(true); // user pressed Chrome's "Stop sharing"
          stream = new MediaStream(audio);
        } else {
          stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
        }
        const mime = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"].find((t) => MediaRecorder.isTypeSupported(t));
        const rec = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
        if (!send({ type: "start_audio" })) throw new Error("Not connected to the server");
        rec.ondataavailable = (e) => { if (e.data.size) send(e.data); };
        media.current = { stream, rec };
        listening.current = true;
        rec.start(250);
      }
      setMic("listening");
    } catch (e) {
      const err = e as DOMException;
      listening.current = false;
      if (source === "tab" && err.name === "NotAllowedError") { setMic("idle"); setMicError("Tab sharing was cancelled."); }
      else if (err.name === "NoAudio") { setMic("error"); setMicError(err.message); }
      else if (err.name === "NotAllowedError" || err.name === "SecurityError") { setMic("denied"); setMicError("Microphone permission denied. Allow it in your browser's site settings."); }
      else if (err.name === "NotFoundError") { setMic("error"); setMicError("No microphone found."); }
      else { setMic("error"); setMicError(err.message || "Could not start microphone."); }
    }
  }, [send, sttProvider, stopMic]);

  return {
    state, conn, mic, micError, sttProvider, startMic, stopMic: () => stopMic(true),
    ask: (text: string) => send({ type: "ask", text }),
    cancel: () => send({ type: "cancel" }),
    setSettings: (model: string, length: string) => send({ type: "settings", model, length }),
  };
}
