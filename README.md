# Studio Agent — AI agent for Roblox Studio

A Windows desktop app that builds inside your open Roblox Studio place: it writes and edits Luau, builds maps and parts, makes working UI, playtests and fixes its own errors. It talks to Studio through Roblox's official built-in MCP server.

## Features
- **Chat / Script**: ask for anything ("add a double jump", "fix my shop script").
- **Game Builder** (like Lemonade): describe a game, get a plan, press *Build this game*. It builds the map, systems, UI and data saving, then playtests and fixes errors. Templates: Obby, Tycoon, Simulator, Tower Defense, Horror, Battle Arena.
- **UI Builder** (like Forge GUI, but every button works): shops, menus, HUDs, inventories, settings, daily rewards, built from real Studio instances with tweens and LocalScripts.
- **Quick actions**: Fix errors, Playtest check, Explain place, Optimize, Code review, Add comments, Undo.
- **Project memory**: remembers each place's systems and your style between sessions.
- **Vision**: attach a reference image or mockup; with Gemini or OpenAI it also checks screen captures of its own work.
- **Prompt enhancer**, saved chat history, custom instructions.
- **3D and assets**: Studio's own tools for AI meshes, materials, animations, procedural models and Creator Store assets.

## AI options
| Mode | Key | Notes |
|---|---|---|
| Free Cloud AI | none | Rotates across free servers (Kilo Gateway, OVHcloud, Pollinations). Limits are per internet connection. |
| Google Gemini | free key | aistudio.google.com/apikey. Best free option, with vision. |
| Groq | free key | console.groq.com/keys. Very fast. |
| OpenRouter | free key | free `:free` models. |
| DeepSeek / OpenAI | paid key | strongest results. |
| Local (Ollama) | none | runs on your PC; use a tool-capable model like `qwen2.5-coder:14b`. |
| Custom | any | any OpenAI-compatible endpoint. |

Keys are stored in Windows Credential Manager.

## Setup
1. Download `StudioAgent.exe` from the latest Release and run it. Windows SmartScreen may warn because the app is unsigned: choose **More info › Run anyway**.
2. In Roblox Studio, open a place, then **Assistant › … › Manage MCP Servers › Enable Studio as MCP server**.
3. In Studio Agent press **Connect to Studio** (the dot turns green), pick a mode and go.

## Run from source
```
pip install -r requirements.txt
python run.py
```
Test without Studio: `set STUDIO_MCP_COMMAND=python tests/fake_studio_mcp.py` then `python run.py`.
