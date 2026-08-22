import os
from pathlib import Path

import pytest
from pytest_lazyfixture import lazy_fixture

from shellinspector.parser import AssertMode
from shellinspector.parser import Command
from shellinspector.parser import ExecutionMode
from shellinspector.parser import Specfile
from shellinspector.runner import RunnerEvent
from shellinspector.runner import ShellinspectorPyContext
from shellinspector.runner import ShellRunner
from shellinspector.runner import disable_color
from shellinspector.runner import run_in_file
from shellinspector.tmux_shell import TimeoutException
from shellinspector.tmux_shell import TmuxShell


@pytest.fixture
def ssh_key_path():
    path = Path(__file__).parent / "keys/id_ed25519"
    assert path.exists()
    return path


@pytest.fixture
def make_runner():
    def make_runner(ssh_config=None, context=None):
        ssh_config = ssh_config or {}
        context = context or {}

        events = []

        def rep(*args, **kwargs):
            events.append((args, kwargs))

        runner = ShellRunner(ssh_config, context)
        runner.add_reporter(rep)

        return runner, events

    return make_runner


@pytest.fixture
def ssh_config(ssh_key_path):
    return {
        "username": "root",
        "server": "127.0.0.1",
        "port": 2222,
        "ssh_key": ssh_key_path,
    }


def test_disable_color():
    if "TERM" in os.environ:
        old_term = os.environ["TERM"]
        os.environ["TERM"] = "something"
    else:
        old_term = None

    with disable_color():
        assert os.environ["TERM"] == "dumb"

    if old_term is not None:
        assert os.environ["TERM"] == "something"
        os.environ["TERM"] = old_term
    else:
        assert "TERM" not in os.environ


def test_disable_color_no_term():
    if "TERM" in os.environ:
        old_term = os.environ["TERM"]
        del os.environ["TERM"]
    else:
        old_term = None

    assert "TERM" not in os.environ

    with disable_color():
        assert os.environ["TERM"] == "dumb"

    assert "TERM" not in os.environ

    if old_term is not None:
        os.environ["TERM"] = old_term


def test_add_reporter():
    events = []

    def rep(*args, **kwargs):
        events.append((args, kwargs))

    runner = ShellRunner({}, {})
    runner.add_reporter(rep)
    runner.add_reporter(rep)
    runner.report("a", "b", {"c": 1})
    runner.report("a", "b", {"c": 2})

    assert events == [
        (("a", "b"), {"c": 1}),
        (("a", "b"), {"c": 1}),
        (("a", "b"), {"c": 2}),
        (("a", "b"), {"c": 2}),
    ]


@pytest.fixture
def command_local_echo_literal():
    return Command(
        ExecutionMode.USER,
        "echo a",
        None,
        None,
        "local",
        AssertMode.LITERAL,
        "a",
        "/some.ispec",
        1,
        "$ echo a",
        False,
        False,
        None,
    )


@pytest.fixture
def command_local_echo_literal_var():
    return Command(
        ExecutionMode.USER,
        "echo $a",
        None,
        None,
        "local",
        AssertMode.LITERAL,
        "{a}",
        "/some.ispec",
        1,
        "$ echo $a",
        False,
        False,
        None,
    )


@pytest.fixture
def command_local_echo_literal_env_var():
    return Command(
        ExecutionMode.ROOT,
        "echo $something",
        "root",
        None,
        "remote",
        AssertMode.LITERAL,
        "value__",
        "/some.ispec",
        1,
        "$ echo $something",
        False,
        False,
        None,
    )


@pytest.fixture
def command_local_echo_literal_fail():
    return Command(
        ExecutionMode.USER,
        "echo a",
        None,
        None,
        "local",
        AssertMode.LITERAL,
        "a",
        "/some.ispec",
        1,
        "$ echo a",
        False,
        False,
        None,
    )


@pytest.fixture
def command_remote_echo_literal():
    return Command(
        ExecutionMode.ROOT,
        "echo a",
        "root",
        None,
        "remote",
        AssertMode.LITERAL,
        "a",
        "/some.ispec",
        1,
        "$ echo a",
        False,
        False,
        None,
    )


@pytest.fixture
def command_local_echo_regex():
    return Command(
        ExecutionMode.USER,
        "echo aaa11aa",
        None,
        None,
        "local",
        AssertMode.REGEX,
        ".*11.*",
        "/some.ispec",
        1,
        "$ echo a",
        False,
        False,
        None,
    )


@pytest.fixture
def command_local_echo_regex_var():
    return Command(
        ExecutionMode.USER,
        "echo $a",
        None,
        None,
        "local",
        AssertMode.REGEX,
        "[{a}]{1}",
        "/some.ispec",
        1,
        "$ echo $a foo",
        False,
        False,
        None,
    )


@pytest.fixture
def command_local_echo_ignore():
    return Command(
        ExecutionMode.USER,
        "echo a",
        None,
        None,
        "local",
        AssertMode.IGNORE,
        "a",
        "/some.ispec",
        1,
        "$ echo a",
        False,
        False,
        None,
    )


@pytest.mark.parametrize(
    "cmd,args,expected_result,expected_events",
    (
        # LITERAL
        (
            lazy_fixture("command_local_echo_literal_fail"),
            ["a", 0],
            True,
            [
                (
                    RunnerEvent.COMMAND_PASSED,
                    {
                        "returncode": 0,
                        "actual": "a",
                        "env": {"a": "b"},
                    },
                ),
            ],
        ),
        # LITERAL w/ variable
        (
            lazy_fixture("command_local_echo_literal_var"),
            ["b", 0],
            True,
            [
                (
                    RunnerEvent.COMMAND_PASSED,
                    {
                        "returncode": 0,
                        "actual": "b",
                        "env": {"a": "b"},
                    },
                ),
            ],
        ),
        # LITERAL & FAIL-Tests
        (
            lazy_fixture("command_local_echo_literal_fail"),
            ["b", 0],
            False,
            [
                (
                    RunnerEvent.COMMAND_FAILED,
                    {
                        "returncode": 0,
                        "actual": "b",
                        "reasons": {"output"},
                        "env": {"a": "b"},
                    },
                ),
            ],
        ),
        (
            lazy_fixture("command_local_echo_literal_fail"),
            ["a", 1],
            False,
            [
                (
                    RunnerEvent.COMMAND_FAILED,
                    {
                        "returncode": 1,
                        "actual": "a",
                        "reasons": {"returncode"},
                        "env": {"a": "b"},
                    },
                ),
            ],
        ),
        (
            lazy_fixture("command_local_echo_literal_fail"),
            ["b", 1],
            False,
            [
                (
                    RunnerEvent.COMMAND_FAILED,
                    {
                        "returncode": 1,
                        "actual": "b",
                        "reasons": {"output", "returncode"},
                        "env": {"a": "b"},
                    },
                ),
            ],
        ),
        # REGEX
        (
            lazy_fixture("command_local_echo_regex"),
            ["aaa11aa", 0],
            True,
            [
                (
                    RunnerEvent.COMMAND_PASSED,
                    {
                        "returncode": 0,
                        "actual": "aaa11aa",
                        "env": {"a": "b"},
                    },
                ),
            ],
        ),
        # REGEX /w variable
        (
            lazy_fixture("command_local_echo_regex_var"),
            ["b foo", 0],
            True,
            [
                (
                    RunnerEvent.COMMAND_PASSED,
                    {
                        "returncode": 0,
                        "actual": "b foo",
                        "env": {"a": "b"},
                    },
                ),
            ],
        ),
        (
            lazy_fixture("command_local_echo_regex"),
            ["b", 0],
            False,
            [
                (
                    RunnerEvent.COMMAND_FAILED,
                    {
                        "returncode": 0,
                        "actual": "b",
                        "reasons": {"output"},
                        "env": {"a": "b"},
                    },
                ),
            ],
        ),
        # IGNORE
        (
            lazy_fixture("command_local_echo_ignore"),
            ["aaa11aa", 0],
            True,
            [
                (
                    RunnerEvent.COMMAND_PASSED,
                    {
                        "returncode": 0,
                        "actual": "aaa11aa",
                        "env": {"a": "b"},
                    },
                ),
            ],
        ),
        (
            lazy_fixture("command_local_echo_ignore"),
            ["b", 0],
            True,
            [
                (
                    RunnerEvent.COMMAND_PASSED,
                    {
                        "returncode": 0,
                        "actual": "b",
                        "env": {"a": "b"},
                    },
                ),
            ],
        ),
    ),
)
def test_check_result(make_runner, cmd, args, expected_result, expected_events):
    runner, events = make_runner()
    result = runner._check_result(cmd, *args, {"a": "b"})

    assert result == expected_result, events

    assert len(events) == len(expected_events)

    for i in range(len(events)):
        assert events[i][0][0] == expected_events[i][0]
        assert events[i][0][1] == cmd
        assert events[i][1] == expected_events[i][1]


def test_check_result_unknown_assert_mode(make_runner, ssh_config):
    runner, events = make_runner(ssh_config)

    cmd = Command(
        ExecutionMode.USER,
        "echo a",
        None,
        None,
        "local",
        "xxx",
        "a",
        "/some.ispec",
        1,
        "$ echo a",
        False,
        False,
        None,
    )

    with pytest.raises(Exception, match="Unknown assert_mode: xxx.*"):
        runner._check_result(cmd, "", 0, {})


@pytest.mark.parametrize(
    "user,host,expected_class",
    (
        (None, "local", TmuxShell),
        ("root", "remote", TmuxShell),
    ),
)
def test_get_session(make_runner, ssh_config, user, host, expected_class):
    runner, events = make_runner(ssh_config)

    cmd = Command(
        ExecutionMode.USER,
        "echo a",
        user,
        None,
        host,
        AssertMode.LITERAL,
        "a",
        "/some.ispec",
        1,
        "$ echo a",
        False,
        False,
        None,
    )

    session1, _ = runner._get_session(cmd, 5)

    assert isinstance(session1, expected_class)

    assert session1.run_command("echo a").strip() == "a"

    session2, _ = runner._get_session(cmd, 5)
    assert id(session1) == id(session2)

    cmd.session_name = "a"

    session3, _ = runner._get_session(cmd, 5)
    assert id(session1) != id(session3)

    session4, _ = runner._get_session(cmd, 5)
    assert id(session3) == id(session4)


def test_get_session_unknown_host(make_runner, ssh_config):
    runner, events = make_runner(ssh_config)

    cmd = Command(
        ExecutionMode.USER,
        "echo a",
        None,
        None,
        "xxx",
        AssertMode.LITERAL,
        "a",
        "/some.ispec",
        1,
        "$ echo a",
        False,
        False,
        None,
    )

    with pytest.raises(Exception, match="Unknown host: xxx.*"):
        runner._get_session(cmd, 5)


def test_timeout_setting(
    make_runner, ssh_config, command_local_echo_literal, command_remote_echo_literal
):
    runner, events = make_runner(ssh_config)

    specfile = Specfile("virtual.ispec")
    specfile.commands = [command_local_echo_literal, command_remote_echo_literal]

    runner.run(specfile, close_sessions=False)

    for event in events:
        assert event[0][0] in (
            RunnerEvent.RUN_STARTING,
            RunnerEvent.COMMAND_STARTING,
            RunnerEvent.COMMAND_PASSED,
            RunnerEvent.RUN_SUCCEEDED,
        ), event

    sessions = list(runner.sessions.values())
    assert len(sessions) == 2

    for session in sessions:
        assert session.timeout == 5


def test_logout(make_runner, ssh_config):
    runner, events = make_runner(ssh_config)
    specfile = Specfile("virtual.ispec")

    specfile.commands = [
        Command(
            ExecutionMode.ROOT,
            "echo a",
            "root",
            None,
            "remote",
            AssertMode.LITERAL,
            "a",
            "/some.ispec",
            1,
            "$ echo a",
            False,
            False,
            None,
        ),
        Command(
            ExecutionMode.ROOT,
            "logout",
            "root",
            None,
            "remote",
            AssertMode.LITERAL,
            "",
            "/some.ispec",
            1,
            "$ echo a",
            False,
            False,
            None,
        ),
        Command(
            ExecutionMode.ROOT,
            "echo b",
            "root",
            None,
            "remote",
            AssertMode.LITERAL,
            "b",
            "/some.ispec",
            1,
            "$ echo a",
            False,
            False,
            None,
        ),
    ]

    runner.run(specfile)

    for event in events:
        assert event[0][0] in (
            RunnerEvent.RUN_STARTING,
            RunnerEvent.COMMAND_STARTING,
            RunnerEvent.COMMAND_PASSED,
            RunnerEvent.RUN_SUCCEEDED,
        ), event


def test_runner_python(mocker, make_runner, ssh_config):
    def fake_run_in_file(filename, si_context, code):
        assert filename == Path("virtual.ispec.py")
        assert isinstance(si_context.env, dict)
        assert si_context.env["HOME"] == "/root"
        assert si_context.env["SI_TARGET"] == "mock"
        assert code == "return_true()"

        return True

    run_in_file = mocker.patch(
        "shellinspector.runner.run_in_file",
        side_effect=fake_run_in_file,
    )

    runner, events = make_runner(ssh_config, {"SI_TARGET": "mock"})
    specfile = Specfile("virtual.ispec")

    specfile.commands = [
        Command(
            ExecutionMode.PYTHON,
            "return_true()",
            "root",
            None,
            "remote",
            AssertMode.LITERAL,
            "",
            "/virtual.ispec",
            1,
            "return_true()",
            False,
            False,
            None,
        ),
    ]

    runner.run(specfile)

    assert len(events) == 4

    for event in events:
        assert event[0][0] in (
            RunnerEvent.RUN_STARTING,
            RunnerEvent.COMMAND_STARTING,
            RunnerEvent.COMMAND_PASSED,
            RunnerEvent.RUN_SUCCEEDED,
        ), event

    assert run_in_file.call_count == 1
    assert run_in_file.call_args[0][0] == Path("virtual.ispec.py")
    context = run_in_file.call_args[0][1]
    assert isinstance(context, ShellinspectorPyContext)
    assert isinstance(context.applied_example, dict)
    assert context.env["HOME"] == "/root"
    assert run_in_file.call_args[0][2] == "return_true()"


def test_runner_python_fail(mocker, make_runner, ssh_config):
    def fake_run_in_file(*args, **kwargs):
        return "fail"

    run_in_file = mocker.patch(
        "shellinspector.runner.run_in_file",
        side_effect=fake_run_in_file,
    )

    runner, events = make_runner(ssh_config)
    specfile = Specfile("virtual.ispec")

    specfile.commands = [
        Command(
            ExecutionMode.PYTHON,
            "return_true()",
            "root",
            None,
            "remote",
            AssertMode.LITERAL,
            "",
            "/virtual.ispec",
            1,
            "return_true()",
            False,
            False,
            None,
        ),
    ]

    runner.run(specfile)

    assert len(events) == 4

    for event in events:
        assert event[0][0] in (
            RunnerEvent.RUN_STARTING,
            RunnerEvent.COMMAND_STARTING,
            RunnerEvent.COMMAND_FAILED,
            RunnerEvent.RUN_FAILED,
        ), event

        if event[0][0] == RunnerEvent.COMMAND_FAILED:
            assert event[1]["message"] == "fail"

    assert run_in_file.call_count == 1


def test_environment2(make_runner, ssh_config, command_local_echo_literal_env_var):
    runner, events = make_runner(ssh_config)
    specfile = Specfile("virtual.ispec")

    specfile.environment = {
        "something": "value__",
    }

    specfile.commands = [command_local_echo_literal_env_var]

    runner.run(specfile)

    for event in events:
        assert event[0][0] in (
            RunnerEvent.RUN_STARTING,
            RunnerEvent.COMMAND_STARTING,
            RunnerEvent.COMMAND_PASSED,
            RunnerEvent.RUN_SUCCEEDED,
        ), event


class FakeSession:
    def __init__(self, command_output, returncode=0, env=None, timeout_exc=None):
        self._command_output = command_output
        self._returncode = returncode
        self._env = env or {}
        self._timeout_exc = timeout_exc
        self.closed = False

    def run_command(self, _line):
        if self._timeout_exc is not None:
            raise self._timeout_exc
        return self._command_output

    def get_returncode(self):
        return self._returncode

    def get_environment(self):
        return self._env

    def close(self):
        self.closed = True

    def set_environment(self, env):
        pass


@pytest.mark.parametrize(
    "session,expected_result,expected_events",
    (
        (
            FakeSession("a", returncode=0, env={"a": "b"}),
            True,
            [
                (
                    RunnerEvent.COMMAND_PASSED,
                    {"returncode": 0, "actual": "a", "env": {"a": "b"}},
                ),
            ],
        ),
        (
            FakeSession("a", timeout_exc=TimeoutException("a", "global", 5)),
            False,
            [
                (
                    RunnerEvent.ERROR,
                    {
                        "message": "global timeout, 5s, could not find end of command output",
                        "actual": "a",
                    },
                ),
            ],
        ),
    ),
)
def test_run_command(
    make_runner,
    command_local_echo_literal_fail,
    session,
    expected_result,
    expected_events,
):
    runner, events = make_runner()
    result = runner._run_command(session, command_local_echo_literal_fail)
    assert result == expected_result, events

    assert len(events) == len(expected_events)

    for i in range(len(events)):
        assert events[i][0][0] == expected_events[i][0]
        assert events[i][0][1] == command_local_echo_literal_fail
        assert events[i][1] == expected_events[i][1]


@pytest.mark.parametrize(
    "session,expected_result,expected_events",
    (
        (
            FakeSession("a", returncode=0, env={"a": "b"}),
            True,
            [
                (RunnerEvent.RUN_STARTING, None, {}),
                (RunnerEvent.COMMAND_STARTING, "echo a", {}),
                (
                    RunnerEvent.COMMAND_PASSED,
                    "echo a",
                    {
                        "returncode": 0,
                        "actual": "a",
                        "env": {"a": "b"},
                    },
                ),
                (RunnerEvent.RUN_SUCCEEDED, None, {}),
            ],
        ),
        (
            FakeSession("a", returncode=1, env={"a": "b"}),
            False,
            [
                (RunnerEvent.RUN_STARTING, None, {}),
                (RunnerEvent.COMMAND_STARTING, "echo a", {}),
                (
                    RunnerEvent.COMMAND_FAILED,
                    "echo a",
                    {
                        "returncode": 1,
                        "actual": "a",
                        "reasons": {"returncode"},
                        "env": {"a": "b"},
                    },
                ),
                (RunnerEvent.RUN_FAILED, None, {}),
            ],
        ),
    ),
)
def test_run1(
    make_runner,
    command_local_echo_literal_fail,
    session,
    expected_result,
    expected_events,
):
    runner, events = make_runner()
    runner._get_session = lambda cmd, timeout: (session, True)
    specfile = Specfile("virtual.ispec")
    specfile.commands = [command_local_echo_literal_fail]

    result = runner.run(specfile)
    assert result == expected_result, events

    assert len(events) == len(expected_events)

    for i in range(len(events)):
        assert events[i][0][0] == expected_events[i][0]
        if expected_events[i][1] is None:
            assert events[i][0][1] is None
        else:
            assert events[i][0][1].command == expected_events[i][1]
        assert events[i][1] == expected_events[i][2]


def test_run_in_file():
    assert (
        run_in_file(
            Path(__file__).parent / "e2e/700_python.ispec.py", None, "return_true()"
        )
        is True
    )
    assert (
        run_in_file(
            Path(__file__).parent / "e2e/700_python.ispec.py", None, "return_str()"
        )
        == "a string"
    )


def test_run_in_file_pass_context():
    class Context:
        pass

    context_in = Context()
    context_out = run_in_file(
        Path(__file__).parent / "e2e/700_python.ispec.py",
        context_in,
        "return_context()",
    )
    assert context_in is context_out
    assert context_in.from_inside is True


def test_run_in_file_multiple_statements():
    with pytest.raises(Exception) as ex:
        run_in_file(
            Path(__file__).parent / "e2e/700_python.ispec.py",
            None,
            "return_true()\nreturn_true()",
        )

    assert "Only one and exactly one function call" in str(ex)
    assert "2" in str(ex)


def test_run_in_file_non_call():
    with pytest.raises(Exception) as ex:
        run_in_file(Path(__file__).parent / "e2e/700_python.ispec.py", None, "1 + 1")

    assert "Only function calls are supported" in str(ex)


def test_real_success(make_runner, ssh_config, command_local_echo_literal_env_var):
    runner, events = make_runner(ssh_config)

    specfile = Specfile(
        "virtual.ispec",
        environment={"something": "value__"},
        commands=[command_local_echo_literal_env_var],
    )

    run_success = runner.run(specfile)
    assert events[0][0][0] == RunnerEvent.RUN_STARTING
    assert events[1][0][0] == RunnerEvent.COMMAND_STARTING
    assert events[2][0][0] == RunnerEvent.COMMAND_PASSED
    assert events[3][0][0] == RunnerEvent.RUN_SUCCEEDED
    assert run_success is True, events


def test_real_fail_output(make_runner, ssh_config, command_local_echo_literal_env_var):
    runner, events = make_runner(ssh_config)

    specfile = Specfile(
        "virtual.ispec",
        environment={"something": "wrong"},
        commands=[command_local_echo_literal_env_var],
    )

    run_success = runner.run(specfile)
    assert events[0][0][0] == RunnerEvent.RUN_STARTING
    assert events[1][0][0] == RunnerEvent.COMMAND_STARTING
    assert events[2][0][0] == RunnerEvent.COMMAND_FAILED
    assert events[2][1]["reasons"] == {"output"}
    assert events[3][0][0] == RunnerEvent.RUN_FAILED
    assert run_success is False, events


def test_real_fail_rc(make_runner, ssh_config):
    runner, events = make_runner(ssh_config)

    specfile = Specfile(
        "virtual.ispec",
        commands=[
            Command(
                ExecutionMode.ROOT,
                "false",
                "root",
                None,
                "remote",
                AssertMode.LITERAL,
                "",
                "/some.ispec",
                1,
                "$ false",
                False,
                False,
                None,
            ),
        ],
    )

    run_success = runner.run(specfile)
    assert events[0][0][0] == RunnerEvent.RUN_STARTING
    assert events[1][0][0] == RunnerEvent.COMMAND_STARTING
    assert events[2][0][0] == RunnerEvent.COMMAND_FAILED
    assert events[2][1]["reasons"] == {"returncode"}
    assert events[3][0][0] == RunnerEvent.RUN_FAILED
    assert run_success is False, events
