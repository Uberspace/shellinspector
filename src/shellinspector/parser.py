import re
from dataclasses import dataclass
from pathlib import Path

EXECUTION_MODES = {
    "$": "run_command_user",
    "%": "run_command_root",
}

ASSERT_MODES = {
    "": "literal",
    "~": "regex",
    "_": "ignore",
}


@dataclass
class Command:
    execution_mode: str
    command: str
    user: str
    host: str
    assert_mode: str
    expected: str
    source_file: Path
    source_line_no: int
    line: str


def parse(path, lines):
    last_command = None
    last_user = None
    re_prefix = re.compile(
        r"^"
        r"(?:\["
        r"(?P<user>[a-z]+)?"
        r"@"
        r"(?P<host>[a-z]+)?"
        r"\])?"
        rf"(?P<execution_mode>[{''.join(EXECUTION_MODES.keys())}])"
        rf"(?P<assert_mode>[{''.join(ASSERT_MODES.keys())}]?)"
        " "
    )

    path = Path(path)

    for line_no, line in enumerate(lines, 1):

        def print_error(msg):
            print(f"{path.name}:{line_no} {msg}")
            print(line)

        is_comment = line.startswith("#")
        is_include = line.startswith("<")

        prefix = re_prefix.match(line)

        if is_comment:
            continue

        if (prefix or is_include) and last_command:
            # output ended, next command follows
            yield last_command
            last_command = None

        if is_include:
            include_path = (path.parent / line).resolve()
            if not include_path.exists():
                print_error(
                    f"include error: file '{line}' (=> '{include_path}') does not exist"
                )
                return False
            yield from parse(include_path)

        if not prefix and not last_command:
            # output before very first command
            print_error("syntax error: unknown prefix or no prefix")
            return False

        if prefix:
            # start of command
            command = line[prefix.span()[1] :]
            user, host, execution_mode, assert_mode = prefix.group(
                "user", "host", "execution_mode", "assert_mode"
            )
            execution_mode = EXECUTION_MODES[execution_mode]
            assert_mode = ASSERT_MODES[assert_mode]

            if execution_mode == "run_command_root":
                user = "root"

            if user is None:
                user = last_user
                last_user = user

            if host is None:
                host = "remote"

            last_command = Command(
                execution_mode,
                command,
                user,
                host,
                assert_mode,
                "",
                path,
                line_no,
                line,
            )
        else:
            # output of last command
            last_command.expected += line + "\n"

    if last_command:
        yield last_command
