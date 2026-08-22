"""Application Service 層：包裝 db／pipeline 呼叫，供 Tkinter UI 與之後的
FastAPI（見 docs/09-web-ui-migration-plan.md）共用，避免兩邊各自重複實作
同一段商業邏輯。
"""
