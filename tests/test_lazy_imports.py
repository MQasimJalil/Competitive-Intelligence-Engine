import os
import subprocess
import sys


def test_app_import_does_not_open_repository_connections():
    env = os.environ.copy()
    env.update(
        {
            "APP_NAME": "Competitor Brief",
            "JOB_REPOSITORY": "postgres",
            "USER_REPOSITORY": "postgres",
            "CREDIT_REPOSITORY": "postgres",
            "AUTH_PROVIDER": "local",
            "DATABASE_URL": "postgresql://invalid:invalid@127.0.0.1:1/invalid",
            "SUPABASE_DB_URL": "",
        }
    )

    result = subprocess.run(
        [sys.executable, "-c", "import app.main; print(app.main.app.title)"],
        cwd=os.getcwd(),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0
    assert "Competitor Brief" in result.stdout
