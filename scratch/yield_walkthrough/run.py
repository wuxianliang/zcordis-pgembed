"""Scratch walkthrough: 3 RLM steps == 3 jobs claims.

Uses pg-agent's pgembed server and v2 SQL, isolated database yield_scratch.
Does not touch da_agent.

Run from anywhere:
  cd /Users/wxl/Projects/pg-agent && uv run python \\
    /Users/wxl/Projects/zcordis-pgembed/scratch/yield_walkthrough/run.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import psycopg2
from pgembed import POSTGRES_BIN_PATH

PG_AGENT = Path("/Users/wxl/Projects/pg-agent")
sys.path.insert(0, str(PG_AGENT))
from server import get_server  # noqa: E402

HERE = Path(__file__).resolve().parent
V2 = PG_AGENT / "v2"
DB = "yield_scratch"
SQL_BASE = [
    V2 / "pg_agent_functional.sql",
    V2 / "pg_agent_rlm.sql",
]
DRIVER = HERE / "install_driver.sql"

MOCK = [
    {"thought": "step1", "code": "SELECT 1 AS n", "final_answer": None},
    {"thought": "step2", "code": "SELECT 2 AS n", "final_answer": None},
    {"thought": "done", "code": None, "final_answer": "ok"},
]


def psql(server, database: str, sql: str) -> str:
    uri = server.get_uri(database)
    proc = subprocess.run(
        [str(POSTGRES_BIN_PATH / "psql"), uri, "-v", "ON_ERROR_STOP=1", "-q"],
        input=sql.encode(),
        capture_output=True,
    )
    out = proc.stdout.decode() + proc.stderr.decode()
    if proc.returncode != 0:
        raise RuntimeError(f"psql failed ({proc.returncode}):\n{out}")
    return out


def load_file(server, database: str, path: Path) -> None:
    print(f"[load] {path.name}")
    psql(server, database, path.read_text())


def main() -> int:
    server = get_server()
    psql(server, "postgres", f"DROP DATABASE IF EXISTS {DB} WITH (FORCE);")
    psql(server, "postgres", f"CREATE DATABASE {DB};")
    print(f"[created] {DB}")

    for path in SQL_BASE:
        load_file(server, DB, path)
    load_file(server, DB, DRIVER)

    uri = server.get_uri(DB)
    conn = psycopg2.connect(uri)
    conn.autocommit = True
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TEMP TABLE _mock_llm_queue (
            id serial PRIMARY KEY,
            raw text NOT NULL
        )
        """
    )
    for row in MOCK:
        cur.execute(
            "INSERT INTO _mock_llm_queue (raw) VALUES (%s)",
            (json.dumps(row),),
        )
    cur.execute(
        """
        CREATE OR REPLACE FUNCTION http_call_llm(p_messages jsonb)
        RETURNS jsonb
        LANGUAGE plpgsql VOLATILE AS $mock$
        DECLARE
            v_id int;
            v_raw text;
        BEGIN
            SELECT id, raw INTO v_id, v_raw
              FROM _mock_llm_queue ORDER BY id LIMIT 1;
            IF NOT FOUND THEN
                RAISE EXCEPTION '_mock_llm_queue empty';
            END IF;
            DELETE FROM _mock_llm_queue WHERE id = v_id;
            RETURN jsonb_build_object('raw', v_raw);
        END;
        $mock$
        """
    )

    cur.execute("SELECT rlm_enqueue(%s, NULL, 10, 1)", ("scratch: three claims",))
    run_id = cur.fetchone()[0]
    print(f"[enqueue] run_id={run_id}")

    reports = []
    for i in range(1, 4):
        worker = f"w{i}"
        cur.execute("SELECT worker_step(%s, 90)", (worker,))
        msg = cur.fetchone()[0]
        cur.execute(
            "SELECT status, claim_token IS NULL FROM jobs WHERE run_id = %s",
            (run_id,),
        )
        status, token_cleared = cur.fetchone()
        cur.execute(
            """
            SELECT string_agg(kind, ',' ORDER BY seq),
                   count(*) FILTER (WHERE kind = 'llm')
              FROM agent_steps WHERE run_id = %s
            """,
            (run_id,),
        )
        kinds, n_llm = cur.fetchone()
        reports.append((i, worker, msg, status, token_cleared, kinds, n_llm))
        print(
            f"[claim {i}] worker={worker} jobs.status={status} "
            f"token_cleared={token_cleared} steps={kinds}"
        )

    cur.execute(
        """
        SELECT count(*), count(DISTINCT claim_token), count(DISTINCT worker_id)
          FROM yield_claim_audit WHERE run_id = %s
        """,
        (run_id,),
    )
    n_claims, n_tokens, n_workers = cur.fetchone()
    cur.execute(
        """
        SELECT seq, kind, payload->>'step_name' AS step_name
          FROM agent_steps WHERE run_id = %s ORDER BY seq
        """,
        (run_id,),
    )
    steps = cur.fetchall()
    cur.execute("SELECT status, result->>'answer' FROM jobs WHERE run_id = %s", (run_id,))
    job_status, answer = cur.fetchone()
    cur.execute("SELECT count(*) FROM _mock_llm_queue")
    leftover = cur.fetchone()[0]

    print("\n=== assertions ===")
    checks = [
        ("3 claims recorded", n_claims == 3, f"n_claims={n_claims}"),
        ("3 distinct claim tokens", n_tokens == 3, f"n_tokens={n_tokens}"),
        ("3 distinct workers", n_workers == 3, f"n_workers={n_workers}"),
        (
            "step kinds llm,tool,llm,tool,llm,final",
            [s[1] for s in steps] == ["llm", "tool", "llm", "tool", "llm", "final"],
            str([s[1] for s in steps]),
        ),
        (
            "step_names s-1,s-1,s-2,s-2,s-3,s-3 (final shares s-3)",
            [s[2] for s in steps]
            == ["s-1", "s-1", "s-2", "s-2", "s-3", "s-3"],
            str([s[2] for s in steps]),
        ),
        ("jobs DONE", job_status == "DONE", job_status),
        ("final answer ok", answer == "ok", answer),
        ("mock queue drained", leftover == 0, leftover),
        (
            "each claim released token before next",
            all(r[4] for r in reports),
            str([(r[0], r[4]) for r in reports]),
        ),
    ]
    ok = True
    for name, cond, detail in checks:
        mark = "PASS" if cond else "FAIL"
        print(f"  {mark}  {name}  ({detail})")
        ok = ok and cond

    conn.close()
    print("\nwalkthrough", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
