"""Application Service 層：包裝 db／pipeline 呼叫，讓 api/ 不必直接依賴
pipeline/ 與 db/，見 docs/archive/09-web-ui-migration-plan.md。

對外丟出的例外型別集中在 services/errors.py。
"""
