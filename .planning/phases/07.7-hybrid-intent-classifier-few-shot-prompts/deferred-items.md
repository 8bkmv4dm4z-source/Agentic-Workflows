# Deferred Items - Phase 07.7

## Pre-existing Test Failures

1. **test_multi_action_queued_and_popped** (`tests/unit/test_action_queue.py`) - Provider call count exceeds expected maximum. Confirmed pre-existing (fails on clean main branch without changes).

2. **MissionIsolationAuditTests** (`tests/integration/test_langgraph_flow.py`) - 4 tests failing with finish rejection loop. Confirmed pre-existing (31 failures before changes, 29 after).
