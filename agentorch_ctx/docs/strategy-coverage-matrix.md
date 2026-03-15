# Agentorch Strategy Coverage Matrix

## Purpose

This matrix maps standalone stub flows to the stable `COLLAB_*` strategy IDs
that must remain selectable in `agentorch_ctx/`.

## Executed Stub Coverage

| Strategy ID                     | Phase    | Stub Coverage                                                                                                                              |
| ------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `COLLAB_PLAN_QUESTIONS_ONLY`    | `plan`   | `agentorch_ctx.tests.stub_e2e.test_stubbed_flows.StubbedStandaloneE2ETest.test_stable_strategy_matrix_executes_each_strategy_in_stub_mode` |
| `COLLAB_PLAN_MINIMAL`           | `plan`   | `agentorch_ctx.tests.stub_e2e.test_stubbed_flows.StubbedStandaloneE2ETest.test_stable_strategy_matrix_executes_each_strategy_in_stub_mode` |
| `COLLAB_PLAN_FULL`              | `plan`   | `agentorch_ctx.tests.stub_e2e.test_stubbed_flows.StubbedStandaloneE2ETest.test_supported_phase_flows_execute_in_stub_mode`                 |
| `COLLAB_PLAN_THOROUGH`          | `plan`   | `agentorch_ctx.tests.stub_e2e.test_stubbed_flows.StubbedStandaloneE2ETest.test_stable_strategy_matrix_executes_each_strategy_in_stub_mode` |
| `COLLAB_IMPL_BATCH_SHOT`        | `impl`   | `agentorch_ctx.tests.stub_e2e.test_stubbed_flows.StubbedStandaloneE2ETest.test_stable_strategy_matrix_executes_each_strategy_in_stub_mode` |
| `COLLAB_IMPL_PATCH_FIRST`       | `impl`   | `agentorch_ctx.tests.stub_e2e.test_stubbed_flows.StubbedStandaloneE2ETest.test_supported_phase_flows_execute_in_stub_mode`                 |
| `COLLAB_IMPL_SPEC_PATCH`        | `impl`   | `agentorch_ctx.tests.stub_e2e.test_stubbed_flows.StubbedStandaloneE2ETest.test_stable_strategy_matrix_executes_each_strategy_in_stub_mode` |
| `COLLAB_IMPL_FILE_BY_FILE`      | `impl`   | `agentorch_ctx.tests.stub_e2e.test_stubbed_flows.StubbedStandaloneE2ETest.test_stable_strategy_matrix_executes_each_strategy_in_stub_mode` |
| `COLLAB_IMPL_SHIELD_FIX`        | `impl`   | `agentorch_ctx.tests.stub_e2e.test_stubbed_flows.StubbedStandaloneE2ETest.test_stable_strategy_matrix_executes_each_strategy_in_stub_mode` |
| `COLLAB_REVIEW_MODE_A`          | `review` | `agentorch_ctx.tests.stub_e2e.test_stubbed_flows.StubbedStandaloneE2ETest.test_stable_strategy_matrix_executes_each_strategy_in_stub_mode` |
| `COLLAB_REVIEW_MODE_B`          | `review` | `agentorch_ctx.tests.stub_e2e.test_stubbed_flows.StubbedStandaloneE2ETest.test_stable_strategy_matrix_executes_each_strategy_in_stub_mode` |
| `COLLAB_REVIEW_PRESET_LITE`     | `review` | `agentorch_ctx.tests.stub_e2e.test_stubbed_flows.StubbedStandaloneE2ETest.test_stable_strategy_matrix_executes_each_strategy_in_stub_mode` |
| `COLLAB_REVIEW_PRESET_STANDARD` | `review` | `agentorch_ctx.tests.stub_e2e.test_stubbed_flows.StubbedStandaloneE2ETest.test_supported_phase_flows_execute_in_stub_mode`                 |
| `COLLAB_REVIEW_PRESET_STRICT`   | `review` | `agentorch_ctx.tests.stub_e2e.test_stubbed_flows.StubbedStandaloneE2ETest.test_stable_strategy_matrix_executes_each_strategy_in_stub_mode` |
| `COLLAB_HARDEN_LITE`            | `harden` | `agentorch_ctx.tests.stub_e2e.test_stubbed_flows.StubbedStandaloneE2ETest.test_stable_strategy_matrix_executes_each_strategy_in_stub_mode` |
| `COLLAB_HARDEN_STANDARD`        | `harden` | `agentorch_ctx.tests.stub_e2e.test_stubbed_flows.StubbedStandaloneE2ETest.test_supported_phase_flows_execute_in_stub_mode`                 |
| `COLLAB_HARDEN_FULL`            | `harden` | `agentorch_ctx.tests.stub_e2e.test_stubbed_flows.StubbedStandaloneE2ETest.test_stable_strategy_matrix_executes_each_strategy_in_stub_mode` |

## Composed Flow Coverage

| Flow            | Coverage                                                                                                                   |
| --------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `review+harden` | `agentorch_ctx.tests.stub_e2e.test_stubbed_flows.StubbedStandaloneE2ETest.test_supported_phase_flows_execute_in_stub_mode` |

## Notes

1. The matrix is intentionally stub-only; live adapter correctness still
   requires `V10`.
2. Explicit strategy selectors are exercised directly so selection stability is
   covered without relying on rubric drift.
