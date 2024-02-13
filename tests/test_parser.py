from pathlib import Path

import pytest

from shellinspector.parser import AssertMode
from shellinspector.parser import Command
from shellinspector.parser import ExecutionMode
from shellinspector.parser import parse


def test_parse():
    specfile = parse(
        "/dev/null",
        [
            "$ echo a",
            "# ignored",
            "a",
            "% ls",
            "file",
            "dir",
            "otherfile",
            "%~ ls dir",
            "file",
        ],
    )
    commands, errors = (specfile.commands, specfile.errors)

    assert len(errors) == 0
    assert len(commands) == 3

    assert commands[0].execution_mode == ExecutionMode.USER
    assert commands[0].command == "echo a"
    assert commands[0].assert_mode == AssertMode.LITERAL
    assert commands[0].expected == "a\n"
    assert commands[0].source_file == Path("/dev/null")
    assert commands[0].source_line_no == 1
    assert commands[1].execution_mode == ExecutionMode.ROOT
    assert commands[1].command == "ls"
    assert commands[1].assert_mode == AssertMode.LITERAL
    assert commands[1].expected == "file\ndir\notherfile\n"
    assert commands[1].source_file == Path("/dev/null")
    assert commands[1].source_line_no == 4
    assert commands[2].execution_mode == ExecutionMode.ROOT
    assert commands[2].command == "ls dir"
    assert commands[2].assert_mode == AssertMode.REGEX
    assert commands[2].source_file == Path("/dev/null")
    assert commands[2].source_line_no == 8


def test_parse_whitespace_literal():
    specfile = parse(
        "/dev/null",
        [
            "$ echo ab",
            "a",
            "b",
        ],
    )
    commands, errors = (specfile.commands, specfile.errors)

    assert len(errors) == 0
    assert len(commands) == 1

    assert commands[0].expected == "a\nb\n"


def test_parse_whitespace_regex():
    specfile = parse(
        "/dev/null",
        [
            "%~ /usr/bin/which --help",
            "Usage: /usr/bin/which [options] [--] COMMAND [...]",
            "Write the full path of COMMAND",
        ],
    )
    commands, errors = (specfile.commands, specfile.errors)

    assert len(errors) == 0
    assert len(commands) == 1

    # no trailing newline at the end because this confuses the regex
    assert (
        commands[0].expected
        == "Usage: /usr/bin/which [options] [--] COMMAND [...]\nWrite the full path of COMMAND"
    )


def test_parse_error():
    path = Path(__file__).parent / "virtual.ispec"
    specfile = parse(
        path,
        [
            "random text1",
            "random text2",
            "% ls1",
            "file",
            "% ls2",
            "file",
        ],
    )
    commands, errors = (specfile.commands, specfile.errors)

    assert len(errors) == 2
    assert errors[0].source_file == path
    assert errors[0].source_line_no == 1
    assert errors[0].source_line == "random text1"
    assert "output before first command," in errors[0].message
    assert errors[1].source_file == path
    assert errors[1].source_line_no == 2
    assert errors[1].source_line == "random text2"
    assert "output before first command," in errors[1].message

    assert len(commands) == 2
    assert commands[0].command == "ls1"
    assert commands[0].expected
    assert commands[0].source_line_no == 3
    assert commands[1].command == "ls2"
    assert commands[1].expected
    assert commands[1].source_line_no == 5


def test_parse_error_include():
    path = Path(__file__).parent / "virtual.ispec"
    specfile = parse(
        path,
        [
            "% ls1",
            "file",
            "<data/test_error.ispec",
        ],
    )
    commands, errors = (specfile.commands, specfile.errors)

    assert len(errors) == 1
    assert errors[0].source_file == path.parent / "data/test_error.ispec"
    assert errors[0].source_line_no == 1
    assert errors[0].source_line == "a"

    assert len(commands) == 2
    assert commands[0].command == "ls1"
    assert commands[0].expected
    assert commands[0].source_file == path
    assert commands[0].source_line_no == 1
    assert commands[1].command == "ls2"
    assert commands[1].expected
    assert commands[1].source_file == path.parent / "data/test_error.ispec"
    assert commands[1].source_line_no == 2


def test_user_reuse():
    specfile = parse(
        "/dev/null",
        [
            "[someuser@]$ ls",
            "$ ls",
            "% ls",
            "$ ls",
            "[someuser@somehost]$ ls",
            "$ ls",
        ],
    )
    commands, errors = (specfile.commands, specfile.errors)

    assert len(errors) == 0

    assert commands[0].user == "someuser"
    assert commands[0].host == "remote"
    assert commands[1].user == "someuser"
    assert commands[1].host == "remote"
    assert commands[2].user == "root"
    assert commands[2].host == "remote"
    assert commands[3].user == "someuser"
    assert commands[3].host == "remote"
    assert commands[4].user == "someuser"
    assert commands[4].host == "somehost"
    assert commands[5].user == "someuser"
    assert commands[5].host == "somehost"


def test_empty():
    specfile = parse("/dev/null", [])
    commands, errors = (specfile.commands, specfile.errors)
    assert len(errors) == 0
    assert len(commands) == 0


@pytest.mark.parametrize(
    "line,result",
    [
        (
            "% ls",
            {"execution_mode": ExecutionMode.ROOT, "assert_mode": AssertMode.LITERAL},
        ),
        (
            "%~ ls",
            {"execution_mode": ExecutionMode.ROOT, "assert_mode": AssertMode.REGEX},
        ),
        (
            "%_ ls",
            {"execution_mode": ExecutionMode.ROOT, "assert_mode": AssertMode.IGNORE},
        ),
        (
            "$ ls",
            {"execution_mode": ExecutionMode.USER, "assert_mode": AssertMode.LITERAL},
        ),
        (
            "$~ ls",
            {"execution_mode": ExecutionMode.USER, "assert_mode": AssertMode.REGEX},
        ),
        (
            "$_ ls",
            {"execution_mode": ExecutionMode.USER, "assert_mode": AssertMode.IGNORE},
        ),
        (
            "[someuser@somehost]$ ls",
            {
                "execution_mode": ExecutionMode.USER,
                "user": "someuser",
                "host": "somehost",
            },
        ),
        (
            "[someuser@]$ ls",
            {
                "execution_mode": ExecutionMode.USER,
                "user": "someuser",
                "host": "remote",
            },
        ),
        (
            "[someuser:sess1@]$ ls",
            {
                "execution_mode": ExecutionMode.USER,
                "user": "someuser",
                "host": "remote",
                "session_name": "sess1",
            },
        ),
        (
            "[@local]$ ls",
            {"execution_mode": ExecutionMode.USER, "user": None, "host": "local"},
        ),
        (
            "[:sess1@local]$ ls",
            {
                "execution_mode": ExecutionMode.USER,
                "user": None,
                "host": "local",
                "session_name": "sess1",
            },
        ),
        (
            "[someuser@local]% ls",
            {"execution_mode": ExecutionMode.ROOT, "user": "root", "host": "local"},
        ),
    ],
)
def test_variants(line, result):
    specfile = parse("/dev/null", [line])
    commands, errors = (specfile.commands, specfile.errors)

    assert len(errors) == 0
    assert commands[0].command == "ls"

    for k, v in result.items():
        assert getattr(commands[0], k) == v, k


def test_include():
    path = Path(__file__).parent / "virtual.ispec"
    specfile = parse(
        path,
        [
            "% ls",
            "file",
            "<data/test.ispec",
            "% ls",
            "file",
        ],
    )
    commands, errors = (specfile.commands, specfile.errors)

    assert len(errors) == 0
    assert len(commands) == 3

    assert commands[0].execution_mode == ExecutionMode.ROOT
    assert commands[0].command == "ls"
    assert commands[0].expected == "file\n"
    assert commands[0].source_file == path
    assert commands[0].source_line_no == 1
    assert commands[1].execution_mode == ExecutionMode.ROOT
    assert commands[1].command == "whoami"
    assert commands[1].expected == "root\n"
    assert commands[1].source_file == Path(__file__).parent / "data/test.ispec"
    assert commands[1].source_line_no == 1
    assert commands[2].execution_mode == ExecutionMode.ROOT
    assert commands[2].command == "ls"
    assert commands[2].expected == "file\n"
    assert commands[2].source_file == path
    assert commands[2].source_line_no == 4


def test_environment():
    path = Path(__file__).parent / "e2e/500_envtest.ispec"
    specfile = parse(path, [])

    assert len(specfile.errors) == 0

    assert specfile.environment == {
        "something": "else",
        "withspace": "with space",
        "valuewithequals": "e=quals",
        # provided twice, last value counts
        "number": "2",
    }


def test_examples():
    path = Path(__file__).parent / "e2e/600_examplestest.ispec"
    specfile = parse(path, [])

    assert len(specfile.errors) == 0

    assert specfile.examples == [
        {
            "PY_COMMAND": "python3.10",
            "PY_VERSION": "3.10",
        },
        {
            "PY_COMMAND": "python3.11",
            "PY_VERSION": "3.11",
        },
    ]


def test_include_missing_file():
    path = Path(__file__).parent / "virtual.ispec"
    specfile = parse(
        path,
        [
            "% ls",
            "file",
            "<data/test_not_existent.ispec",
            "% ls",
            "file",
        ],
    )

    assert len(specfile.errors) == 1
    assert "test_not_existent.ispec does not exist" in specfile.errors[0].message


def test_command_short_literal():
    cmd = Command(
        ExecutionMode.USER,
        "echo a",
        None,
        None,
        "local",
        AssertMode.LITERAL,
        "a\nb\n",
        "/some.ispec",
        1,
        "$ echo a\nb",
    )
    assert cmd.short == "USER(None@local) `echo a` (expect 2 lines, LITERAL)"


def test_command_short_regex():
    cmd = Command(
        ExecutionMode.USER,
        "echo a",
        None,
        None,
        "local",
        AssertMode.REGEX,
        "a\nb",
        "/some.ispec",
        1,
        "$ echo a\nb",
    )
    assert cmd.short == "USER(None@local) `echo a` (expect 2 lines, REGEX)"
