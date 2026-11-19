import importlib.util
import shutil
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

script_path = Path(__file__).resolve().parents[1] / "scripts" / "new_migration.py"
spec = importlib.util.spec_from_file_location("new_migration", script_path)
assert spec and spec.loader
new_migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(new_migration)


def test_revisions_are_module_owned_and_use_uuid_v7():
    scripts = ScriptDirectory.from_config(
        Config(str(new_migration.BACKEND / "alembic.ini"))
    )
    revisions = list(scripts.walk_revisions())

    assert revisions
    for script in revisions:
        assert Path(script.path).parent.name in script.branch_labels
        assert uuid.UUID(hex=script.revision).version == 7
        assert len(script.revision) == 32
    assert "inventory" in {Path(script.path).parent.name for script in revisions}


def test_generator_uses_uuid_v7_and_correct_module_branch():
    for _ in range(20):
        revision = new_migration.new_revision_id()
        assert len(revision) == 32
        assert uuid.UUID(hex=revision).version == 7

    with patch.object(new_migration.command, "revision") as create:
        new_migration.create_revision("inventory", "add inventory field")

    assert create.call_args.kwargs["head"] == "inventory@head"
    assert create.call_args.kwargs["branch_label"] is None
    assert Path(create.call_args.kwargs["version_path"]).name == "inventory"
    assert uuid.UUID(hex=create.call_args.kwargs["rev_id"]).version == 7


def test_generator_rejects_unknown_modules():
    with pytest.raises(ValueError, match="Unknown module"):
        new_migration.create_revision("other", "add table")


def test_generator_keeps_module_branches_separate(tmp_path, monkeypatch):
    shutil.copy2(new_migration.BACKEND / "alembic.ini", tmp_path / "alembic.ini")
    shutil.copytree(
        new_migration.BACKEND / "migrations",
        tmp_path / "migrations",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    monkeypatch.setattr(new_migration, "BACKEND", tmp_path)
    monkeypatch.setattr(new_migration, "VERSIONS", tmp_path / "migrations" / "versions")

    new_migration.create_revision("inventory", "new inventory field")
    new_migration.create_revision("reservations", "create reservation schema")
    scripts = ScriptDirectory.from_config(Config(str(tmp_path / "alembic.ini")))
    revisions = list(scripts.walk_revisions())

    assert len(revisions) >= 3
    assert {Path(script.path).parent.name for script in scripts.get_revisions("heads")} == {
        "inventory",
        "payments",
        "reservations",
    }
    for script in revisions:
        assert uuid.UUID(hex=script.revision).version == 7
