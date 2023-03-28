import os
from pathlib import Path

import pytest
from pytest_lazyfixture import lazy_fixture

from shellinspector.parser import AssertMode
from shellinspector.parser import Command
from shellinspector.parser import ExecutionMode
from shellinspector.runner import LocalShell
from shellinspector.runner import RemoteShell
from shellinspector.runner import RunnerEvent
from shellinspector.runner import ShellRunner
from shellinspector.runner import disable_color
from shellinspector.runner import get_localshell
from shellinspector.runner import get_ssh_session


@pytest.fixture
def ssh_key_path():
    path = Path(__file__).parent / "keys/id_ed25519"
    assert path.exists()
    return path


@pytest.fixture
def make_runner():
    def make_runner():
        events = []

        def rep(*args, **kwargs):
            events.append((args, kwargs))

        runner = ShellRunner({}, {})
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
    assert os.environ["TERM"] != "dumb"

    with disable_color():
        assert os.environ["TERM"] == "dumb"

    assert os.environ["TERM"] != "dumb"


def test_disable_color_no_term():
    old_term = os.environ["TERM"]
    del os.environ["TERM"]
    assert "TERM" not in os.environ

    with disable_color():
        # doesn't crash
        pass

    assert "TERM" not in os.environ
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


def test_get_localshell():
    shell = get_localshell()
    shell.sendline("echo a")
    assert shell.prompt(), shell.before
    assert shell.before.decode() == "a\r\n"


def test_get_ssh_session(ssh_config):
    shell = get_ssh_session(ssh_config)
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
def command_local_echo():
    return Command(
        ExecutionMode.USER,
        "echo a",
        None,
        None,
        "local",
        AssertMode.LITERAL,
        "a",
        "/some.spec",
        1,
        "$ echo a",
    )


@pytest.mark.parametrize(
    "cmd,args,expected_result,expected_events",
    (
        (
            lazy_fixture("command_local_echo"),
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
        (
            lazy_fixture("command_local_echo"),
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
            lazy_fixture("command_local_echo"),
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
            lazy_fixture("command_local_echo"),
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
