"""Answer-free Codex transport, using the user's existing ChatGPT login.

No SDK, API key, answer bundle, scoring imports, or conversation reuse.
The catalog copy changes tool exposure ONLY, not model IDs or effort support.
An HTTP fixture checks the actual outgoing payload before any real puzzle run.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

HARNESS_VERSION = "gpt_subscription_blind_v1"
CONDITIONS = {"thinking_off": "none", "effort_low": "low",
              "effort_high": "high", "control_no_clues": "high"}
DEFAULT_MODELS = ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"]
FEATURES_OFF = (
    "plugins", "apps", "memories", "hooks", "shell_tool", "unified_exec",
    "multi_agent", "multi_agent_v2", "code_mode", "code_mode_host",
    "code_mode_only", "browser_use", "browser_use_external", "computer_use",
    "image_generation", "view_image", "goals", "sleep_tool", "skill_search",
    "tool_suggest", "workspace_dependencies", "shell_snapshot",
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def cli_path() -> str:
    path = os.environ.get("TOUCHSTONE_CODEX_BIN") or shutil.which("codex")
    if not path:
        raise RuntimeError("Codex CLI not found; install it and sign in with ChatGPT.")
    return path


def catalog_path() -> Path:
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "models_cache.json"


def isolated_catalog(source: dict, models: list[str]) -> dict:
    known = {m["slug"]: m for m in source["models"]}
    unknown = set(models) - set(known)
    if unknown:
        raise ValueError(f"Models absent from subscription catalog: {sorted(unknown)}")
    result = []
    for name in models:
        model = dict(known[name])
        model.update(shell_type="disabled", apply_patch_tool_type=None,
                     experimental_supported_tools=[], tool_mode=None,
                     node_repl_disabled=True, multi_agent_version="v1",
                     include_skills_usage_instructions=False,
                     include_plugin_usage_instructions=False,
                     include_apps_usage_instructions=False)
        result.append(model)
    return {"models": result}


def clean_env() -> dict:
    # Keep normal login discovery; never copy or print auth.json or its tokens.
    banned = {"OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL",
              "OPENAI_ORG_ID", "OPENAI_PROJECT_ID"}
    return {k: v for k, v in os.environ.items() if k not in banned}


def config(root: Path, effort: str) -> dict:
    cfg = {
        "forced_login_method": "chatgpt", "model_provider": "openai",
        "project_doc_max_bytes": 0, "web_search": "disabled",
        "model_reasoning_effort": effort,
        "sqlite_home": str(root / "state"), "log_dir": str(root / "logs"),
        "model_catalog_json": str(root / "models.json"),
        "model_instructions_file": str(root / "instructions.txt"),
        "include_environment_context": False, "include_apps_instructions": False,
        "include_permissions_instructions": False,
        "include_collaboration_mode_instructions": False,
        "developer_instructions": "", "personality": "none",
        "skills.include_instructions": False, "skills.bundled.enabled": False,
        "agents.enabled": False,
        "tools.update_plan.enabled": False,
        "tools.experimental_request_user_input.enabled": False,
        "history.persistence": "none", "orchestrator.mcp.enabled": False,
        "orchestrator.skills.enabled": False,
        "features.skip_host_skill_discovery": True,
        "suppress_unstable_features_warning": True,
        "features.unbounded_connection_retries": False,
    }
    cfg.update({"features." + feature: False for feature in FEATURES_OFF})
    return cfg


def call(model: str, effort: str, prompt: str, system: str, catalog: dict,
         timeout: float = 180, overrides: dict | None = None) -> dict:
    with tempfile.TemporaryDirectory(prefix="ts_gpt_blind_") as folder:
        root = Path(folder).resolve()
        cwd = root / "empty"
        cwd.mkdir()
        (root / "models.json").write_text(json.dumps(catalog))
        (root / "instructions.txt").write_text(system)
        cfg = config(root, effort)
        if overrides:
            cfg.update(overrides)  # Used ONLY by the offline wire fixture.
        cmd = [cli_path(), "exec", "--strict-config", "--ignore-user-config",
               "--ignore-rules", "--ephemeral", "--skip-git-repo-check",
               "--json", "--sandbox", "read-only", "-C", str(cwd), "-m", model]
        for key, value in cfg.items():
            cmd.extend(["-c", key + "=" + json.dumps(value)])
        cmd.append("-")
        started = time.perf_counter()
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                              cwd=cwd, env=clean_env(), timeout=timeout)
        wall_ms = (time.perf_counter() - started) * 1000
    if proc.returncode:
        raise RuntimeError(f"Codex exited {proc.returncode}: "
                           f"{(proc.stderr + proc.stdout)[-2000:]}")
    events = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    parsed = parse_events(events, effort)
    parsed.update(wall_ms=wall_ms, events=events)
    return parsed


def parse_events(events: list[dict], effort: str) -> dict:
    starts = [e for e in events if e.get("type") == "turn.started"]
    ends = [e for e in events if e.get("type") == "turn.completed"]
    if len(starts) != 1 or len(ends) != 1:
        raise ValueError("Expected exactly one complete turn: " + json.dumps(events)[-1500:])
    allowed = {"thread.started", "turn.started", "turn.completed",
               "item.started", "item.updated", "item.completed"}
    messages = []
    for event in events:
        if event.get("type") not in allowed:
            raise ValueError("Unexpected event (possible tool/error): " + json.dumps(event))
        if event["type"].startswith("item."):
            item = event["item"]
            if item.get("type") not in {"agent_message", "reasoning"}:
                raise ValueError("Non-text item (possible tool/error): " + json.dumps(item))
            if event["type"] == "item.completed" and item["type"] == "agent_message":
                messages.append(item["text"])
    usage = ends[0]["usage"]
    for key in ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens"):
        if type(usage.get(key)) is not int or usage[key] < 0:
            raise ValueError(f"Missing/invalid usage counter: {key}")
    if effort == "none" and usage["reasoning_output_tokens"] != 0:
        raise ValueError("Thinking-off produced reasoning tokens; refusing to label it off.")
    if not messages:
        raise ValueError("No final model response")
    return {"text": "\n".join(messages), "usage": usage,
            "num_turns": 1, "tool_events": 0,
            "thread_id": next(e["thread_id"] for e in events if e["type"] == "thread.started")}


def parse_answer(text: str) -> str | None:
    matches = re.findall(r"ANSWER\s*:\s*\**\s*([A-Ga-g])\s*([1-7])", text, re.I)
    matches = matches or re.findall(r"\b([A-Ga-g])\s?([1-7])\b", text)
    return "".join(matches[-1]).upper() if matches else None


def classify_strategy(text: str) -> dict:
    cells = set(re.findall(r"\b([A-D][1-4])\b", text))
    axis = len(re.findall(r"\b(column|row)s?\b.{0,40}\b(only|must be|remaining|left|eliminat)", text, re.I))
    return {"distinct_cells_named": len(cells), "axis_elimination_phrases": axis,
            "looks_like_enumeration": len(cells) >= 10}
