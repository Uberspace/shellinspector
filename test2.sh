#!/usr/bin/env bash
set -euo pipefail

HOST="lutodev.uberspace.de"
SESSION="automated-$(date +%s)-$$"

# Large PTY so programs don't wrap output at 80 columns.
TMUX_WIDTH=1000
TMUX_HEIGHT=100

# Large enough for the expected terminal history.
HISTORY_LIMIT=1000000

SSH_OPTS=(
    -o ServerAliveInterval=10
    -o ServerAliveCountMax=3
)

ssh_remote() {
    ssh "${SSH_OPTS[@]}" "$HOST" "$@"
}

echo "Creating tmux session: $SESSION"

# Start a persistent interactive shell in a detached tmux session.
ssh_remote "
    tmux new-session -d \
        -s '$SESSION' \
        -x '$TMUX_WIDTH' \
        -y '$TMUX_HEIGHT'

    tmux set-option -t '$SESSION' history-limit '$HISTORY_LIMIT'
"

# Run a command in the existing shell.
run_command() {
    local cmd="$1"
    local id
    id="$(date +%s%N)-$$"

    echo "Running [$id]: $cmd" >&2

    # Clear previous scrollback.
    ssh_remote "tmux clear-history -t '$SESSION'"

    local payload
    payload="printf '\\n__COMMAND_START__:$id\\n'; $cmd; rc=\$?; printf '\\n__COMMAND_END__:$id:%s\\n' \"\$rc\""

    ssh_remote \
        "tmux send-keys -t '$SESSION' -- $(printf '%q' "$payload") Enter"

    # Only the ID goes to stdout, so command substitution gets exactly this.
    printf '%s\n' "$id"
}

# Wait until a particular command has completed and return its captured output.
collect_command() {
    local id="$1"

    while :; do
        local output

        if ! output="$(ssh_remote \
            "tmux capture-pane -p -S - -t '$SESSION' 2>/dev/null")"; then
            echo "SSH/session unavailable; retrying..." >&2
            sleep 1
            continue
        fi

        if grep -Fq "__COMMAND_END__:$id:" <<<"$output"; then
            printf '%s\n' "$output"
            return
        fi

        sleep 1
    done
}


###############################################################################
# Example
###############################################################################

cmd_id="$(run_command 'echo CMD1')"
output="$(collect_command "$cmd_id")"

printf '====================='
printf '%s\n' "$output"
printf '====================='
echo

###############################################################################
# Second command -- SAME interactive shell
###############################################################################

cmd_id="$(run_command 'echo CMD2')"
output="$(collect_command "$cmd_id")"

printf '====================='
printf '%s\n' "$output"
printf '====================='

###############################################################################
# Cleanup
###############################################################################

ssh_remote "tmux kill-session -t '$SESSION'" || true
