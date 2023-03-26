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


def get_ssh_session(ssh_config):
    with disable_color():
        s = pxssh.pxssh(echo=False, timeout=5)
        s.login(**ssh_config)
        return s


def get_localshell():
    with disable_color():
        shell = localshell(timeout=5)
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
        self.ssh_config = ssh_config
        self.context = context

    @contextmanager
    def _get_session(self, cmd):
        """
        Create or reuse a shell session used to run the given command.

            with _get_session(cmd) as session:
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

        if cmd.host == "local":
            # ignore username, if we're operating locally
            key = ("local", cmd.session_name)
        elif cmd.host == "remote":
            key = (
                self.ssh_config["server"],
                self.ssh_config["port"],
                cmd.user,
                cmd.session_name,
            )

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

        # launch a child shell so we can easily reset the environment variables
        session.sendline("bash")

        # new shell means new prompt, so reconfigure the prompt recognition
        session.set_unique_prompt()
        # trigger a fresh prompt so .prompt() is faster
        session.sendline("")
        assert session.prompt()

        try:
            # do the actual work on the caller's side
            yield session
        finally:
            if session.closed:
                # caller closed or crashed the session,
                # forget it so it will be reinitialized if we need it again
                del self.sessions[key]
            else:
                # session is still alive, exit the extra shell we started
                # earlier to reset the environment variables
                session.sendline("exit")
                assert session.prompt()

    def set_environment(self, session, context):
        for k, v in context.items():
            session.sendline(f"export {k}='{shlex.quote(str(v))}'")
            assert session.prompt()

    def run(self, commands):
        for cmd in commands:
            yield RunnerEvent.COMMAND_STARTING, cmd, {}

            with self._get_session(cmd) as session:
                self.set_environment(session, self.context)

                session.sendline(cmd.command)
                found_prompt = session.prompt()
                actual_output = session.before.decode().strip()

                yield RunnerEvent.COMMAND_COMPLETED, cmd, {}

                if not found_prompt:
                    yield RunnerEvent.ERROR, cmd, {
                        "message": "could not find prompt for command",
                        "actual": actual_output,
                    }
                    session.close()
                    break

                session.sendline("echo $?")
                found_prompt = session.prompt()
                actual_rc = session.before.decode().strip()

                if not found_prompt:
                    yield RunnerEvent.ERROR, cmd, {
                        "message": "could not find prompt for return code",
                        "actual": actual_rc,
                    }
                    session.close()
                    break

                returncode = int(actual_rc)

            if cmd.assert_mode == AssertMode.LITERAL:
                output_matches = actual_output == cmd.expected.strip()
            elif cmd.assert_mode == AssertMode.REGEX:
                output_matches = re.search(
                    cmd.expected.strip(), actual_output, re.MULTILINE
                )
            elif cmd.assert_mode == AssertMode.IGNORE:
                output_matches = True
            else:
                raise NotImplementedError(f"Unknown assert_mode: {cmd.assert_mode}")

            if output_matches and returncode == 0:
                yield RunnerEvent.COMMAND_PASSED, cmd, {
                    "returncode": returncode,
                    "actual": actual_output,
                }
            else:
                reasons = []

                if returncode != 0:
                    reasons.append("returncode")
                if not output_matches:
                    reasons.append("output")

                yield RunnerEvent.COMMAND_FAILED, cmd, {
                    "reasons": reasons,
                    "returncode": returncode,
                    "actual": actual_output,
                }
                break
        else:
            yield RunnerEvent.RUN_FAILED, None, {}
            return

        yield RunnerEvent.RUN_SUCCEEDED, None, {}
