"""Generation adapter: a small HTTP service between Nocturna and ACE-Step 1.5.

Nocturna speaks a tiny, stable contract (GET /health, POST /generate). This adapter
translates it to ACE-Step's asynchronous REST API (release_task -> query_result ->
/v1/audio), saves the audio into Nocturna's media folder, and reports provenance.
"""
