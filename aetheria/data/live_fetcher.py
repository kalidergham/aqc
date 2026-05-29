"""
data/live_fetcher.py
====================

[قيد التطوير — يُستكمل بعد الخطوة 4]

جلب البيانات اللحظية (Live) من حساب MetaTrader 5 عبر MetaApi (SDK متوافق مع
Linux/Termux، بخلاف مكتبة MetaTrader5 الرسمية التي تعمل على Windows فقط).

الوظيفة المخطّطة:
    - فتح اتصال بحساب MT5 التجريبي باستخدام METAAPI_TOKEN و ACCOUNT_ID.
    - جلب آخر N شمعة لزوج وفريم محددين كـ pandas.DataFrame (نفس صيغة csv_fetcher).
    - توفير تدفّق دوري (كل دقيقة) لتغذية المحركات في وضع التداول اللحظي.

ملاحظة: MetaApi SDK غير متزامن (async)؛ لذلك الدوال هنا ستكون coroutines.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class LiveFetcher:
    """
    موصل البيانات اللحظية مع MetaTrader 5 عبر MetaApi.

    Attributes:
        token: توكن MetaApi.
        account_id: معرّف حساب MT5 في MetaApi.
        _connection: كائن الاتصال (يُهيّأ عند connect()).
    """

    def __init__(self, token: str, account_id: str) -> None:
        """تهيئة الموصل بالبيانات السرّية (دون فتح اتصال بعد)."""
        self.token = token
        self.account_id = account_id
        self._connection = None  # يُملأ في connect()

    async def connect(self) -> None:
        """
        فتح اتصال بحساب MT5 عبر MetaApi.

        TODO (بعد الخطوة 4):
            from metaapi_cloud_sdk import MetaApi
            api = MetaApi(self.token)
            account = await api.metatrader_account_api.get_account(self.account_id)
            await account.deploy(); await account.wait_connected()
            self._connection = account.get_rpc_connection()
            await self._connection.connect()
        """
        raise NotImplementedError("LiveFetcher.connect — قيد التطوير (الخطوة اللاحقة)")

    async def get_candles(self, symbol: str, timeframe: str, count: int = 200):
        """
        جلب آخر ``count`` شمعة لزوج وفريم محددين.

        Returns (مخطّط): pandas.DataFrame بنفس صيغة csv_fetcher
        (open/high/low/close/volume بفهرس زمني).
        """
        raise NotImplementedError("LiveFetcher.get_candles — قيد التطوير")
