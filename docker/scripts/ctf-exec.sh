#!/bin/bash
# /usr/local/bin/ctf-exec
# Visible command execution helper for CTF Desktop Agent.
#
# Runs commands inside the tmux terminal so they are visible on the noVNC
# desktop, while capturing stdout/stderr/exit_code to files for the API.
#
# Usage: ctf-exec <exec_id> <base_dir> [working_dir]
# The actual command is read from <base_dir>/<exec_id>.cmd

set -u

EXEC_ID="$1"
BASE_DIR="$2"
WORK_DIR="${3:-}"

CMD_FILE="${BASE_DIR}/${EXEC_ID}.cmd"
STDOUT_FILE="${BASE_DIR}/${EXEC_ID}.stdout"
STDERR_FILE="${BASE_DIR}/${EXEC_ID}.stderr"
RC_FILE="${BASE_DIR}/${EXEC_ID}.rc"

# Read the command from file (avoids shell escaping issues with tmux send-keys)
if [ ! -f "$CMD_FILE" ]; then
    echo "" > "$STDOUT_FILE"
    echo "Command file not found: $CMD_FILE" > "$STDERR_FILE"
    echo "1" > "$RC_FILE"
    exit 1
fi

COMMAND=$(cat "$CMD_FILE")

# Change to working directory if specified
if [ -n "$WORK_DIR" ]; then
    cd "$WORK_DIR" 2>/dev/null || {
        echo "" > "$STDOUT_FILE"
        echo "Failed to cd to: $WORK_DIR" > "$STDERR_FILE"
        echo "1" > "$RC_FILE"
        exit 1
    }
fi

# Display the command with a colored prompt
echo -e "\033[1;32m\$\033[0m \033[1;37m${COMMAND}\033[0m"

# Execute: tee stdout to file + terminal, pipe stderr through a FIFO
STDERR_FIFO="${BASE_DIR}/${EXEC_ID}.fifo"
mkfifo "$STDERR_FIFO" 2>/dev/null

# Background: tee stderr to file while also showing it in terminal
tee "$STDERR_FILE" < "$STDERR_FIFO" >&2 &
TEE_PID=$!

# Run the command: stdout -> tee (terminal + file), stderr -> FIFO
eval "$COMMAND" 2>"$STDERR_FIFO" | tee "$STDOUT_FILE"
CMD_EXIT=${PIPESTATUS[0]}

# Wait for stderr tee to finish
wait $TEE_PID 2>/dev/null

# Clean up FIFO
rm -f "$STDERR_FIFO"

# Write exit code last — this is the completion signal
echo "$CMD_EXIT" > "$RC_FILE"
