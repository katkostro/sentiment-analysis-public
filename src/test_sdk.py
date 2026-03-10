"""Quick end-to-end test of the SDK function tool loop."""
import os, json, sys, time

sys.path.insert(0, os.path.dirname(__file__))

with open(os.path.join(os.path.dirname(__file__), "..", ".env")) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip()

from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.agents.models import ToolOutput
from language_tools import TOOL_DISPATCH

config = json.load(open(os.path.join(os.path.dirname(__file__), "..", "agent_config.json")))
client = AIProjectClient(endpoint=config["endpoint"], credential=DefaultAzureCredential())

thread = client.agents.threads.create()
client.agents.messages.create(
    thread_id=thread.id,
    role="user",
    content=(
        "Analyse the sentiment of these survey responses:\n"
        "1. The service was excellent and the staff were very helpful.\n"
        "2. Very slow and rude staff. Completely disappointed.\n"
        "3. Average experience, nothing special.\n"
        "Show overall distribution and key themes."
    ),
)

run = client.agents.runs.create(thread_id=thread.id, agent_id=config["agent_id"])
terminal = {"completed", "failed", "cancelled", "expired"}

while run.status not in terminal:
    time.sleep(1)
    run = client.agents.runs.get(thread_id=thread.id, run_id=run.id)
    print("Status:", run.status)
    if run.status == "requires_action":
        outputs = []
        for call in run.required_action.submit_tool_outputs.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            print(f"  -> calling {call.function.name}({list(args.keys())})")
            result = TOOL_DISPATCH[call.function.name](**args)
            outputs.append(ToolOutput(tool_call_id=call.id, output=result))
        run = client.agents.runs.submit_tool_outputs(
            thread_id=thread.id, run_id=run.id, tool_outputs=outputs
        )

print("\nFinal status:", run.status)
if run.status == "failed":
    print("Error:", run.last_error)
else:
    last = client.agents.messages.get_last_message_text_by_role(
        thread_id=thread.id, role="assistant"
    )
    print("\nReply:\n", last.text.value if last else "(no response)")
