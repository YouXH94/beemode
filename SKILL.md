# BeeMode Orchestrator Skill

## Description

BeeMode is a multi-agent orchestration system for OpenClaw that enables:
- **Sequential / Parallel / Conditional** execution modes
- **Dynamic task injection** (inject_now) mid-workflow
- **Phase skip** (agent requests to skip a phase)
- **Graceful stop** at any time
- **Honey Fetch** tracking — each sub-agent completion = 1 Honey Fetch
- **Dual-FIFO IPC** for reliable daemon ↔ main-agent communication

Use when you want to run multi-step, multi-agent workflows where:
- Tasks have logical dependencies
- Agents may discover new sub-tasks dynamically
- You want real-time progress visibility without mid-loop prompts
- You need to inject tasks or stop remotely

## Usage

### Quick Start

```python
from beemode import BeeMode


bee = BeeMode(workspace="/path/to/project")
bee.add_fetch_callback(lambda f: print(f"Done: {f.worker}"))
bee.run_phases(phases)
```

### Architecture

```
┌─────────────────────────────────────────────┐
│  You (QQ / Chat)                            │
│  "开始跑" / "插队：xxx" / "停止"           │
└──────────┬──────────────────────────────────┘
           │ sessions_spawn
           ▼
┌─────────────────────────────────────────────┐
│  OpenClaw Main Agent (this agent)          │
│  • Receives QQ commands                    │
│  • Spawns sub-agents via sessions_spawn    │
│  • Reports progress to QQ                  │
└──────────┬──────────────────────────────────┘
           │ BeeMode Python class
           ▼
┌─────────────────────────────────────────────┐
│  BeeMode Python Orchestrator                │
│  • run_phases()                           │
│  • inject_now()                            │
│  • stop()                                  │
└─────────────────────────────────────────────┘
```

### Core API

```python
bee = BeeMode(workspace="/path/to/project")

# Register progress callback (called after each Honey Fetch)
bee.add_fetch_callback(lambda f: print(f"[{f.fetch_id}] {f.worker} {f.status}"))

# Start orchestration
bee.run_phases(phases)

# Inject a task from QQ (called from main agent message handler)
bee.inject_now(
    name="user-inserted",
    action="修一下卡牌闪烁",
    task="Read GameRoot.ts, find card rendering issue, fix it",
    priority="high"   # "high" = front of queue, "normal" = back
)

# Stop everything
bee.stop(reason="用户在QQ发了停止")
```

### Phase Definition Format

```python
phases = [
    {
        "name": "Phase-1: 数值调整",
        "workers": [
            {
                "name": "tuner",           # display name
                "action": "调整参数",      # short summary
                "task": "详细prompt给sub-agent",
                "condition": "build_pass", # optional unlock gate
            },
            ...
        ],
        "loops": 3,        # repeat this phase 3 times
        "mode": "sequential"  # sequential | parallel | conditional
    },
    {
        "name": "Phase-2: 并行任务",
        "workers": [...],
        "loops": 2,
        "mode": "parallel"   # all workers run simultaneously
    },
]
```

### Execution Modes

| Mode | Behavior |
|------|----------|
| `sequential` | Workers run one by one, in order |
| `parallel` | All workers run concurrently (uses ThreadPoolExecutor) |
| `conditional` | After each worker, inspect result → decide next worker dynamically |

### Agent Return Control Directives

Sub-agents can return these fields to control the workflow:

```python
{
    "status": "ok",
    "inject_task": {            # Dynamically inject a new task
        "name": "fix-i18n",
        "action": "补全中文翻译",
        "task": "...",
        "priority": "high"      # high → front of queue
    },
    "skip_phase": "Phase-3",    # Skip an entire phase by name
    "halt": True,               # Stop the entire workflow
    "halt_reason": "Fatal error"
}
```

### Dual FIFO Daemon Mode

For long-running workflows where you want the daemon to run in the background:

```bash
# Terminal 1 — start daemon
python3 beemode/src/daemon.py --workspace /path/to/project

# Terminal 2 — send commands
echo "STOP|reason=user_requested" > /tmp/beemode_in.fifo
```

FIFO protocol:
- **FIFO_IN** (daemon writes → main agent reads): `EXEC|<task_id>|<worker>|<action>`
- **FIFO_OUT** (main agent writes → daemon reads): `DONE|<task_id>|<result>`

Logs: `/tmp/beemode_honey_log.jsonl`

## Key Concepts

### Honey Fetch
One complete cycle: **sub-agent spawn → execution → result returned → next dispatch decided**.
Each Honey Fetch is logged with worker, loop, status, and timing.

### Conditional Dispatch
After each worker completes, BeeMode inspects the agent's return value:
- `inject_task` → creates a new task and inserts it into the queue
- `skip_phase` → marks the named phase as skipped
- `halt` → stops all further execution

This means the workflow is **data-driven**, not statically programmed.

### Inject from External Command
When you receive "插队：xxx" from QQ, call:
```python
bee.inject_now(name="user-task", action="用户插队", task="xxx", priority="high")
```
The task will run at the front of the next loop.

### Stop
When you receive "停止" from QQ:
```python
bee.stop(reason="用户在QQ发了停止命令")
```
Current worker completes, then all loops stop gracefully.

## Files

- `src/beemode.py` — Core BeeMode class
- `src/daemon.py` — Daemon with dual FIFO IPC
- `examples/demo_phases.py` — Example phase definitions (general demo)
- `examples/demo.py` — Demo with mock execution
- `examples/demo_real.py` — Demo with sessions_spawn integration outline

## Requirements

- Python 3.8+
- OpenClaw with `sessions_spawn` available (main agent context)
- `websocket-client` Python package: `pip install websocket-client`

## Notes

- Default mode is `sequential` — use `parallel` only when workers are truly independent
- `conditional` mode is recommended for workflows where agents discover new tasks
- The daemon mode requires a separate process to read/write FIFOs; it cannot run inside the OpenClaw agent process itself
- If no `sessions_spawn` is available, use the dry-run mode (mock `_execute_fetch`)
