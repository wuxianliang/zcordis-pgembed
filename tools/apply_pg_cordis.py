#!/usr/bin/env python3
"""Apply the canonical pg_cordis SQL tree onto an embedded PostgreSQL instance."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SQL_ROOT = REPO_ROOT / "sql"
DEFAULT_PGDATA = REPO_ROOT / ".pgdata"

SQL_NAME_RE = re.compile(r"^(\d{4})_([a-z0-9][a-z0-9_]*)\.sql$")
DB_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
RESET_FORBIDDEN = frozenset({"postgres", "template0", "template1"})
BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
FORBIDDEN_STMTS = (
    re.compile(r"\bCREATE\s+DATABASE\b", re.I),
    re.compile(r"\bDROP\s+DATABASE\b", re.I),
    re.compile(r"\bCREATE\s+EXTENSION\b", re.I),
    re.compile(r"\bCREATE\s+SCHEMA\s+(IF\s+NOT\s+EXISTS\s+)?absurd\b", re.I),
    re.compile(r"\bGRANT\b", re.I),
    re.compile(r"\bREVOKE\b", re.I),
    re.compile(r"\bCREATE\s+(ROLE|USER)\b", re.I),
    re.compile(r"\bALTER\s+DEFAULT\s+PRIVILEGES\b", re.I),
    re.compile(r"\bCREATE\s+TABLE\s+(IF\s+NOT\s+EXISTS\s+)?public\.", re.I),
    re.compile(
        r"(?:^|;)\s*(BEGIN|COMMIT|ROLLBACK|END|START\s+TRANSACTION)\s*;",
        re.I | re.M,
    ),
)


class ApplyError(Exception):
    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


def discover_sql_files(sql_root: Path) -> list[Path]:
    if not sql_root.is_dir():
        raise ApplyError(f"sql-root is not a directory: {sql_root}", 2)

    nested = [
        p
        for p in sql_root.rglob("*.sql")
        if p.is_file() and p.parent.resolve() != sql_root.resolve()
    ]
    if nested:
        raise ApplyError(f"nested .sql files are not allowed: {nested[0]}", 2)

    children = [p for p in sql_root.iterdir() if p.is_file()]
    sqlish = [p for p in children if p.name.lower().endswith(".sql")]
    if not sqlish:
        raise ApplyError(f"no .sql files in {sql_root}", 2)

    parsed: list[tuple[int, Path]] = []
    seen: dict[str, Path] = {}
    for path in sqlish:
        match = SQL_NAME_RE.fullmatch(path.name)
        if match is None:
            raise ApplyError(f"invalid SQL filename: {path.name}", 2)
        prefix = match.group(1)
        if prefix in seen:
            raise ApplyError(
                f"duplicate numeric prefix {prefix}: {seen[prefix].name} and {path.name}",
                2,
            )
        seen[prefix] = path
        parsed.append((int(prefix), path))

    if "0000" not in seen or seen["0000"].name != "0000_kernel.sql":
        raise ApplyError("0000_kernel.sql is required", 2)

    parsed.sort(key=lambda item: item[0])
    return [path for _, path in parsed]


def strip_sql_comments(text: str) -> str:
    text = BLOCK_COMMENT_RE.sub(" ", text)
    lines = []
    for line in text.splitlines():
        if "--" in line:
            line = line.split("--", 1)[0]
        lines.append(line)
    return "\n".join(lines)


def _blank_span(text: str, start: int, end: int) -> str:
    return "".join("\n" if ch == "\n" else " " for ch in text[start:end])


def _is_ident_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _dollar_tag_at(text: str, i: int) -> str | None:
    if i >= len(text) or text[i] != "$":
        return None
    j = i + 1
    while j < len(text) and _is_ident_char(text[j]):
        j += 1
    if j < len(text) and text[j] == "$":
        return text[i + 1 : j]
    return None


def sanitize_sql_for_preflight(text: str) -> str:
    """Blank comments and quoted spans while preserving newlines.

    Dollar-quote and string delimiters are recognized only in SQL state so a
    lookalike inside a single-quoted literal cannot hide top-level COMMIT.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if ch == "-" and nxt == "-":
            j = i
            while j < n and text[j] != "\n":
                j += 1
            out.append(_blank_span(text, i, j))
            i = j
            continue
        if ch == "/" and nxt == "*":
            depth = 1
            j = i + 2
            while j < n and depth:
                if text[j] == "/" and j + 1 < n and text[j + 1] == "*":
                    depth += 1
                    j += 2
                    continue
                if text[j] == "*" and j + 1 < n and text[j + 1] == "/":
                    depth -= 1
                    j += 2
                    continue
                j += 1
            out.append(_blank_span(text, i, j))
            i = j
            continue
        if (
            ch in "Ee"
            and nxt == "'"
            and (i == 0 or not _is_ident_char(text[i - 1]))
        ):
            j = i + 2
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if text[j] == "'":
                    if j + 1 < n and text[j + 1] == "'":
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            out.append(_blank_span(text, i, j))
            i = j
            continue
        if ch == "'":
            j = i + 1
            while j < n:
                if text[j] == "'":
                    if j + 1 < n and text[j + 1] == "'":
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            out.append(_blank_span(text, i, j))
            i = j
            continue
        if ch == '"':
            j = i + 1
            while j < n:
                if text[j] == '"':
                    if j + 1 < n and text[j + 1] == '"':
                        j += 2
                        continue
                    j += 1
                    break
                j += 1
            out.append(_blank_span(text, i, j))
            i = j
            continue
        tag = _dollar_tag_at(text, i)
        if tag is not None:
            closer = f"${tag}$"
            k = text.find(closer, i + len(closer))
            end = n if k == -1 else k + len(closer)
            out.append(_blank_span(text, i, end))
            i = end
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def strip_sql_dollar_quotes(text: str) -> str:
    return sanitize_sql_for_preflight(text)


def preflight_sql(path: Path, body: str) -> None:
    for lineno, line in enumerate(body.splitlines(), start=1):
        if line.lstrip().startswith("\\"):
            raise ApplyError(
                f"{path.name}:{lineno}: psql meta-commands are forbidden",
                2,
            )
    scanned = sanitize_sql_for_preflight(body)
    for pattern in FORBIDDEN_STMTS:
        if pattern.search(scanned):
            raise ApplyError(
                f"{path.name}: forbidden SQL: {pattern.pattern}",
                2,
            )


def load_sql_files(files: list[Path]) -> list[tuple[Path, str]]:
    loaded: list[tuple[Path, str]] = []
    for path in files:
        try:
            body = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ApplyError(f"cannot read {path}: {exc}", 2) from exc
        except UnicodeDecodeError as exc:
            raise ApplyError(f"invalid encoding in {path}: {exc}", 2) from exc
        if body and not body.endswith("\n"):
            body += "\n"
        preflight_sql(path, body)
        loaded.append((path, body))
    return loaded


def validate_database_name(name: str, *, reset: bool) -> None:
    if not DB_NAME_RE.fullmatch(name):
        raise ApplyError(
            "invalid --database: use a lowercase identifier [a-z_][a-z0-9_]*",
            2,
        )
    if name in RESET_FORBIDDEN and (reset or name != "postgres"):
        raise ApplyError(f"refusing database name {name}", 2)


def resolve_pgdata(flag: str | None) -> Path:
    if flag:
        return Path(flag).expanduser()
    env = os.environ.get("PGCORDIS_PGDATA")
    if env:
        return Path(env).expanduser()
    return DEFAULT_PGDATA


def run_psql(
    server,
    database: str,
    sql: str,
    *,
    extra_args: list[str] | None = None,
) -> str:
    from pgembed import POSTGRES_BIN_PATH

    args = [
        str(POSTGRES_BIN_PATH / "psql"),
        server.get_uri(database),
        "--no-psqlrc",
        "-v",
        "ON_ERROR_STOP=1",
        "-q",
    ]
    if extra_args:
        args.extend(extra_args)
    proc = subprocess.run(
        args,
        input=sql.encode(),
        capture_output=True,
        check=False,
    )
    out = proc.stdout.decode() + proc.stderr.decode()
    if proc.returncode != 0:
        raise ApplyError(f"psql failed ({proc.returncode}):\n{out}", 1)
    return out


def database_exists(server, name: str) -> bool:
    sql = f"SELECT datname FROM pg_database WHERE datname = '{name}';"
    out = run_psql(server, "postgres", sql, extra_args=["-t", "-A"]).strip()
    return out == name


def ensure_target_database(server, database: str, reset: bool) -> None:
    exists = database_exists(server, database)
    if reset and exists:
        run_psql(
            server,
            "postgres",
            f"DROP DATABASE {database} WITH (FORCE);",
        )
        exists = False
    if not exists:
        try:
            run_psql(server, "postgres", f"CREATE DATABASE {database};")
        except ApplyError as exc:
            if database_exists(server, database):
                return
            raise ApplyError(
                f"could not create database {database}: {exc}",
                1,
            ) from exc


def apply_source_tree(server, database: str, loaded: list[tuple[Path, str]]) -> None:
    chunks = ["SELECT pg_advisory_xact_lock(hashtext('pg_cordis.apply'));"]
    for path, body in loaded:
        chunks.append(f"-- pg_cordis source: {path.name}")
        chunks.append(body)
    stream = "\n".join(chunks)
    run_psql(server, database, stream, extra_args=["--single-transaction"])


def verify_bootstrap(server, database: str) -> None:
    nsp = run_psql(
        server,
        database,
        "SELECT nspname FROM pg_namespace WHERE nspname = 'cordis';",
        extra_args=["-t", "-A"],
    ).strip()
    if nsp != "cordis":
        raise ApplyError("bootstrap verification failed: schema cordis missing", 1)

    identity = run_psql(
        server,
        database,
        """
SELECT pg_get_function_identity_arguments(p.oid)
     || '|' ||
       pg_get_function_result(p.oid)
FROM pg_proc p
JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'cordis'
  AND p.proname = 'get_schema_version'
  AND p.pronargs = 0;
""",
        extra_args=["-t", "-A"],
    ).strip()
    if identity != "|text":
        raise ApplyError(
            "bootstrap verification failed: "
            "cordis.get_schema_version() must exist with no arguments and return text; "
            f"got {identity!r}",
            1,
        )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pgdata", default=None, help="PGDATA for pgembed.get_server")
    parser.add_argument("--database", required=True, help="target database name")
    parser.add_argument(
        "--sql-root",
        default=None,
        help="SQL source directory (default: repository sql/)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="drop and recreate the target database (destructive)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        code = exc.code
        return 2 if code not in (0, None) else 0

    try:
        validate_database_name(args.database, reset=args.reset)
        sql_root = Path(args.sql_root).expanduser() if args.sql_root else DEFAULT_SQL_ROOT
        sql_root = sql_root.resolve()
        files = discover_sql_files(sql_root)
        loaded = load_sql_files(files)
        pgdata = resolve_pgdata(args.pgdata).resolve()
        mode = "reset" if args.reset else "in-place"
        print(f"pgdata={pgdata}")
        print(f"database={args.database}")
        print(f"sql-root={sql_root}")
        print(f"mode={mode}")
        print("files=" + ",".join(path.name for path, _ in loaded))

        from pgembed import get_server

        server = get_server(pgdata)
        ensure_target_database(server, args.database, args.reset)
        apply_source_tree(server, args.database, loaded)
        verify_bootstrap(server, args.database)
        print("bootstrap verification ok")
        return 0
    except ApplyError as exc:
        print(exc, file=sys.stderr)
        return exc.code
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — map unexpected startup errors
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
