# Oracle Review

Reconnecting... 1/5

## Summary

Round 2 fixes both previously open P1 findings: transport exceptions no longer retain DSN, SQL, or response objects through exception chaining, and the client’s catalog helper references are protected from `search_path` shadowing, including a regression test against a shadowed `md5(text)`. The previously identified P2 items are also addressed: timeout and timestamp validation, strict UTF-8 decoding, sleep feature-probe behavior, the named test cases, and the stale plan status sentence. No plan deviation, numbered SQL, SQL-tree/dependency leak, host-side impersonation or callable execution, cache, P09 wrapper, or provider-key mismatch remains evident. **No P0 or open P1 findings; this passes the stated review gate.**

## P2 — Consider

1. **`tests/test_p10_host_sql_seam.py::test_p10_psql_transport_errors_and_output_validation` — output-limit and non-standard JSON-number coverage remain incomplete**

   The added coverage verifies NUL handling, empty success output, and credential-bearing timeout traceback sanitization, but the deep-plan transport assertions also call for coverage of the 8 MiB output bound and rejection of non-standard JSON values such as `NaN`/infinity. Those cases are not included in the reported additions.

   This is primarily a test-coverage gap if the implementation already enforces the output limit and uses a strict JSON parser. If it relies directly on Python’s default `json.loads`, `NaN` and infinities may be accepted, so that behavior should be confirmed against the protocol contract.

   **Suggestion:** extend the existing transport test with:
   - output just over the configured maximum, asserting `CordisProtocolError`;
   - `NaN` and positive/negative infinity in otherwise valid JSON, asserting rejection;
   - the exact boundary value if the limit’s inclusive/exclusive behavior is contractual.

2. **Verification evidence — the reported run does not include the required cross-protocol suite**

   The supplied result confirms `tests/test_p10_host_sql_seam.py -q` passes all 18 tests, but the P10 contract also specifies the cross-protocol P00–P09/P19/P10 run with 211 passing tests. Nothing in the round-two result confirms that suite was rerun after the transport and SQL-template changes.

   **Suggestion:** run and record the required cross-protocol command before merge. This is not an implementation blocker if that suite has passed separately, but the current evidence only proves the P10-local tests.