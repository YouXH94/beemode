# 🐝 BeeMode

> OpenClaw multi-agent orchestration toolkit.

A lightweight Python library for orchestrating multi-step, multi-agent workflows
using OpenClaw's `sessions_spawn` API. Designed for developers who want reliable
agent pipelines without mid-loop human confirmation.

## Features

- **3 execution modes**: Sequential, Parallel, Conditional
- **Dynamic task injection**: inject high-priority tasks from outside the loop
- **Phase skipping**: agents can request to skip named phases
- **Graceful stop**: stop all loops cleanly at any time
- **Honey Fetch model**: each agent completion is one tracked "fetch" with full logs
- **Dual-FIFO daemon**: background orchestration with reliable IPC

## Install

```bash
pip install websocket-client
```

No other dependencies.

## Quick Start

```python
from beemode import BeeMode

bee = BeeMode(workspace="/path/to/your/project")

# Optional: register a callback for each completed fetch
def on_fetch(fetch):
    print(f"Done: {fetch.worker} | status={fetch.status}")

bee.add_fetch_callback(on_fetch)

# Define your phases (see examples/demo_phases.py)
bee.run_phases(YOUR_PHASES)
```

## Core API

| Method | Description |
|--------|-------------|
| `run_phases(phases)` | Start the full orchestration |
| `inject_now(name, action, task, priority="high")` | Inject a task into the next round |
| `stop(reason="")` | Stop all loops after current worker finishes |
| `status()` | Return current state dict |

## Phase Definition Format

```python
phases = [
    {
        "name":   "Phase-1: 数值调整",
        "workers": [
            {
                "name":     "tuner",
                "action":   "调整战斗数值",
                "task":     "Read src/gameplay/combat/CombatTuning.ts, adjust parameters...",
            },
        ],
        "loops": 3,            # repeat this phase 3 times
        "mode":  "sequential", # sequential | parallel | conditional
    },
]
```

## Execution Modes

| Mode | Behavior |
|------|----------|
| `sequential` | Workers run one by one, in order |
| `parallel` | All workers run concurrently |
| `conditional` | After each worker, inspect result → inject tasks or halt |

## Agent Control Directives

Agents return these fields to dynamically control the workflow:

```python
{
    "status":       "ok",
    "inject_task":  {"name": "...", "action": "...", "task": "..."},
    "skip_phase":   "Phase-3",
    "halt":         True,
    "halt_reason":  "Fatal error"
}
```

## Example Output

```
[11:33:18] 🌸 BeeMode 启动 — 3 个阶段
[11:33:18] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 
[11:33:18] 🌸 [Phase 1/3] Phase-1: 分析与规划
[11:33:18] ──  Loop 1/2 
[11:33:18] 🍯 #1 [planner] START — 制定工作计划
[11:33:19] ✅ #1 [planner] DONE
[11:33:19] 🍯 #2 [researcher] START — 收集背景资料
[11:33:19] ✅ #2 [researcher] DONE
[11:33:22] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 
[11:33:22] 🌸 [Phase 3/3] Phase-3: 条件调度演示
[11:33:22] 🍯 #11 [builder] START — 构建核心模块
[11:33:22] ✅ #11 [builder] DONE
[11:33:22] 🆕 [builder] 注入: repair-i18n
[11:33:22] 🍯 #12 [repair-i18n] START — 补全缺失的中文翻译
[11:33:23] ✅ #12 [repair-i18n] DONE
[11:33:23] 🌻 所有阶段完成!
[11:33:23] 📊 累计 Honey Fetches: 12
```

## Project Structure

```
beemode/
├── src/
│   ├── __init__.py       — Package init, exports BeeMode & HoneyFetch
│   ├── beemode.py         — Core BeeMode class (~380 lines)
│   └── daemon.py          — Dual-FIFO daemon (~240 lines)
├── examples/
│   ├── demo.py            — Run this to see orchestration in action
│   └── demo_phases.py     — Example phase definitions
├── SKILL.md               — Full skill documentation (for OpenClaw users)
├── README.md              — This file
├── LICENSE                — MIT
└── .gitignore
```

## Dual-FIFO Daemon Mode

For long-running background workflows:

```bash
# Terminal 1
python3 src/daemon.py --workspace /path/to/project

# Send commands via FIFO
echo "STOP|reason=user_requested" > /tmp/beemode_in.fifo
```

Protocol:
- `FIFO_IN` (daemon writes → main reads): `EXEC|<task_id>|<worker>|<action>`
- `FIFO_OUT` (main writes → daemon reads): `DONE|<task_id>|<result>`
- Logs: `/tmp/beemode_honey_log.jsonl`

## License

MIT
