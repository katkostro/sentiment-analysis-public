"""
Interactive chat session with the Sentiment Analysis Foundry agent.

Usage:
  python src/chat_with_agent.py [--file <excel_file>]

If --file is specified, the Excel file is uploaded and the agent
is asked to analyse it. Otherwise, starts an interactive chat loop.
"""

from __future__ import annotations

import argparse
import json
import sys

from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.agents.models import FilePurpose, MessageAttachment, CodeInterpreterTool


def load_config() -> dict:
    with open("agent_config.json", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat with the Sentiment Analysis agent")
    parser.add_argument("--file", type=str, help="Excel file to upload for analysis")
    args = parser.parse_args()

    config = load_config()
    agent_id = config["agent_id"]
    endpoint = config["endpoint"]

    credential = DefaultAzureCredential()
    client = AIProjectClient(endpoint=endpoint, credential=credential)

    # Create a thread
    thread = client.agents.create_thread()
    print(f"Thread created: {thread.id}\n")

    if args.file:
        # Upload file and ask for analysis
        print(f"📄 Uploading {args.file} ...")
        uploaded = client.agents.upload_file_and_poll(
            file_path=args.file,
            purpose=FilePurpose.AGENTS,
        )
        print(f"   File ID: {uploaded.id}\n")

        attachment = MessageAttachment(
            file_id=uploaded.id,
            tools=[CodeInterpreterTool().definitions[0]],
        )

        client.agents.create_message(
            thread_id=thread.id,
            role="user",
            content="Please analyse the sentiment of all survey responses in the attached Excel file. "
            "Provide an overall summary, highlight any negative feedback, and give recommendations.",
            attachments=[attachment],
        )

        run = client.agents.create_and_process_run(
            thread_id=thread.id,
            agent_id=agent_id,
        )

        if run.status == "failed":
            print(f"❌ Run failed: {run.last_error}")
            sys.exit(1)

        messages = client.agents.list_messages(thread_id=thread.id)
        for msg in reversed(messages.data):
            if msg.role == "assistant":
                for block in msg.content:
                    if hasattr(block, "text"):
                        print(block.text.value)
        return

    # Interactive chat loop
    print("💬 Sentiment Analysis Agent (type 'quit' to exit)")
    print("=" * 50)

    while True:
        user_input = input("\nYou: ").strip()
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
        for msg in messages.data:
            if msg.role == "assistant":
                for block in msg.content:
                    if hasattr(block, "text"):
                        print(f"\nAgent: {block.text.value}")
                break


if __name__ == "__main__":
    main()
