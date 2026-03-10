"""
Test runner for the Sentiment Analysis Foundry Agent.

Usage:
  # Test 1 — upload Excel file and get full analysis
  python src/test_agent.py --file "Survey Samples.xlsx"

  # Test 2 — interactive chat (type messages, 'quit' to exit)
  python src/test_agent.py --interactive

  # Test 3 — run a quick non-interactive chat with a preset message
  python src/test_agent.py --message "Analyse the sentiment of: 'Great service!', 'Very slow delivery', 'Excellent product but expensive'"
"""

from __future__ import annotations

import argparse
import json
import sys
import os

from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.agents.models import FilePurpose, MessageAttachment, CodeInterpreterTool


# ─── Helpers ─────────────────────────────────────────────────────────────────

def load_config() -> dict:
    config_path = os.path.join(os.path.dirname(__file__), "..", "agent_config.json")
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def print_assistant_reply(messages) -> None:
    for msg in messages.data:
        if msg.role == "assistant":
            for block in msg.content:
                if hasattr(block, "text"):
                    print(f"\nAgent:\n{block.text.value}")
            break


# ─── Test: File upload analysis ──────────────────────────────────────────────

def test_file_analysis(client: AIProjectClient, agent_id: str, file_path: str) -> None:
    print(f"\n{'='*60}")
    print(f"TEST: File Analysis — {file_path}")
    print(f"{'='*60}")

    if not os.path.exists(file_path):
        print(f"❌ File not found: {file_path}")
        sys.exit(1)

    thread = client.agents.create_thread()
    print(f"Thread: {thread.id}")

    print(f"Uploading {file_path} ...")
    uploaded = client.agents.upload_file_and_poll(
        file_path=file_path,
        purpose=FilePurpose.AGENTS,
    )
    print(f"File ID: {uploaded.id}")

    attachment = MessageAttachment(
        file_id=uploaded.id,
        tools=[CodeInterpreterTool().definitions[0]],
    )

    client.agents.create_message(
        thread_id=thread.id,
        role="user",
        content=(
            "Please analyse all survey responses in the attached Excel file. "
            "Use sentiment analysis, key phrase extraction, and NER. "
            "Provide: overall sentiment distribution, top themes, any negative responses requiring attention, "
            "and 3 actionable recommendations."
        ),
        attachments=[attachment],
    )

    print("Running agent (this may take a moment)...")
    run = client.agents.create_and_process_run(
        thread_id=thread.id,
        agent_id=agent_id,
    )

    if run.status == "failed":
        print(f"❌ Run failed: {run.last_error}")
        sys.exit(1)

    messages = client.agents.list_messages(thread_id=thread.id)
    print_assistant_reply(messages)


# ─── Test: Single message (non-interactive) ──────────────────────────────────

def test_message(client: AIProjectClient, agent_id: str, message: str) -> None:
    print(f"\n{'='*60}")
    print("TEST: Single Message")
    print(f"{'='*60}")

    thread = client.agents.create_thread()
    print(f"Thread: {thread.id}")

    client.agents.create_message(
        thread_id=thread.id,
        role="user",
        content=message,
    )

    print("Running agent...")
    run = client.agents.create_and_process_run(
        thread_id=thread.id,
        agent_id=agent_id,
    )

    if run.status == "failed":
        print(f"❌ Run failed: {run.last_error}")
        sys.exit(1)

    messages = client.agents.list_messages(thread_id=thread.id)
    print_assistant_reply(messages)


# ─── Test: Interactive chat ───────────────────────────────────────────────────

def test_interactive(client: AIProjectClient, agent_id: str) -> None:
    print(f"\n{'='*60}")
    print("TEST: Interactive Chat (type 'quit' to exit)")
    print(f"{'='*60}")

    thread = client.agents.create_thread()
    print(f"Thread: {thread.id}\n")

    while True:
        user_input = input("You: ").strip()
        if not user_input or user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break

        client.agents.create_message(
            thread_id=thread.id,
            role="user",
            content=user_input,
        )

        run = client.agents.create_and_process_run(
            thread_id=thread.id,
            agent_id=agent_id,
        )

        if run.status == "failed":
            print(f"❌ Run failed: {run.last_error}")
            continue

        messages = client.agents.list_messages(thread_id=thread.id)
        print_assistant_reply(messages)


# ─── Entry point ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Test the Sentiment Analysis Foundry Agent")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", type=str, help="Path to Excel file for analysis")
    group.add_argument("--interactive", action="store_true", help="Start interactive chat")
    group.add_argument("--message", type=str, help="Send a single message and print the response")
    args = parser.parse_args()

    config = load_config()
    credential = DefaultAzureCredential()
    client = AIProjectClient(endpoint=config["endpoint"], credential=credential)

    print(f"Agent: {config['agent_name']} ({config['agent_id']})")

    if args.file:
        test_file_analysis(client, config["agent_id"], args.file)
    elif args.message:
        test_message(client, config["agent_id"], args.message)
    elif args.interactive:
        test_interactive(client, config["agent_id"])


if __name__ == "__main__":
    main()
