from app.store import ChatStore, Database, Turn


def test_chats_survive_restart(tmp_path):
    url = f"sqlite:///{tmp_path / 'chats.db'}"
    st = ChatStore(Database(url))
    a, b = st.create("A"), st.create("B")
    a.add_source("cv", "a.pdf", "Built a Kubernetes operator in Go.")
    a.history.append(Turn("Why Go?", "Because..."))
    a.save()
    st.delete(b.id)

    restarted = ChatStore(Database(url))  # simulates a server restart
    assert list(restarted.chats) == [a.id]
    ra = restarted.get(a.id)
    assert ra.history[0].question == "Why Go?"
    assert ra.index.search("kubernetes")[0][1].source_name == "a.pdf"  # index rebuilt per chat
