import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


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
    session_name: str
    host: str
    assert_mode: AssertMode
    expected: str
    source_file: Path
    source_line_no: int
    line: str

    @property
    def line_count(self):
        # TODO: replace this with .removesuffix("\n").count("\n")+1 once we drop py3.7
        count = self.expected.count("\n")
        if self.expected and self.expected[-1] != "\n":
            count += 1
        return count

    @property
    def short(self):
        return f"{self.execution_mode.name}({self.user}@{self.host}) `{self.command}` (expect {self.line_count} lines, {self.assert_mode.name})"


@dataclass
class Error:
    source_file: Path
    source_line_no: int
    source_line: str
    message: str


# parse a line like
#   [user@host]$ ls
# into ("user", "host", "$")
RE_PREFIX = re.compile(
    r"^"
    # optional [user@host]
    r"(?:\["
    r"(?P<user>[a-z]+)?"
    r"(?::(?P<session_name>[a-z0-9]+))?"
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

    errors = []
    commands = []

    for line_no, line in enumerate(lines, 1):
        # comment
        if line.startswith("#"):
            continue

        prefix = RE_PREFIX.match(line)

        # output before very first command
        if not prefix and not commands:
            errors.append(
                Error(
                    path,
                    line_no,
                    line,
                    "syntax error: output before first command, missing prefix?",
                )
            )
            continue

        # include
        if line.startswith("<"):
            include_path = (path.parent / line[1:]).resolve()

            if not include_path.exists():
                errors.append(
                    Error(
                        path,
                        line_no,
                        line,
                        f"include error: {include_path} does not exist",
                    )
                )
            else:
                include_errors, include_commands = parse(
                    include_path, include_path.read_text().splitlines()
                )
                errors.extend(include_errors)
                commands.extend(include_commands)

            continue

        # start of command
        if prefix:
            command = line[prefix.span()[1] :]
            user, session_name, host, execution_mode, assert_mode = prefix.group(
                "user", "session_name", "host", "execution_mode", "assert_mode"
            )

            execution_mode = ExecutionMode(execution_mode)
            assert_mode = AssertMode(
                assert_mode if assert_mode else AssertMode.LITERAL.value
            )

            if execution_mode == ExecutionMode.ROOT:
                user = "root"

            try:
                last_command = next(
                    cmd
                    for cmd in reversed(commands)
                    if cmd.execution_mode == execution_mode
                )
                user = user or last_command.user
                host = host or last_command.host
            except (StopIteration, IndexError):
                host = host or "remote"

            commands.append(
                Command(
                    execution_mode,
                    command,
                    user,
                    session_name,
                    host,
                    assert_mode,
                    "",
                    path,
                    line_no,
                    line,
                )
            )
        else:
            # add output line to last command
            commands[-1].expected += line + "\n"

    for cmd in commands:
        if cmd.assert_mode == AssertMode.REGEX:
            # remove trailing new lines for regexes, see syntax.md
            cmd.expected = cmd.expected.rstrip("\n")

    return (errors, commands)
