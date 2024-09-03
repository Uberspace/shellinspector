#!/usr/bin/env python3

import ast
import dataclasses
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
from shellinspector.parser import ExecutionMode
from shellinspector.parser import Specfile

LOGGER = logging.getLogger(Path(__file__).name)


class TimeoutException(Exception):
    def __init__(self, output_so_far: str):
        self.output_so_far = output_so_far
        super().__init__()


@dataclasses.dataclass
class ShellinspectorPyContext:
    applied_example: dict
    env: dict


def run_in_file(filename: Path, si_context: dict, code: str):
    """
    Load the python code within `filename` and run the given python code within.
    Additionally, set all values in si_context as global variables. The code
    within `code` must be a single function call. Its return value will be
    returned by this function.
    """
    with open(filename) as f:
        node = ast.parse(f.read(), filename)

    call_ast = ast.parse(code)

    if len(call_ast.body) != 1:
        raise NotImplementedError(
            f"Only one and exactly one function call is supported, you provided {len(call_ast.body)} statements"
        )

    call = call_ast.body[0].value

    if not isinstance(call, ast.Call):
        raise NotImplementedError(
            f"Only function calls are supported, you provided {call}"
        )

    call.args.insert(0, ast.Name(id="context", ctx=ast.Load()))

    # add function call for the given function_name and args,
    # also add an extra argument in front passing the given si_context.
    call = ast.Assign(
        targets=[ast.Name(id="_return_value", ctx=ast.Store())],
        value=call,
    )

    node.body.append(call)
    ast.fix_missing_locations(node)

    globalz = {
        "context": si_context,
    }

    obj = compile(node, filename=filename, mode="exec")
    exec(obj, globalz, globalz)

    return globalz["_return_value"]


class RemoteShell(pxssh.pxssh):
    def __init__(self, *args, **kwargs):
        # ignoring the echoed commands doesn't seem to work for local commands
        # just disabling echo is easier than debugging this.
        kwargs["echo"] = False
        super().__init__(*args, **kwargs)

        self.push_depth = 0

    def run_command(self, line):
        self.sendline(line)
        found_prompt = self.prompt()
        actual_output = self.before.decode()
        actual_output = actual_output.replace("\r\n", "\n")

        if found_prompt:
            return actual_output
        else:
            self.close()
            raise TimeoutException(actual_output)

    def set_environment(self, context):
        for k, v in context.items():
            self.sendline(f"export {k}={shlex.quote(str(v))}")
            assert self.prompt()

    def get_environment(self):
        output = self.run_command("export")

        env = {}

        for line in output.splitlines():
            line = line.removeprefix("export ")
            line = line.removeprefix("declare -x ")
            k, _, v = line.partition("=")

            if not v:
                continue

            env[k] = " ".join(shlex.split(v))

        return env

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
            return

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


def get_ssh_session(ssh_config, timeout_seconds):
    with disable_color():
        shell = RemoteShell(timeout=timeout_seconds)
        shell.login(**ssh_config)
        return shell


def get_localshell(timeout_seconds):
    with disable_color():
        shell = LocalShell(timeout=timeout_seconds)
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

    def _make_session(self, key, cmd, timeout_seconds):
        LOGGER.debug("creating session: %s", key)
        if cmd.host == "local":
            LOGGER.debug("new local shell session")
            session = self.sessions[key] = get_localshell(timeout_seconds)
        else:
            ssh_config = {
                **self.ssh_config,
                "username": cmd.user,
                "server": self.ssh_config["server"],
                "port": self.ssh_config["port"],
            }
            LOGGER.debug("connecting via SSH: %s", ssh_config)
            session = get_ssh_session(ssh_config, timeout_seconds)

        if logging.root.level == logging.DEBUG:
            # use .buffer here, because pexpect wants to write bytes, not strs
            session.logfile = sys.stdout.buffer

        return session

    def _get_session(self, cmd, timeout_seconds):
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
            self.sessions[key] = self._make_session(key, cmd, timeout_seconds)
        elif self.sessions[key].closed:
            # destroy and reconnect, if there is a broken session
            LOGGER.debug("closing failed session: %s", key)
            self._close_session(cmd)
            self.sessions[key] = self._make_session(key, cmd, timeout_seconds)
        else:
            # reuse, if we're already connected
            LOGGER.debug("reusing session: %s", key)

        return self.sessions[key]

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
        try:
            command_output = session.run_command(cmd.command)
        except TimeoutException as ex:
            self.report(
                RunnerEvent.ERROR,
                cmd,
                {
                    "message": "timeout, could not find prompt for command",
                    "actual": ex.output_so_far,
                },
            )
            return False

        try:
            rc_output = session.run_command("echo $?")
        except TimeoutException as ex:
            self.report(
                RunnerEvent.ERROR,
                cmd,
                {
                    "message": "timeout, could not find prompt for return code",
                    "actual": ex.output_so_far,
                },
            )
            return False

        rc_output = int(rc_output)

        return self._check_result(cmd, command_output, int(rc_output))

    def run(self, specfile: Specfile, outer_used_sessions=None):
        if outer_used_sessions:
            used_sessions = outer_used_sessions
        else:
            used_sessions = set()

        try:
            if specfile.fixture_specfile_pre:
                self.run(specfile.fixture_specfile_pre, used_sessions)

            for cmd in specfile.commands:
                self.report(RunnerEvent.COMMAND_STARTING, cmd, {})
                session = self._get_session(cmd, specfile.settings.timeout_seconds)

                if cmd.execution_mode == ExecutionMode.PYTHON:
                    ctx = ShellinspectorPyContext({}, {})
                    filename = specfile.path.with_suffix(".ispec.py")
                    ctx.env = session.get_environment()
                    original_env = ctx.env.copy()

                    try:
                        result = run_in_file(filename, ctx, cmd.command)
                    except Exception as ex:
                        LOGGER.exception(f"could not run python command: {cmd.command}")
                        result = str(ex)

                    if result is True:
                        changed_env = dict(ctx.env.items() - original_env.items())
                        LOGGER.info(
                            "setting changed env vars: "
                            + " ".join(f"{k}='{v}'" for k, v in changed_env.items())
                        )
                        session.set_environment(changed_env)
                        self.report(RunnerEvent.COMMAND_PASSED, cmd, {})
                    else:
                        self.report(
                            RunnerEvent.COMMAND_FAILED, None, {"message": result}
                        )
                        self.report(RunnerEvent.RUN_FAILED, None, {})

                        if specfile.fixture_specfile_post:
                            self.run(specfile.fixture_specfile_post, used_sessions)

                        return False
                else:
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

                        if specfile.fixture_specfile_post:
                            self.run(specfile.fixture_specfile_post, used_sessions)

                        return False

            if specfile.fixture_specfile_post:
                self.run(specfile.fixture_specfile_post, used_sessions)

        finally:
            if outer_used_sessions is None:
                for session in used_sessions:
                    session.pop_state()

        self.report(RunnerEvent.RUN_SUCCEEDED, None, {})

        return True
