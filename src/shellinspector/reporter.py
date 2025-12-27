import logging
import os
import sys
from pathlib import Path

from termcolor import colored

from shellinspector.logging import get_logger
from shellinspector.runner import RunnerEvent

LOGGER = get_logger(Path(__file__).name)


class ConsoleReporter:
    def __init__(self, only_show_failed_runs=False):
        self.has_unfinished_line = False
        self.only_show_failed_runs = only_show_failed_runs
        self.buffer = []

    def print_indented(self, prefix, text, color):
        if not text:
            prefix += " (none)"
        self.print(colored(prefix, "light_grey"))
        for line in text.splitlines():
            self.print(colored(f"{' ' * 3} {line.strip()}", color))

    def reset_line(self):
        if "TERM" in os.environ:
            sys.stdout.write("\033[2K\033[1G")
        else:
            sys.stdout.write("\n")

    def print(self, *args, new_line=True):
        end = "\n"
        if not new_line:
            self.has_unfinished_line = True
            end = ""
        elif self.has_unfinished_line:
            self.reset_line()

        if self.only_show_failed_runs:
            if end:
                self.buffer.append(args)
        else:
            print(*args, end=end)

        if self.has_unfinished_line:
            sys.stdout.flush()

    def _print_buffer(self):
        for line in self.buffer:
            print(*line)

        self.buffer = []

    def __call__(self, event, cmd, **kwargs):
        if "env" in kwargs:
            line = cmd.get_line_with_variables(kwargs["env"])
        elif cmd:
            line = getattr(cmd, "line", None)

        if cmd:
            if cmd.specfile and cmd.specfile.is_fixture:
                prefix = f"[F{cmd.source_line_no:2}]"
            else:
                prefix = f"[{cmd.source_line_no:3}]"
        else:
            prefix = ""

        if event == RunnerEvent.COMMAND_STARTING:
            self.print(
                colored(f"{prefix} RUN  {line}", "light_grey"),
                new_line=(logging.root.level <= logging.DEBUG),
            )
        elif event == RunnerEvent.ERROR:
            self.print(colored(f"{prefix} ERR  {line}", "red"))
            self.print(colored("  " + kwargs["message"], "red"))
            self.print_indented("  output before giving up:", kwargs["actual"], "red")
        elif event == RunnerEvent.COMMAND_PASSED:
            self.print(colored(f"{prefix} PASS {line}", "green"))
        elif event == RunnerEvent.COMMAND_FAILED:
            self.print(colored(f"{prefix} FAIL {line}", "red"))
            if "message" in kwargs:
                self.print(colored(f'  {kwargs["message"]}', "red"))
            if "returncode" in kwargs["reasons"]:
                rc = kwargs["returncode"]
                self.print(colored("  command failed", "red"))
                self.print(colored("    expected: 0", "light_grey"))
                self.print(colored(f"    actual:   {rc}", "light_grey"))
                self.print_indented("    output:", kwargs["actual"], "white")
            if "output" in kwargs["reasons"]:
                self.print(colored("  output did not match", "red"))
                self.print_indented(
                    "    expected:",
                    cmd.get_expected_with_vars(kwargs.get("env", {})),
                    "light_grey",
                )
                self.print_indented("    actual:", kwargs["actual"], "white")
        elif event == RunnerEvent.RUN_FAILED:
            self._print_buffer()
        elif event == RunnerEvent.RUN_SUCCEEDED:
            if self.only_show_failed_runs:
                self.buffer = []
                self.print(colored("Success", "green"))
