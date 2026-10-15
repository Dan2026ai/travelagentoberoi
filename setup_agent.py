"""
One-time setup: creates the Travel Planner agent + environment in your Claude Console
and prints the two IDs to put in your hosting provider's environment variables.

Skip this if you already created the agent in Console — just copy its Agent ID and
Environment ID from there instead.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python setup_agent.py
"""

import os
import pathlib

from anthropic import Anthropic

MODEL = os.environ.get("MODEL", "claude-sonnet-5-5")
PROMPT_FILE = pathlib.Path(__file__).with_name("travel-agent-system-prompt.md")


def load_system_prompt() -> str:
    text = PROMPT_FILE.read_text(encoding="utf-8")
    # Drop the setup note at the top of the file (everything before the first '---' line).
    marker = "\n---\n"
    return text.split(marker, 1)[1].strip() if marker in text else text.strip()


def main() -> None:
    client = Anthropic()

    agent = client.beta.agents.create(
        name="Travel Planner",
        model=MODEL,
        system=load_system_prompt(),
        tools=[
            {
                "type": "agent_toolset_20260401",
                # Turn everything off by default (no bash, file editing, etc.)...
                "default_config": {"enabled": False},
                # ...and enable only web search + web fetch, auto-approved.
                "configs": [
                    {"name": "web_search", "enabled": True, "permission_policy": {"type": "always_allow"}},
                    {"name": "web_fetch", "enabled": True, "permission_policy": {"type": "always_allow"}},
                ],
            }
        ],
    )

    environment = client.beta.environments.create(
        name="travel-planner-env",
        config={"type": "cloud"},
    )

    print("\nDone. Add these to your hosting environment variables:\n")
    print(f"AGENT_ID={agent.id}")
    print(f"ENVIRONMENT_ID={environment.id}\n")


if __name__ == "__main__":
    main()
