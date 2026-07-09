"""Glue that lets `_interruptible_api_call` opt into intent-based routing.

The hook is fail-open: any error or skip condition returns ``None``,
meaning "do not route — let the caller use its existing client/kwargs."
The main dispatch path is unchanged when the hook returns None.

v2 changes:
- Honors the per-route model config map from ``intent_router.routes``.
- For local routes strips ``tools``, ``stream_options``, ``tool_choice``,
  ``service_tier``, ``reasoning``, and cloud-specific ``extra_*`` keys.
- Forces ``stream=False`` on every local route (Ollama/lm-studio/vLLM).
- Supports ``advisory`` mode: classify and log, but never actually swap.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

from agent.routing.intent_router import IntentRouter, RouteDecision
from agent.routing.heuristic_router import HeuristicRouter
from agent.model_metadata import is_local_endpoint

logger = logging.getLogger(__name__)

# Models we treat as "already local" — never re-route these.
# NOTE: "gemma" removed; devstral is the sole local workhorse.
_LOCAL_MODEL_PREFIXES: Tuple[str, ...] = (
    "devstral",
    "mistral",
    "llama",
    "qwen",
    "phi",
    "nomic",
    "ollama/",
)

# Cloud-only kwargs that local backends (Ollama, lm-studio, vLLM, llama.cpp)
# either reject or silently mis-handle.
_STRIP_FOR_LOCAL: frozenset[str] = frozenset(
    {
        "stream_options",
        "extra_body",
        "extra_headers",
        "extra_query",
        "service_tier",
        "reasoning",
        "reasoning_effort",
    }
)

_router_singleton: Optional[IntentRouter] = None
_heuristic_singleton: Optional[HeuristicRouter] = None
_config_loaded: bool = False
_router_enabled: bool = False
_router_mode: str = "llm"  # "llm" or "heuristic"
_router_model: str = "mistral:7b-instruct"
_router_base_url: str = "http://localhost:11434/v1"
_router_log_path: Optional[str] = None
_router_timeout_s: float = 8.0
_router_keep_alive: Optional[str] = None
_advisory: bool = False
_routes_map: Dict[str, Dict[str, Any]] = {}


def _robin_home() -> Path:
    home = os.environ.get("ROBIN_HOME") or str(Path.home() / ".robin")
    return Path(home)


def _load_config_once() -> None:
    """Read intent_router config from ROBIN_HOME/config.yaml. Idempotent."""
    global _config_loaded, _router_enabled, _router_mode
    global _router_model, _router_base_url, _router_log_path
    global _router_timeout_s, _router_keep_alive
    global _advisory, _routes_map
    if _config_loaded:
        return
    _config_loaded = True

    cfg_path = _robin_home() / "config.yaml"
    if not cfg_path.exists():
        logger.debug("intent router: no config.yaml at %s", cfg_path)
        return
    try:
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
    except yaml.YAMLError as exc:
        logger.warning("intent router: config.yaml parse failed: %s", exc)
        return

    block = cfg.get("intent_router") or {}
    _router_enabled = bool(block.get("enabled", False))
    if not _router_enabled:
        logger.info("intent router: disabled via config")
        return

    _router_mode = str(block.get("mode", "llm")).lower()
    _router_model = str(block.get("model", _router_model))
    _router_base_url = str(block.get("base_url", _router_base_url))
    _advisory = bool(block.get("advisory", False))

    raw_timeout = block.get("timeout")
    if raw_timeout is not None:
        try:
            _router_timeout_s = float(raw_timeout)
        except (TypeError, ValueError):
            logger.warning("intent router: invalid timeout '%s', using default %s", raw_timeout, _router_timeout_s)
    _router_keep_alive = block.get("keep_alive")

    # Load the routes map (route_name -> {model, provider, base_url, api_key, ...})
    raw_routes = block.get("routes") or {}
    if isinstance(raw_routes, dict):
        _routes_map = {
            str(k): dict(v) if isinstance(v, dict) else {"model": str(v)}
            for k, v in raw_routes.items()
        }
    else:
        _routes_map = {}

    raw_log = block.get("log_path")
    if raw_log:
        expanded = str(raw_log).replace("${ROBIN_HOME}", str(_robin_home()))
        expanded = os.path.expandvars(os.path.expanduser(expanded))
        _router_log_path = expanded
    else:
        _router_log_path = str(_robin_home() / "logs" / "router.jsonl")
    logger.info(
        "intent router: enabled (mode=%s model=%s base_url=%s log=%s advisory=%s routes=%s)",
        _router_mode, _router_model, _router_base_url, _router_log_path, _advisory, list(_routes_map.keys()),
    )


def _get_router():
    global _router_singleton, _heuristic_singleton
    _load_config_once()
    if not _router_enabled:
        return None
    if _router_mode == "heuristic":
        if _heuristic_singleton is None:
            _heuristic_singleton = HeuristicRouter()
        return _heuristic_singleton
    if _router_singleton is None:
        _router_singleton = IntentRouter(
            base_url=_router_base_url,
            model=_router_model,
            log_path=_router_log_path,
            timeout_s=_router_timeout_s,
            keep_alive=_router_keep_alive,
        )
    return _router_singleton


def _last_user_message(messages: list) -> str:
    for msg in reversed(messages or []):
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = [
                p.get("text", "")
                for p in content
                if isinstance(p, dict) and p.get("type") == "text"
            ]
            return "\n".join(parts).strip()
    return ""


def _is_already_local(api_kwargs: dict) -> bool:
    model = (api_kwargs.get("model") or "").lower()
    if any(model.startswith(p) for p in _LOCAL_MODEL_PREFIXES):
        return True
    return False


def _route_is_local(route_config: Dict[str, Any]) -> bool:
    """Determine whether a route config points to a local endpoint."""
    base_url = route_config.get("base_url", "")
    if base_url and is_local_endpoint(base_url):
        return True
    model = (route_config.get("model") or "").lower()
    if any(model.startswith(p) for p in _LOCAL_MODEL_PREFIXES):
        return True
    return False


def maybe_route_local(
    api_kwargs: dict,
    api_mode: str,
    *,
    build_local_client,
) -> Optional[Tuple[dict, Any, RouteDecision]]:
    """Decide whether to swap this call to a route from the intent router map.

    Returns None to mean "no routing; use existing client/kwargs."
    Returns (new_api_kwargs, route_client_or_config, decision) when routing applies.

    ``build_local_client`` is a callable that receives ``base_url`` and
    ``api_key`` and returns an OpenAI-compatible client for that endpoint.
    """
    router = _get_router()
    if router is None:
        return None
    if api_mode != "chat_completions":
        return None
    if _is_already_local(api_kwargs):
        return None

    prompt = _last_user_message(api_kwargs.get("messages") or [])
    if not prompt:
        return None

    decision = router.classify(prompt)

    # Advisory mode: log but never swap.
    if _advisory:
        logger.info(
            "intent router: ADVISORY (intent=%s complexity=%s route_to=%s "
            "latency_ms=%s)",
            decision.intent, decision.complexity, decision.route_to,
            decision.latency_ms,
        )
        return None

    route_name = decision.route_to

    # If the decision is to keep the main model (kimi), don't intercept —
    # let the existing provider chain handle it. Only local routes need swapping.
    if route_name == "kimi":
        logger.debug(
            "intent router: kimi route → pass-through (intent=%s complexity=%s latency_ms=%s)",
            decision.intent, decision.complexity, decision.latency_ms,
        )
        return None

    route_cfg = _routes_map.get(route_name)

    # If the routes map doesn't contain this route, fall back to the legacy
    # hardcoded deepseek swap so we don't break partially-upgraded configs.
    if route_cfg is None:
        logger.warning(
            "intent router: route '%s' not found in routes map; falling back "
            "to hardcoded deepseek", route_name,
        )
        route_cfg = {"model": "DeepSeek-V4-Flash", "base_url": "https://robin-claude.openai.azure.com/openai/deployments/DeepSeek-V4-Flash?api-version=2024-05-01-preview", "api_key": os.getenv("AZURE_OPENAI_KEY", "")}

    # Determine whether this route is local → strip cloud-only kwargs.
    local = _route_is_local(route_cfg)

    new_kwargs = dict(api_kwargs)
    new_kwargs["model"] = route_cfg["model"]

    if local:
        for k in _STRIP_FOR_LOCAL:
            new_kwargs.pop(k, None)
        new_kwargs["stream"] = False
        # Some Ollama versions choke on max_tokens; keep it if present but
        # don't add it.  Ollama supports it as "num_predict" via extra_body,
        # but we just stripped extra_body, so native max_tokens is fine.

        # --- Context Trimming for Local Routes ---
        # The local model executes simple tool-calling tasks. Sending 15k+ tokens
        # of RAG memory dramatically increases TTFT latency. We trim it down here.
        messages = list(new_kwargs.get("messages", []))
        if messages and isinstance(messages[-1], dict) and messages[-1].get("role") == "user":
            content = messages[-1].get("content", "")
            if isinstance(content, str):
                from agent.routing.heuristic_router import _strip_injected_context
                # Duplicate the message dict to avoid mutating the original
                new_msg = dict(messages[-1])
                new_msg["content"] = _strip_injected_context(content)
                messages[-1] = new_msg
        
        # Limit history to the system prompt + last 5 messages
        if len(messages) > 6:
            sys_msgs = [m for m in messages if isinstance(m, dict) and m.get("role") == "system"]
            messages = sys_msgs + messages[-5:]
            
        new_kwargs["messages"] = messages

    base_url = route_cfg.get("base_url", "http://localhost:11434/v1")
    api_key = route_cfg.get("api_key", "ollama")

    # Build a client for this specific route's endpoint.
    route_client = build_local_client(base_url=base_url, api_key=api_key)

    logger.info(
        "intent router: swapped to route=%s model=%s local=%s "
        "(intent=%s complexity=%s latency_ms=%s)",
        route_name, route_cfg["model"], local,
        decision.intent, decision.complexity, decision.latency_ms,
    )
    return new_kwargs, route_client, decision
