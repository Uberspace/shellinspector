import re
import typing
from dataclasses import dataclass
from dataclasses import replace
from enum import Enum
from pathlib import Path

import yaml


class ExecutionMode(Enum):
    USER = "$"
    ROOT = "%"
    PYTHON = "!"


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


@dataclass
class Specfile:
    path: Path
    commands: list[Command]
    errors: list[Error]
    environment: dict[str, str]
    examples: list[dict[str, str]]
    applied_example: dict

    def __init__(
        self, path, commands=None, errors=None, environment=None, examples=None
    ):
        self.path = Path(path)
        self.commands = commands or []
        self.errors = errors or []
        self.environment = environment or {}
        self.examples = examples or []
        self.applied_example = None

    def copy(self):
        return Specfile(
            self.path,
            [replace(c) for c in self.commands],
            [replace(e) for e in self.errors],
            self.environment.copy(),
            [e.copy() for e in self.examples],
        )

    def as_example(self, example):
        copy = self.copy()
        copy.applied_example = example

        for cmd in copy.commands:
            cmd.command = cmd.command.format(**example)
            cmd.line = cmd.line.format(**example)
            cmd.expected = cmd.expected.format(**example)

        return copy


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


def parse_yaml_multidoc(stream: typing.IO) -> tuple[str, str]:
    if stream.read(3) != "---":
        stream.seek(0)
        return {}, stream.read()
    else:
        stream.seek(0)

    loader = yaml.SafeLoader(stream)

    try:
        # load the 1st document (up to '---') as yaml ...
        frontmatter = loader.get_data()
        # ... and the rest as plain text, to be parsed later,
        # minus \x00 at the end added by the yaml parser as EOF
        commands = loader.buffer[loader.pointer + 1 : -1]
    finally:
        loader.dispose()

    if frontmatter is None:
        frontmatter = {}

    return frontmatter, commands


def parse_commands(specfile: Specfile, commands: str) -> None:
    for line_no, line in enumerate(commands.splitlines(), 1):
        # comment
        if line.startswith("#"):
            continue

        prefix = RE_PREFIX.match(line)

        # output before very first command
        if not prefix and not specfile.commands:
            specfile.errors.append(
                Error(
                    specfile.path,
                    line_no,
                    line,
                    "syntax error: output before first command, missing prefix?",
                )
            )
            continue

        # include
        if line.startswith("<"):
            include_path = (specfile.path.parent / line[1:]).resolve()

            try:
                with open(include_path) as f:
                    included_specfile = parse(include_path, f)

                specfile.errors.extend(included_specfile.errors)
                specfile.commands.extend(included_specfile.commands)
            except FileNotFoundError:
                specfile.errors.append(
                    Error(
                        specfile.path,
                        line_no,
                        line,
                        f"include error: {include_path} does not exist",
                    )
                )
            continue

        # start of a new command
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

            # reuse user and host from last command if not specified
            try:
                last_command = next(
                    cmd
                    for cmd in reversed(specfile.commands)
                    if cmd.execution_mode == execution_mode
                )
                user = user or last_command.user
                host = host or last_command.host
            except (StopIteration, IndexError):
                host = host or "remote"

            specfile.commands.append(
                Command(
                    execution_mode,
                    command,
                    user,
                    session_name,
                    host,
                    assert_mode,
                    "",
                    specfile.path,
                    line_no,
                    line,
                )
            )

            if not user and execution_mode == ExecutionMode.USER and host != "local":
                specfile.errors.append(
                    Error(
                        specfile.path,
                        line_no,
                        line,
                        "syntax error: command (and all before it) do not have a user specified",
                    )
                )
        else:
            # add output line to last command
            specfile.commands[-1].expected += line + "\n"

    for cmd in specfile.commands:
        if cmd.assert_mode == AssertMode.REGEX:
            # remove trailing new lines for regexes, see syntax.md
            cmd.expected = cmd.expected.rstrip("\n")


def parse(path: str, stream: typing.IO) -> Specfile:
    specfile = Specfile(path)

    frontmatter, commands = parse_yaml_multidoc(stream)

    specfile.examples = frontmatter.get("examples", [])
    specfile.environment = frontmatter.get("environment", {})

    parse_commands(specfile, commands)

    return specfile
