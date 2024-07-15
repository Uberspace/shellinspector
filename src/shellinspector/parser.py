import dataclasses
import re
import typing
from contextlib import suppress
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


@dataclasses.dataclass
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


@dataclasses.dataclass
class Error:
    source_file: Path
    source_line_no: int
    source_line: str
    message: str


@dataclasses.dataclass
class Settings:
    timeout_seconds: int
    include_dirs: list[Path]
    fixture_dirs: list[Path]

    def __init__(self, timeout_seconds=5):
        self.timeout_seconds = timeout_seconds
        self.include_dirs = []
        self.fixture_dirs = []


@dataclasses.dataclass
class Specfile:
    path: Path
    commands: list[Command]
    errors: list[Error]
    environment: dict[str, str]
    examples: list[dict[str, str]]
    fixture: typing.Optional[str]
    fixture_specfile_pre: typing.Optional["Specfile"]
    fixture_specfile_post: typing.Optional["Specfile"]
    applied_example: dict
    settings: Settings

    def __init__(
        self, path, commands=None, errors=None, environment=None, examples=None
    ):
        self.path = Path(path)
        self.commands = commands or []
        self.errors = errors or []
        self.environment = environment or {}
        self.examples = examples or []
        self.fixture = None
        self.fixture_specfile_pre = None
        self.fixture_specfile_post = None
        self.applied_example = None
        self.settings = Settings()

    def copy(self):
        return Specfile(
            self.path,
            [dataclasses.replace(c) for c in self.commands],
            [dataclasses.replace(e) for e in self.errors],
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


def parse_yaml_multidoc(stream: typing.IO) -> tuple[dict, str]:
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


def include_file(
    specfile: Specfile, line_no, line, dirs: list[Path], file_path: Path
) -> typing.Optional[Specfile]:
    for include_dir in dirs:
        include_path = (include_dir / file_path).resolve()

        try:
            with open(include_path) as f:
                return parse(include_path, f)
        except FileNotFoundError:
            continue

        break
    else:
        dirs_str = [str(d) for d in dirs]
        specfile.errors.append(
            Error(
                specfile.path,
                line_no,
                line,
                f"error: {file_path} does not exist in any directory: {','.join(dirs_str)}",
            )
        )


def parse_commands(specfile: Specfile, commands: str) -> None:
    for line_no, line in enumerate(commands.splitlines(), 1):
        # comment
        if line.startswith("#"):
            continue

        # include
        if line.startswith("<"):
            included_specfile = include_file(
                specfile, line_no, line, specfile.settings.include_dirs, Path(line[1:])
            )
            if included_specfile:
                specfile.errors.extend(included_specfile.errors)
                specfile.commands.extend(included_specfile.commands)
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


def parse_global_config(
    ispec_path: typing.Union[str, Path]
) -> tuple[dict, typing.Optional[Path]]:
    search_path = Path(ispec_path)

    while str(search_path) != search_path.root:
        search_path = Path(search_path).parent

        try:
            with open(search_path / "shellinspector.yaml") as f:
                return yaml.safe_load(f), search_path / "shellinspector.yaml"
        except FileNotFoundError:
            pass

        if (search_path / ".git").exists():
            break

    return {}, None


def parse(path: typing.Union[str, Path], stream: typing.IO) -> Specfile:
    path = Path(path)
    specfile = Specfile(path)

    config, config_path = parse_global_config(path)

    frontmatter, commands = parse_yaml_multidoc(stream)

    # use values in frontmatter if they exist, otherwise use global config
    for key in ["examples", "environment", "fixture"]:
        try:
            value = frontmatter[key]
        except LookupError:
            value = config.get(key, None)

        if value is not None:
            setattr(specfile, key, value)

    frontmatter_settings = frontmatter.get("settings", {})
    global_settings = config.get("settings", {})

    path_setting_keys = ["include_dirs", "fixture_dirs"]

    for key in dataclasses.fields(specfile.settings):
        value = None

        with suppress(LookupError):
            value = global_settings[key.name]
            root_path = config_path.parent

        with suppress(LookupError):
            value = frontmatter_settings[key.name]
            root_path = specfile.path.parent

        if key.name in path_setting_keys:
            value = value or getattr(specfile.settings, key.name)
            value = [(root_path / Path(p)).resolve() for p in value]
            value.append(specfile.path.parent)

        if not value:
            continue

        setattr(specfile.settings, key.name, value)

    if specfile.fixture:
        specfile.fixture_specfile_pre = include_file(
            specfile,
            0,
            "fixture_pre",
            specfile.settings.fixture_dirs,
            Path(f"{specfile.fixture}_pre.ispec"),
        )

    parse_commands(specfile, commands)

    if specfile.fixture:
        specfile.fixture_specfile_post = include_file(
            specfile,
            0,
            "fixture_post",
            specfile.settings.fixture_dirs,
            Path(f"{specfile.fixture}_post.ispec"),
        )

    return specfile
