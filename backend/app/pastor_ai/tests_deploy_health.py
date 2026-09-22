import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from pastor_ai.deploy_status import read_deploy_status


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


class ReadDeployStatusTests(unittest.TestCase):
    def test_in_sync_clean_checkout(self):
        with TemporaryDirectory() as raw:
            ws = Path(raw)
            _git(ws, "init", "-b", "master")
            _git(ws, "config", "user.email", "test@example.com")
            _git(ws, "config", "user.name", "test")
            (ws / "file").write_text("one\n", encoding="utf-8")
            _git(ws, "add", "file")
            _git(ws, "commit", "-m", "one")
            sha = subprocess.check_output(
                ["git", "-C", str(ws), "rev-parse", "HEAD"], text=True
            ).strip()
            _git(ws, "update-ref", "refs/remotes/origin/master", sha)
            (ws / ".git_channel").write_text("master\n", encoding="utf-8")
            (ws / "DEPLOYED_SHA").write_text(sha + "\n", encoding="utf-8")
            (ws / "DEPLOYED_ORIGIN_SHA").write_text(sha + "\n", encoding="utf-8")
            (ws / "DEPLOYED_AT").write_text("2026-09-22T00:00:00Z\n", encoding="utf-8")
            status = read_deploy_status(ws)
            self.assertTrue(status["in_sync"])
            self.assertFalse(status["dirty"])
            self.assertEqual(status["git_sha"], sha)
            self.assertEqual(status["origin_sha"], sha)

    def test_dirty_overlay_is_not_in_sync(self):
        with TemporaryDirectory() as raw:
            ws = Path(raw)
            _git(ws, "init", "-b", "master")
            _git(ws, "config", "user.email", "test@example.com")
            _git(ws, "config", "user.name", "test")
            (ws / "file").write_text("one\n", encoding="utf-8")
            _git(ws, "add", "file")
            _git(ws, "commit", "-m", "one")
            sha = subprocess.check_output(
                ["git", "-C", str(ws), "rev-parse", "HEAD"], text=True
            ).strip()
            _git(ws, "update-ref", "refs/remotes/origin/master", sha)
            (ws / ".git_channel").write_text("master\n", encoding="utf-8")
            (ws / "file").write_text("overlay\n", encoding="utf-8")
            status = read_deploy_status(ws)
            self.assertTrue(status["dirty"])
            self.assertFalse(status["in_sync"])
            self.assertEqual(status["git_sha"], sha)
