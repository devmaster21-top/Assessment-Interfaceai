from cuagent.models import CapabilityArtifact, CapabilityStep, InputSpec, OutputSpec, StateCondition, TargetLocator, LocatorCandidate, ValueSource


def test_artifact_roundtrip():
    artifact = CapabilityArtifact(
        capability_id="lookup_savings",
        name="Lookup savings",
        description="Lookup a member savings balance",
        target_app="demo",
        entry_point="http://127.0.0.1:8000/",
        allowed_hosts=["127.0.0.1"],
        inputs=[InputSpec(name="member_id", description="Member ID")],
        outputs=[OutputSpec(name="savings_balance", description="Savings balance")],
        steps=[
            CapabilityStep(
                id="step_01",
                kind="type",
                target=TargetLocator(description="Member ID", candidates=[LocatorCandidate(strategy="label", value="Member ID")]),
                value=ValueSource(parameter="member_id"),
            )
        ],
        success_checkpoint=StateCondition(kind="text_contains", value="Savings Balance"),
    )
    restored = CapabilityArtifact.model_validate_json(artifact.model_dump_json())
    assert restored.steps[0].value.parameter == "member_id"
