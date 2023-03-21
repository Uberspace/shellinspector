import re
from dataclasses import dataclass
from pathlib import Path
from enum import Enum


class ExecutionMode(Enum):
    USER = "$"
    ROOT = "%"


class AssertMode(Enum):
    LITERAL = "="
    REGEX = "~"
    IGNORE = "_"


@dataclass
class Command:
    execution_mode: ExecutionMode
    command: str
    user: str
    host: str
    assert_mode: AssertMode
    expected: str
    source_file: Path
    source_line_no: int
    line: str

# parse a line like
#   [user@host]$ ls
# into ("user", "host", "$")
RE_PREFIX = re.compile(
    r"^"
    # optional [user@host]
    r"(?:\["
    r"(?P<user>[a-z]+)?"
    r"@"
    r"(?P<host>[a-z]+)?"
    r"\])?"
    # $ or %
    rf"(?P<execution_mode>[{''.join(m.value for m in ExecutionMode)}])"
    # nothing or _ or ~ or
    rf"(?P<assert_mode>[{''.join(m.value for m in AssertMode)}]?)"
    " "
)

def parse(path, lines):
    path = Path(path)

    current_command = None
    last_user = None
    last_host = "remote"

    for line_no, line in enumerate(lines, 1):

        def print_error(msg):
            print(f"{path.name}:{line_no} {msg}")
            print(line)

        is_comment = line.startswith("#")
        is_include = line.startswith("<")

        if is_comment:
            continue

        prefix = RE_PREFIX.match(line)

        # output ended, next command follows
        if (prefix or is_include) and current_command:
            yield current_command
            current_command = None

        if is_include:
            include_path = (path.parent / line[1:]).resolve()
            if not include_path.exists():
                print_error(
                    f"include error: file '{line}' (=> '{include_path}') does not exist"
                )
                return False
            yield from parse(include_path, include_path.read_text().splitlines())
            continue

        # output before very first command
        if not prefix and not current_command:
            print_error("syntax error: unknown prefix or no prefix")
            return False

        # start of command
        if prefix:
            command = line[prefix.span()[1] :]
            user, host, execution_mode, assert_mode = prefix.group(
                "user", "host", "execution_mode", "assert_mode"
            )

            execution_mode = ExecutionMode(execution_mode)
            assert_mode = AssertMode(assert_mode if assert_mode else AssertMode.LITERAL.value)

            if execution_mode == ExecutionMode.ROOT:
                user = "root"

            user = user or last_user
            host = host or last_host

            last_host = host

            if execution_mode == ExecutionMode.USER:
                last_user = user

            current_command = Command(
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
            current_command.expected += line + "\n"

    if current_command:
        yield current_command
