import os
from pathlib import Path


def load_env_file(dotenv_path: str | os.PathLike | None = None) -> None:
    """
    Minimal .env loader (no external dependency).

    - Loads KEY=VALUE pairs into os.environ if KEY is not already set.
    - Ignores blank lines and lines starting with '#'.
    - Supports optional single/double quotes around VALUE.
    """
    if dotenv_path is None:
        dotenv_path = Path(__file__).resolve().parent / ".env"
    else:
        dotenv_path = Path(dotenv_path)

    if not dotenv_path.exists() or not dotenv_path.is_file():
        return

    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()

        if not key or key.startswith("#"):
            continue

        if (len(value) >= 2) and (
            (value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")
        ):
            value = value[1:-1]

        os.environ.setdefault(key, value)
