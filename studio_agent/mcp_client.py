"""Stdio client for Roblox Studio's built-in MCP server.

Studio side (once): Assistant > ... > Manage MCP Servers > "Enable Studio as MCP server".
Windows launches the server with:  cmd.exe /c %LOCALAPPDATA%\\Roblox\\mcp.bat
macOS launches:                    /Applications/RobloxStudio.app/Contents/MacOS/StudioMCP

Every Studio tool except list_roblox_studios takes a studio_id. This client binds to one
Studio instance and fills studio_id in for every call, so the AI never has to.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time

PROTOCOL_VERSION = "2025-06-18"


class MCPError(RuntimeError):
    pass


def default_command() -> list[str]:
    override = os.environ.get("STUDIO_MCP_COMMAND")
    if override:
        return override.split()
    if sys.platform == "win32":
        bat = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Roblox", "mcp.bat")
        return ["cmd.exe", "/c", bat]
    if sys.platform == "darwin":
        for base in ("/Applications", os.path.expanduser("~/Applications")):
            p = os.path.join(base, "RobloxStudio.app/Contents/MacOS/StudioMCP")
            if os.path.exists(p):
                return [p]
        return ["/Applications/RobloxStudio.app/Contents/MacOS/StudioMCP"]
    raise MCPError("Roblox Studio only runs on Windows and macOS.")


class StudioMCP:
    """One MCP server process, one session, bound to one Studio instance."""

    def __init__(self, command: list[str] | None = None, timeout: float = 120.0):
        self.command = command
        self.timeout = timeout
        self.proc: subprocess.Popen | None = None
        self.studio_id: str | None = None
        self.studio_name: str = ""
        self._id = 0
        self._lines: "queue.Queue[bytes | None]" = queue.Queue()
        self._lock = threading.Lock()
        self._tools: list[dict] = []

    # ---------------------------------------------------------------- transport
    def start(self) -> None:
        if self.proc and self.proc.poll() is None:
            return
        if not self.command:
            self.command = default_command()
        if sys.platform == "win32" and self.command[:2] == ["cmd.exe", "/c"]:
            if not os.path.exists(self.command[2]):
                raise MCPError(
                    "Roblox Studio's MCP launcher wasn't found. Install or update Roblox Studio, "
                    "then enable Assistant > ... > Manage MCP Servers > Enable Studio as MCP server."
                )
        flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
        self.proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        self._lines = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()
        r = self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "studio-agent", "version": "1.0.0"},
            },
            30,
        )
        if "result" not in r:
            raise MCPError(f"Studio MCP didn't initialize: {r}")
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        self.studio_id = None

    def _reader(self) -> None:
        proc = self.proc
        assert proc and proc.stdout
        for line in proc.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def _send(self, obj: dict) -> None:
        if not self.proc or self.proc.poll() is not None:
            raise MCPError("The Studio MCP process isn't running.")
        assert self.proc.stdin
        self.proc.stdin.write((json.dumps(obj) + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def _request(self, method: str, params: dict | None = None, timeout: float | None = None) -> dict:
        with self._lock:
            self._id += 1
            rid = self._id
            msg = {"jsonrpc": "2.0", "id": rid, "method": method}
            if params is not None:
                msg["params"] = params
            self._send(msg)
            deadline = time.time() + (timeout or self.timeout)
            while True:
                left = deadline - time.time()
                if left <= 0:
                    raise MCPError(f"{method}: Studio didn't answer in {timeout or self.timeout:.0f}s")
                try:
                    line = self._lines.get(timeout=left)
                except queue.Empty:
                    continue
                if line is None:
                    raise MCPError("Studio MCP closed the connection.")
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue  # stray log output
                if obj.get("id") == rid:
                    return obj
                # notifications and server->client requests are ignored

    # ---------------------------------------------------------------- MCP
    def list_tools(self, refresh: bool = False) -> list[dict]:
        if self._tools and not refresh:
            return self._tools
        r = self._request("tools/list", {})
        self._tools = r.get("result", {}).get("tools", [])
        return self._tools

    def raw_call(self, name: str, args: dict | None = None, timeout: float | None = None) -> dict:
        r = self._request("tools/call", {"name": name, "arguments": args or {}}, timeout)
        if "error" in r:
            raise MCPError(f"{name}: {r['error'].get('message', r['error'])}")
        return r.get("result", {})

    @staticmethod
    def text_of(result: dict) -> str:
        return "\n".join(
            c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"
        )

    def studios(self) -> list[dict]:
        txt = self.text_of(self.raw_call("list_roblox_studios"))
        try:
            data = json.loads(txt)
        except json.JSONDecodeError:
            return []
        if isinstance(data, list):
            return data
        return data.get("studios", []) if isinstance(data, dict) else []

    def bind(self, want: str | None = None, wait_s: float = 12) -> str:
        """Pick the Studio instance to drive (the only one open, or the one matching `want`)."""
        found: list[dict] = []
        end = time.time() + wait_s
        while True:
            found = self.studios()
            if found or time.time() > end:
                break
            time.sleep(1.5)
        if not found:
            raise MCPError(
                "No Roblox Studio is connected. Open a place in Studio and turn on "
                "Assistant > ... > Manage MCP Servers > Enable Studio as MCP server."
            )
        pick = found[0]
        if want:
            w = want.lower()
            matches = [s for s in found if any(w in str(v).lower() for v in s.values())]
            if matches:
                pick = matches[0]
        self.studio_id = str(pick.get("studio_id") or pick.get("studioId") or pick.get("id"))
        self.studio_name = str(pick.get("name") or pick.get("place_name") or self.studio_id)
        return self.studio_id

    def call(self, name: str, args: dict | None = None, timeout: float | None = None) -> dict:
        a = dict(args or {})
        if name != "list_roblox_studios":
            if not self.studio_id:
                self.bind()
            a["studio_id"] = self.studio_id
        deadline = time.time() + 45
        while True:
            res = self.raw_call(name, a, timeout)
            # When Studio reconnects to a new host process, calls briefly report no Studio.
            if not (res.get("isError") and "No Roblox Studio instances are connected" in self.text_of(res)):
                return res
            if time.time() > deadline:
                return res
            time.sleep(2)
