"""Shared P00/P01 pytest harness. Apply execution stays a subprocess."""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

import pytest
from pgembed import POSTGRES_BIN_PATH, get_server

REPO = Path(__file__).resolve().parents[1]
APPLY = REPO / "tools" / "apply_pg_cordis.py"
SQL = REPO / "sql"
_SQL_PREFIX_RE = re.compile(r"^(\d{4})_")


def run_apply(
    *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, str(APPLY), *args],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=False,
        env=merged,
    )


def psql(server, database: str, sql: str, *extra: str) -> str:
    args = [
        str(POSTGRES_BIN_PATH / "psql"),
        server.get_uri(database),
        "--no-psqlrc",
        "-v",
        "ON_ERROR_STOP=1",
        "-q",
        "-t",
        "-A",
        *extra,
    ]
    proc = subprocess.run(args, input=sql.encode(), capture_output=True, check=False)
    out = proc.stdout.decode() + proc.stderr.decode()
    if proc.returncode != 0:
        raise RuntimeError(f"psql failed ({proc.returncode}):\n{out}")
    return out.strip()


def next_sql_prefix(tree: Path) -> str:
    prefixes = [
        int(match.group(1))
        for path in tree.iterdir()
        if path.is_file() and (match := _SQL_PREFIX_RE.match(path.name))
    ]
    return f"{max(prefixes, default=-1) + 1:04d}"


def load_apply_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("apply_pg_cordis", APPLY)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {APPLY}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PsqlSession:
    def __init__(self, proc: subprocess.Popen[str]) -> None:
        self._proc = proc
        self._seq = 0
        self._closed = False

    def execute(self, sql: str) -> list[str]:
        if self._closed or self._proc.stdin is None or self._proc.stdout is None:
            raise RuntimeError("psql session is closed")
        if self._proc.poll() is not None:
            rest = self._proc.stdout.read()
            raise RuntimeError(
                f"psql exited ({self._proc.returncode}) before execute:\n{rest}"
            )
        self._seq += 1
        marker = f"__P01_SENTINEL_{self._seq}_{uuid.uuid4().hex}__"
        payload = sql if sql.rstrip().endswith(";") else f"{sql};"
        self._proc.stdin.write(payload + "\n")
        self._proc.stdin.write(f"\\echo {marker}\n")
        self._proc.stdin.flush()
        lines: list[str] = []
        while True:
            line = self._proc.stdout.readline()
            if line == "":
                raise RuntimeError(
                    f"psql exited ({self._proc.returncode}) before sentinel {marker}"
                )
            if line.rstrip("\n") == marker:
                break
            stripped = line.rstrip("\n")
            if stripped != "":
                lines.append(stripped)
        return lines

    def commit(self) -> list[str]:
        return self.execute("COMMIT")

    def rollback(self) -> list[str]:
        return self.execute("ROLLBACK")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._proc.stdin is not None:
            try:
                self._proc.stdin.close()
            except BrokenPipeError:
                pass
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait(timeout=5)


@contextmanager
def psql_session(server, database: str, *extra: str) -> Iterator[PsqlSession]:
    args = [
        str(POSTGRES_BIN_PATH / "psql"),
        server.get_uri(database),
        "--no-psqlrc",
        "-v",
        "ON_ERROR_STOP=1",
        "-q",
        "-t",
        "-A",
        *extra,
    ]
    proc = subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    session = PsqlSession(proc)
    try:
        yield session
    finally:
        if proc.poll() is None:
            try:
                session.rollback()
            except Exception:
                pass
        session.close()


@pytest.fixture(scope="session")
def pgdata(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("pgdata")
