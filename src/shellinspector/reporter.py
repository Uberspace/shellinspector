import sys
import os
from turtle import color

from termcolor import colored

from shellinspector.runner import RunnerEvent


def print_with_prefix(prefix, text, color):
    print(colored(prefix, "light_grey"))
    for line in text.splitlines():
        print(colored(f"{' ' * 3} {line.strip()}", color))


def reset_line():
    if "TERM" in os.environ:
        sys.stdout.write("\033[2K\033[1G")
    else:
        sys.stdout.write("\n")


def print_runner_event(event, cmd, **kwargs):
    if event == RunnerEvent.COMMAND_STARTING:
        print(colored(f"RUN  {cmd.line}", "light_grey"), end="")
        sys.stdout.flush()
    elif event == RunnerEvent.COMMAND_COMPLETED:
        reset_line()
    elif event == RunnerEvent.ERROR:
        print(colored(f"EROR {cmd.line}", "red"))
        print(colored(kwargs["message"], "red"))
        print_with_prefix("output before giving up: ", kwargs["actual"], "red")
    elif event == RunnerEvent.COMMAND_PASSED:
        print(colored(f"PASS {cmd.line}", "green"))
    elif event == RunnerEvent.COMMAND_FAILED:
        print(colored(f"FAIL {cmd.line}", "red"))
        if "returncode" in kwargs["reasons"]:
            print(colored(f"  command failed", "red"))
            print(colored("    expected: 0", "light_grey"))
            print(colored(f"    actual:   {kwargs['returncode']}", "light_grey"))
        if "output" in kwargs["reasons"]:
            print(colored(f"  output did not match", "red"))
            print_with_prefix("    expected: ", cmd.expected, "light_grey")
            if kwargs["actual"]:
                print_with_prefix("    actual: ", kwargs["actual"], "white")
            else:
                print_with_prefix("    actual: (no output)", "", "white")
