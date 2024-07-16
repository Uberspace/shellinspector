from io import StringIO
from pathlib import Path

import pytest
import yaml

from shellinspector.parser import AssertMode
from shellinspector.parser import Command
from shellinspector.parser import ExecutionMode
from shellinspector.parser import parse
from shellinspector.parser import parse_global_config
from shellinspector.parser import parse_yaml_multidoc


def make_stream(lines, frontmatter=None):
    if frontmatter:
        frontmatter = yaml.safe_dump(frontmatter)
        tests = "\n".join(lines)
        result = f"---\n{frontmatter}\n---\n{tests}\n"
    else:
        result = "\n".join(lines) + "\n"

    return StringIO(result)


@pytest.mark.parametrize(
    "input,frontmatter,tests",
    [
        (
            "",
            {},
            "",
        ),
        (
            "a\nb\nc",
            {},
            "a\nb\nc",
        ),
        (
            "---\n{'a': 1}",
            {"a": 1},
            "",
        ),
        (
            "---\n{'a': 1}\n---\na\nb\nc",
            {"a": 1},
            "a\nb\nc",
        ),
        (
            "---\n\n---\n% echo ab\na\nb\n",
            {},
            "% echo ab\na\nb\n",
        ),
    ],
)
def test_parse_yaml_multidoc(input, frontmatter, tests):
    rfrontmatter, rtests = parse_yaml_multidoc(StringIO(input))
    assert rfrontmatter == frontmatter
    assert rtests == tests


def test_parse():
    specfile = parse(
        "/dev/null",
        make_stream(
            [
                "[usr@]$ echo a",
                "# ignored",
                "a",
                "$ echo b",
                "b",
                "% ls",
                "file",
                "dir",
                "otherfile",
                "%~ ls dir",
                "file",
                "! func()",
            ]
        ),
    )
    commands, errors = (specfile.commands, specfile.errors)

    assert len(errors) == 0, errors
    assert len(commands) == 5

    assert commands[0].execution_mode == ExecutionMode.USER
    assert commands[0].user == "usr"
    assert commands[0].command == "echo a"
    assert commands[0].assert_mode == AssertMode.LITERAL
    assert commands[0].expected == "a\n"
    assert commands[0].source_file == Path("/dev/null")
    assert commands[0].source_line_no == 1
    assert commands[1].execution_mode == ExecutionMode.USER
    assert commands[1].user == "usr"
    assert commands[1].command == "echo b"
    assert commands[1].assert_mode == AssertMode.LITERAL
    assert commands[1].expected == "b\n"
    assert commands[1].source_file == Path("/dev/null")
    assert commands[1].source_line_no == 4
    assert commands[2].execution_mode == ExecutionMode.ROOT
    assert commands[2].user == "root"
    assert commands[2].command == "ls"
    assert commands[2].assert_mode == AssertMode.LITERAL
    assert commands[2].expected == "file\ndir\notherfile\n"
    assert commands[2].source_file == Path("/dev/null")
    assert commands[2].source_line_no == 6
    assert commands[3].execution_mode == ExecutionMode.ROOT
    assert commands[3].user == "root"
    assert commands[3].command == "ls dir"
    assert commands[3].assert_mode == AssertMode.REGEX
    assert commands[3].source_file == Path("/dev/null")
    assert commands[3].source_line_no == 10
    assert commands[4].execution_mode == ExecutionMode.PYTHON
    assert commands[4].command == "func()"
    assert commands[4].assert_mode == AssertMode.LITERAL
    assert commands[4].source_file == Path("/dev/null")
    assert commands[4].source_line_no == 12


def test_parse_whitespace_literal():
    specfile = parse(
        "/dev/null",
        make_stream(
            [
                "% echo ab",
                "a",
                "b",
            ]
        ),
    )
    commands, errors = (specfile.commands, specfile.errors)

    assert len(errors) == 0
    assert len(commands) == 1

    assert commands[0].expected == "a\nb\n"


def test_parse_whitespace_regex():
    specfile = parse(
        "/dev/null",
        make_stream(
            [
                "%~ /usr/bin/which --help",
                "Usage: /usr/bin/which [options] [--] COMMAND [...]",
                "Write the full path of COMMAND",
            ]
        ),
    )
    commands, errors = (specfile.commands, specfile.errors)

    assert len(errors) == 0
    assert len(commands) == 1

    # no trailing newline at the end because this confuses the regex
    assert (
        commands[0].expected
        == "Usage: /usr/bin/which [options] [--] COMMAND [...]\nWrite the full path of COMMAND"
    )


def test_parse_error_no_user():
    specfile = parse(
        "/dev/null",
        make_stream(
            [
                "$ echo a",
                "a",
            ]
        ),
    )
    _, errors = (specfile.commands, specfile.errors)

    assert len(errors) == 1
    assert "not have a user specified" in errors[0].message


def test_parse_error():
    path = Path(__file__).parent / "virtual.ispec"
    specfile = parse(
        path,
        make_stream(
            [
                "random text1",
                "random text2",
                "% ls1",
                "file",
                "% ls2",
                "file",
            ]
        ),
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
        make_stream(
            [
                "% ls1",
                "file",
                "<data/test_error.ispec",
            ]
        ),
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
        make_stream(
            [
                "[someuser@]$ ls",
                "$ ls",
                "% ls",
                "$ ls",
                "[someuser@somehost]$ ls",
                "$ ls",
            ]
        ),
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
    specfile = parse("/dev/null", StringIO(""))
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
            "[someuser@local]% ls",
            {"execution_mode": ExecutionMode.ROOT, "user": "root", "host": "local"},
        ),
        (
            "[someuser@local]! ls",
            {
                "execution_mode": ExecutionMode.PYTHON,
                "user": "someuser",
                "host": "local",
            },
        ),
    ],
)
def test_variants(line, result):
    specfile = parse("/dev/null", make_stream([line]))
    commands, errors = (specfile.commands, specfile.errors)

    assert len(errors) == 0
    assert commands[0].command == "ls"

    for k, v in result.items():
        assert getattr(commands[0], k) == v, k


@pytest.mark.parametrize(
    "ispec_path,include_dirs,include_path",
    [
        (Path(__file__).parent / "virtual.ispec", "", "data/test.ispec"),
        (Path(__file__).parent / "virtual.ispec", "data", "test.ispec"),
    ],
)
def test_include(ispec_path, include_dirs, include_path):
    specfile = parse(
        ispec_path,
        make_stream(
            [
                "---",
                "settings:",
                f"  include_dirs: [{include_dirs}]",
                "---",
                "% ls",
                "file",
                f"<{include_path}",
                "% ls",
                "file",
            ]
        ),
    )
    commands, errors = (specfile.commands, specfile.errors)

    assert len(errors) == 0
    assert len(commands) == 3

    assert commands[0].execution_mode == ExecutionMode.ROOT
    assert commands[0].command == "ls"
    assert commands[0].expected == "file\n"
    assert commands[0].source_file == ispec_path
    assert commands[0].source_line_no == 1
    assert commands[1].execution_mode == ExecutionMode.ROOT
    assert commands[1].command == "whoami"
    assert commands[1].expected == "root\n"
    assert "test.ispec" in str(commands[1].source_file)
    assert commands[1].source_line_no == 1
    assert commands[2].execution_mode == ExecutionMode.ROOT
    assert commands[2].command == "ls"
    assert commands[2].expected == "file\n"
    assert commands[2].source_file == ispec_path
    assert commands[2].source_line_no == 4


def test_environment():
    path = Path(__file__).parent / "virtual.ispec"
    specfile = parse(
        path,
        make_stream(
            [
                "---",
                "environment:",
                "  # comment",
                "  something: else",
                "  withspace  :   with space",
                "  number: 1",
                "  number: 2",
                "---",
            ]
        ),
    )

    assert len(specfile.errors) == 0

    assert specfile.environment == {
        "something": "else",
        "withspace": "with space",
        # provided twice, last value counts
        "number": 2,
    }


def test_examples():
    path = Path(__file__).parent / "virtual.ispec"
    specfile = parse(
        path,
        make_stream(
            [
                "---",
                "examples:",
                '  - PY_VERSION: "3.10"',
                '    PY_COMMAND: "python3.10"',
                '  - PY_VERSION: "3.11"',
                '    PY_COMMAND: "python3.11"',
                "---",
            ]
        ),
    )

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
        make_stream(
            [
                "% ls",
                "file",
                "<data/test_not_existent.ispec",
                "% ls",
                "file",
            ]
        ),
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


@pytest.mark.parametrize(
    "ispec_path,expected_cfg",
    [
        ("with_dotgit_1/tests/some.ispec", {"with_dotgit_1": True}),
        ("with_dotgit_2/tests/some.ispec", {}),
        ("same_dir/tests/some.ispec", {"same_dir": True}),
        ("none/tests/some.ispec", {}),
        ("/dev/null", {}),
    ],
)
def test_parse_global_config(ispec_path, expected_cfg):
    git_dirs = [
        Path(__file__).parent
        / "config_tests/parse_global_config/with_dotgit_2/tests/.git",
        Path(__file__).parent / "config_tests/parse_global_config/with_dotgit_1/.git",
    ]

    for git_dir in git_dirs:
        git_dir.touch()

    cfg, cfg_path = parse_global_config(
        Path(__file__).parent / "config_tests/parse_global_config" / ispec_path
    )

    assert cfg == expected_cfg


def test_global_config_combine():
    specfile = parse(
        Path(__file__).parent / "config_tests/parse_global_config/combine/some.ispec",
        make_stream(
            [
                "---",
                "environment:",
                "    FROM_ISPEC: 1",
                "examples:",
                "    - FROM_ISPEC: 1",
                "---",
            ]
        ),
    )

    assert specfile.environment == {"FROM_ISPEC": 1}
    assert specfile.examples == [{"FROM_ISPEC": 1}]


def test_global_config_default():
    specfile = parse(
        Path(__file__).parent / "config_tests/parse_global_config/combine/some.ispec",
        make_stream(["---", "---"]),
    )

    assert specfile.environment == {"FROM_CONFIG": 1}
    assert specfile.examples == [{"FROM_CONFIG": 1}]
    assert specfile.settings.timeout_seconds == 99
    assert specfile.settings.include_dirs == [
        Path(__file__).parent / "config_tests/parse_global_config/includes",
        Path(__file__).parent / "config_tests/parse_global_config/combine",
    ]
    assert specfile.settings.fixture_dirs == [
        Path(__file__).parent / "config_tests/parse_global_config/fixtures",
        Path(__file__).parent / "config_tests/parse_global_config/combine",
    ]


def test_fixture():
    specfile = parse(
        Path(__file__).parent / "some.ispec",
        make_stream(
            [
                "---",
                "fixture: e2e/fixtures/create_user",
                "---",
            ]
        ),
    )

    assert specfile.fixture == "e2e/fixtures/create_user"
    assert not specfile.errors, specfile.errors
    assert specfile.fixture_specfile_pre
    assert len(specfile.fixture_specfile_pre.commands) == 2
    assert specfile.fixture_specfile_post
    assert len(specfile.fixture_specfile_post.commands) == 1
