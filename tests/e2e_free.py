import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from studio_agent.mcp_client import StudioMCP
from studio_agent.llm import ChatClient, FreePoolClient
from studio_agent.agent import Agent
from studio_agent.providers import get_provider

s = StudioMCP(command=[sys.executable, os.path.join(os.path.dirname(__file__), "fake_studio_mcp.py")], timeout=30)
s.start(); print("bound", s.bind(), s.studio_name)
p = get_provider("free")
llm = FreePoolClient(on_status=print)
a = Agent(llm, s)
a.set_mode(sys.argv[1] if len(sys.argv) > 1 else "chat")
print([t["function"]["name"] for t in a.tools()])
out = a.run("Create a red anchored part named RedBlock at 0,10,0 in Workspace.", lambda k, t: print(k.upper(), t[:200]))
print("FINAL:", out[:500]); print("backend", llm.last_backend)
if a.mode == "game":
    print("PLAN:", a.plan_game("tiny 3-stage obby")[:800])
s.stop()
