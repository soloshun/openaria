"""Smoke tests for the offline Sprint 4 and Sprint 5 cookbooks."""

import runpy
from pathlib import Path


def test_guarded_proposal_cookbook_runs_without_execution(capsys: object) -> None:
    runpy.run_path(str(Path("cookbook/guarded-proposal/demo.py")))


def test_verification_replay_cookbook_runs_offline(capsys: object) -> None:
    runpy.run_path(str(Path("cookbook/verification-replay/demo.py")))
