from fastapi.testclient import TestClient

import app.main as main


def _until(ws, kind):
    while (m := ws.receive_json())["type"] != kind:
        pass
    return m


def test_two_devices_share_live_session(monkeypatch):
    async def fake_stream(messages, model, max_tokens):
        yield "Synced "
        yield "answer."

    monkeypatch.setattr(main.llm, "stream", fake_stream)
    monkeypatch.setattr(main.settings, "stt_provider", "browser")
    c = TestClient(main.app)
    chat = c.post("/api/chats", json={"title": "sync"}).json()
    with c.websocket_connect(f"/ws/{chat['id']}") as phone, c.websocket_connect(f"/ws/{chat['id']}") as desk:
        phone_id = phone.receive_json()["client_id"]
        desk.receive_json()
        # phone takes the mic; desktop is told and cannot take it as well
        phone.send_json({"type": "start_audio"})
        assert _until(desk, "mic")["owner"] == phone_id
        desk.send_json({"type": "start_audio"})
        assert "another device" in _until(desk, "stt_status")["message"]
        # phone's live transcript appears on the desktop
        phone.send_json({"type": "transcript", "text": "Tell me about", "is_final": False})
        assert _until(desk, "transcript")["interim"] == "Tell me about"
        # desktop asks by text; both devices receive the same streamed answer
        desk.send_json({"type": "ask", "text": "What is your strongest skill?"})
        for ws in (phone, desk):
            m = _until(ws, "answer_end")
            assert m["final"] and m["text"] == "Synced answer."
