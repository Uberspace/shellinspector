#!/usr/bin/env python3

import enum
import logging
import os
import re
import shlex
import sys
from contextlib import contextmanager
from pathlib import Path

from pexpect import pxssh
from pexpect import spawn
from pexpect.pxssh import ExceptionPxssh

from shellinspector.parser import AssertMode

LOGGER = logging.getLogger(Path(__file__).name)


class RemoteShell(pxssh.pxssh):
    def __init__(self, *args, **kwargs):
        # ignoring the echoed commands doesn't seem to work for local commands
        # just disabling echo is easier than debugging this.
        kwargs["echo"] = False
        super().__init__(*args, **kwargs)

        self.push_depth = 0

    def set_environment(self, context):
        for k, v in context.items():
            self.sendline(f"export {k}='{shlex.quote(str(v))}'")
            assert self.prompt()

    def push_state(self):
        self.push_depth += 1

        # launch a child shell so we can easily reset the environment variables
        self.sendline("bash")

        # new shell means new prompt, so reconfigure the prompt recognition
        self.set_unique_prompt()
        # trigger a fresh prompt so .prompt() is faster
        self.sendline("")
        assert self.prompt()

        self.sendline(f"export SHELLINSPECTOR_PROMPT_STATE={self.push_depth}")
        assert self.prompt()

    def pop_state(self):
        if self.closed:
            raise Exception("Session is closed")

        self.sendline("echo $SHELLINSPECTOR_PROMPT_STATE")
        assert self.prompt()
        out = self.before.decode().strip()

        if not out or int(out) != self.push_depth:
            raise Exception(
                "Test shell was exited, check if your test script contains an exit command"
            )

        self.sendline("exit")
        assert self.prompt()

        self.push_depth -= 1


class LocalShell(RemoteShell):
    """Like RemoteShell/pxssh, but uses a local shell instead of a remote ssh one."""

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
    else:
        old_term = None

    os.environ["TERM"] = "dumb"  # disable any color ouput in SSH

    yield

    if old_term is not None:
        os.environ["TERM"] = old_term
    else:
        del os.environ["TERM"]


def get_ssh_session(ssh_config):
    with disable_color():
        shell = RemoteShell(timeout=5)
        shell.login(**ssh_config)
        return shell


def get_localshell():
    with disable_color():
        shell = LocalShell(timeout=5)
        shell.login()
        return shell


class RunnerEvent(enum.Enum):
    COMMAND_STARTING = enum.auto()
    COMMAND_COMPLETED = enum.auto()
    COMMAND_PASSED = enum.auto()
    COMMAND_FAILED = enum.auto()
    RUN_SUCCEEDED = enum.auto()
    RUN_FAILED = enum.auto()
    ERROR = enum.auto()


class ShellRunner:
    def __init__(self, ssh_config, context):
        self.sessions = {}
        self.reporters = []
        self.ssh_config = ssh_config
        self.context = context

    def _get_session_key(self, cmd):
        if cmd.host == "local":
            # ignore username, if we're operating locally
            return (
                "local",
                cmd.session_name,
            )
        elif cmd.host == "remote":
            return (
                self.ssh_config["server"],
                self.ssh_config["port"],
                cmd.user,
                cmd.session_name,
            )
        else:
            raise NotImplementedError(f"Unknown host: {cmd.host}")

    def _close_session(self, cmd):
        key = self._get_session_key(cmd)

        if key in self.sessions:
            LOGGER.debug("closing session: %s", key)
            self.sessions[key].close()
            del self.sessions[key]
        else:
            raise Exception(
                f"Session could not be closed, because it doesn't exist, command: {cmd}"
            )

    def _get_session(self, cmd):
        """
        Create or reuse a shell session used to run the given command.

            session = _get_session(cmd)
            session.sendline("echo a")
            session.prompt()
            assert session.before.decode() == "a"

        If cmd.host is "local", this opens a shell session as the current user
        on the current machine. Username and port are ignored. If server is
        remote, this uses the ssh(1) command to establish a connection to the
        server given in __init__.

        It also makes sure that the environment is as clean as possible, so you
        can use environment variables freely.

        The yielded session object is a `pexpect.pxssh.pxssh`:
        https://pexpect.readthedocs.io/en/stable/api/pxssh.html#pxssh-class
        """

        key = self._get_session_key(cmd)

        if key not in self.sessions:
            # connect, if there is no session
            LOGGER.debug("creating session: %s", key)
            if cmd.host == "local":
                LOGGER.debug("new local shell session")
                session = self.sessions[key] = get_localshell()
            else:
                ssh_config = {
                    **self.ssh_config,
                    "username": cmd.user,
                    "server": self.ssh_config["server"],
                    "port": self.ssh_config["port"],
                }
                LOGGER.debug("connecting via SSH: %s", ssh_config)
                session = self.sessions[key] = get_ssh_session(ssh_config)

            if logging.root.level == logging.DEBUG:
                # use .buffer here, because pexpect wants to write bytes, not strs
                session.logfile = sys.stdout.buffer
        else:
            # reuse, if we're already connected
            LOGGER.debug("reusing session: %s", key)
            session = self.sessions[key]

        return session

    def add_reporter(self, reporter):
        self.reporters.append(reporter)

    def report(self, event, cmd, kwargs):
        for reporter in self.reporters:
            reporter(event, cmd, **kwargs)

    def _check_result(self, cmd, command_output, returncode):
        if cmd.assert_mode == AssertMode.LITERAL:
            output_matches = command_output == cmd.expected
        elif cmd.assert_mode == AssertMode.REGEX:
            output_matches = re.search(cmd.expected, command_output, re.MULTILINE)
        elif cmd.assert_mode == AssertMode.IGNORE:
            output_matches = True
        else:
            raise NotImplementedError(f"Unknown assert_mode: {cmd.assert_mode}")

        if output_matches and returncode == 0:
            self.report(
                RunnerEvent.COMMAND_PASSED,
                cmd,
                {
                    "returncode": returncode,
                    "actual": command_output,
                },
            )

            return True
        else:
            reasons = set()

            if returncode != 0:
                reasons.add("returncode")
            if not output_matches:
                reasons.add("output")

            self.report(
                RunnerEvent.COMMAND_FAILED,
                cmd,
                {
                    "reasons": reasons,
                    "returncode": returncode,
                    "actual": command_output,
                },
            )

            return False

    def _run_command(self, session, cmd):
        def sendline(line, prompt_cause):
            session.sendline(line)
            found_prompt = session.prompt()
            actual_output = session.before.decode()
            actual_output = actual_output.replace("\r\n", "\n")

            if found_prompt:
                return actual_output
            else:
                session.close()
                self.report(
                    RunnerEvent.ERROR,
                    cmd,
                    {
                        "message": "could not find prompt for " + prompt_cause,
                        "actual": actual_output,
                    },
                )
                return False

        if (command_output := sendline(cmd.command, "command")) is False:
            return False

        if (rc_output := sendline("echo $?", "return code")) is False:
            return False

        return self._check_result(cmd, command_output, int(rc_output))

    def run(self, specfile):
        used_sessions = set()

        try:
            for cmd in specfile.commands:
                self.report(RunnerEvent.COMMAND_STARTING, cmd, {})

                session = self._get_session(cmd)

                if cmd.command == "logout":
                    self._close_session(cmd)
                    used_sessions.remove(session)
                    self.report(
                        RunnerEvent.COMMAND_PASSED,
                        cmd,
                        {"returncode": 0, "actual": ""},
                    )
                    continue

                if session not in used_sessions:
                    used_sessions.add(session)
                    session.set_environment(specfile.environment)
                    session.set_environment(self.context)
                    session.push_state()

                if not self._run_command(session, cmd):
                    self.report(RunnerEvent.RUN_FAILED, None, {})
                    return False
        finally:
            for session in used_sessions:
                session.pop_state()

        self.report(RunnerEvent.RUN_SUCCEEDED, None, {})

        return True
