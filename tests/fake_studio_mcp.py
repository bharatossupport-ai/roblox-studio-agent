"""A fake Studio MCP server (stdio) for testing without Roblox Studio."""
import json, sys

TOOLS = [
    {"name": "list_roblox_studios", "description": "List studios", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "execute_luau", "description": "Runs Luau code in Studio.", "inputSchema": {"type": "object", "properties": {
        "studio_id": {"type": "string"}, "code": {"type": "string"}, "datamodel_type": {"type": "string", "enum": ["Edit", "Client", "Server"]}},
        "required": ["studio_id", "code", "datamodel_type"]}},
    {"name": "search_game_tree", "description": "Explores the instance hierarchy.", "inputSchema": {"type": "object", "properties": {
        "studio_id": {"type": "string"}, "path": {"type": "string"}}, "required": ["studio_id"]}},
    {"name": "multi_edit", "description": "Edits or creates a script.", "inputSchema": {"type": "object", "properties": {
        "studio_id": {"type": "string"}, "path": {"type": "string"}, "datamodel_type": {"type": "string"},
        "edits": {"type": "array", "items": {"type": "object", "properties": {"old_string": {"type": "string"}, "new_string": {"type": "string"}}}}},
        "required": ["studio_id", "path", "edits"]}},
    {"name": "submit_feedback", "description": "x", "inputSchema": {"type": "object", "properties": {}}},
]
LOG = []
for line in sys.stdin:
    msg = json.loads(line)
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:
        continue
    if method == "initialize":
        res = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "fake", "version": "0"}}
    elif method == "tools/list":
        res = {"tools": TOOLS}
    elif method == "tools/call":
        name, args = msg["params"]["name"], msg["params"]["arguments"]
        sys.stderr.write(f"CALL {name} {json.dumps(args)[:200]}\n")
        if name == "list_roblox_studios":
            txt = json.dumps({"studios": [{"studio_id": "abc123", "name": "TestPlace"}]})
        elif "studio_id" not in args:
            txt = "missing studio_id"
        elif name == "search_game_tree":
            txt = json.dumps([{"path": "game.Workspace.Baseplate", "class": "Part"}, {"path": "game.Workspace.SpawnLocation", "class": "SpawnLocation"}])
        else:
            txt = "OK"
        res = {"content": [{"type": "text", "text": txt}], "isError": False}
    else:
        res = {}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid, "result": res}) + "\n")
    sys.stdout.flush()
