# Oracle Review



## Summary and verdict

The implementation adds a separate, declarative `cordis.paradigm_policies` registry; validates policy envelopes and slot signatures; seeds `codeact` and `rlm` with `spawn_mode='always_enqueue'`; preserves runtime seed overrides with `ON CONFLICT DO NOTHING`; and provides data-driven fold/parse/observe slots plus the observation wrapper without an identity-based branch. Those core choices comply with the P19 deep plan. **Verdict: Not pass.** No P0 issues were identified, but one reachable validator error path violates the required SQLSTATE contract, and the review diff contains unrelated P04/P05 behavior changes that prevent treating this as a focused P19 shipset.

## P1 — Should fix

- **`sql/0019_p19_paradigm_policies.sql:268-277` — oversized clip values escape with the wrong SQLSTATE.**  
  `_validate_paradigm_policy` casts the JSON number directly to `integer` before checking the one-million upper bound:

  ```sql
  v_clip := (v_clip_raw #>> '{}')::integer;
  IF v_clip > 1000000 THEN ...
  ```

  A valid JSON integer such as `2147483648` or a much larger digit string raises PostgreSQL `22003` during the cast, rather than the plan-mandated `22023 / invalid observation_clip_chars`. This is a reachable public validation path and contradicts the plan’s requirement that all validator failures use `22023`. Validate the textual/numeric range before the `integer` cast, or catch numeric overflow and re-raise the stable `22023` error. Add a regression case for an out-of-range value larger than PostgreSQL `integer`.

- **`tests/test_p01_claim.py:298-326`, `tests/test_p01_claim.py:333-431`, `sql/README.md:55` — the P19 review shipset contains unrelated P04/P05 changes.**  
  The P19 plan limits `test_p01_claim.py` to changing full-tree version assertions to `p19`, but this diff also rewrites retry exhaustion, stale-release backoff, and due-sleep claiming behavior. The README likewise adds a detailed P05 driver section. These changes may be valid for their respective P items, but they are not P19 implementation work and cannot be assessed from this P19-only artifact because the corresponding production SQL is outside the selected diff. This also conflicts with the repository rule that one P’s implementation review and commit contain only that P. Rebase P19 on committed/reviewed P04/P05 work, or remove/split the unrelated hunks before resubmitting the P19 implementation review.

## P2 — Consider

- **`tests/test_p00_sql_source.py:78-83`, `tests/test_p00_sql_source.py:205-210` — exact SQL-tree assertions were weakened to substring checks.**  
  The previous test verified the complete ordered `files=...` list, while the new checks only require `0000`, `0019`, and—where applicable—the probe filename. The test would now pass if an intermediate numbered file were skipped or reordered, despite the deep plan explicitly retaining the product-tree file-list contract. Restore an assertion over the complete ordered current tree, or derive the expected ordered list from the fixture and compare it to the apply output.

- **`sql/README.md:55` — the newly added P05 paragraph contradicts the version ladder.**  
  It says “the current product tree still ends at `0006` and reports `p06`,” immediately after the ladder declares `0019`/`p19` as the current product tree. Update the sentence to describe only a tree truncated through `0005`/`0006`, without calling it current.

- **`sql/0019_p19_paradigm_policies.sql:129-384`, `sql/0019_p19_paradigm_policies.sql:412-526` — built-ins are not consistently schema-qualified as required by the deep plan.**  
  The functions correctly pin `search_path` to `pg_catalog`, so this is not presently exploitable, but calls such as `jsonb_typeof`, `btrim`, `octet_length`, `to_regprocedure`, `clock_timestamp`, `left`, and `to_jsonb` omit the planned `pg_catalog.` qualification. Apply the plan’s qualification rule consistently to avoid future drift if function settings are changed.