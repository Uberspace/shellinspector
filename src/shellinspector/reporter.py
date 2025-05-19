import logging
import os
import sys
from pathlib import Path

from termcolor import colored

from shellinspector.logging import get_logger
from shellinspector.runner import RunnerEvent

LOGGER = get_logger(Path(__file__).name)


class ConsoleReporter:
    def __init__(self):
        self.has_unfinished_line = False

    def print_indented(self, prefix, text, color):
        if not text:
            prefix += " (none)"
        print(colored(prefix, "light_grey"))
        for line in text.splitlines():
            print(colored(f"{' ' * 3} {line.strip()}", color))

    def reset_line(self):
        if "TERM" in os.environ:
            sys.stdout.write("\033[2K\033[1G")
        else:
            sys.stdout.write("\n")

    def print(self, *args, **kwargs):
        if kwargs.get("end", None) == "":
            self.has_unfinished_line = True
        elif self.has_unfinished_line:
            self.reset_line()

        print(*args, **kwargs)

        if self.has_unfinished_line:
            sys.stdout.flush()

    def __call__(self, event, cmd, **kwargs):
        if "env" in kwargs:
            line = cmd.get_line_with_variables(kwargs["env"])
        elif cmd:
            line = getattr(cmd, "line", None)

        if event == RunnerEvent.COMMAND_STARTING:
            if logging.root.level > logging.DEBUG:
                end = ""
            else:
                end = "\n"
            self.print(
                colored(f"[{cmd.source_line_no_zeroed}] RUN  {line}", "light_grey"),
                end=end,
            )
        elif event == RunnerEvent.ERROR:
            self.print(colored(f"[{cmd.source_line_no_zeroed}] ERR  {line}", "red"))
            self.print(colored("  " + kwargs["message"], "red"))
            self.print_indented("  output before giving up:", kwargs["actual"], "red")
        elif event == RunnerEvent.COMMAND_PASSED:
            self.print(colored(f"[{cmd.source_line_no_zeroed}] PASS {line}", "green"))
        elif event == RunnerEvent.COMMAND_FAILED:
            self.print(colored(f"[{cmd.source_line_no_zeroed}] FAIL {line}", "red"))
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
                self.print_indented("    expected:", cmd.expected, "light_grey")
                self.print_indented("    actual:", kwargs["actual"], "white")
