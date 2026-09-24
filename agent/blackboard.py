"""Multi-Agent Shared Blackboard Bus for Robin.

Provides a thread-safe in-memory blackboard workspace and event bus for
coordinating concurrent subagents (delegate_task), background workers, and
multi-stage reasoning pipelines.

Features:
  - Key-Value shared state store with namespace support and versioning
  - Topic-based Pub/Sub event bus with event history and callbacks
  - Structured artifact repository for intermediate reasoning/code outputs
  - Thread-safe synchronization primitives and atomic snapshots
"""

from __future__ import annotations

import collections
import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class BlackboardEntry:
    key: str
    value: Any
    updated_by: str
    timestamp: float
    version: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BlackboardEvent:
    event_id: str
    topic: str
    payload: Any
    sender_id: str
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BlackboardArtifact:
    artifact_id: str
    name: str
    content: Any
    artifact_type: str  # e.g., "code", "json", "diff", "text", "plan"
    producer_id: str
    timestamp: float
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class Blackboard:
    """Thread-safe blackboard and event coordination bus for autonomous agents."""

    _instance: Optional[Blackboard] = None
    _global_lock = threading.Lock()

    def __init__(self, session_id: Optional[str] = None) -> None:
        self.session_id: str = session_id or str(uuid.uuid4())[:8]
        self._lock = threading.RLock()
        self._store: Dict[str, BlackboardEntry] = {}
        self._events: collections.deque[BlackboardEvent] = collections.deque(maxlen=1000)
        self._subscribers: Dict[str, List[Callable[[BlackboardEvent], None]]] = collections.defaultdict(list)
        self._artifacts: Dict[str, BlackboardArtifact] = {}
        self._active_agents: Set[str] = set()

    @classmethod
    def get_global(cls) -> Blackboard:
        """Access or initialize the singleton global blackboard."""
        with cls._global_lock:
            if cls._instance is None:
                cls._instance = cls(session_id="global")
            return cls._instance

    @classmethod
    def reset_global(cls) -> None:
        """Reset the singleton global blackboard."""
        with cls._global_lock:
            cls._instance = None

    # --- Agent Lifecycle Tracking ---

    def register_agent(self, agent_id: str) -> None:
        """Register an active worker/subagent."""
        with self._lock:
            self._active_agents.add(agent_id)
            self.publish("agent:registered", {"agent_id": agent_id}, sender_id="blackboard")

    def unregister_agent(self, agent_id: str) -> None:
        """Unregister a finished worker/subagent."""
        with self._lock:
            self._active_agents.discard(agent_id)
            self.publish("agent:unregistered", {"agent_id": agent_id}, sender_id="blackboard")

    def get_active_agents(self) -> List[str]:
        """List currently active agent IDs."""
        with self._lock:
            return sorted(self._active_agents)

    # --- Key-Value State Operations ---

    def put(
        self,
        key: str,
        value: Any,
        agent_id: str = "system",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> BlackboardEntry:
        """Set or update a value in the blackboard."""
        with self._lock:
            now = time.time()
            prev = self._store.get(key)
            version = (prev.version + 1) if prev else 1
            entry = BlackboardEntry(
                key=key,
                value=value,
                updated_by=agent_id,
                timestamp=now,
                version=version,
                metadata=metadata or {},
            )
            self._store[key] = entry
            self.publish(
                f"state:{key}",
                {"key": key, "value": value, "version": version, "updated_by": agent_id},
                sender_id=agent_id,
            )
            return entry

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value by key."""
        with self._lock:
            entry = self._store.get(key)
            return entry.value if entry else default

    def get_entry(self, key: str) -> Optional[BlackboardEntry]:
        """Retrieve the complete metadata entry for a key."""
        with self._lock:
            return self._store.get(key)

    def has(self, key: str) -> bool:
        """Check if a key exists."""
        with self._lock:
            return key in self._store

    def delete(self, key: str, agent_id: str = "system") -> bool:
        """Remove a key from the blackboard."""
        with self._lock:
            if key in self._store:
                del self._store[key]
                self.publish(f"state:deleted:{key}", {"key": key}, sender_id=agent_id)
                return True
            return False

    def list_keys(self, prefix: str = "") -> List[str]:
        """List all keys, optionally matching a prefix."""
        with self._lock:
            if not prefix:
                return sorted(self._store.keys())
            return sorted(k for k in self._store.keys() if k.startswith(prefix))

    # --- Pub/Sub Event Bus ---

    def publish(self, topic: str, payload: Any, sender_id: str = "system") -> BlackboardEvent:
        """Publish an event to a topic channel and trigger subscribers."""
        event = BlackboardEvent(
            event_id=str(uuid.uuid4())[:8],
            topic=topic,
            payload=payload,
            sender_id=sender_id,
            timestamp=time.time(),
        )

        callbacks_to_run: List[Callable[[BlackboardEvent], None]] = []
        with self._lock:
            self._events.append(event)
            # Match exact topic or wildcard '*'
            callbacks_to_run.extend(self._subscribers.get(topic, []))
            callbacks_to_run.extend(self._subscribers.get("*", []))

        # Invoke callbacks outside lock to prevent deadlocks
        for cb in callbacks_to_run:
            try:
                cb(event)
            except Exception as e:
                logger.warning("Error in blackboard subscriber for topic %s: %s", topic, e)

        return event

    def subscribe(self, topic: str, callback: Callable[[BlackboardEvent], None]) -> Callable[[], None]:
        """Subscribe to a topic. Returns an unsubscribe callable."""
        with self._lock:
            self._subscribers[topic].append(callback)

        def unsubscribe() -> None:
            with self._lock:
                if callback in self._subscribers.get(topic, []):
                    self._subscribers[topic].remove(callback)

        return unsubscribe

    def get_events(
        self,
        topic: Optional[str] = None,
        since_timestamp: float = 0.0,
        limit: int = 50,
    ) -> List[BlackboardEvent]:
        """Query event history filtered by topic and timestamp."""
        with self._lock:
            matched: List[BlackboardEvent] = []
            for ev in reversed(self._events):
                if ev.timestamp >= since_timestamp:
                    if topic is None or ev.topic == topic or ev.topic.startswith(f"{topic}:"):
                        matched.append(ev)
                if len(matched) >= limit:
                    break
            return list(reversed(matched))

    # --- Artifact Store ---

    def post_artifact(
        self,
        name: str,
        content: Any,
        artifact_type: str = "text",
        producer_id: str = "system",
        tags: Optional[List[str]] = None,
    ) -> str:
        """Store a structured intermediate artifact and notify agents."""
        artifact_id = f"art-{str(uuid.uuid4())[:8]}"
        artifact = BlackboardArtifact(
            artifact_id=artifact_id,
            name=name,
            content=content,
            artifact_type=artifact_type,
            producer_id=producer_id,
            timestamp=time.time(),
            tags=tags or [],
        )
        with self._lock:
            self._artifacts[artifact_id] = artifact
            self.publish(
                "artifact:created",
                {"artifact_id": artifact_id, "name": name, "type": artifact_type, "producer": producer_id},
                sender_id=producer_id,
            )
        return artifact_id

    def get_artifact(self, artifact_id: str) -> Optional[BlackboardArtifact]:
        """Retrieve an artifact by ID."""
        with self._lock:
            return self._artifacts.get(artifact_id)

    def list_artifacts(self, tag: Optional[str] = None) -> List[BlackboardArtifact]:
        """List artifacts, optionally filtered by tag."""
        with self._lock:
            if tag is None:
                return list(self._artifacts.values())
            return [a for a in self._artifacts.values() if tag in a.tags]

    # --- Snapshot & Reset ---

    def get_snapshot(self) -> Dict[str, Any]:
        """Get an atomic full snapshot of the blackboard state."""
        with self._lock:
            return {
                "session_id": self.session_id,
                "active_agents": list(self._active_agents),
                "state": {k: v.to_dict() for k, v in self._store.items()},
                "artifact_count": len(self._artifacts),
                "event_count": len(self._events),
            }

    def clear(self) -> None:
        """Clear all stored state, artifacts, and event history."""
        with self._lock:
            self._store.clear()
            self._events.clear()
            self._subscribers.clear()
            self._artifacts.clear()
            self._active_agents.clear()
