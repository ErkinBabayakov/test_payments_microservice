import asyncio
import logging

import httpx

from app.config import settings

log = logging.getLogger(__name__)

async def send_webhook_with_retries(url: str, payload: dict) -> bool:
    """Возрвращает True, если доставлен. Не бросает исключение, т.к. ошибка webhook не должна ронять 
    обработку платежа"""
    
    delay = settings.BASE_DELAY
    async with httpx.AsyncClient(timeout=settings.WEBHOOK_TIMEOUT_SECONDS) as client:
        for attempt in range(1, settings.WEBHOOK_MAX_RETRIES + 1):
            try:
                response = await client.post(url=url, json=payload)
                if 200 <= response.status_code < 300:
                    log.info("Webhook delivered url=%s attempt=%d", url, attempt)

                    return True
                if 400 <= response.status_code < 500:
                    log.warning("webhook rejected (4xx) url=%s status=%d attempt=%d",
                                url, response.status_code, attempt)
                    return False
                
                log.warning(
                    "webhook failed (5xx) url=%s status=%d attempt=%d",
                    url, response.status_code, attempt,
                )
            except httpx.HTTPError as exc:
                log.warning("webhook error url=%s err=%s attempt=%d", url, exc, attempt)

            if attempt < settings.WEBHOOK_MAX_RETRIES:
                await asyncio.sleep(delay)
                delay *= 2

    log.error("webhook dropped after %d attempts url=%s", settings.WEBHOOK_MAX_RETRIES, url)
    return False