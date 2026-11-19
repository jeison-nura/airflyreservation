"""Create a module-owned Alembic revision with a UUIDv7 identifier."""

import argparse
import secrets
import time
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).resolve().parents[1]
VERSIONS = BACKEND / "migrations" / "versions"


def new_revision_id() -> str:
    # UUIDv7: 48-bit Unix milliseconds, version 7, 74 random bits, RFC variant.
    milliseconds = time.time_ns() // 1_000_000
    randomness = secrets.randbits(74)
    value = (
        (milliseconds << 80)
        | (7 << 76)
        | ((randomness >> 62) << 64)
        | (2 << 62)
        | (randomness & ((1 << 62) - 1))
    )
    return uuid.UUID(int=value).hex  # Alembic's default version_num is VARCHAR(32).


def create_revision(module: str, message: str) -> None:
    if module not in {"inventory", "reservations", "payments"}:
        raise ValueError(f"Unknown module: {module}")

    config = Config(str(BACKEND / "alembic.ini"))
    scripts = ScriptDirectory.from_config(config)
    has_branch = any(
        module in (script.branch_labels or ()) for script in scripts.walk_revisions()
    )
    existing = scripts.get_revisions(f"{module}@heads") if has_branch else ()
    if len(existing) > 1:
        raise ValueError(f"Module {module} has multiple heads; merge them first")

    directory = VERSIONS / module
    directory.mkdir(parents=True, exist_ok=True)
    command.revision(
        config,
        message=message,
        head=f"{module}@head" if existing else "base",
        branch_label=None if existing else module,
        version_path=str(directory),
        rev_id=new_revision_id(),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("module", choices=("inventory", "reservations", "payments"))
    parser.add_argument("message")
    arguments = parser.parse_args()
    create_revision(arguments.module, arguments.message)
