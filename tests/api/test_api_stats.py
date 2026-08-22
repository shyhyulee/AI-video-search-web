from __future__ import annotations


def test_get_stats_returns_zero_on_empty_db(client):
    resp = client.get("/api/v1/stats")
    assert resp.status_code == 200
    assert resp.json() == {
        "pending_count": 0, "analyzed_count": 0, "segment_count": 0, "total_cost_usd": 0.0,
    }
