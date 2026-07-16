"""Offline deterministic replay metrics over synthetic lifecycle outcomes."""

from lumis_sdk.evaluation import ReplayCase, evaluate_replay

metrics = evaluate_replay(
    [
        ReplayCase(
            id="schema-drift-passed",
            expected_diagnosis="schema_drift",
            observed_diagnosis="schema_drift",
            expected_escalation=False,
            observed_escalation=False,
            expected_verification="passed",
            observed_verification="passed",
        ),
        ReplayCase(
            id="unknown-escalated",
            expected_diagnosis="unknown",
            observed_diagnosis="unknown",
            expected_escalation=True,
            observed_escalation=True,
            expected_verification="unknown",
            observed_verification="unknown",
        ),
    ]
)
print(metrics.model_dump_json(indent=2))
