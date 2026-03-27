#!/usr/bin/env python3
"""
BeeMode Demo — Mock Execution
============================
Demonstrates orchestration without real sessions_spawn.
Each worker just sleeps 0.3s (simulates work).

Run:
  python3 examples/demo.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from beemode import BeeMode

DEMO_PHASES = [
    {
        "name": "Phase-1: 分析与规划",
        "workers": [
            {"name": "planner",   "action": "制定工作计划",     "task": "分析需求，输出计划文档"},
            {"name": "researcher","action": "收集背景资料",     "task": "搜索相关技术资料"},
        ],
        "loops": 2,
        "mode": "sequential",
    },
    {
        "name": "Phase-2: 开发与验证（并行）",
        "workers": [
            {"name": "frontend",  "action": "前端开发",        "task": "实现 UI 组件"},
            {"name": "backend",   "action": "后端开发",         "task": "实现 API 接口"},
            {"name": "tester",    "action": "编写测试用例",      "task": "覆盖核心路径"},
        ],
        "loops": 2,
        "mode": "parallel",
    },
    {
        "name": "Phase-3: 条件调度演示",
        "workers": [
            {
                "name": "builder",
                "action": "构建核心模块",
                "task": "执行构建...",
                # Simulated: builder will inject a task after running
            },
        ],
        "loops": 1,
        "mode": "conditional",
    },
]


class DemoBeeMode(BeeMode):
    """BeeMode with mock _execute_fetch — simulates real sub-agent work."""

    def _execute_fetch(self, worker: dict, context: dict | None) -> dict:
        """
        Override to simulate what sessions_spawn would return.
        In production, this is handled by the OpenClaw main agent.
        """
        import time
        time.sleep(0.3)

        # Simulate a builder that injects a repair task
        name = worker.get("name", "")
        if name == "builder":
            return {
                "status": "ok",
                "inject_task": {
                    "name": "repair-i18n",
                    "action": "补全缺失的中文翻译",
                    "task": "扫描代码库，找到未翻译的英文字符串并补全",
                    "priority": "high",
                }
            }
        return {"status": "ok", "halt": False, "inject_task": None, "skip_phase": None}


def main():
    print("\n" + "=" * 55)
    print("🐝 BeeMode Demo — Mock Execution")
    print("=" * 55 + "\n")

    bee = DemoBeeMode()

    # Show each fetch in real time
    def on_fetch(fetch):
        emoji = {"done": "✅", "running": "🍯", "halted": "🛑"}.get(fetch.status, "❓")
        print(f"  {emoji} Fetch #{fetch.fetch_id:03d} [{fetch.worker}] {fetch.status.upper()}")

    bee.add_fetch_callback(on_fetch)
    bee.run_phases(DEMO_PHASES)

    print()
    print("Final status:", json.dumps(bee.status(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    import json
    main()
