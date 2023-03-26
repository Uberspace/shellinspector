import logging
import os
import sys
from pathlib import Path

from termcolor import colored

from shellinspector.runner import RunnerEvent

LOGGER = logging.getLogger(Path(__file__).name)


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
        if event == RunnerEvent.COMMAND_STARTING:
            if logging.root.level > logging.DEBUG:
                end = ""
            else:
                end = "\n"
            self.print(colored(f"RUN  {cmd.line}", "light_grey"), end=end)
        elif event == RunnerEvent.ERROR:
            self.print(colored(f"ERR  {cmd.line}", "red"))
            self.print(colored("  " + kwargs["message"], "red"))
            self.print_indented("  output before giving up:", kwargs["actual"], "red")
        elif event == RunnerEvent.COMMAND_PASSED:
            self.print(colored(f"PASS {cmd.line}", "green"))
        elif event == RunnerEvent.COMMAND_FAILED:
            self.print(colored(f"FAIL {cmd.line}", "red"))
            if "returncode" in kwargs["reasons"]:
                rc = kwargs["returncode"]
                self.print(colored("  command failed", "red"))
                self.print(colored("    expected: 0", "light_grey"))
                self.print(colored(f"    actual:   {rc}", "light_grey"))
            if "output" in kwargs["reasons"]:
                self.print(colored("  output did not match", "red"))
                self.print_indented("    expected:", cmd.expected, "light_grey")
                self.print_indented("    actual:", kwargs["actual"], "white")
