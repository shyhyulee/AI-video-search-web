"""services 層對外丟出的例外型別，集中定義在這裡。

拆出來的理由：這些例外是「服務層對 API 層的契約」，不屬於任何單一服務模組。
最明顯的是 VideoNotFoundError——api/videos.py 有 5 處拿它表達「影片找不到」，
但它原本住在 job_manager 裡，跟 job 完全無關；api/errors.py 的對映表也因此
得 import 三個不同模組才湊得齊，順帶把 job_manager 連同它的 analyzer／
downloader 相依一起拉進來。

繼承關係只有兩層：ServiceError 是共同基底（API 層要一次攔截時用），
JobManagerError 沿用原名，保留「job 相關」這個分類。
"""
from __future__ import annotations


class ServiceError(Exception):
    """services 層例外的共同基底。"""


class JobManagerError(ServiceError):
    """背景工作（下載／分析）相關例外的共同基底。"""


class VideoNotFoundError(JobManagerError):
    """找不到指定的影片。"""


class DuplicateJobError(JobManagerError):
    """同一支影片／同一個網址已經有排隊中或執行中的同類型工作。"""


class DurationLimitExceededError(JobManagerError):
    """影片長度超過 analyzer.MAX_DURATION_SEC。"""


class InvalidUrlError(JobManagerError):
    """不是有效的 YouTube 網址。"""


class JobNotFoundError(JobManagerError):
    """找不到指定的工作。"""


class InvalidJobStateError(JobManagerError):
    """工作目前狀態不允許這個操作（例如對非 failed 的工作呼叫 retry）。"""


class ConversationNotFoundError(ServiceError):
    """找不到指定的 conversation_id。"""


class DocumentNotFoundError(ServiceError):
    """這支影片還沒有整理過的文件。

    對前端來說這是**正常狀態**不是錯誤（它靠這個 404 決定要顯示「尚未整理」
    還是文件內容），但回應形狀跟其他 404 一樣，所以照樣走例外對映——原本是
    端點自己手刻 JSONResponse，同一層有兩種產生錯誤回應的方式。
    """


class ThumbnailUnavailableError(ServiceError):
    """產不出這支影片的縮圖（檔案不存在或 ffmpeg 擷取失敗）。理由同
    DocumentNotFoundError。"""


class YoutubeSearchError(ServiceError):
    """YouTube 搜尋失敗（yt-dlp 解析失敗、網路問題、YouTube 改版等）。"""


class FrameUnavailableError(ServiceError):
    """抽不出這支影片指定時間點的畫面（檔案不存在或 ffmpeg 擷取失敗）。

    跟 ThumbnailUnavailableError 分開而不是共用：縮圖抽不出來對前端是正常狀態
    （顯示佔位圖就好），停格問答抽不出來則是使用者剛送出的請求失敗了，訊息要
    講得出是哪一秒。兩者的 HTTP 狀態碼也不同。
    """
