"""The container entrypoint is what makes a rebuild honest:

* it starts the worker pool alongside the web process, so a deploy can never
  serve the app with nothing claiming jobs;
* every slot gets a stable WORKER_ID, so a restarted process overwrites its own
  `workers` row instead of adding an outdated one;
* SIGTERM reaches the workers, so they can requeue their in-flight jobs instead
  of being SIGKILLed with a live lease left behind;
* a crashed slot is restarted in place, so the web keeps working instead of
  silently running with no workers.
"""

from __future__ import annotations

import os
import signal
import stat
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = ROOT / "docker-entrypoint.sh"


def _stub(bindir: Path, name: str, log: Path) -> None:
    """Stand-in for `python` / `uvicorn` that records TERM delivery."""
    path = bindir / name
    path.write_text(
        "#!/bin/sh\n"
        f'echo "{name} up worker_id=${{WORKER_ID:-none}}" >> "{log}"\n'
        f'trap \'echo "{name} term worker_id=${{WORKER_ID:-none}}" >> "{log}"; exit 0\' TERM INT\n'
        f'echo "{name} ready worker_id=${{WORKER_ID:-none}}" >> "{log}"\n'
        "while :; do sleep 0.05; done\n"
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _wait_for(log: Path, needle: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if needle in log.read_text():
            return
        time.sleep(0.05)
    raise AssertionError(f"entrypoint never logged {needle!r}:\n{log.read_text()}")


def test_entrypoint_labels_slots_and_forwards_term(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "log"
    log.touch()
    for name in ("python", "uvicorn"):
        _stub(bindir, name, log)

    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "WORKERS": "2"}
    proc = subprocess.Popen(
        ["sh", str(ENTRYPOINT)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for(log, "uvicorn ready")
        _wait_for(log, "python ready worker_id=worker-1")
        _wait_for(log, "python ready worker_id=worker-2")
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=10) == 0  # a requested stop is a clean exit
    finally:
        if proc.poll() is None:
            proc.kill()

    # Signal delivery is asynchronous: a stub handles TERM on its next `sleep`
    # wake-up, which can be after the entrypoint itself has exited.
    _wait_for(log, "python term worker_id=worker-1")
    _wait_for(log, "python term worker_id=worker-2")
    text = log.read_text()
    assert text.count("term worker_id=worker-") == 2  # both workers, not just PID 1
    assert "uvicorn term" in text


def test_entrypoint_restarts_a_crashed_worker(tmp_path):
    """A worker that exits must come back in place."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "log"
    log.touch()
    marker = tmp_path / "crashed-once"
    python = bindir / "python"
    python.write_text(
        "#!/bin/sh\n"
        f'echo "worker up worker_id=${{WORKER_ID:-none}}" >> "{log}"\n'
        f'if [ ! -e "{marker}" ]; then touch "{marker}"; '
        f'echo "worker crash" >> "{log}"; exit 7; fi\n'
        f'trap \'echo "worker term worker_id=${{WORKER_ID:-none}}" >> "{log}"; exit 0\' TERM INT\n'
        f'echo "worker ready worker_id=${{WORKER_ID:-none}}" >> "{log}"\n'
        "while :; do sleep 0.05; done\n"
    )
    python.chmod(python.stat().st_mode | stat.S_IEXEC)
    _stub(bindir, "uvicorn", log)

    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "WORKERS": "1",
        "WORKER_RESTART_DELAY": "0.1",
    }
    proc = subprocess.Popen(
        ["sh", str(ENTRYPOINT)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for(log, "worker crash")
        _wait_for(log, "worker ready worker_id=worker-1")
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=10) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
    _wait_for(log, "worker term worker_id=worker-1")


def test_worker_id_env_override(monkeypatch):
    from worker.main import _worker_id

    monkeypatch.setenv("WORKER_ID", "worker-1")
    assert _worker_id() == "worker-1"
    monkeypatch.delenv("WORKER_ID")
    assert _worker_id().startswith("worker-")
