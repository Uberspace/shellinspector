#!/usr/bin/env python3

import ast
import dataclasses
import enum
import logging
import os
import re
from contextlib import contextmanager
from pathlib import Path

from shellinspector.logging import get_logger
from shellinspector.parser import AssertMode
from shellinspector.parser import Command
from shellinspector.parser import ExecutionMode
from shellinspector.parser import FixtureScope
from shellinspector.parser import Specfile
from shellinspector.tmux_shell import TimeoutException
from shellinspector.tmux_shell import TmuxShell

LOGGER = get_logger(Path(__file__).name)


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


class RunnerEvent(enum.Enum):
    COMMAND_STARTING = enum.auto()
    COMMAND_COMPLETED = enum.auto()
    COMMAND_PASSED = enum.auto()
    COMMAND_FAILED = enum.auto()
    RUN_STARTING = enum.auto()
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

    def close_all_sessions(self):
        for session in self.sessions.values():
            session.close()
        self.sessions.clear()

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

        verbose = logging.root.level == logging.DEBUG

        with disable_color():
            if cmd.host == "local":
                LOGGER.debug("new local tmux shell session")
                session = TmuxShell(timeout=timeout_seconds, verbose=verbose)
            else:
                LOGGER.debug("connecting via SSH (tmux): %s", self.ssh_config)
                session = TmuxShell(
                    timeout=timeout_seconds,
                    verbose=verbose,
                    server=self.ssh_config["server"],
                    port=self.ssh_config["port"],
                    username=cmd.user,
                    ssh_key=self.ssh_config.get("ssh_key"),
                )
            session.login()

        self.sessions[key] = session
        return session

    def _get_root_session(self, timeout_seconds):
        return self._get_session(
            Command(
                ExecutionMode.ROOT,
                "",
                "root",
                None,
                "remote",
                AssertMode.LITERAL,
                "",
                "",
                0,
                "",
                False,
                False,
                None,
            ),
            timeout_seconds,
        )[0]

    def _get_session(self, cmd, timeout_seconds):
        """
        Create or reuse a TmuxShell session used to run the given command.

            session = _get_session(cmd)
            output = session.run_command("echo a")
            assert output == "a"

        If cmd.host is "local", this opens a shell session as the current user
        on the current machine. Username and port are ignored. If server is
        remote, this uses the ssh(1) command to establish a connection to the
        server given in __init__.
        """

        key = self._get_session_key(cmd)

        if key not in self.sessions:
            # connect, if there is no session
            self.sessions[key] = self._make_session(key, cmd, timeout_seconds)
            created = True
        elif self.sessions[key].closed:
            # destroy and reconnect, if there is a broken session
            LOGGER.debug("closing failed session: %s", key)
            self._close_session(cmd)
            self.sessions[key] = self._make_session(key, cmd, timeout_seconds)
            created = True
        else:
            # reuse, if we're already connected
            LOGGER.debug("reusing session: %s", key)
            created = False

        return self.sessions[key], created

    def add_reporter(self, reporter):
        self.reporters.append(reporter)

    def report(self, event, cmd, kwargs):
        for reporter in self.reporters:
            reporter(event, cmd, **kwargs)

    def _check_result(self, cmd, command_output, returncode, env):
        expected = cmd.get_expected_with_vars(env)
        if cmd.assert_mode == AssertMode.LITERAL:
            output_matches = command_output.strip("\r\n") == expected
        elif cmd.assert_mode == AssertMode.REGEX:
            output_matches = re.search(expected, command_output, re.MULTILINE)
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
                    "env": env,
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
                    "env": env,
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

        return self._check_result(
            cmd,
            command_output,
            session.get_returncode(),
            session.get_environment(),
        )

    def run(self, specfile: Specfile, close_sessions=True):
        self.report(RunnerEvent.RUN_STARTING, None, {})

        try:
            if (
                specfile.fixture_specfile_pre
                and specfile.fixture_scope == FixtureScope.FILE
            ):
                pre_success = self.run(
                    specfile.fixture_specfile_pre, close_sessions=False
                )
                if not pre_success:
                    return False

                si_user = None
                for session in self.sessions.values():
                    try:
                        si_user = session.get_environment()["SI_USER"]
                        break
                    except Exception:
                        pass

                if si_user:
                    specfile.environment["SI_USER"] = si_user

                    for session in self.sessions.values():
                        session.set_environment({"SI_USER": si_user})

            for cmd in specfile.commands:
                self.report(RunnerEvent.COMMAND_STARTING, cmd, {})

                if cmd.user is None and cmd.host == "remote":
                    root_env = self._get_root_session(
                        specfile.settings.timeout_seconds
                    ).get_environment()

                    try:
                        cmd.user = root_env["SI_USER"]
                    except LookupError:
                        self.report(
                            RunnerEvent.COMMAND_FAILED,
                            cmd,
                            {
                                "message": f"Could not open session: no user was specified and $SI_USER is unset. Found env: {root_env}",
                                "reasons": [],
                            },
                        )
                        self.report(RunnerEvent.RUN_FAILED, None, {})
                        return False

                try:
                    session, session_created = self._get_session(
                        cmd, specfile.settings.timeout_seconds
                    )
                except Exception as ex:
                    self.report(
                        RunnerEvent.COMMAND_FAILED,
                        cmd,
                        {
                            "message": f"Could not open session: {str(ex)}",
                            "reasons": [],
                        },
                    )
                    self.report(RunnerEvent.RUN_FAILED, None, {})
                    return False

                if session_created:
                    session.set_environment(specfile.environment)
                    session.set_environment(self.context)

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
                            RunnerEvent.COMMAND_FAILED,
                            cmd,
                            {"message": result, "reasons": []},
                        )
                        self.report(RunnerEvent.RUN_FAILED, None, {})

                        if (
                            specfile.fixture_specfile_post
                            and specfile.fixture_scope == FixtureScope.FILE
                        ):
                            self.run(
                                specfile.fixture_specfile_post, close_sessions=False
                            )

                        return False
                else:
                    if cmd.command == "logout":
                        self._close_session(cmd)
                        self.report(
                            RunnerEvent.COMMAND_PASSED,
                            cmd,
                            {"returncode": 0, "actual": ""},
                        )
                        continue

                    if not self._run_command(session, cmd):
                        self.report(RunnerEvent.RUN_FAILED, None, {})

                        if (
                            specfile.fixture_specfile_post
                            and specfile.fixture_scope == FixtureScope.FILE
                        ):
                            self.run(
                                specfile.fixture_specfile_post, close_sessions=False
                            )

                        return False

            if (
                specfile.fixture_specfile_post
                and specfile.fixture_scope == FixtureScope.FILE
            ):
                post_success = self.run(
                    specfile.fixture_specfile_post, close_sessions=False
                )
                if not post_success:
                    return False

        finally:
            if close_sessions:
                self.close_all_sessions()

        self.report(RunnerEvent.RUN_SUCCEEDED, None, {})

        return True
