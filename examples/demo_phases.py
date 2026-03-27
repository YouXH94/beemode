"""
Example BeeMode Phase Definitions
=================================

These phases are for demonstration only.
For real Avalon tasks, see: projects/avalon/avalon_phases.py
"""

DEMO_PHASES = [
    {
        "name": "Phase-1: 分析与规划",
        "workers": [
            {"name": "planner",    "action": "制定工作计划",      "task": "分析需求，输出计划文档"},
            {"name": "researcher", "action": "收集背景资料",      "task": "搜索相关技术资料"},
        ],
        "loops": 2,
        "mode": "sequential",
    },
    {
        "name": "Phase-2: 开发与验证（并行）",
        "workers": [
            {"name": "frontend", "action": "前端开发",    "task": "实现 UI 组件"},
            {"name": "backend",  "action": "后端开发",    "task": "实现 API 接口"},
            {"name": "tester",   "action": "编写测试用例", "task": "覆盖核心路径"},
        ],
        "loops": 2,
        "mode": "parallel",
    },
    {
        "name": "Phase-3: 条件调度演示",
        "workers": [
            {"name": "builder", "action": "构建核心模块", "task": "执行构建..."},
        ],
        "loops": 1,
        "mode": "conditional",
    },
]
