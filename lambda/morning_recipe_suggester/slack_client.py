"""Slack Bot Token(Web API)を使ったSlackとのやり取り。

chat.postMessage / conversations.history / reactions.add / reactions.get を
標準ライブラリのurllib.requestのみで呼び出す(追加のサードパーティ依存を避け、
CDKのLambdaコードアセットに依存関係バンドリングの仕組みを増やさないため)。

Incoming Webhookではなくchat.postMessageに統一している理由: 在庫消費管理の
pull型トラッキングには投稿メッセージのts(タイムスタンプ)が必須だが、
Incoming Webhookはtsを返さないため。
"""
import json
import urllib.parse
import urllib.request
from typing import Optional

import boto3

SLACK_API_BASE = "https://slack.com/api"
_REQUEST_TIMEOUT_SECONDS = 10


def get_bot_token(parameter_name: str, region_name: str) -> str:
    ssm = boto3.client("ssm", region_name=region_name)
    response = ssm.get_parameter(Name=parameter_name, WithDecryption=True)
    return response["Parameter"]["Value"]


class SlackClient:
    def __init__(self, bot_token: str, channel_id: str) -> None:
        self._bot_token = bot_token
        self._channel_id = channel_id
        self._bot_user_id: Optional[str] = None

    def _post(self, method: str, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{SLACK_API_BASE}/{method}",
            data=body,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "Authorization": f"Bearer {self._bot_token}",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read())
        if not result.get("ok"):
            raise RuntimeError(f"Slack API error calling {method}: {result.get('error')}")
        return result

    def _get(self, method: str, params: dict) -> dict:
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(
            f"{SLACK_API_BASE}/{method}?{query}",
            headers={"Authorization": f"Bearer {self._bot_token}"},
            method="GET",
        )
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read())
        if not result.get("ok"):
            raise RuntimeError(f"Slack API error calling {method}: {result.get('error')}")
        return result

    def _get_bot_user_id(self) -> str:
        if self._bot_user_id is None:
            result = self._get("auth.test", {})
            self._bot_user_id = result["user_id"]
        return self._bot_user_id

    def post_message(self, text: str) -> str:
        result = self._post("chat.postMessage", {"channel": self._channel_id, "text": text})
        return result["ts"]

    def fetch_new_messages(self, oldest_ts: Optional[str]) -> list[dict]:
        """oldest_ts(exclusive)以降の新着メッセージを、bot自身の投稿を除いて古い順に返す。

        Slack APIのレート制限(1リクエスト15件・1分1回、2025-05-29以降作成のアプリが対象)
        に配慮し、1リクエストあたり15件・next_cursorでページネーションする。
        """
        bot_user_id = self._get_bot_user_id()
        messages: list[dict] = []
        cursor = None
        while True:
            params = {"channel": self._channel_id, "limit": "15"}
            if oldest_ts:
                params["oldest"] = oldest_ts
            if cursor:
                params["cursor"] = cursor
            result = self._get("conversations.history", params)
            for msg in result.get("messages", []):
                if msg.get("user") == bot_user_id or msg.get("bot_id"):
                    continue
                if msg.get("subtype"):
                    continue  # channel_join等のシステムメッセージ(通常投稿にはsubtypeが無い)を除外
                if oldest_ts and msg["ts"] == oldest_ts:
                    continue  # oldestはinclusiveのため、処理済みの境界メッセージを除外する
                if msg.get("text"):
                    messages.append(msg)
            cursor = result.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break
        return sorted(messages, key=lambda m: m["ts"])  # historyはデフォルトで新しい順なので古い順に戻す

    def add_reaction(self, message_ts: str, emoji_name: str) -> None:
        try:
            self._post("reactions.add", {
                "channel": self._channel_id, "timestamp": message_ts, "name": emoji_name,
            })
        except RuntimeError as e:
            if "already_reacted" in str(e):
                return
            raise

    def get_reactions(self, message_ts: str) -> list[str]:
        result = self._get("reactions.get", {"channel": self._channel_id, "timestamp": message_ts})
        message = result.get("message", {})
        return [r["name"] for r in message.get("reactions", [])]
