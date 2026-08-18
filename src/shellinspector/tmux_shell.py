import re
import shlex
import subprocess
import time
from pathlib import Path

from shellinspector.logging import get_logger

LOGGER = get_logger(Path(__file__).name)

TMUX_WIDTH = 1000
TMUX_HEIGHT = 100
HISTORY_LIMIT = 1_000_000

COMMAND_START = "__COMMAND_START__"
COMMAND_END = "__COMMAND_END__"


class TimeoutException(Exception):
    def __init__(self, output_so_far: str):
        self.output_so_far = output_so_far
        super().__init__()


class TmuxShell:
    """
    Drives a shell session inside a detached tmux session, either on the
    local machine or on a remote host over SSH. The tmux session outlives
    any individual command invocation (and any individual SSH connection,
    in the remote case), so shell state (cwd, env vars, ...) survives
    connection hiccups.
    """

    def __init__(
        self,
        timeout=5,
        poll_interval=0.15,
        server=None,
        port=22,
        username=None,
        ssh_key=None,
        verbose=False,
    ):
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.server = server
        self.port = port
        self.username = username
        self.ssh_key = ssh_key
        self.verbose = verbose

        self.closed = True

        # own tmux server (-L) per instance: the default server exits once
        # its last session closes, so sharing one risks a close() racing
        # another instance's login().
        self._socket_name = f"si-{time.time_ns()}-{id(self)}"
        self._session_name = "main"
        # trailing pane lines not yet known to belong to a completed
        # command; _capture_pane() starts each capture this far back.
        self._unread_lines = 0
        self._control_path = None

    @property
    def _is_remote(self):
        return self.server is not None

    def _run(self, args, timeout=None):
        """Run a local command, or the same command wrapped in ssh if remote."""
        if self._is_remote:
            ssh_cmd = ["ssh", *self._ssh_opts(), self._ssh_target]
            payload = " ".join(shlex.quote(a) for a in args)
            full_cmd = [*ssh_cmd, "--", payload]
        else:
            full_cmd = args

        try:
            result = subprocess.run(
                full_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as ex:
            if self.verbose:
                print(f"+ {shlex.join(full_cmd)}")
                print((ex.output or b"").decode(errors="replace").strip())
            raise TimeoutException((ex.output or b"").decode(errors="replace")) from ex

        if self.verbose:
            print(f"+ {shlex.join(full_cmd)}")
            print(result.stdout.decode(errors="replace").strip())

        if result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, full_cmd, output=result.stdout
            )

        return result

    def _tmux(self, *args, timeout=None):
        return self._run(["tmux", "-L", self._socket_name, *args], timeout=timeout)

    def _ssh_opts(self):
        opts = [
            "-o",
            "ServerAliveInterval=10",
            "-o",
            "ServerAliveCountMax=3",
            "-o",
            f"ControlPath={self._control_path}",
            "-o",
            "ControlMaster=auto",
            "-o",
            "ControlPersist=60",
            "-p",
            str(self.port),
        ]

        if self.ssh_key:
            opts += ["-i", str(self.ssh_key)]

        return opts

    @property
    def _ssh_target(self):
        return f"{self.username}@{self.server}" if self.username else self.server

    def login(self):
        if self._is_remote:
            self._control_path = f"/tmp/si-tmux-ctl-{time.time_ns()}-{id(self)}"
            # establish the multiplexed master connection up front
            self._run(["true"], timeout=self.timeout)

        self._unread_lines = 0

        # login shell (-l) for remote sessions so PATH/profile setup
        # matches an interactive `ssh host` session (e.g. ~/.local/bin).
        bash_args = (
            ["bash", "-l"] if self._is_remote else ["bash", "--noprofile", "--norc"]
        )

        # PS1 is inherited from the environment; --noprofile/--norc/-l
        # don't reset it. An exported PS1 with syntax bash can't parse
        # (e.g. a zsh prompt with $(...) substitutions) gets evaluated on
        # every prompt redraw and pollutes captured output, so pin it.
        bash_args = ["env", "PS1=[\\u@\\h \\W]\\$ ", *bash_args]

        self._tmux(
            "new-session",
            "-d",
            "-s",
            self._session_name,
            "-x",
            str(TMUX_WIDTH),
            "-y",
            str(TMUX_HEIGHT),
            *bash_args,
            timeout=self.timeout,
        )
        self._tmux(
            "set-option",
            "-t",
            self._session_name,
            "history-limit",
            str(HISTORY_LIMIT),
            timeout=self.timeout,
        )

        self.closed = False

        return True

    def close(self):
        if self.closed:
            return

        # best-effort cleanup: the server may already be gone (e.g. killed
        # by something else) or unreachable, so a failure here shouldn't
        # stop close() from completing or raise out of a cleanup path.
        try:
            self._tmux("kill-server", timeout=self.timeout)
        except (subprocess.CalledProcessError, TimeoutException):
            pass

        if self._is_remote and self._control_path:
            # run locally, not via _run(): _run() always wraps args as a
            # remote command, but "ssh -O exit" must run locally against
            # the control socket to tear down the ControlMaster.
            try:
                subprocess.run(
                    ["ssh", "-O", "exit", *self._ssh_opts(), self._ssh_target],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=self.timeout,
                )
            except subprocess.TimeoutExpired:
                pass

        self.closed = True

    def _capture_pane(self, lines_back):
        """
        Capture from lines_back lines back through the current bottom of
        the pane (-S -N -E -).
        """
        start = f"-{lines_back}" if lines_back else "-"

        result = self._tmux(
            "capture-pane",
            "-p",
            "-S",
            start,
            "-E",
            "-",
            "-t",
            self._session_name,
            timeout=self.timeout,
        )
        return result.stdout.decode()

    def run_command(self, line):
        command_id = f"{time.time_ns()}-{id(self)}"

        # single-line payload avoids extra echoed prompt redraws; only a
        # heredoc forces `line` onto its own newline-isolated segment,
        # since its terminator must be alone on its physical line.
        rc_and_end = f"rc=$?; printf '\\n{COMMAND_END}:{command_id}:%s\\n' \"$rc\""
        if "\n" in line:
            payload = (
                f"printf '\\n{COMMAND_START}:{command_id}\\n'\n{line}\n{rc_and_end}"
            )
        else:
            # empty line leaves ";;" (syntax error outside case); ":" is
            # a no-op that keeps the payload valid.
            command = line or ":"
            payload = (
                f"printf '\\n{COMMAND_START}:{command_id}\\n'; {command}; {rc_and_end}"
            )

        self._tmux(
            "send-keys",
            "-t",
            self._session_name,
            "--",
            payload,
            "Enter",
            timeout=self.timeout,
        )

        # anchored to start-of-line so the echoed printf argument (not
        # preceded by a newline) never matches, only its evaluated output.
        re_start = re.compile(
            rf"^{re.escape(COMMAND_START)}:{re.escape(command_id)}$", re.MULTILINE
        )
        re_end = re.compile(
            rf"^{re.escape(COMMAND_END)}:{re.escape(command_id)}:(?P<rc>[0-9]+)$",
            re.MULTILINE,
        )
        # matches the echoed "<prompt> rc=$?; printf ..." line right before
        # the end marker's real output.
        re_rc_and_end_echo = re.compile(
            rf"^.*{re.escape(rc_and_end)}$\n?", re.MULTILINE
        )

        deadline = time.monotonic() + self.timeout

        # grow the search window until the start marker is found, so it
        # always converges instead of polling a too-narrow capture forever.
        search_lines = self._unread_lines

        while True:
            output = self._capture_pane(search_lines)

            start_match = re_start.search(output)

            end_match = None
            for m in re_end.finditer(output):
                end_match = m

            if start_match and end_match:
                break

            if not start_match:
                search_lines = max(search_lines, 1) * 2

            if time.monotonic() > deadline:
                self.close()
                raise TimeoutException(output)

            time.sleep(self.poll_interval)

        command_output = output[start_match.end() : end_match.start()]

        if "\n" in line:
            # bash echoes line back across as many physical lines as it has
            # (plus its own "> " heredoc continuation prompts); skip that
            # echoed block rather than pattern-matching it. +2 accounts for
            # printf(START)'s own blank line plus the split-count offset.
            command_output = command_output.split("\n", line.count("\n") + 2)[-1]
            command_output = re_rc_and_end_echo.sub("", command_output)

        command_output = command_output.strip("\n")

        # trailing content after the end marker (e.g. the next prompt) that
        # the next capture must still include.
        self._unread_lines = output[end_match.end() :].count("\n")

        self._last_returncode = int(end_match.group("rc"))

        return command_output

    def get_returncode(self):
        return self._last_returncode

    def get_environment(self):
        output = self.run_command("export")

        env = {}

        for line in output.splitlines():
            line = line.removeprefix("export ")
            line = line.removeprefix("declare -x ")
            k, _, v = line.partition("=")

            if not v:
                continue

            try:
                env[k] = " ".join(shlex.split(v))
            except ValueError:
                LOGGER.debug(
                    "Could not get value of env variable %s, continuing anyway. Original value: %s",
                    k,
                    v,
                )

        return env

    def set_environment(self, context):
        for k, v in context.items():
            self.run_command(f"export {k}={shlex.quote(str(v))}")
