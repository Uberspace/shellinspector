import subprocess
from pathlib import Path

import pytest

from shellinspector.tmux_shell import TimeoutException
from shellinspector.tmux_shell import TmuxShell


@pytest.fixture
def shell():
    shell = TmuxShell(timeout=5)
    shell.login()
    yield shell
    shell.close()


@pytest.fixture
def ssh_key_path():
    path = Path(__file__).parent / "keys/id_ed25519"
    assert path.exists()
    return path


@pytest.fixture
def remote_shell(ssh_key_path):
    shell = TmuxShell(
        timeout=5,
        server="127.0.0.1",
        port=2222,
        username="root",
        ssh_key=ssh_key_path,
    )
    shell.login()
    yield shell
    shell.close()


def test_login_creates_tmux_session(shell):
    assert shell.closed is False

    result = subprocess.run(
        ["tmux", "-L", shell._socket_name, "list-sessions", "-F", "#{session_name}"],
        capture_output=True,
        text=True,
    )
    assert shell._session_name in result.stdout.splitlines()


def test_run_command_output():
    shell = TmuxShell(timeout=5)
    shell.login()

    output = shell.run_command("echo a && echo b")
    assert output == "a\nb"
    assert shell.get_returncode() == 0

    output = shell.run_command("echo c")
    assert output == "c"
    assert shell.get_returncode() == 0

    shell.close()


def test_run_command_returncode(shell):
    shell.run_command("false")
    assert shell.get_returncode() == 1

    shell.run_command("true")
    assert shell.get_returncode() == 0


def test_run_command_state_persists(shell):
    shell.run_command("cd /tmp")
    output = shell.run_command("pwd")
    assert output == "/tmp"


def test_run_command_after_output_heavy_command(shell):
    # a command producing many lines shifts later markers far back in
    # tmux's history-relative addressing; make sure the next command is
    # still located correctly afterwards.
    shell.run_command("seq 1 200")
    output = shell.run_command("echo after_seq")
    assert output == "after_seq"


def test_scrollback_not_cleared(shell):
    shell.run_command("echo first")
    shell.run_command("echo second")

    result = subprocess.run(
        [
            "tmux",
            "-L",
            shell._socket_name,
            "capture-pane",
            "-p",
            "-S",
            "-",
            "-t",
            shell._session_name,
        ],
        capture_output=True,
        text=True,
    )

    assert "first" in result.stdout
    assert "second" in result.stdout


def test_run_command_timeout():
    shell = TmuxShell(timeout=1, poll_interval=0.1)
    shell.login()

    with pytest.raises(TimeoutException):
        shell.run_command("sleep 5")

    assert shell.closed is True


def test_run_raises_on_nonzero_returncode(shell):
    # a failed tmux/ssh invocation (not the polled-for remote command)
    # must raise rather than be silently treated as success.
    with pytest.raises(subprocess.CalledProcessError):
        shell._tmux("capture-pane", "-t", "nonexistent-session", timeout=shell.timeout)


def test_run_raises_timeout_exception_on_hung_invocation(shell):
    # a hung underlying subprocess.run() call (the tmux/ssh invocation
    # itself, not the remote command being polled for) must surface as
    # TimeoutException, same as run_command's own polling-loop timeout.
    with pytest.raises(TimeoutException):
        shell._run(["sleep", "5"], timeout=0.2)


def test_close_kills_tmux_session():
    shell = TmuxShell(timeout=5)
    shell.login()
    socket_name = shell._socket_name

    shell.close()
    assert shell.closed is True

    # close() kills the whole (per-instance) tmux server, so no server
    # should be listening on this socket anymore.
    result = subprocess.run(
        ["tmux", "-L", socket_name, "list-sessions"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def test_close_is_idempotent(shell):
    shell.close()
    shell.close()
    assert shell.closed is True


def test_close_tolerates_already_dead_server(shell):
    # server can die out from under the controller (e.g. crashed, or
    # killed by something else); close() must still complete cleanly
    # rather than raising out of a cleanup path.
    subprocess.run(["tmux", "-L", shell._socket_name, "kill-server"])

    shell.close()

    assert shell.closed is True


def test_get_environment(shell):
    shell.run_command("export SPACES='a b'")

    env = shell.get_environment()
    assert len(env) > 5
    assert env["SPACES"] == "a b"


def test_set_environment(shell):
    shell.set_environment(
        {
            "VAR1": "aa",
            "VAR2": "bb",
        }
    )

    assert shell.run_command("echo $VAR1") == "aa"
    assert shell.run_command("echo $VAR2") == "bb"


def test_two_sessions_are_independent():
    shell1 = TmuxShell(timeout=5)
    shell1.login()
    shell2 = TmuxShell(timeout=5)
    shell2.login()

    shell1.set_environment({"ONLY_IN_1": "yes"})

    assert shell1.run_command("echo $ONLY_IN_1") == "yes"
    assert shell2.run_command("echo $ONLY_IN_1") == ""

    shell1.close()
    shell2.close()


def test_verbose_prints_commands_and_output(capsys):
    shell = TmuxShell(timeout=5, verbose=True)
    shell.login()

    shell.run_command("echo hello_verbose")

    captured = capsys.readouterr()
    assert "tmux" in captured.out
    assert "hello_verbose" in captured.out

    shell.close()


def test_not_verbose_by_default_prints_nothing(shell, capsys):
    shell.run_command("echo silent")

    captured = capsys.readouterr()
    assert captured.out == ""


def test_multiline_output(shell):
    output = shell.run_command("printf 'l1\\nl2\\nl3\\n'")
    assert output == "l1\nl2\nl3"


def test_empty_command(shell):
    output = shell.run_command("")
    assert output == ""
    assert shell.get_returncode() == 0

    output = shell.run_command("echo after_empty")
    assert output == "after_empty"


def test_command_id_uniqueness_does_not_confuse_markers(shell):
    # run a command whose *output* contains text that looks like a marker,
    # to make sure we don't stop early on it.
    output = shell.run_command("echo '__COMMAND_END__:notarealid:0'")
    assert output == "__COMMAND_END__:notarealid:0"
    assert shell.get_returncode() == 0


def test_heredoc(shell):
    # e.g. `cat >foo <<HERE\nfoo\nbar\nHERE`, as used throughout u8-host's
    # ispec files. The parser joins this into a single multi-line command
    # string before it reaches run_command.
    output = shell.run_command("cat <<HERE\nfoo\nbar\nHERE")
    assert output == "foo\nbar"


def test_nested_command_substitution(shell):
    # roles/generator-caddy/tests/create_delete_user.ispec uses
    # $(printf "%06d" $((16#$(openssl rand -hex 4) % 1000000))) - $() nested
    # two levels deep with arithmetic expansion mixed in.
    output = shell.run_command("echo $(echo $(echo nested))")
    assert output == "nested"


def test_single_and_double_quote_mix(shell):
    # roles/lang-php/tests/config_web.ispec mixes single and double quotes
    # with embedded $variables and escaped double-quotes in one line.
    output = shell.run_command("""echo '<?php $e = "value"; echo "$e\\n";'""")
    assert output == """<?php $e = "value"; echo "$e\\n";"""


def test_pipe_and_stderr_redirect(shell):
    # roles/lang-php/tests/composer.ispec pipes through multiple commands
    # and redirects 2>&1.
    output = shell.run_command("echo hello 2>&1 | tr a-z A-Z | grep HELLO")
    assert output == "HELLO"
    assert shell.get_returncode() == 0


def test_large_output(shell):
    # tests/check-system-services.ispec and friends pipe large listings
    # through several filters; make sure output beyond a single tmux
    # screenful round-trips intact.
    output = shell.run_command("seq 1 500")
    lines = output.splitlines()
    assert lines[0] == "1"
    assert lines[-1] == "500"
    assert len(lines) == 500


def test_large_output_after_tiny_command(shell):
    # a tiny command leaves self._unread_lines small; if the next command
    # produces much more output, the start marker scrolls past that
    # narrow initial window before the first poll, so the window must
    # grow to find it instead of polling an unchanging one until timeout.
    shell.run_command("echo x")
    output = shell.run_command("seq 1 500")
    lines = output.splitlines()
    assert lines[0] == "1"
    assert lines[-1] == "500"
    assert len(lines) == 500


def test_or_true_swallows_nonzero_exit(shell):
    # roles/sudo/tests/remove-sudo.ispec and others rely on `|| true` to
    # turn a failing command into a passing one.
    shell.run_command("false || true")
    assert shell.get_returncode() == 0


def test_semicolon_then_echo_rc(shell):
    # roles/passwd/tests/prevent-password-change.ispec runs
    # `passwd; echo $?` - a command whose own output includes the return
    # code of a prior, semicolon-separated command.
    output = shell.run_command("false; echo $?")
    assert output == "1"
    assert shell.get_returncode() == 0


def test_exported_function_persists(shell):
    # tests/mail-sending.ispec defines a shell function and exports it
    # with `export -f`, then calls it from a later command line.
    shell.run_command("greet() { echo hi $1; }; export -f greet")
    output = shell.run_command("greet world")
    assert output == "hi world"


def test_remote_run_command_output(remote_shell):
    output = remote_shell.run_command("echo a && echo b")
    assert output == "a\nb"
    assert remote_shell.get_returncode() == 0

    output = remote_shell.run_command("echo c")
    assert output == "c"
    assert remote_shell.get_returncode() == 0


def test_remote_run_command_state_persists(remote_shell):
    remote_shell.run_command("cd /tmp")
    output = remote_shell.run_command("pwd")
    assert output == "/tmp"


def test_remote_get_environment(remote_shell):
    remote_shell.run_command("export SPACES='a b'")

    env = remote_shell.get_environment()
    assert len(env) > 5
    assert env["HOME"] == "/root"
    assert env["SPACES"] == "a b"


def test_remote_login_is_login_shell(remote_shell):
    # remote sessions are launched as `bash -l` so PATH/profile setup
    # matches what an interactive `ssh host` session gets.
    output = remote_shell.run_command("shopt -q login_shell && echo yes || echo no")
    assert output == "yes"


def test_remote_control_master_reused_across_commands(remote_shell):
    # ControlPersist keeps one master connection alive; every run_command
    # after login() should reuse it instead of re-authenticating, so the
    # control socket must exist and stay the same throughout.
    control_path = remote_shell._control_path
    assert Path(control_path).exists()

    remote_shell.run_command("echo one")
    remote_shell.run_command("echo two")

    assert remote_shell._control_path == control_path
    assert Path(control_path).exists()


def test_remote_close_tears_down_control_master(ssh_key_path):
    shell = TmuxShell(
        timeout=5,
        server="127.0.0.1",
        port=2222,
        username="root",
        ssh_key=ssh_key_path,
    )
    shell.login()
    control_path = shell._control_path
    assert Path(control_path).exists()

    shell.close()

    assert shell.closed is True
    assert not Path(control_path).exists()


def test_two_remote_sessions_do_not_share_control_socket(ssh_key_path):
    shell1 = TmuxShell(
        timeout=5, server="127.0.0.1", port=2222, username="root", ssh_key=ssh_key_path
    )
    shell1.login()
    shell2 = TmuxShell(
        timeout=5, server="127.0.0.1", port=2222, username="root", ssh_key=ssh_key_path
    )
    shell2.login()

    assert shell1._control_path != shell2._control_path

    shell1.set_environment({"ONLY_IN_1": "yes"})
    assert shell1.run_command("echo $ONLY_IN_1") == "yes"
    assert shell2.run_command("echo $ONLY_IN_1") == ""

    shell1.close()
    shell2.close()
