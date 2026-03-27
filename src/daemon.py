#!/usr/bin/env python3
"""
BeeMode Daemon — Dual-FIFO Orchestration Runner
==============================================

Key fixes (v2.2):
  • Dual FIFO: daemon reads IN / writes OUT — no read-write deadlock
  • Both ends open with O_RDWR so FIFO never blocks on open()
  • Results written to /tmp/beemode_honey_log.jsonl

IPC protocol:
  FIFO_IN  (daemon → main agent):  EXEC|<task_id>|<worker>|<action>
  FIFO_OUT (main agent → daemon):  DONE|<task_id>|<result>

Logs:
  /tmp/beemode_honey_log.jsonl — one JSON dict per line, each Honey Fetch record
"""

import os
import sys
import json
import time
import signal
import select
import errno
import argparse
from datetime import datetime
from typing import Optional

FIFO_IN  = "/tmp/beemode_in.fifo"
FIFO_OUT = "/tmp/beemode_out.fifo"
LOG_FILE = "/tmp/beemode_honey_log.jsonl"


def ts():
    return datetime.now().strftime("%H:%M:%S")


def log(*args, prefix="[BEE]"):
    line = f"[{ts()}] {prefix} {' '.join(str(a) for a in args)}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


class NonBlockingFIFO:
    """Non-blocking FIFO using O_RDWR to avoid deadlock."""

    def __init__(self, path: str, rd: bool = True, wr: bool = False):
        self.path    = path
        self._buffer = []

        # O_RDWR: never blocks on open (critical fix!)
        flags = os.O_RDWR | os.O_NONBLOCK
        try:
            os.mkfifo(path)
        except FileExistsError:
            pass
        self._fd = os.open(path, flags)
        log(f"FIFO opened: {path} (fd={self._fd})", prefix="[FIFO]")

    def read_all(self) -> list[str]:
        lines = []
        try:
            data = os.read(self._fd, 8192).decode("utf-8", errors="replace")
            if data:
                parts = data.split("\n")
                # keep incomplete tail in buffer
                if parts and not parts[-1].endswith("\n"):
                    self._buffer = [parts[-1]]
                    parts = parts[:-1]
                else:
                    self._buffer.clear()
                lines = [l.strip() for l in parts if l.strip()]
        except OSError as e:
            if e.errno not in (errno.EAGAIN, errno.EWOULDBLOCK):
                log(f"FIFO read error: {e}", prefix="[FIFO-ERR]")
        return lines

    def write(self, msg: str) -> bool:
        try:
            os.write(self._fd, (msg + "\n").encode("utf-8"))
            return True
        except OSError as e:
            if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                return False
            log(f"FIFO write error: {e}", prefix="[FIFO-ERR]")
            return False

    def close(self):
        try:
            os.close(self._fd)
        except Exception:
            pass


def write_fifo(path: str, msg: str) -> bool:
    try:
        flags = os.O_RDWR | os.O_NONBLOCK
        try:
            os.mkfifo(path)
        except FileExistsError:
            pass
        fd = os.open(path, flags)
        try:
            os.write(fd, (msg + "\n").encode())
        finally:
            os.close(fd)
        return True
    except OSError:
        return False


def send_exec(fifo_in: NonBlockingFIFO, task_id: str, worker: str, action: str) -> bool:
    msg = f"EXEC|{task_id}|{worker}|{action}"
    ok = fifo_in.write(msg)
    if ok:
        log(f"[→ main] EXEC task={task_id} worker={worker}", prefix="[FIFO]")
    else:
        log(f"[→ main] FIFO 写满，{worker} 等待中...", prefix="[FIFO]")
    return ok


def wait_done(fifo_out: NonBlockingFIFO, task_id: str, timeout: float = 0.3) -> Optional[dict]:
    waited = 0
    while True:
        for line in fifo_out.read_all():
            if line.startswith("DONE|"):
                parts = line.split("|", 3)
                if len(parts) >= 2 and parts[1] == task_id:
                    return {"task_id": parts[1], "result": parts[2] if len(parts) > 2 else ""}
        waited += 1
        if waited * 0.3 >= timeout:
            return None
        time.sleep(0.1)


def run_daemon(phases: list[dict], workspace: str):
    log("=" * 55)
    log("🐝 BeeMode v2.2 Daemon 启动")
    log("=" * 55)
    log(f"FIFO_IN:  {FIFO_IN}")
    log(f"FIFO_OUT: {FIFO_OUT}")
    log(f"LOG_FILE: {LOG_FILE}")

    # Init FIFO
    fifo_in  = NonBlockingFIFO(FIFO_IN, rd=True, wr=False)
    fifo_out = NonBlockingFIFO(FIFO_OUT, rd=False, wr=True)

    # Clear log
    try:
        os.remove(LOG_FILE)
    except FileExistsError:
        pass

    # Graceful shutdown
    def on_signal(signum, frame):
        log("[🛑 SIGTERM] 优雅停止...")
        fifo_in.close()
        fifo_out.close()
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT,  on_signal)

    fetch_counter = [0]
    stop_flag     = [False]

    def dispatch_one(task_id: str, worker: str, action: str,
                     loop: int) -> dict:
        fetch_counter[0] += 1
        fid = fetch_counter[0]

        log(f"[🍯 #{fid}] {worker} START — {action[:50]}", prefix="[FETCH]")
        log(f"[📤→main] task={task_id} worker={worker}", prefix="[FIFO]")

        ok = send_exec(fifo_in, task_id, worker, action)
        if not ok:
            log(f"[⚠️ FIFO 满] {worker} 跳过", prefix="[FIFO]")

        result = wait_done(fifo_out, task_id, timeout=0.5)
        if result:
            log(f"[✅ #{fid}] {worker} DONE", prefix="[FETCH]")
        else:
            log(f"[⏳ #{fid}] {worker} 无 DONE 回报（main 可能未响应）", prefix="[FETCH]")

        return {
            "fetch_id": fid,
            "worker":   worker,
            "task_id":  task_id,
            "result":   result or {},
        }

    # Main loop
    total = len(phases)
    log(f"[🌸] {total} 个阶段")

    try:
        for phase_idx, phase in enumerate(phases, 1):
            phase_name = phase.get("name", f"Phase-{phase_idx}")
            workers    = phase.get("workers", [])
            loops      = phase.get("loops", 1)
            mode       = phase.get("mode", "sequential")

            log(f"[🌸 Phase {phase_idx}/{total}] {phase_name}")
            log(f"       {loops} loops × {len(workers)} [{mode}]")

            for loop in range(1, loops + 1):
                if stop_flag[0]:
                    break
                log(f"[── Loop {loop}/{loops} ──]")

                for w in workers:
                    if stop_flag[0]:
                        break
                    task_id = f"fetch-{fetch_counter[0]+1:03d}"
                    name    = w.get("name", "?")
                    action  = w.get("action", "")
                    dispatch_one(task_id, name, action, loop)
                    print()

    finally:
        fifo_in.close()
        fifo_out.close()
        log(f"[📊] 累计 Fetches: {fetch_counter[0]}")
        log("[👋 Daemon 退出]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BeeMode Daemon")
    parser.add_argument("--workspace", default="~/.openclaw/workspace-codex2")
    parser.add_argument("--demo",    action="store_true")
    args = parser.parse_args()

    phases = []
    if args.demo:
        phases = [
            {"name": "Demo", "workers": [
                {"name": "worker-A", "action": "任务A"},
                {"name": "worker-B", "action": "任务B"},
            ], "loops": 2, "mode": "sequential"},
        ]

    run_daemon(phases, workspace=args.workspace)
