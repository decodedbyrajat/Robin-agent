"""Self-reflection checkpoints for the Robin agent loop.

Injects periodic reflection prompts that ask the model to evaluate its
progress and decide whether to continue, adjust strategy, or stop.

This prevents "agent wandering" — long sequences of tool calls that
don't make meaningful progress toward the goal.

Usage:
    from agent.reflection import ReflectionTracker
    
    tracker = ReflectionTracker(interval=10, max_stuck_cycles=3)
    
    # In the agent loop, after each tool execution:
    reflection = tracker.check(api_call_count, tool_names, tool_results)
    if reflection:
        messages.append(reflection)  # inject as system message
"""

import logging
import time
from collections import Counter
from typing import Optional

logger = logging.getLogger(__name__)

# The reflection prompt injected every N tool calls
_REFLECTION_PROMPT = """[SELF-REFLECTION CHECKPOINT — iteration {iteration}/{max_iter}]

Pause and assess your progress:

1. **Goal check**: What was the user's original request? Am I on track?
2. **Progress**: What have I accomplished since the last checkpoint?
3. **Efficiency**: Am I repeating similar tool calls? Could I be more direct?
4. **Blockers**: Is anything preventing progress? Do I need to change approach?
5. **Next step**: What is the single most impactful action to take next?

If you're stuck in a loop or not making progress, explicitly acknowledge it
and try a fundamentally different approach. If the task is essentially complete,
wrap up and deliver the result to the user.

Tool call pattern (last {window} calls): {tool_pattern}
Elapsed time: {elapsed}s"""

# Shorter nudge when loops are detected
_LOOP_DETECTED_PROMPT = """[⚠️ LOOP DETECTED — iteration {iteration}/{max_iter}]

You have called the same tool(s) {repeat_count} times in succession:
  → {repeated_tools}

This suggests you may be stuck. Before making another tool call:
1. Stop and re-read the user's original request
2. Consider: is this approach working? What evidence do I have?
3. Try a FUNDAMENTALLY DIFFERENT approach, or deliver what you have

Do NOT repeat the same tool call pattern again."""


class ReflectionTracker:
    """Tracks agent progress and generates reflection checkpoints."""

    def __init__(
        self,
        interval: int = 10,
        max_stuck_cycles: int = 3,
        loop_threshold: int = 3,
        enabled: bool = True,
    ):
        """
        Args:
            interval: Inject a reflection prompt every N tool calls.
            max_stuck_cycles: After this many reflection cycles with no
                apparent progress, inject a stronger "stop and reconsider" msg.
            loop_threshold: Number of identical consecutive tool calls
                before triggering a loop detection warning.
            enabled: Master switch — set False to disable all reflection.
        """
        self.interval = interval
        self.max_stuck_cycles = max_stuck_cycles
        self.loop_threshold = loop_threshold
        self.enabled = enabled

        # State
        self._start_time = time.monotonic()
        self._tool_history: list[str] = []
        self._last_checkpoint_at: int = 0
        self._stuck_cycles: int = 0
        self._last_tool_pattern_hash: Optional[str] = None

    def record_tool_call(self, tool_name: str) -> None:
        """Record that a tool was called."""
        self._tool_history.append(tool_name)

    def check(
        self,
        api_call_count: int,
        max_iterations: int,
    ) -> Optional[dict]:
        """Check if a reflection prompt should be injected.

        Returns a message dict (role=system) to inject, or None.
        """
        if not self.enabled:
            return None

        # Check for loops first (higher priority than interval checkpoints)
        loop_msg = self._detect_loops(api_call_count, max_iterations)
        if loop_msg:
            return loop_msg

        # Interval-based reflection
        calls_since_checkpoint = api_call_count - self._last_checkpoint_at
        if calls_since_checkpoint >= self.interval:
            return self._generate_reflection(api_call_count, max_iterations)

        return None

    def _detect_loops(
        self, api_call_count: int, max_iterations: int
    ) -> Optional[dict]:
        """Check if the agent is stuck in a tool-calling loop."""
        if len(self._tool_history) < self.loop_threshold:
            return None

        recent = self._tool_history[-self.loop_threshold :]
        if len(set(recent)) == 1:
            # Same tool called N times in a row
            elapsed = int(time.monotonic() - self._start_time)
            content = _LOOP_DETECTED_PROMPT.format(
                iteration=api_call_count,
                max_iter=max_iterations,
                repeat_count=self.loop_threshold,
                repeated_tools=recent[0],
            )
            self._last_checkpoint_at = api_call_count
            self._stuck_cycles += 1
            logger.info(
                "Loop detected at iteration %d: %s called %d times",
                api_call_count,
                recent[0],
                self.loop_threshold,
            )
            return {"role": "system", "content": content}

        return None

    def _generate_reflection(
        self, api_call_count: int, max_iterations: int
    ) -> dict:
        """Generate a standard reflection checkpoint."""
        window = min(10, len(self._tool_history))
        recent = self._tool_history[-window:] if window > 0 else []
        tool_counts = Counter(recent)
        tool_pattern = ", ".join(
            f"{name}×{count}" for name, count in tool_counts.most_common(5)
        )
        if not tool_pattern:
            tool_pattern = "(no tools called yet)"

        elapsed = int(time.monotonic() - self._start_time)

        # Check if pattern changed since last checkpoint
        current_hash = str(sorted(tool_counts.items()))
        if current_hash == self._last_tool_pattern_hash:
            self._stuck_cycles += 1
        else:
            self._stuck_cycles = 0
        self._last_tool_pattern_hash = current_hash

        content = _REFLECTION_PROMPT.format(
            iteration=api_call_count,
            max_iter=max_iterations,
            window=window,
            tool_pattern=tool_pattern,
            elapsed=elapsed,
        )

        if self._stuck_cycles >= self.max_stuck_cycles:
            content += (
                f"\n\n⚠️ WARNING: {self._stuck_cycles} consecutive reflection "
                "checkpoints with the same tool pattern. You appear to be stuck. "
                "Please deliver a partial result or ask the user for guidance."
            )

        self._last_checkpoint_at = api_call_count
        logger.info(
            "Reflection checkpoint at iteration %d (stuck_cycles=%d)",
            api_call_count,
            self._stuck_cycles,
        )
        return {"role": "system", "content": content}

    def reset(self) -> None:
        """Reset all tracking state (e.g. for a new conversation turn)."""
        self._start_time = time.monotonic()
        self._tool_history.clear()
        self._last_checkpoint_at = 0
        self._stuck_cycles = 0
        self._last_tool_pattern_hash = None
