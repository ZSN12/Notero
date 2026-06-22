"""Tests for stroke annotation persistence on the Note resource."""

import pytest


@pytest.mark.integration
def test_save_and_load_annotations(client, auth_headers, sample_session):
    """PUT annotations should be returned by subsequent GET."""
    session_id = str(sample_session.id)
    annotations = {
        "slides": {
            "1": [
                {
                    "type": "stroke",
                    "color": "#3b82f6",
                    "width": 4,
                    "points": [{"x": 0.1, "y": 0.2}, {"x": 0.3, "y": 0.4}],
                }
            ]
        }
    }

    res = client.put(
        f"/api/notes/session/{session_id}",
        headers={**auth_headers, "Content-Type": "application/json"},
        json={"content": "pad annotations test", "annotations": annotations},
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["annotations"] == annotations

    res = client.get(f"/api/notes/session/{session_id}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["annotations"] == annotations


@pytest.mark.integration
def test_update_without_annotations_preserves_existing(client, auth_headers, sample_session):
    """A PUT that omits annotations must not wipe previously saved strokes."""
    session_id = str(sample_session.id)
    annotations = {"slides": {"2": [{"type": "stroke", "color": "#ef4444", "width": 2, "points": []}]}}

    client.put(
        f"/api/notes/session/{session_id}",
        headers={**auth_headers, "Content-Type": "application/json"},
        json={"content": "first", "annotations": annotations},
    )

    res = client.put(
        f"/api/notes/session/{session_id}",
        headers={**auth_headers, "Content-Type": "application/json"},
        json={"content": "second"},
    )
    assert res.status_code == 200
    assert res.json()["annotations"] == annotations


@pytest.mark.integration
def test_update_with_null_annotations_clears_strokes(client, auth_headers, sample_session):
    """Explicitly sending annotations=null should clear the stored annotations."""
    session_id = str(sample_session.id)
    client.put(
        f"/api/notes/session/{session_id}",
        headers={**auth_headers, "Content-Type": "application/json"},
        json={
            "content": "with annotations",
            "annotations": {"slides": {"1": []}},
        },
    )

    res = client.put(
        f"/api/notes/session/{session_id}",
        headers={**auth_headers, "Content-Type": "application/json"},
        json={"content": "without annotations", "annotations": None},
    )
    assert res.status_code == 200
    assert res.json()["annotations"] is None
