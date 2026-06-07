# -*- coding: utf-8 -*-
"""
CCASS TelegramPusher — 直接 Telegram Bot API 推送，附重試/降級/限速處理

參考 DSA `src/notification_sender/telegram_sender.py` 架構，
為 CCASS 掃描器提供穩健的 Telegram 發送能力，唔依賴 GAS。

用法:
    pusher = TelegramPusher(bot_token="...", chat_id="-100...")
    pusher.send_message("**粗體** _斜體_", parse_mode="Markdown")
    pusher.send_alert("00700", "POC_BREAKOUT", "騰訊 POC 突破 $400")
"""

from __future__ import annotations

import logging
import re
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Telegram 消息最大長度
_TG_MAX_LENGTH = 4096


class TelegramPusher:
    """直接 Telegram Bot API 推送器，備有重試、Markdown 降級、rate-limit 處理。"""

    def __init__(self, bot_token: str, chat_id: str, *, message_thread_id: Optional[str] = None):
        """
        Args:
            bot_token: Telegram Bot Token（由 @BotFather 獲取）
            chat_id:  目標 chat/channel ID（負數為 channel/supergroup）
            message_thread_id: （可選）topic/thread ID
        """
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._message_thread_id = message_thread_id

    @property
    def configured(self) -> bool:
        """檢查基本配置是否完整。"""
        return bool(self._bot_token and self._chat_id)

    # ── Public API ────────────────────────────────────────────────────────────

    def send_message(
        self,
        text: str,
        *,
        parse_mode: str = "Markdown",
        disable_web_page_preview: bool = True,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        """發送一條 Telegram 文字訊息（含重試 + 降級）。

        Returns:
            True 如果發送成功
        """
        if not self.configured:
            logger.warning("TelegramPusher 配置不完整，跳過推送")
            return False

        if len(text) <= _TG_MAX_LENGTH:
            return self._send_single(text, parse_mode=parse_mode,
                                     disable_web_page_preview=disable_web_page_preview,
                                     timeout_seconds=timeout_seconds)
        else:
            return self._send_chunked(text, parse_mode=parse_mode,
                                      disable_web_page_preview=disable_web_page_preview,
                                      timeout_seconds=timeout_seconds)

    def send_alert(
        self,
        stock_code: str,
        alert_type: str,
        message: str,
        *,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        """發送 CCASS 掃描器 alert 專用方法。

        自動格式化為統一 alert 格式再送出。
        """
        full_text = f"*[{alert_type}]* `{stock_code}`\n{message}"
        return self.send_message(full_text, timeout_seconds=timeout_seconds)

    # ── Internal: single message ──────────────────────────────────────────────

    def _send_single(
        self,
        text: str,
        *,
        parse_mode: str = "Markdown",
        disable_web_page_preview: bool = True,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        """發送單條 Telegram 訊息，含指數退避重試、rate-limit 處理、Markdown 降級。"""
        api_url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        telegram_text = self._convert_to_telegram_markdown(text)

        payload: dict = {
            "chat_id": self._chat_id,
            "text": telegram_text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if self._message_thread_id:
            payload["message_thread_id"] = self._message_thread_id

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                response = requests.post(api_url, json=payload, timeout=timeout_seconds or 10)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                if attempt < max_retries:
                    delay = 2 ** attempt  # 2s, 4s
                    logger.warning(
                        "Telegram request failed (attempt %d/%d): %s, retrying in %ds...",
                        attempt, max_retries, e, delay,
                    )
                    time.sleep(delay)
                    continue
                else:
                    logger.error("Telegram request failed after %d attempts: %s", max_retries, e)
                    return False

            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    logger.info("Telegram 消息發送成功")
                    return True
                else:
                    error_desc = result.get("description", "未知錯誤")
                    logger.error("Telegram 返回錯誤: %s", error_desc)

                    # Markdown 解析失敗 → 降級為純文字
                    if self._should_fallback_to_plain_text(error_desc=error_desc):
                        if self._send_plain_text_fallback(api_url, payload, text, timeout_seconds):
                            return True
                    return False

            elif response.status_code == 429:
                # Rate limited — 尊重 Retry-After header
                retry_after = int(response.headers.get("Retry-After", 2 ** attempt))
                if attempt < max_retries:
                    logger.warning(
                        "Telegram rate limited, retrying in %ds (attempt %d/%d)...",
                        retry_after, attempt, max_retries,
                    )
                    time.sleep(retry_after)
                    continue
                else:
                    logger.error("Telegram rate limited after %d attempts", max_retries)
                    return False

            else:
                # 5xx server errors → retry
                if attempt < max_retries and response.status_code >= 500:
                    delay = 2 ** attempt
                    logger.warning(
                        "Telegram server error HTTP %d (attempt %d/%d), retrying in %ds...",
                        response.status_code, attempt, max_retries, delay,
                    )
                    time.sleep(delay)
                    continue
                # Check for Markdown parse errors in response
                if self._should_fallback_to_plain_text(response_text=response.text):
                    if self._send_plain_text_fallback(api_url, payload, text, timeout_seconds):
                        return True
                logger.error("Telegram 請求失敗: HTTP %d", response.status_code)
                logger.error("響應內容: %s", response.text[:300])
                return False

        return False

    def _send_plain_text_fallback(
        self,
        api_url: str,
        payload: dict,
        text: str,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        """Markdown 解析失敗時，用純文字重試。"""
        logger.info("Telegram Markdown 解析失敗，嘗試純文字格式重發...")
        plain_payload = dict(payload)
        plain_payload.pop("parse_mode", None)
        plain_payload["text"] = text  # 用原始 text，唔用轉換後嘅 telegram_text

        try:
            response = requests.post(api_url, json=plain_payload, timeout=timeout_seconds or 10)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            logger.error("Telegram plain-text fallback failed: %s", e)
            return False

        if response.status_code == 200:
            try:
                result = response.json()
            except ValueError:
                logger.error("Telegram 純文字回退失敗: 非 JSON 響應")
                logger.error("響應內容: %s", response.text[:300])
                return False

            if result.get("ok"):
                logger.info("Telegram 消息發送成功（純文字）")
                return True

            logger.error("Telegram 純文字回退失敗: API 返回 ok=false")
            logger.error("響應內容: %s", response.text[:300])
            return False

        logger.error("Telegram 純文字回退失敗: HTTP %d", response.status_code)
        logger.error("響應內容: %s", response.text[:300])
        return False

    # ── Internal: chunked messages ────────────────────────────────────────────

    def _send_chunked(
        self,
        content: str,
        *,
        parse_mode: str = "Markdown",
        disable_web_page_preview: bool = True,
        timeout_seconds: Optional[float] = None,
    ) -> bool:
        """分段發送長消息（按 `\\n---\\n` 分隔）。"""
        sections = content.split("\n---\n")
        current_chunk: list[str] = []
        current_length = 0
        all_success = True
        chunk_index = 1

        for section in sections:
            section_length = len(section) + 5  # +5 for "\n---\n"

            if current_length + section_length > _TG_MAX_LENGTH:
                if current_chunk:
                    chunk_content = "\n---\n".join(current_chunk)
                    logger.info("發送 Telegram 消息塊 %d...", chunk_index)
                    if not self._send_single(
                        chunk_content,
                        parse_mode=parse_mode,
                        disable_web_page_preview=disable_web_page_preview,
                        timeout_seconds=timeout_seconds,
                    ):
                        all_success = False
                    chunk_index += 1
                current_chunk = [section]
                current_length = section_length
            else:
                current_chunk.append(section)
                current_length += section_length

        if current_chunk:
            chunk_content = "\n---\n".join(current_chunk)
            logger.info("發送 Telegram 消息塊 %d...", chunk_index)
            if not self._send_single(
                chunk_content,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
                timeout_seconds=timeout_seconds,
            ):
                all_success = False

        return all_success

    # ── Markdown helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _should_fallback_to_plain_text(error_desc: str = "", response_text: str = "") -> bool:
        """檢測 Telegram Markdown 解析失敗，需要降級為純文字。"""
        haystack = f"{error_desc}\n{response_text}".lower()
        markers = (
            "can't parse entities",
            "can't parse entity",
            "can't find end of the entity",
            "parse entities",
            "parse_mode",
            "markdown",
        )
        return any(marker in haystack for marker in markers)

    @staticmethod
    def _convert_to_telegram_markdown(text: str) -> str:
        """將標準 Markdown 轉換為 Telegram 支援嘅格式。

        Telegram Markdown 限制:
        - 唔支援 # 標題
        - 用 *bold* 而非 **bold**
        - 用 _italic_
        - 特殊符號要 escape（除咗 link）
        """
        import uuid as _uuid

        result = text

        # 移除 # 標題標記（Telegram 唔支援）
        result = re.sub(r"^#{1,6}\s+", "", result, flags=re.MULTILINE)

        # 轉換 **bold** → *bold*
        result = re.sub(r"\*\*(.+?)\*\*", r"*\1*", result)

        # 保護 link syntax [text](url)
        _link_placeholder = f"__LINK_{_uuid.uuid4().hex[:8]}__"
        _links: list[str] = []

        def _save_link(m: re.Match) -> str:
            _links.append(m.group(0))
            return f"{_link_placeholder}{len(_links) - 1}"

        result = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", _save_link, result)

        # Escape 特殊符號
        for char in ["[", "]", "(", ")"]:
            result = result.replace(char, f"\\{char}")

        # 還原 link
        for i, link in enumerate(_links):
            result = result.replace(f"{_link_placeholder}{i}", link)

        return result
