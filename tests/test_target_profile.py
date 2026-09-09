from cuagent.target_profile import (
    demo_business_outcomes,
    demo_hard_failures,
    demo_recoverable_conditions,
)


def test_error_taxonomy_is_explicit():
    assert {r.code for r in demo_business_outcomes()} == {"member_not_found"}
    assert {r.code for r in demo_recoverable_conditions()} == {"session_expired"}
    assert {r.code for r in demo_hard_failures()} == {"permission_denied"}
