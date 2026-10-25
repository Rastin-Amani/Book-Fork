#!/bin/sh
# One container: the web process plus N supervised translation workers.
#
# The Docker CMD is this script, so every build and redeploy starts a worker
# pool — a deployment can never serve the app with nothing claiming jobs.
#
#   * each slot has a stable WORKER_ID, so a restarted process overwrites its
#     own `workers` row instead of leaving a stale heartbeat behind;
#   * SIGTERM is forwarded to every child, so `docker stop` lets a worker
#     requeue its in-flight job instead of being SIGKILLed with a live lease;
#   * a crashed slot is restarted in place, so a worker crash does not leave
#     the web serving while every job sits queued.
set -e

: "${WORKERS:=1}"
: "${WORKER_RESTART_DELAY:=5}"
echo "entrypoint: starting ${WORKERS} worker process(es) + web"

pids=""
web_pid=""

stop() {
  trap - TERM INT
  # Unquoted on purpose: word-split into one pid per argument.
  # shellcheck disable=SC2086
  kill -TERM $pids $web_pid 2>/dev/null || true
  wait
  exit 0
}
trap stop TERM INT

run_slot() {
  slot="$1"
  child=""
  stopping=0
  trap 'stopping=1; if [ -n "$child" ]; then kill -TERM "$child" 2>/dev/null || true; wait "$child" 2>/dev/null || true; fi' TERM INT
  while [ "$stopping" -eq 0 ]; do
    WORKER_ID="worker-$slot" python -m worker.main &
    child=$!
    status=0
    wait "$child" || status=$?
    child=""
    if [ "$stopping" -eq 1 ] || [ "$status" -eq 0 ]; then
      return 0
    fi
    echo "entrypoint: worker-$slot exited with status $status — restarting in ${WORKER_RESTART_DELAY}s" >&2
    sleep "$WORKER_RESTART_DELAY" &
    child=$!
    wait "$child" || true
    child=""
  done
}

i=1
while [ "$i" -le "$WORKERS" ]; do
  run_slot "$i" &
  pids="$pids $!"
  i=$((i + 1))
done

uvicorn app.main:app --host 0.0.0.0 --port 8000 &
web_pid="$!"
pids="$pids $web_pid"

# Web is the container's lifecycle anchor: if it exits, take the pool down too,
# and keep its exit status so a crashed web is not reported as a clean stop.
web_status=0
wait "$web_pid" || web_status=$?
# shellcheck disable=SC2086
kill -TERM $pids 2>/dev/null || true
wait || true
exit "$web_status"
