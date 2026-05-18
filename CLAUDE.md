# Project guidance for Claude Code

Operational notes for working in this codebase. Keep additions tight and
load-bearing.

## Test execution discipline

### Pytest timeouts

The project uses `pytest-timeout` with a 30-second default per test
configured in `pyproject.toml`. If a test exceeds this, pytest fails the
suite with a clear timeout message identifying the hung test.

**When the test suite appears stuck:**

1. Do NOT retry blindly. The 30 s timeout means any hang of multiple
   minutes is anomalous — either a test is genuinely slow, or pytest
   itself is stuck, or worker processes have deadlocked.
2. Check Python process count: `tasklist | findstr python.exe` (Windows)
   / `ps aux | grep python | wc -l` (Linux/macOS). If more than ~3-4
   Python processes exist when pytest is "running," workers may have
   piled up.
3. Kill stuck workers before retrying: Task Manager / `taskkill /F /IM
   python.exe` (Windows) or `pkill -9 -f pytest` (Linux/macOS). After
   killing, do NOT retry the same way — investigate which test hung
   first.
4. If a specific test class consistently hangs, surface in the task
   report rather than retrying. There may be a test-infrastructure bug
   (DB lock leak, subprocess wait, never-awaited coroutine) that needs
   addressing.

**Background:** Task 101 (commit `dda5519`) saw pytest hang for ~1 hour
with 7-8 worker processes consuming all 32 GB system RAM. Only resolved
by manually killing Python processes via Task Manager. The 30 s timeout
+ this guidance are the guardrails against recurrence.

### Per-test timeout override

For tests that legitimately need more than 30 s, mark them individually:

```python
@pytest.mark.timeout(60)
def test_slow_integration():
    ...
```

Use sparingly. A test needing >60 s is a smell — surface it for
refactoring rather than normalizing the slow path.

### Resource limits

The development environment has 32 GB RAM. Test runs should not approach
that limit. If a test or fixture causes resource exhaustion, surface as a
finding rather than working around it (e.g., do not silently lower test
coverage or skip the slow test — flag the root cause).

### Parallel execution

This project does not currently use `pytest-xdist`. If it is added later,
the per-test timeout still fires per worker, but worker accumulation is
still possible if many tests deadlock simultaneously. The timeout
shortens the wait but does not eliminate the failure mode — keep the
process-count check in step 2 above.
