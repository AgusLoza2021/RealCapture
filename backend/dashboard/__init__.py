"""Companion dashboard: web UI served by the capture backend (see odd/tasks/companion-dashboard.md)."""

from backend.dashboard.hub import BroadcastHub, DashboardHub

__all__ = ["BroadcastHub", "DashboardHub"]
