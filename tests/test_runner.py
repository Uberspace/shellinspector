import os
from pathlib import Path

import pytest
from pytest_lazyfixture import lazy_fixture

from shellinspector.parser import AssertMode
from shellinspector.parser import Command
from shellinspector.parser import ExecutionMode
from shellinspector.parser import Specfile
from shellinspector.runner import LocalShell
from shellinspector.runner import RemoteShell
from shellinspector.runner import RunnerEvent
from shellinspector.runner import ShellinspectorPyContext
from shellinspector.runner import ShellRunner
from shellinspector.runner import disable_color
from shellinspector.runner import get_localshell
from shellinspector.runner import get_ssh_session
from shellinspector.runner import run_in_file


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


def test_localshell():
    with disable_color():
        shell = LocalShell(timeout=2)
        shell.login()
    shell.sendline("echo a && echo b")
    assert shell.prompt(), shell.before
    assert shell.before.decode() == "a\r\nb\r\n"
    shell.sendline("echo c")
    assert shell.prompt(), shell.before
    assert shell.before.decode() == "c\r\n"


def test_localshell_state():
    with disable_color():
        shell = LocalShell(timeout=2)
        shell.login()

    shell.sendline("echo $OUTERVAR")
    assert shell.prompt(), shell.before
    assert shell.before.decode().strip() == ""

    shell.sendline("export OUTERVAR=1")
    assert shell.prompt(), shell.before
    shell.sendline("echo $OUTERVAR")
    assert shell.prompt(), shell.before
    assert shell.before.decode().strip() == "1"

    shell.push_state()

    shell.sendline("echo $OUTERVAR")
    assert shell.prompt(), shell.before
    assert shell.before.decode().strip() == "1"

    shell.sendline("export INNERVAR=1")
    assert shell.prompt(), shell.before

    shell.sendline("echo $INNERVAR")
    assert shell.prompt(), shell.before
    assert shell.before.decode().strip() == "1"

    shell.pop_state()

    shell.sendline("echo $OUTERVAR")
    assert shell.prompt(), shell.before
    assert shell.before.decode().strip() == "1"

    shell.sendline("echo $INNERVAR")
    assert shell.prompt(), shell.before
    assert shell.before.decode().strip() == ""


def test_localshell_state_kill_session():
    with disable_color():
        shell = LocalShell(timeout=2)
        shell.login()

    shell.push_state()

    shell.sendline("exit")
    assert shell.prompt(), shell.before

    with pytest.raises(Exception, match="Test shell was exited.*"):
        shell.pop_state()


def test_localshell_set_environment():
    with disable_color():
        shell = LocalShell(timeout=2)
        shell.login()

    shell.set_environment(
        {
            "VAR1": "aa",
            "VAR2": "bb",
        }
    )

    shell.sendline("echo $VAR1")
    assert shell.prompt(), shell.before
    assert shell.before.decode().strip() == "aa"

    shell.sendline("echo $VAR2")
    assert shell.prompt(), shell.before
    assert shell.before.decode().strip() == "bb"


def test_remoteshell(ssh_config):
    with disable_color():
        shell = RemoteShell(timeout=2)
        shell.login(**ssh_config)

    shell.sendline("echo a && echo b")
    assert shell.prompt(), shell.before
    assert shell.before.decode() == "a\r\nb\r\n"
    shell.sendline("echo c")
    assert shell.prompt(), shell.before
    assert shell.before.decode() == "c\r\n"


def test_remoteshell_get_environment(ssh_config):
    with disable_color():
        shell = RemoteShell(timeout=2)
        shell.login(**ssh_config)

    shell.sendline("export SPACES='a b'")
    assert shell.prompt(), shell.before

    env = shell.get_environment()
    assert len(env) > 5
    assert env["HOME"] == "/root"
    assert env["SPACES"] == "a b"


def test_get_localshell():
    shell = get_localshell(5)
    shell.sendline("echo a")
    assert shell.prompt(), shell.before
    assert shell.before.decode() == "a\r\n"


def test_get_ssh_session(ssh_config):
    shell = get_ssh_session(ssh_config, 5)
    shell.sendline("echo a")
    assert shell.prompt(), shell.before
    assert shell.before.decode() == "a\r\n"


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
        "a\n",
        "/some.ispec",
        1,
        "$ echo a",
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
        "a\n",
        "/some.ispec",
        1,
        "$ echo a",
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
                    },
                ),
            ],
        ),
    ),
)
def test_check_result(make_runner, cmd, args, expected_result, expected_events):
    runner, events = make_runner()
    result = runner._check_result(cmd, *args)

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
    )

    with pytest.raises(Exception, match="Unknown assert_mode: xxx.*"):
        runner._check_result(cmd, "", 0)


@pytest.mark.parametrize(
    "user,host,expected_class",
    (
        (None, "local", LocalShell),
        ("root", "remote", RemoteShell),
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
    )

    session1 = runner._get_session(cmd, 5)

    assert isinstance(session1, expected_class)

    session1.sendline("echo a")
    assert session1.prompt()
    assert session1.before.decode().strip() == "a"

    session2 = runner._get_session(cmd, 5)
    assert id(session1) == id(session2)

    cmd.session_name = "a"

    session3 = runner._get_session(cmd, 5)
    assert id(session1) != id(session3)

    session4 = runner._get_session(cmd, 5)
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
    )

    with pytest.raises(Exception, match="Unknown host: xxx.*"):
        runner._get_session(cmd, 5)


def test_timeout_setting(
    make_runner, ssh_config, command_local_echo_literal, command_remote_echo_literal
):
    runner, events = make_runner(ssh_config)

    specfile = Specfile("virtual.ispec")
    specfile.commands = [command_local_echo_literal, command_remote_echo_literal]

    runner.run(specfile)

    for event in events:
        assert event[0][0] in (
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
            "a\n",
            "/some.ispec",
            1,
            "$ echo a",
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
        ),
        Command(
            ExecutionMode.ROOT,
            "echo b",
            "root",
            None,
            "remote",
            AssertMode.LITERAL,
            "b\n",
            "/some.ispec",
            1,
            "$ echo a",
        ),
    ]

    runner.run(specfile)

    for event in events:
        assert event[0][0] in (
            RunnerEvent.COMMAND_STARTING,
            RunnerEvent.COMMAND_PASSED,
            RunnerEvent.RUN_SUCCEEDED,
        ), event


def test_runner_python(mocker, make_runner, ssh_config):
    def fake_run_in_file(filename, si_context, code):
        assert filename == Path("virtual.ispec.py")
        assert isinstance(si_context.env, dict)
        assert si_context.env["HOME"] == "/root"
        assert code == "return_true()"

        return True

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
        ),
    ]

    runner.run(specfile)

    assert len(events) == 3

    for event in events:
        assert event[0][0] in (
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
        ),
    ]

    runner.run(specfile)

    assert len(events) == 3

    for event in events:
        assert event[0][0] in (
            RunnerEvent.COMMAND_STARTING,
            RunnerEvent.COMMAND_FAILED,
            RunnerEvent.RUN_FAILED,
        ), event

        if event[0][0] == RunnerEvent.COMMAND_FAILED:
            assert event[1]["message"] == "fail"

    assert run_in_file.call_count == 1


def test_environment(make_runner, ssh_config):
    runner, events = make_runner(ssh_config)
    specfile = Specfile("virtual.ispec")

    specfile.environment = {
        "something": "value__",
    }

    specfile.commands = [
        Command(
            ExecutionMode.ROOT,
            "echo $something",
            "root",
            None,
            "remote",
            AssertMode.LITERAL,
            "value__\n",
            "/some.ispec",
            1,
            "$ echo $something",
        ),
    ]

    runner.run(specfile)

    for event in events:
        assert event[0][0] in (
            RunnerEvent.COMMAND_STARTING,
            RunnerEvent.COMMAND_PASSED,
            RunnerEvent.RUN_SUCCEEDED,
        ), event


class FakeSession(RemoteShell):
    def __init__(self, prompt_works, before):
        self._prompt_works = prompt_works
        self._before = before
        self._lines = []
        self._closed = False

    def sendline(self, line):
        self._lines.append(line)

    def prompt(self):
        if not self._before:
            raise Exception(
                "Ran out of before outputs, provide more. Lines so far: "
                + ",".join(self._lines)
            )
        self.before = self._before.pop(0)
        return self._prompt_works.pop(0)

    def close(self):
        self._closed = True

    def push_state(self):
        pass

    def pop_state(self):
        pass

    def set_environment(self, env):
        pass


@pytest.mark.parametrize(
    "prompt_works,actual_output,expected_result,expected_events",
    (
        (
            [True, True],
            [b"a", b"0"],
            True,
            [
                (RunnerEvent.COMMAND_PASSED, {"returncode": 0, "actual": "a"}),
            ],
        ),
        (
            [False, True],
            [b"a", b"0"],
            False,
            [
                (
                    RunnerEvent.ERROR,
                    {
                        "message": "timeout, could not find prompt for command",
                        "actual": "a",
                    },
                ),
            ],
        ),
        (
            [True, False],
            [b"a", b"0"],
            False,
            [
                (
                    RunnerEvent.ERROR,
                    {
                        "message": "timeout, could not find prompt for return code",
                        "actual": "0",
                    },
                )
            ],
        ),
    ),
)
def test_run_command(
    make_runner,
    command_local_echo_literal_fail,
    prompt_works,
    actual_output,
    expected_result,
    expected_events,
):
    session = FakeSession(prompt_works, actual_output)
    runner, events = make_runner()
    result = runner._run_command(session, command_local_echo_literal_fail)
    assert result == expected_result, events

    assert len(events) == len(expected_events)

    for i in range(len(events)):
        assert events[i][0][0] == expected_events[i][0]
        assert events[i][0][1] == command_local_echo_literal_fail
        assert events[i][1] == expected_events[i][1]


@pytest.mark.parametrize(
    "prompt_works,actual_output,expected_result,expected_events",
    (
        (
            [True, True],
            [b"a", b"0"],
            True,
            [
                (RunnerEvent.COMMAND_STARTING, "echo a", {}),
                (
                    RunnerEvent.COMMAND_PASSED,
                    "echo a",
                    {"returncode": 0, "actual": "a"},
                ),
                (RunnerEvent.RUN_SUCCEEDED, None, {}),
            ],
        ),
        (
            [True, True],
            [b"a", b"1"],
            False,
            [
                (RunnerEvent.COMMAND_STARTING, "echo a", {}),
                (
                    RunnerEvent.COMMAND_FAILED,
                    "echo a",
                    {"returncode": 1, "actual": "a", "reasons": {"returncode"}},
                ),
                (RunnerEvent.RUN_FAILED, None, {}),
            ],
        ),
    ),
)
def test_run1(
    make_runner,
    command_local_echo_literal_fail,
    prompt_works,
    actual_output,
    expected_result,
    expected_events,
):
    runner, events = make_runner()
    session = FakeSession(prompt_works, actual_output)
    runner._get_session = lambda cmd, timeout: session
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
