# TmuxShell

`TmuxShell` (`src/shellinspector/tmux_shell.py`) drives a shell session
inside a detached `tmux` session, either locally or over SSH. It's used
by `ShellRunner` for all command execution.

## Why tmux

A persistent tmux session survives SSH connection drops: the shell
keeps running (with its cwd, env vars, etc.) even if the controlling SSH
connection dies. `TmuxShell` just polls the detached session rather than
holding an interactive connection open.

## Command execution

There's no prompt detection. `run_command(line)` wraps `line` in sentinel
markers and polls `tmux capture-pane` until the end marker appears:

```
printf '\n__COMMAND_START__:<id>\n'
<line>
rc=$?; printf '\n__COMMAND_END__:<id>:%s\n' "$rc"
```

sent via `tmux send-keys`. The command's output is whatever falls
between the two markers' matches.

Normally these three lines (start-marker printf, `line`, end-marker printf)
are `; `-joined into one physical line before being sent, so bash only
draws its interactive prompt once per command instead of once per line. A
`line` containing a heredoc can't be joined that way, since its terminator
must be alone on its own physical line, so it's sent as-is across multiple
real lines instead.

Each `TmuxShell` instance runs its own tmux server (`-L <unique-socket>`)
rather than sharing the default one, so one instance's `close()` can't
race another's `login()`.

## Capture-pane addressing

`tmux capture-pane -S` line numbers are relative to the current bottom of
the pane, not absolute — content still in the live pane gets renumbered
as the pane advances. `TmuxShell` tracks `self._unread_lines`: after each
command, it remembers how many trailing lines might still be relevant and
starts the next capture that far back. This is always recomputed from
what was actually captured, so it self-corrects.

## Remote (SSH) mode

Passing `server=` makes `TmuxShell` drive `tmux` over SSH instead of as a
local subprocess, using an SSH ControlMaster (`ControlPersist=60`) so
repeated commands reuse one connection. `close()` tears down both the
tmux session and the ControlMaster.
