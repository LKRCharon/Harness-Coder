from __future__ import annotations

from dataclasses import dataclass


ACTIVE_RUN_READ_ONLY_COMMANDS = frozenset({"help", "status", "trace"})


@dataclass(frozen=True, slots=True)
class RunControlDecision:
    allowed: bool
    status: str
    message: str
    reason: str | None = None


class RunControlPlane:
    """Shared run-control decisions for CLI, TUI, and eval entrypoints."""

    def __init__(
        self,
        active_run_read_only_commands: frozenset[str] = ACTIVE_RUN_READ_ONLY_COMMANDS,
    ) -> None:
        self.active_run_read_only_commands = active_run_read_only_commands

    def start_run(self, active_run: bool) -> RunControlDecision:
        if not active_run:
            return RunControlDecision(allowed=True, status="ready", message="")
        return RunControlDecision(
            allowed=False,
            status="run blocked: active run",
            message="Agent is still running. Wait for it to finish.",
            reason="active_run",
        )

    def request_exit(self, active_run: bool) -> RunControlDecision:
        if not active_run:
            return RunControlDecision(allowed=True, status="ready", message="")
        return RunControlDecision(
            allowed=False,
            status="exit blocked: active run",
            message=(
                "Agent is still running. Wait for it to finish before exiting. "
                "Cancellation is not implemented yet."
            ),
            reason="active_run",
        )

    def slash_command(self, command: str, active_run: bool) -> RunControlDecision:
        normalized = normalize_slash_command(command)
        if not active_run or normalized in self.active_run_read_only_commands:
            return RunControlDecision(allowed=True, status="ready", message="")

        return RunControlDecision(
            allowed=False,
            status=f"/{normalized} blocked: active run",
            message=(
                f"/{normalized} is blocked while the agent is running. "
                f"Allowed commands: {self.allowed_commands_label()}."
            ),
            reason="active_run",
        )

    def allowed_commands_label(self) -> str:
        return ", ".join(
            f"/{command}" for command in sorted(self.active_run_read_only_commands)
        )


def normalize_slash_command(command: str) -> str:
    return command[1:] if command.startswith("/") else command
