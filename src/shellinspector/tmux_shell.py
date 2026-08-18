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

        # each instance gets its own tmux server (-L) rather than sharing
        # the ambient default one: tmux exits its server once its last
        # session is killed (the default exit-empty behavior), so sharing
        # a server between instances lets one instance's close() race
        # another's login() if the closing one happened to hold the last
        # remaining session.
        self._socket_name = f"si-{time.time_ns()}-{id(self)}"
        self._session_name = "main"
        # how many trailing lines of the pane (counting back from the
        # bottom) are not yet known to belong to a completed command;
        # _capture_pane() starts each capture -_unread_lines back so it
        # always includes any content still to be matched.
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

        result = subprocess.run(
            full_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )

        if self.verbose:
            print(f"+ {shlex.join(full_cmd)}")
            print(result.stdout.decode(errors="replace").strip())

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

        # Remote sessions are launched as a login shell (-l), so PATH and
        # other env setup from .profile/.bash_profile match what an
        # interactive `ssh host` session would get (e.g. ~/.local/bin on
        # PATH) -- pxssh's ssh-based login() gets this for free since sshd
        # itself starts a login shell; TmuxShell has to ask for it
        # explicitly since it launches bash directly as a tmux command.
        # Local sessions intentionally skip profile/rc files to keep them
        # predictable and match LocalShell's plain `/bin/bash` behavior.
        bash_args = (
            ["bash", "-l"] if self._is_remote else ["bash", "--noprofile", "--norc"]
        )

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

        self._tmux("kill-server", timeout=self.timeout)

        if self._is_remote and self._control_path:
            # this must run locally, not via _run() -- _run() always wraps
            # its args as a command to execute on the remote host, but
            # "ssh -O exit" needs to run locally against the control
            # socket to tear down the ControlMaster.
            subprocess.run(
                ["ssh", "-O", "exit", *self._ssh_opts(), self._ssh_target],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=self.timeout,
            )

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

        # every embedded newline we send is a real keystroke, so bash
        # echoes and re-prompts for each `\n`-separated segment; a plain
        # `; `-joined payload keeps that down to a single echoed line
        # (entirely before the start marker, so it never pollutes the
        # captured output). That breaks for a `line` containing a heredoc,
        # since its terminator must be alone on its line -- so only then is
        # `line` put on its own segment, isolated by real newlines, while
        # everything around it stays `; `-joined (and thus still only
        # echoed once, right before the start marker) since neither of
        # those fixed segments can themselves contain a heredoc.
        rc_and_end = f"rc=$?; printf '\\n{COMMAND_END}:{command_id}:%s\\n' \"$rc\""
        if "\n" in line:
            payload = (
                f"printf '\\n{COMMAND_START}:{command_id}\\n'\n{line}\n{rc_and_end}"
            )
        else:
            # an empty line would leave two bare `;` back to back (";;"),
            # which is a syntax error outside a case statement -- ":" is
            # bash's no-op builtin, so it keeps the payload valid without
            # changing the returncode/output of a genuinely empty command.
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

        # anchored to start-of-line so the echoed input line (which contains
        # this same marker text as a quoted printf argument, not preceded by
        # a newline) never matches -- only the marker's actual evaluated
        # output, which printf always prefixes with \n, does.
        re_start = re.compile(
            rf"^{re.escape(COMMAND_START)}:{re.escape(command_id)}$", re.MULTILINE
        )
        re_end = re.compile(
            rf"^{re.escape(COMMAND_END)}:{re.escape(command_id)}:(?P<rc>[0-9]+)$",
            re.MULTILINE,
        )
        # matches the echoed "<prompt> rc=$?; printf ..." line that appears
        # right before the end marker's real output whenever line contains
        # a heredoc (see above: that's the only case rc_and_end ends up on
        # its own echoed segment instead of being consumed silently).
        re_rc_and_end_echo = re.compile(
            rf"^.*{re.escape(rc_and_end)}$\n?", re.MULTILINE
        )

        deadline = time.monotonic() + self.timeout

        # self._unread_lines is a good starting guess (it's exactly enough
        # to cover the previous command's leftovers), but this command's
        # own output can easily scroll past it before we get to poll --
        # e.g. a one-line previous command followed by an `export` dumping
        # hundreds of lines pushes the start marker far below that initial
        # window. Since the start marker's distance from the current
        # bottom only grows as more output is appended after it, growing
        # the window whenever it's still missing always converges instead
        # of polling an unchanging, too-narrow capture forever.
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
            # line was sent as its own newline-separated segment, so bash
            # echoes it back keystroke-for-keystroke across exactly as many
            # physical lines as line itself has; skip that echoed block
            # rather than trying to match its rendering (which includes
            # bash's own "> " continuation prompt for heredoc bodies). +1
            # of the split count is the blank line printf(START) itself
            # ends with, right before the echo of line begins.
            command_output = command_output.split("\n", line.count("\n") + 2)[-1]
            command_output = re_rc_and_end_echo.sub("", command_output)

        command_output = command_output.strip("\n")

        # next capture starts fresh relative to a new "now", so remember
        # only the trailing content after our end marker (e.g. the next
        # prompt) that hasn't been consumed yet and must be re-included.
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
