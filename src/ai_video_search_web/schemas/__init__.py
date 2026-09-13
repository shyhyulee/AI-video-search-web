"""API 對外的 Pydantic 契約，跟 pipeline 內部私有的 LLM structured output
schema（例如 pipeline/vlm.py 的 _SceneAnalysis）分開，不合併復用，見
docs/archive/09-web-ui-migration-plan.md 2.5 節。
"""
