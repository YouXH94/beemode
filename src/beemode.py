#!/usr/bin/env python3
"""
BeeMode — OpenClaw Multi-Agent Orchestrator
==========================================

A Python orchestration layer for managing multi-agent workflows
using OpenClaw's sessions_spawn API.

Design principles:
  • Honey Fetch: each sub-agent completion + next-round dispatch = 1 Honey Fetch
  • Conditional dispatch: agent results ({inject_task, skip_phase, halt})
    dynamically determine the next worker
  • No mid-loop human confirmation unless explicitly requested
  • Stop command available at any time
  • Dual-FIFO communication for reliable IPC

Usage (from OpenClaw main agent):
  from beemode import BeeMode

  bee = BeeMode(workspace="/path/to/project")
  bee.set_fetch_callback(lambda f: print(f"Done: {f.worker}"))
  bee.run_phases(PHASES)
"""

import json
import time
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, Callable


# ── Constants ──────────────────────────────────────────────────────────────

WORKSPACE = "~/.openclaw/workspace-codex2"
BEE_LOG   = "/tmp/beemode_honey_log.jsonl"


# ── Data Models ────────────────────────────────────────────────────────────

@dataclass
class HoneyFetch:
    """One complete Honey Fetch record."""
    fetch_id:    int
    loop:        int
    worker:       str
    action:       str
    status:       str          # running | done | halted | injected
    progress:     float = 0.0
    message:      str   = ""
    result:       Optional[dict] = None
    injected_by:  Optional[str] = None
    ts_start:     str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))
    ts_end:       Optional[str] = None


# ── BeeMode Core ─────────────────────────────────────────────────────────

class BeeMode:
    """
    Orchestrator for multi-agent workflows.

    Key methods:
      run_phases(phases)    — Start the full orchestration
      inject_now(task_dict) — Inject a task into the next round (high priority)
      stop(reason)          — Stop all loops gracefully
      status()              — Current state dict
    """

    def __init__(self, workspace: str = WORKSPACE):
        self.workspace = workspace
        self.fetches: list[HoneyFetch] = []
        self.fetch_counter = 0
        self.loop_count   = 0
        self._running     = False
        self._halted      = False
        self._halt_reason = ""
        self._stop_flag   = threading.Event()
        self._injected: list[dict] = []      # external inject queue
        self._skip_phases: set[str] = set()
        self._inject_lock  = threading.Lock()
        self._callbacks: list[Callable] = []
        self._pending_results: dict[str, dict] = {}

    # ── Public API ──────────────────────────────────────────────────────

    def inject_now(self, name: str, action: str, task: str = "",
                    priority: str = "high", condition: str = ""):
        """
        Inject a task into the next round of execution.

        Args:
            name:     Worker name (display only)
            action:   Short action description
            task:     Full task prompt (sent to sub-agent)
            priority: "high" (front of queue) or "normal"
            condition: Optional unlock condition
        """
        with self._inject_lock:
            self._injected.append({
                "name":      name,
                "action":    action,
                "task":      task,
                "priority": priority,
                "condition": condition,
            })
        self._log("🆕", f"[插队] {name} [priority={priority}]")

    def stop(self, reason: str = "用户手动停止"):
        """Stop all loops after current worker finishes."""
        self._log("🛑", f"[停止] 原因: {reason}")
        self._halted      = True
        self._halt_reason = reason
        self._stop_flag.set()

    def add_fetch_callback(self, cb: Callable[[HoneyFetch], None]):
        """Register a callback called after each Honey Fetch completes."""
        self._callbacks.append(cb)

    def status(self) -> dict:
        """Return current orchestration state."""
        return {
            "running":        self._running,
            "halted":         self._halted,
            "halt_reason":    self._halt_reason,
            "stop_set":        self._stop_flag.is_set(),
            "total_fetches":   self.fetch_counter,
            "loop":            self.loop_count,
            "skip_phases":     list(self._skip_phases),
            "pending_injects": [t["name"] for t in self._injected],
        }

    # ── Private ─────────────────────────────────────────────────────

    def _log(self, emoji: str, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {emoji} {msg}"
        print(line, flush=True)

    def _save(self, fetch: HoneyFetch):
        self.fetches.append(fetch)
        with open(BEE_LOG, "a") as f:
            f.write(json.dumps(asdict(fetch), ensure_ascii=False) + "\n")

    def _fire_callbacks(self, fetch: HoneyFetch):
        for cb in self._callbacks:
            try:
                cb(fetch)
            except Exception:
                pass

    def _should_stop(self) -> bool:
        return self._stop_flag.is_set()

    # ── dispatch ────────────────────────────────────────────────────

    def dispatch(self, worker: dict, context: dict | None = None) -> dict:
        """
        Execute one worker task (one Honey Fetch).

        The real implementation delegates to sessions_spawn from the
        OpenClaw main agent.  This class manages orchestration only.

        Agent can return control directives:
          { inject_task: {...}, skip_phase: "Phase-X", halt: true }
        """
        name   = worker.get("name", "unknown")
        action = worker.get("action", worker.get("task", "")[:60])
        task   = worker.get("task", "")

        if self._should_stop():
            return {"worker": name, "halt": True, "reason": "stop_flag"}

        self.fetch_counter += 1
        fid = self.fetch_counter

        fetch = HoneyFetch(
            fetch_id=fid,
            loop=self.loop_count,
            worker=name,
            action=action,
            status="running",
            progress=0.0,
            message=f"#{fid} {name}",
        )
        self._save(fetch)
        self._log("🍯", f"#{fid} [{name}] START — {action[:50]}")

        # ── Execute (sub-class or external override) ─────────────
        result = self._execute_fetch(worker, context)
        # ───────────────────────────────────────────────────────

        fetch.status   = "done"
        fetch.progress = 100.0
        fetch.result   = result
        fetch.ts_end   = datetime.now().strftime("%H:%M:%S")
        self._save(fetch)
        self._fire_callbacks(fetch)
        self._log("✅", f"#{fid} [{name}] DONE")

        injected = []
        skipped  = []

        # Agent: inject task
        if result.get("inject_task"):
            t = result["inject_task"]
            t["priority"] = t.get("priority", "normal")
            injected.append(t)
            self._log("🆕", f"[{name}] 注入: {t['name']}")

        # Agent: skip phase
        if result.get("skip_phase"):
            ph = result["skip_phase"]
            self._skip_phases.add(ph)
            skipped.append(ph)
            self._log("⏭", f"[{name}] 跳过: {ph}")

        return {
            "worker":   name,
            "fetch_id": fid,
            "result":   result,
            "injected": injected,
            "skipped":  skipped,
            "halt":     result.get("halt", False),
            "halt_reason": result.get("halt_reason", ""),
        }

    def _execute_fetch(self, worker: dict, context: dict | None) -> dict:
        """
        Override this method in a sub-class to plug in real sessions_spawn.
        Default implementation sleeps 0.3s (dry-run).
        """
        time.sleep(0.3)
        return {
            "status":   "ok",
            "halt":     False,
            "inject_task": None,
            "skip_phase":  None,
            "error_count": 0,
        }

    # ── Phase Runner ───────────────────────────────────────────────

    def run_phase(self, phase: dict, idx: int, total: int):
        phase_name = phase.get("name", f"Phase-{idx}")
        workers    = phase.get("workers", [])
        loops      = phase.get("loops", 1)
        mode       = phase.get("mode", "sequential")

        self._log("━" * 50, "")
        self._log("🌸", f"[Phase {idx}/{total}] {phase_name}")
        self._log("🌸", f"  {loops} loops × {len(workers)} workers [{mode}]")
        self._log("━" * 50, "")

        for loop in range(1, loops + 1):
            self.loop_count = loop
            if self._should_stop():
                self._log("🛑", f"Loop {loop} 停止")
                return

            self._log("──", f" Loop {loop}/{loops} ")

            if mode == "conditional":
                self._cond(workers, phase_name)
            else:
                self._seq(workers)

            print()

    def _seq(self, workers: list):
        for w in workers:
            if self._should_stop():
                return
            r = self.dispatch(w)
            if r.get("halt"):
                self._log("🛑", f"HALT: {r.get('halt_reason')}")
                return

    def _cond(self, workers: list, phase_name: str):
        """
        Conditional execution: after each worker, _handle_result
        may inject new tasks (inserted at front of pending) or
        return True to halt.
        """
        pending = list(workers)
        done_names: list[str] = []
        max_iters = len(workers) * 5
        iters = 0

        while pending and iters < max_iters:
            iters += 1

            if self._should_stop():
                self._log("🛑", f"[{phase_name}] 停止")
                return

            # ── External inject queue (from QQ "插队") ───────────
            with self._inject_lock:
                while self._injected:
                    t = self._injected.pop(0)
                    self._log("🆕", f"  → 执行插队: {t['name']}")
                    r = self.dispatch(t)
                    done_names.append(t["name"])
                    if self._handle_result(r, pending, done_names, phase_name):
                        return

            if not pending:
                break   # queue drained

            # ── Normal worker ───────────────────────────────────
            w = pending.pop(0)
            self._log("🍯", f"  {w.get('name','?')} → 执行")
            r = self.dispatch(w)
            done_names.append(w["name"])
            if self._handle_result(r, pending, done_names, phase_name):
                return

        if iters >= max_iters:
            self._log("⚠️", f"[{phase_name}] 达到最大迭代，防止死循环")

    def _handle_result(self, r: dict, pending: list, done: list, phase_name: str) -> bool:
        """Returns True if phase should halt."""
        if r.get("halt"):
            self._log("🛑", f"[{phase_name}] HALT: {r.get('halt_reason')}")
            return True

        for t in r.get("injected", []):
            t["priority"] = t.get("priority", "normal")
            pending.insert(0, t)
            self._log("🆕", f"  → 注入: {t['name']} (队首)")

        for ph in r.get("skipped", []):
            self._skip_phases.add(ph)
            self._log("⏭", f"  → 跳过: {ph}")

        return False

    # ── Entry Point ─────────────────────────────────────────────────

    def run_phases(self, phases: list[dict]):
        """
        Run all phases until completion or stop() is called.

        Args:
            phases: list of Phase dicts.  Each phase:
              {
                "name":   "Phase name",
                "workers": [{"name": ..., "action": ..., "task": ..., "condition": ...}, ...],
                "loops":  N,
                "mode":   "sequential" | "parallel" | "conditional",
              }
        """
        self._running = True
        self._stop_flag.clear()
        self._halted = False
        self.fetches.clear()

        self._log("🌸", f"BeeMode 启动 — {len(phases)} 个阶段")
        self._log("🌸", f"  插队=✅  停止=✅  条件调度=✅")
        print()

        try:
            for idx, phase in enumerate(phases, 1):
                if self._should_stop():
                    self._log("🛑", f"[Phase {idx}] 停止")
                    break
                phase_name = phase.get("name", f"Phase-{idx}")
                if phase_name in self._skip_phases:
                    self._log("⏭", f"[Phase {idx}/{len(phases)}] {phase_name} — 已跳过")
                    continue
                self.run_phase(phase, idx, len(phases))
                if self._should_stop():
                    break
        finally:
            self._running = False

        if not self._should_stop():
            self._log("🌻", "所有阶段完成!")
        else:
            self._log("🛑", f"被停止 — 原因: {self._halt_reason}")

        self._log("📊", f"累计 Honey Fetches: {self.fetch_counter}")
