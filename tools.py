import json
import platform
import subprocess
import re
from dataclasses import dataclass
from pathlib import Path


class PolicyError(Exception):
    """Raised when a requested action violates policy.json."""

    pass


@dataclass(frozen=True)
class Tool:
    """
    Metadata for one tool.

    name: what the user types after "run"
    description: what appears in the help menu
    category: used for policy decisions, such as network approval
    action: the Python function that actually performs the work
    """

    name: str
    description: str
    category: str
    action: callable


class ToolRegistry:
    """
    Central place where tools are registered and policy is enforced.

    This is the main safety boundary for Phase 1. The CLI never runs arbitrary
    shell text from the user. It can only ask this registry to run known tools
    that we registered in Python and enabled in policy.json.
    """

    def __init__(self, policy_path="policy.json", reports_dir="reports"):
        self.policy_path = Path(policy_path)
        self.reports_dir = Path(reports_dir)
        self.policy = self.load_policy()
        self.tools = {}
        self.register_defaults()

    def load_policy(self):
        """Read policy.json so rules can change without editing Python code."""
        if not self.policy_path.exists():
            raise FileNotFoundError(f"Missing policy file: {self.policy_path}")
        return json.loads(self.policy_path.read_text(encoding="utf-8"))

    def register(self, tool):
        """Add one allowed tool to the registry."""
        self.tools[tool.name] = tool

    def register_defaults(self):
        """
        Register the starter tool set.

        Adding a future tool should start here, but it should also get a matching
        entry in policy.json. That two-step process is intentional friction.
        """
        self.register(
            Tool(
                name="ping",
                description="Send a small ping test to a host.",
                category="network",
                action=self.ping,
            )
        )
        self.register(
            Tool(
                name="nslookup",
                description="Run a DNS lookup for a host or domain.",
                category="network",
                action=self.nslookup,
            )
        )
        self.register(
            Tool(
                name="report",
                description="Generate a markdown report from recent tool results.",
                category="local",
                action=self.report,
            )
        )

    def list_tools(self):
        return [self.tools[name] for name in sorted(self.tools)]

    def get_policy_for_tool(self, tool_name):
        return self.policy.get("tools", {}).get(tool_name, {})

    def is_enabled(self, tool_name):
        return self.get_policy_for_tool(tool_name).get("enabled", False)

    def request_proposal(self, tool_name, target):
        """Return a durable, human-readable proposal for a tool request."""
        self.validate_request(tool_name, target)
        policy = self.get_policy_for_tool(tool_name)
        return {
            "action_type": "run_tool",
            "description": f"Run tool '{tool_name}' against '{target}'",
            "payload": {"tool": tool_name, "target": target},
            "risk_level": policy.get("risk_level", "unknown"),
            "requires_approval": self.requires_approval(tool_name),
        }

    def request_agent_proposal(self, agent, tool_name, target):
        """Return a tool proposal only if the agent and global policy both allow it."""
        self.validate_agent_tool_request(agent, tool_name, target)
        proposal = self.request_proposal(tool_name, target)
        proposal["description"] = (
            f"Agent '{agent.get('name', 'unknown')}' requests "
            f"tool '{tool_name}' against '{target}'"
        )
        proposal["payload"]["agent_id"] = agent.get("id")
        return proposal

    def validate_agent_tool_request(self, agent, tool_name, target):
        """Apply per-agent allowed tool checks before global tool policy."""
        if not agent:
            raise PolicyError("Agent is required for automation tool requests.")
        if agent.get("status", "active") != "active":
            raise PolicyError(f"Agent is not active: {agent.get('name', 'unknown')}")

        allowed_tools = agent.get("allowed_tools", [])
        if not allowed_tools:
            raise PolicyError(
                f"Agent '{agent.get('name', 'unknown')}' has no allowed tools."
            )
        if tool_name not in allowed_tools:
            raise PolicyError(
                f"Agent '{agent.get('name', 'unknown')}' is not allowed to use tool: "
                f"{tool_name}"
            )

        self.validate_request(tool_name, target)

    def requires_approval(self, tool_name):
        """
        Decide whether a human must approve this action.

        The tool-specific rule wins first. Then we apply category-wide policy,
        such as requiring approval for all network tools.
        """
        tool = self.tools[tool_name]
        tool_policy = self.get_policy_for_tool(tool_name)
        if tool_policy.get("requires_approval", False):
            return True
        return (
            tool.category == "network"
            and self.policy.get("require_approval_for_network_tools", True)
        )

    def run(self, tool_name, target, memory):
        """Validate and execute a known tool."""
        self.validate_request(tool_name, target)
        return self.tools[tool_name].action(target, memory)

    def validate_request(self, tool_name, target):
        """
        Preflight check before approval or execution.

        This prevents awkward flows where the app asks for approval and then
        immediately blocks the action anyway.
        """
        if tool_name not in self.tools:
            raise PolicyError(f"Unknown tool: {tool_name}")
        if not self.is_enabled(tool_name):
            raise PolicyError(f"Tool is disabled by policy: {tool_name}")
        if not isinstance(target, str) or not target.strip():
            raise PolicyError("Tool target is required.")
        if len(target) > self.policy.get("max_target_length", 200):
            raise PolicyError("Tool target is too long.")
        if any(ch in target for ch in "\r\n\t"):
            raise PolicyError("Tool target cannot contain control characters.")
        if self.tools[tool_name].category == "network":
            self.validate_network_target(target)

    def validate_network_target(self, target):
        """
        Enforce the allowed_domains list from policy.json.

        This is deliberately conservative. Only exact allowed domains or their
        subdomains pass. For example, "localhost" passes if listed, and
        "host.testlab.local" passes if "testlab.local" is listed.
        """
        allowed_domains = self.policy.get("allowed_domains", [])
        if not allowed_domains:
            raise PolicyError("No network targets are allowed by policy.")

        normalized_target = target.strip().lower().rstrip(".")
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,252}", normalized_target):
            raise PolicyError("Network target must be a plain hostname or domain.")
        if ".." in normalized_target:
            raise PolicyError("Network target cannot contain empty domain labels.")

        for domain in allowed_domains:
            normalized_domain = domain.lower().rstrip(".")
            if normalized_target == normalized_domain:
                return
            if normalized_target.endswith(f".{normalized_domain}"):
                return

        raise PolicyError(
            f"Network target '{target}' is not listed in allowed_domains."
        )

    def ping(self, target, memory):
        """Run the registered ping tool."""
        command = ping_command(target)
        return run_command(command)

    def nslookup(self, target, memory):
        """Run the registered DNS lookup tool."""
        return run_command(["nslookup", target])

    def report(self, target, memory):
        """
        Generate a markdown report from recent tool results.

        Reports are intentionally local files. They let the user inspect what
        happened without sending data anywhere.
        """
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        title = target.strip() or "Agent Hart Report"
        slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in title).strip("-")
        slug = slug or "agent-hart-report"
        path = self.reports_dir / f"{slug}.md"

        lines = [
            f"# {title}",
            "",
            "## Recent Tool Results",
            "",
        ]
        recent_results = memory.recent_tool_results(limit=10)
        if not recent_results:
            lines.append("No tool results have been saved yet.")
        else:
            for result in recent_results:
                lines.extend(
                    [
                        f"### {result['tool']} -> {result['target']}",
                        f"- Status: {result['status']}",
                        f"- Created: {result['created_at']}",
                        "",
                        "```text",
                        result["output"].strip(),
                        "```",
                        "",
                    ]
                )

        path.write_text("\n".join(lines), encoding="utf-8")
        return f"Report generated: {path}"


def ping_command(target):
    """Return the correct ping command for Windows, macOS, or Linux."""
    system = platform.system().lower()
    if system == "windows":
        return ["ping", "-n", "4", target]
    return ["ping", "-c", "4", target]


def run_command(command):
    """
    Execute a prebuilt command safely.

    Notice that user input is never passed through shell=True. The command is a
    list like ["ping", "-n", "4", "localhost"], which avoids shell parsing and
    blocks tricks such as adding "& delete something" to the target.
    """
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    output = completed.stdout.strip() or completed.stderr.strip()
    if completed.returncode == 0:
        return output
    return f"Command exited with code {completed.returncode}.\n{output}"
