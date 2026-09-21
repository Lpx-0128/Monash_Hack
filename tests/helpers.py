"""Small helpers shared by the API-level tests."""

import time


def poll_case(client, case_id: str, expected_status: str, timeout: float = 20) -> dict:
    """Wait for a case to reach ``expected_status``, or fail with what it did reach."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        response = client.get(f"/api/v1/cases/{case_id}")
        if response.status_code == 200:
            last = response.json()
            if last["workflow_status"] == expected_status:
                return last
        time.sleep(0.2)
    raise AssertionError(
        f"timed out waiting for {case_id} to reach {expected_status}; "
        f"last status was {(last or {}).get('workflow_status')!r}"
    )


def create_and_wait(client, email_id: str, expected_status: str, timeout: float = 20) -> dict:
    response = client.post("/api/v1/cases", json={"email_id": email_id})
    assert response.status_code in (200, 202), response.text
    return poll_case(client, email_id, expected_status, timeout)
