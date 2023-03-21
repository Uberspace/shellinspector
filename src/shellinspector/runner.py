#!/usr/bin/env python3

import os
import re
import shlex
import sys
from contextlib import contextmanager

from pexpect import pxssh
from pexpect import spawn
from pexpect.pxssh import ExceptionPxssh
from termcolor import colored

from shellinspector.parser import AssertMode


class localshell(pxssh.pxssh):
    """allow to treat local shell sessons as ssh connections, so we can use the same code for both"""

    def __init__(self, *args, **kwargs):
        # ignoring the echoed commands doesn't seem to work for local commands
        # just disabling echo is easier than debugging this.
        kwargs["echo"] = False
        super().__init__(*args, **kwargs)

    def login(
        self,
        sync_original_prompt=True,
        auto_prompt_reset=True,
        sync_multiplier=1,
        *args,
        **kwargs,
    ):
        spawn._spawn(self, "/bin/bash")

        if sync_original_prompt:
            if not self.sync_original_prompt(sync_multiplier):
                self.close()
                raise ExceptionPxssh("could not synchronize with original prompt")

        if auto_prompt_reset:
            if not self.set_unique_prompt():
                self.close()
                raise ExceptionPxssh(
                    "could not set shell prompt "
                    "(received: %r, expected: %r)."
                    % (
                        self.before,
                        self.PROMPT,
                    )
                )

        return True


@contextmanager
def disable_color():
    if "TERM" in os.environ:
        old_term = os.environ["TERM"]
        os.environ["TERM"] = "dumb"  # disable any color ouput in SSH
        yield
        os.environ["TERM"] = old_term
    else:
        yield


def get_ssh_session(sshconfig):
    with disable_color():
        s = pxssh.pxssh(echo=False, timeout=5)
        s.login(**sshconfig)
        return s


def get_localshell():
    with disable_color():
        shell = localshell(timeout=5)
        shell.login()
        return shell


def print_with_prefix(prefix, text, color):
    print(colored(prefix, "light_grey"))
    for line in text.splitlines():
        print(colored(f"{' ' * 3} {line.strip()}", color))


def reset_line():
    if "TERM" in os.environ:
        sys.stdout.write("\033[2K\033[1G")
    else:
        sys.stdout.write("\n")


class ShellRunner:
    def __init__(self):
        self.sessions = {}

    @contextmanager
    def _get_session(self, key, ctx):
        if key not in self.sessions:
            if key[1] == "local":
                self.sessions[(None, "local", None)] = get_localshell()
            else:
                self.sessions[key] = get_ssh_session(
                    {
                        "username": key[0],
                        "server": key[1],
                        "port": key[2],
                    }
                )

        self.sessions[key].sendline("bash")

        self.sessions[key].set_unique_prompt()

        # trigger a fresh prompt to .prompt() is faster
        self.sessions[key].sendline("")
        assert self.sessions[key].prompt()

        for k, v in ctx.items():
            self.sessions[key].sendline(f"export {k}='{shlex.quote(str(v))}'")
            assert self.sessions[key].prompt()

        try:
            yield self.sessions[key]
        finally:
            if self.sessions[key].closed:
                del self.sessions[key]
            else:
                self.sessions[key].sendline("exit")
                assert self.sessions[key].prompt()

    def run(self, commands, sshconfig):
        ctx = {
            "SI_TARGET": sshconfig["server"],
            "SI_TARGET_SSH_USERNAME": sshconfig["username"],
            "SI_TARGET_SSH_PORT": sshconfig["port"],
        }

        remote_session_key = (sshconfig["username"], sshconfig["server"], sshconfig["port"])

        for cmd in commands:
            print(colored(f"RUN  {cmd.line}", "light_grey"), end="")
            sys.stdout.flush()

            if cmd.user is not None or cmd.host is not None:
                if cmd.host == "local":
                    session_key = (None, "local", None)
                elif cmd.host == "remote":
                    session_key = remote_session_key

            with self._get_session(session_key, ctx) as session:
                session.sendline(cmd.command)
                found_prompt = session.prompt()
                actual = session.before.decode().strip()

                reset_line()

                if not found_prompt:
                    print(colored(f"FAIL {cmd.line}", "red"))
                    print(colored("could not find prompt", "red"))
                    print_with_prefix("output before giving up: ", actual, "red")
                    session.close()
                    return False

                session.sendline("echo $?")
                assert session.prompt(), "getting command RC failed"
                returncode = int(session.before.strip())

            if cmd.assert_mode == AssertMode.LITERAL:
                matches = actual == cmd.expected.strip()
            elif cmd.assert_mode == AssertMode.REGEX:
                matches = re.search(cmd.expected.strip(), actual, re.MULTILINE)
            elif cmd.assert_mode == AssertMode.IGNORE:
                matches = True
            else:
                raise NotImplementedError(f"Unknown assert_mode: {cmd.assert_mode}")

            passes = matches and returncode == 0

            if passes:
                print(colored(f"PASS {cmd.line}", "green"))
            else:
                print(colored(f"FAIL {cmd.line}", "red"))
                if returncode != 0:
                    print(colored(f"command failed (RC={returncode})", "red"))
                if not matches:
                    print_with_prefix("expected: ", cmd.expected, "light_grey")
                    print_with_prefix("actual: ", actual, "white")
                return False

        return True
