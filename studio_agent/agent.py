"""The agent loop: the AI picks Studio tools, we run them through MCP, repeat until done."""
from __future__ import annotations

import base64
import json
import mimetypes
import re
from pathlib import Path
from typing import Callable

from .llm import ChatClient
from .mcp_client import StudioMCP

SKIP_TOOLS = {"submit_feedback", "list_roblox_studios"}
MAX_RESULT_CHARS = 12000

SYSTEM_PROMPT = """You are Studio Agent, an expert Roblox developer working directly inside the user's open Roblox Studio place.
You act through tools; you never ask the user to paste code themselves.

How to work:
- Look before you change: use search_game_tree, inspect_instance, script_search and script_read to understand the place.
- Create or edit scripts with multi_edit (datamodel_type "Edit"). Use game.ServerScriptService / StarterPlayer / ReplicatedStorage paths that fit the job.
- Build parts, models and properties with execute_luau (datamodel_type "Edit"). Anchor parts that should not fall.
- Write modern, typed-where-useful Luau. Server logic in Scripts, client UI/input in LocalScripts, shared code in ModuleScripts.
- To check your work, start a playtest with start_stop_play, read get_console_output, fix errors, then stop the playtest.
- Never touch anything the user did not ask about. Never delete content unless asked.
- Keep going step by step until the request is fully done, then reply with a short summary of what you changed.
"""

GAME_PROMPT = """
MODE: GAME BUILDER. You are building a complete, playable Roblox game, not a snippet.
Work through the approved plan in order and finish every part of it:
1. World: build the map with execute_luau (terrain via workspace.Terrain:FillBlock / FillBall, anchored parts grouped in named Models in Workspace, spawn locations, lighting via game.Lighting and Atmosphere). Use generate_procedural_model, generate_mesh, generate_material or search_asset + insert_asset for props when they help.
2. Systems: one Script per system in ServerScriptService (game loop, leaderstats, currency, data saving with DataStoreService wrapped in pcall, damage, rounds...), shared config and helpers as ModuleScripts in ReplicatedStorage, RemoteEvents in ReplicatedStorage.Remotes. Validate everything the client sends on the server.
3. UI: a ScreenGui per screen in StarterGui (see UI rules below), driven by LocalScripts in StarterPlayer.StarterPlayerScripts or inside the ScreenGui.
4. Test: start a playtest, read the console, fix every error and warning you caused, repeat until clean, then stop the playtest and save_place.
Finish with a short summary: what was built, how to play, and ideas for next steps.
"""

UI_PROMPT = """
UI RULES (polished, game-ready interfaces built from real Studio instances so every button works):
- Build with execute_luau in the Edit datamodel: ScreenGui (ResetOnSpawn=false, ZIndexBehavior=Sibling, IgnoreGuiInset where it fits) in StarterGui.
- Size and position with Scale, add UIAspectRatioConstraint to panels, UISizeConstraint/UIScale for big screens, and keep it usable on phones (buttons at least ~44px tall).
- Style consistently: one palette (background, panel, accent, text), UICorner on every frame/button, UIStroke outlines, UIGradient for depth, UIPadding, UIListLayout/UIGridLayout for lists and grids, FredokaOne/GothamBold-style fonts with TextScaled and UITextSizeConstraint.
- Make it alive: a LocalScript wires every button (open/close, tabs, purchases via RemoteEvents), hover/press tweens with TweenService, panels pop in with a scale tween.
- Name every instance clearly (ShopFrame, CloseButton, CoinLabel) so the user can edit it later.
- For icons or art, use generate_material/search_asset/insert_asset or upload_image from a URL the user gives you.
"""


LOCAL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "Save a durable note about this place (architecture, conventions, the user's style "
                           "preferences, decisions) to project memory. It is shown to you in every future session.",
            "parameters": {
                "type": "object",
                "properties": {"note": {"type": "string", "description": "One concise fact to remember."}},
                "required": ["note"],
            },
        },
    }
]

QUICK_ACTIONS = {
    "fix": "Read the Studio output with get_console_output (start a short playtest first if the log is empty), find every error and warning, fix their causes in the scripts, re-test until the output is clean, then summarize the fixes.",
    "explain": "Explain how this place works: find the main scripts and systems, then give a clear, beginner-friendly overview of each system, how they talk to each other (remotes, modules) and where to edit common things. Do not change anything.",
    "optimize": "Review the scripts for performance and security problems (loops without waits, per-frame work that could be event-driven, memory leaks from unconnected connections, unvalidated RemoteEvents, too many parts that could be anchored or merged). Fix the important ones and summarize what changed.",
    "comment": "Add clear comments and section headers to the main scripts without changing behavior, and rename unclear variables where it is safe.",
    "test": "Start a playtest, let it run, read the console output, check that the main systems work, stop the playtest and report what works and what is broken. Fix any errors you find.",
    "review": "Do a code review of the scripts like a senior Roblox engineer: bugs, exploit risks, bad patterns, DataStore safety. List the findings by severity and fix the critical ones.",
}


def memory_path(place: str) -> Path:
    from .config import config_dir
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", place or "default")[:80]
    d = config_dir() / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{safe}.md"


def image_part(path_or_b64: str, mime: str = "") -> dict:
    if Path(path_or_b64).exists():
        mime = mimetypes.guess_type(path_or_b64)[0] or "image/png"
        data = base64.b64encode(Path(path_or_b64).read_bytes()).decode()
    else:
        data = path_or_b64
        mime = mime or "image/png"
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}


def mcp_tools_to_openai(tools: list[dict]) -> list[dict]:
    out = []
    for t in tools:
        name = t.get("name", "")
        if not name or name in SKIP_TOOLS:
            continue
        schema = json.loads(json.dumps(t.get("inputSchema") or {"type": "object", "properties": {}}))
        props = schema.get("properties") or {}
        props.pop("studio_id", None)  # filled in by the client
        schema["properties"] = props
        if "required" in schema:
            schema["required"] = [r for r in schema["required"] if r != "studio_id"]
            if not schema["required"]:
                schema.pop("required")
        schema.setdefault("type", "object")
        out.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": (t.get("description") or "")[:1024],
                    "parameters": schema,
                },
            }
        )
    return out


def result_images(result: dict) -> list[dict]:
    return [c for c in result.get("content", []) if c.get("type") == "image" and c.get("data")]


def result_to_text(result: dict) -> str:
    parts = []
    for c in result.get("content", []):
        if c.get("type") == "text":
            parts.append(c.get("text", ""))
        elif c.get("type") == "image":
            parts.append("[Image returned (screen capture).]")
    txt = "\n".join(parts).strip() or json.dumps(result)[:2000]
    if result.get("isError"):
        txt = "ERROR: " + txt
    if len(txt) > MAX_RESULT_CHARS:
        txt = txt[:MAX_RESULT_CHARS] + f"\n...[truncated, {len(txt) - MAX_RESULT_CHARS} more chars]"
    return txt


class Agent:
    def __init__(self, llm: ChatClient, studio: StudioMCP, custom_prompt: str = "", max_steps: int = 40,
                 vision: bool = False):
        self.llm = llm
        self.vision = vision
        self.studio = studio
        self.max_steps = max_steps
        self.custom_prompt = custom_prompt
        self.mode = "chat"
        self.messages: list[dict] = [{"role": "system", "content": self._system()}]
        self.stop_requested = False
        self._tools: list[dict] | None = None

    def _system(self) -> str:
        prompt = SYSTEM_PROMPT
        if self.mode == "game":
            prompt += GAME_PROMPT + UI_PROMPT
        elif self.mode == "ui":
            prompt += "\nMODE: UI BUILDER. The user wants game interfaces.\n" + UI_PROMPT
        else:
            prompt += UI_PROMPT
        if self.custom_prompt.strip():
            prompt += f"\nExtra instructions from the user:\n{self.custom_prompt}\n"
        prompt += "\nUse the remember tool to save durable facts about this place (systems, conventions, the user's preferences).\n"
        mem = self.memory()
        if mem.strip():
            prompt += f"\nPROJECT MEMORY for this place (from earlier sessions):\n{mem[-6000:]}\n"
        if self.vision:
            prompt += "\nYou can see images: use screen_capture to check how builds and UI look, and match any reference image the user attaches.\n"
        return prompt

    # ------------------------------------------------------------- memory
    def memory(self) -> str:
        p = memory_path(self.studio.studio_name)
        return p.read_text("utf-8") if p.exists() else ""

    def remember(self, note: str) -> str:
        p = memory_path(self.studio.studio_name)
        with p.open("a", encoding="utf-8") as f:
            f.write(f"- {note.strip()}\n")
        return "Saved to project memory."

    def enhance_prompt(self, text: str) -> str:
        """Rewrite a short request into a detailed, buildable spec (prompt enhancer)."""
        ask = ("Rewrite this Roblox Studio request as a detailed, specific build request: concrete mechanics, "
               "numbers, style and colors, UI, and edge cases. Keep the user's intent; at most 150 words. "
               "Reply with only the rewritten request.\n\nRequest: " + text)
        msgs = [{"role": "user", "content": ask}]
        return (self.llm.complete(msgs, None).get("content") or text).strip()

    def set_mode(self, mode: str) -> None:
        self.mode = mode if mode in ("chat", "game", "ui") else "chat"
        self.messages[0] = {"role": "system", "content": self._system()}

    def reset(self) -> None:
        self.messages = [{"role": "system", "content": self._system()}]

    def plan_game(self, idea: str) -> str:
        """Phase 1 of Game Builder: a build plan with no tool calls, for the user to approve."""
        ask = (
            "Write a build plan for this Roblox game. No tool calls. Use short markdown sections: "
            "Concept, Core loop, World/map, Systems (one line each: script name and job), UI screens, "
            "Monetization hooks (optional), Build order. Keep it achievable in one session.\n\nGame idea: " + idea
        )
        msgs = [{"role": "system", "content": self._system()}, {"role": "user", "content": ask}]
        return (self.llm.complete(msgs, None).get("content") or "").strip()

    def tools(self) -> list[dict]:
        if self._tools is None:
            self._tools = mcp_tools_to_openai(self.studio.list_tools()) + LOCAL_TOOLS
        return self._tools

    def run(
        self,
        user_text: str,
        on_event: Callable[[str, str], None] = lambda kind, text: None,
        images: list[str] | None = None,
    ) -> str:
        """Run one request. on_event(kind, text): kind is 'tool', 'result', 'thought' or 'error'.
        images: file paths of reference pictures (used when the model supports vision)."""
        self.stop_requested = False
        self.messages[0] = {"role": "system", "content": self._system()}  # refresh memory
        if images and self.vision:
            content: list | str = [{"type": "text", "text": user_text}] + [image_part(p) for p in images]
        else:
            content = user_text + ("\n(The user attached a reference image, but this AI model can't see images.)" if images else "")
        self.messages.append({"role": "user", "content": content})
        tools = self.tools()
        limit = self.max_steps * 3 if self.mode == "game" else self.max_steps
        for _ in range(limit):
            if self.stop_requested:
                return "Stopped."
            msg = self.llm.complete(self.messages, tools)
            calls = msg.get("tool_calls") or []
            content = msg.get("content") or ""
            entry: dict = {"role": "assistant", "content": content}
            if calls:
                entry["tool_calls"] = calls
            self.messages.append(entry)
            if not calls:
                return content or "(done)"
            if content.strip():
                on_event("thought", content.strip())
            pending_images: list[dict] = []
            for call in calls:
                fn = call.get("function", {})
                name = fn.get("name", "")
                raw = fn.get("arguments") or "{}"
                try:
                    args = raw if isinstance(raw, dict) else json.loads(raw)
                except json.JSONDecodeError:
                    args = None
                if args is None:
                    text = "ERROR: your tool arguments were not valid JSON. Send them again as a JSON object."
                elif name == "remember":
                    text = self.remember(str(args.get("note", "")))
                    on_event("tool", f"remember: {str(args.get('note', ''))[:200]}")
                else:
                    on_event("tool", f"{name} {json.dumps(args)[:300]}")
                    try:
                        res = self.studio.call(name, args)
                        text = result_to_text(res)
                        if self.vision:
                            pending_images.extend(result_images(res))
                    except Exception as e:  # keep the loop alive, let the AI recover
                        text = f"ERROR: {e}"
                    on_event("result", text[:600])
                self.messages.append(
                    {"role": "tool", "tool_call_id": call.get("id", name), "name": name, "content": text}
                )
                if self.stop_requested:
                    return "Stopped."
            if pending_images:
                self.messages.append({"role": "user", "content": [{"type": "text", "text": "Images returned by the tools above:"}]
                                      + [image_part(i["data"], i.get("mimeType", "image/png")) for i in pending_images[-2:]]})
        return "I hit the step limit for one request. Tell me to continue and I'll pick up where I left off."
