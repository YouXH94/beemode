"""
BeeMode — OpenClaw Multi-Agent Orchestrator
==========================================
A Python orchestration layer for managing multi-agent workflows.

Usage:
  from beemode import BeeMode
  bee = BeeMode(workspace="/path/to/project")
  bee.run_phases(phases)
"""

from beemode.beemode import BeeMode, HoneyFetch

__all__ = ["BeeMode", "HoneyFetch"]
