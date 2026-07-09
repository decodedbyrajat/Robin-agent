"""Regression test for config.yaml `security.redact_secrets: false` toggle.

Bug: `agent/redact.py` snapshots `_REDACT_ENABLED` from the env var
`ROBIN_REDACT_SECRETS` at module-import time. `robin_cli/main.py` at
line ~174 calls `setup_logging(mode="cli")` which transitively imports
`agent.redact` — BEFORE any config bridge ran. So if a user set
`security.redact_secrets: false` in config.yaml (instead of as an env var
in .env), the toggle was silently ignored in both `robin chat` and
`robin gateway run`.

Fix: bridge `security.redact_secrets` from config.yaml → `ROBIN_REDACT_SECRETS`
env var in `robin_cli/main.py` BEFORE the `setup_logging()` call.
"""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_redact_secrets_false_in_config_yaml_is_honored(tmp_path):
    """Setting `security.redact_secrets: false` in config.yaml must disable
    redaction — even though it's set in YAML, not as an env var."""
    robin_home = tmp_path / ".robin"
    robin_home.mkdir()

    # Write a config.yaml with redact_secrets: false
    (robin_home / "config.yaml").write_text(
        textwrap.dedent(
            """\
            security:
              redact_secrets: false
            """
        )
    )
    # Empty .env so nothing else sets the env var
    (robin_home / ".env").write_text("")

    # Spawn a fresh Python process that imports robin_cli.main and checks
    # _REDACT_ENABLED. Must be a subprocess — we need a clean module state.
    probe = textwrap.dedent(
        """\
        import sys, os
        # Make absolutely sure the env var is not pre-set
        os.environ.pop("ROBIN_REDACT_SECRETS", None)
        sys.path.insert(0, %r)
        import robin_cli.main  # triggers the bridge + setup_logging
        import agent.redact
        print(f"REDACT_ENABLED={agent.redact._REDACT_ENABLED}")
        print(f"ENV_VAR={os.environ.get('ROBIN_REDACT_SECRETS', '<unset>')}")
        """
    ) % str(REPO_ROOT)

    env = dict(os.environ)
    env["ROBIN_HOME"] = str(robin_home)
    env.pop("ROBIN_REDACT_SECRETS", None)

    result = subprocess.run(
        [sys.executable, "-c", probe],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=30,
    )
    assert result.returncode == 0, f"probe failed: {result.stderr}"
    assert "REDACT_ENABLED=False" in result.stdout, (
        f"Config toggle not honored.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "ENV_VAR=false" in result.stdout


def test_redact_secrets_default_false_when_unset(tmp_path):
    """Without the config key, redaction stays OFF by default.

    Secret redaction is opt-in — users who want it must set
    `security.redact_secrets: true` explicitly (or ROBIN_REDACT_SECRETS=true).
    """
    robin_home = tmp_path / ".robin"
    robin_home.mkdir()
    (robin_home / "config.yaml").write_text("{}\n")  # empty config
    (robin_home / ".env").write_text("")

    probe = textwrap.dedent(
        """\
        import sys, os
        os.environ.pop("ROBIN_REDACT_SECRETS", None)
        sys.path.insert(0, %r)
        import robin_cli.main
        import agent.redact
        print(f"REDACT_ENABLED={agent.redact._REDACT_ENABLED}")
        """
    ) % str(REPO_ROOT)

    env = dict(os.environ)
    env["ROBIN_HOME"] = str(robin_home)
    env.pop("ROBIN_REDACT_SECRETS", None)

    result = subprocess.run(
        [sys.executable, "-c", probe],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=30,
    )
    assert result.returncode == 0, f"probe failed: {result.stderr}"
    assert "REDACT_ENABLED=False" in result.stdout


def test_redact_secrets_true_in_config_yaml_is_honored(tmp_path):
    """Setting `security.redact_secrets: true` in config.yaml must enable
    redaction — even though it's set in YAML, not as an env var."""
    robin_home = tmp_path / ".robin"
    robin_home.mkdir()
    (robin_home / "config.yaml").write_text(
        textwrap.dedent(
            """\
            security:
              redact_secrets: true
            """
        )
    )
    (robin_home / ".env").write_text("")

    probe = textwrap.dedent(
        """\
        import sys, os
        os.environ.pop("ROBIN_REDACT_SECRETS", None)
        sys.path.insert(0, %r)
        import robin_cli.main
        import agent.redact
        print(f"REDACT_ENABLED={agent.redact._REDACT_ENABLED}")
        print(f"ENV_VAR={os.environ.get('ROBIN_REDACT_SECRETS', '<unset>')}")
        """
    ) % str(REPO_ROOT)

    env = dict(os.environ)
    env["ROBIN_HOME"] = str(robin_home)
    env.pop("ROBIN_REDACT_SECRETS", None)

    result = subprocess.run(
        [sys.executable, "-c", probe],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=30,
    )
    assert result.returncode == 0, f"probe failed: {result.stderr}"
    assert "REDACT_ENABLED=True" in result.stdout, (
        f"Config toggle not honored.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "ENV_VAR=true" in result.stdout


def test_dotenv_redact_secrets_beats_config_yaml(tmp_path):
    """.env ROBIN_REDACT_SECRETS takes precedence over config.yaml."""
    robin_home = tmp_path / ".robin"
    robin_home.mkdir()
    (robin_home / "config.yaml").write_text(
        textwrap.dedent(
            """\
            security:
              redact_secrets: false
            """
        )
    )
    # .env force-enables redaction
    (robin_home / ".env").write_text("ROBIN_REDACT_SECRETS=true\n")

    probe = textwrap.dedent(
        """\
        import sys, os
        os.environ.pop("ROBIN_REDACT_SECRETS", None)
        sys.path.insert(0, %r)
        import robin_cli.main
        import agent.redact
        print(f"REDACT_ENABLED={agent.redact._REDACT_ENABLED}")
        print(f"ENV_VAR={os.environ.get('ROBIN_REDACT_SECRETS', '<unset>')}")
        """
    ) % str(REPO_ROOT)

    env = dict(os.environ)
    env["ROBIN_HOME"] = str(robin_home)
    env.pop("ROBIN_REDACT_SECRETS", None)

    result = subprocess.run(
        [sys.executable, "-c", probe],
        env=env,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        timeout=30,
    )
    assert result.returncode == 0, f"probe failed: {result.stderr}"
    # .env value wins
    assert "REDACT_ENABLED=True" in result.stdout
    assert "ENV_VAR=true" in result.stdout
