import pytest
from agent.blackboard import Blackboard, BlackboardEvent


def test_blackboard_basic_kv():
    bb = Blackboard(session_id="test-1")
    assert not bb.has("plan")

    entry = bb.put("plan", {"step": 1, "goal": "init"}, agent_id="subagent-alpha")
    assert entry.version == 1
    assert bb.has("plan")
    assert bb.get("plan")["goal"] == "init"

    # Update value
    entry2 = bb.put("plan", {"step": 2, "goal": "verify"}, agent_id="subagent-beta")
    assert entry2.version == 2
    assert bb.get("plan")["step"] == 2

    # Delete
    assert bb.delete("plan")
    assert not bb.has("plan")
    assert bb.get("plan", "default_val") == "default_val"


def test_blackboard_pubsub():
    bb = Blackboard(session_id="test-2")
    received = []

    def on_task_event(event: BlackboardEvent):
        received.append(event.payload)

    unsub = bb.subscribe("task:progress", on_task_event)

    bb.publish("task:progress", {"percent": 50}, sender_id="worker-1")
    bb.publish("task:progress", {"percent": 100}, sender_id="worker-1")
    bb.publish("other:topic", {"ignored": True})

    assert len(received) == 2
    assert received[0]["percent"] == 50
    assert received[1]["percent"] == 100

    unsub()
    bb.publish("task:progress", {"percent": 101})
    assert len(received) == 2


def test_blackboard_artifacts():
    bb = Blackboard(session_id="test-3")
    art_id = bb.post_artifact(
        name="diff_output",
        content="--- a.py\n+++ b.py",
        artifact_type="diff",
        producer_id="reviewer-1",
        tags=["diff", "core"],
    )

    assert art_id.startswith("art-")
    artifact = bb.get_artifact(art_id)
    assert artifact is not None
    assert artifact.name == "diff_output"
    assert artifact.content == "--- a.py\n+++ b.py"

    tagged = bb.list_artifacts(tag="core")
    assert len(tagged) == 1
    assert tagged[0].artifact_id == art_id


def test_blackboard_snapshot_and_agents():
    bb = Blackboard(session_id="test-4")
    bb.register_agent("worker-a")
    bb.register_agent("worker-b")
    assert bb.get_active_agents() == ["worker-a", "worker-b"]

    bb.put("config:env", "production")
    snapshot = bb.get_snapshot()
    assert snapshot["session_id"] == "test-4"
    assert "worker-a" in snapshot["active_agents"]
    assert "config:env" in snapshot["state"]

    bb.unregister_agent("worker-a")
    assert bb.get_active_agents() == ["worker-b"]
