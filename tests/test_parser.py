from pathlib import Path
import pytest

from shellinspector.parser import parse


def test_parse():
    commands = list(
        parse(
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
    )

    assert len(commands) == 3
    assert commands[0].execution_mode == "run_command_user"
    assert commands[0].command == "echo a"
    assert commands[0].assert_mode == "literal"
    assert commands[0].expected == "a\n"
    assert commands[0].source_file == Path("/dev/null")
    assert commands[0].source_line_no == 1
    assert commands[1].execution_mode == "run_command_root"
    assert commands[1].command == "ls"
    assert commands[1].assert_mode == "literal"
    assert commands[1].expected == "file\ndir\notherfile\n"
    assert commands[1].source_file == Path("/dev/null")
    assert commands[1].source_line_no == 4
    assert commands[2].execution_mode == "run_command_root"
    assert commands[2].command == "ls dir"
    assert commands[2].assert_mode == "regex"
    assert commands[2].source_file == Path("/dev/null")
    assert commands[2].source_line_no == 8


@pytest.mark.parametrize(
    "lines",
    [
        [],
        [""],
        ["\n"],
    ]
)
def test_empty(lines):
    commands = list(parse("/dev/null", lines))
    assert len(commands) == 0


@pytest.mark.parametrize(
    "line,result",
    [
        (
            "% ls",
            {"execution_mode": "run_command_root", "assert_mode": "literal"},
        ),
        (
            "%~ ls",
            {"execution_mode": "run_command_root", "assert_mode": "regex"},
        ),
        (
            "%_ ls",
            {"execution_mode": "run_command_root", "assert_mode": "ignore"},
        ),
        (
            "$ ls",
            {"execution_mode": "run_command_user", "assert_mode": "literal"},
        ),
        (
            "$~ ls",
            {"execution_mode": "run_command_user", "assert_mode": "regex"},
        ),
        (
            "$_ ls",
            {"execution_mode": "run_command_user", "assert_mode": "ignore"},
        ),
        (
            "[someuser@somehost]$ ls",
            {"execution_mode": "run_command_user", "user": "someuser", "host": "somehost"},
        ),
        (
            "[someuser@]$ ls",
            {"execution_mode": "run_command_user", "user": "someuser", "host": "remote"},
        ),
        (
            "[@local]$ ls",
            {"execution_mode": "run_command_user", "user": None, "host": "local"},
        ),
        (
            "[someuser@local]% ls",
            {"execution_mode": "run_command_root", "user": "root", "host": "local"},
        ),
    ],
)
def test_variants(line, result):
    command = next(parse("/dev/null", [line]))

    assert command.command == "ls"

    for k, v in result.items():
        assert getattr(command, k) == v


def test_include():
    path = Path(__file__).parent / "virtual.spec"
    commands = list(
        parse(
            path,
            [
                "% ls",
                "file",
                f"<data/test.spec",
                "% ls",
                "file",
            ],
        )
    )

    assert len(commands) == 3
    assert commands[0].execution_mode == "run_command_root"
    assert commands[0].command == "ls"
    assert commands[0].expected == "file\n"
    assert commands[0].source_file == path
    assert commands[0].source_line_no == 1
    assert commands[1].execution_mode == "run_command_root"
    assert commands[1].command == "whoami"
    assert commands[1].expected == "root\n"
    assert commands[1].source_file == Path(__file__).parent / "data/test.spec"
    assert commands[1].source_line_no == 1
    assert commands[2].execution_mode == "run_command_root"
    assert commands[2].command == "ls"
    assert commands[2].expected == "file\n"
    assert commands[2].source_file == path
    assert commands[2].source_line_no == 4
