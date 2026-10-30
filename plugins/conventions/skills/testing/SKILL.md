---
name: testing
description: >-
  Test-writing and test-review discipline: TDD order, curating the suite instead
  of appending to it, testing at the public boundary, rejecting tests that
  cannot fail, determinism, and fixture size. Use when writing, changing,
  deleting, or reviewing tests, adding a regression test for a bug, or judging
  a diff's test coverage. A repo's own AGENTS.md testing rules refine these and
  win where they differ.
---

# Testing

- **TDD-first.** Write a failing test before the implementation, make it pass,
  then verify the full suite is green before committing. Default for features
  and bugfixes; instrument and debug brittle tests rather than paper over them.
- **Test suite discipline: curate, don't append.** Size suites to decision
  branches, not coverage: about one case per distinct path (`if/else`,
  `switch`, `catch`), 1-2 for pure utilities, none for getters/setters,
  pass-throughs, or framework defaults. When behavior changes, edit the
  existing tests first, delete tests for removed paths, and merge overlapping
  ones into parameterized tables (`@pytest.mark.parametrize`, `test.each`, Go
  subtests). A bug repro is one minimal unit test at the root component, not a
  copied integration harness. Before writing test code, state what is added,
  updated, and deleted.
- **Test observable behavior at the boundary.** Exercise the public API or
  feature surface, not private helpers: the suite should survive the
  implementation being replaced wholesale. Prefer real implementations or
  lightweight fakes at the system's edge over mocks; assert resulting state and
  output, never that specific internal calls were made. Keep core logic
  testable without I/O, subprocesses, or sleeps; mark a test that genuinely
  needs them slow/integration so it stays out of the default suite.
- **A test that cannot fail is worse than none.** Tautology patterns to reject,
  in review and in your own work: asserting a mock returns what it was
  configured to return; `is not None` or "didn't raise" as the only assertion;
  try/except swallowing the assert; snapshots regenerated without reading the
  diff. Assert specific values and shapes, with failure output (parameter ids,
  message-bearing asserts) that localizes the bug without a debugger.
- **Deterministic by construction.** No sleeps, no wall clock, seeded
  randomness, no live network, order-independent fixtures. A test that needs a
  rerun to pass is broken, not flaky-but-green: fix or delete it rather than
  leaning on retry machinery.
- **Test data earns its size.** Minimal inline fixtures and builders over
  checked-in golden dumps; a reader should see from the test itself why the
  expected value is correct.
