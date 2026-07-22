"""DynamoDBアクセス層。

single-table設計: household_id(PK, 固定値"default") + captured_at(SK)。
SKのプレフィックスでアイテム種別を区別する:
- SNAPSHOT#<iso timestamp> : 食材スナップショット(食材名リスト、有無管理のみ・数量は持たない)
- SLACK_CURSOR             : Slack新着メッセージ取り込みカーソル(singleton)
- RECIPE_MSG#<message ts>  : 朝の提案メッセージ ⇔ 使用食材の対応記録(在庫消費のpull型トラッキング用)

食材名の正規化ルール(このモジュール・ingredient_normalizer.py・scripts/seed_ingredients.py で共通):
小文字・trim済みの英語名を正準形とする。表記が揺れると消費/追加の集合演算が壊れるため厳守する。
"""
import datetime
import os
from dataclasses import dataclass, field
from typing import Optional

import boto3
from boto3.dynamodb.conditions import Attr, Key

HOUSEHOLD_ID = "default"
SNAPSHOT_TTL_DAYS = 14
RECIPE_MSG_TTL_DAYS = int(os.environ.get("CONSUMPTION_WINDOW_DAYS", "4"))


@dataclass(frozen=True)
class RecipeMessageRecord:
    message_ts: str
    ingredients_used: list[str]
    recipe_titles: list[str] = field(default_factory=list)
    consumed: bool = False


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _ttl_epoch(days: int) -> int:
    return int((_now() + datetime.timedelta(days=days)).timestamp())


class DynamoStore:
    def __init__(self, table_name: str, region_name: str) -> None:
        self._table = boto3.resource("dynamodb", region_name=region_name).Table(table_name)

    def get_latest_ingredients(self) -> list[str]:
        response = self._table.query(
            KeyConditionExpression=Key("household_id").eq(HOUSEHOLD_ID)
            & Key("captured_at").begins_with("SNAPSHOT#"),
            ScanIndexForward=False,
            Limit=1,
        )
        items = response.get("Items", [])
        if not items:
            return []
        return [item["name"] for item in items[0].get("items", [])]

    def put_snapshot(self, ingredient_names: list[str]) -> None:
        now = _now()
        self._table.put_item(
            Item={
                "household_id": HOUSEHOLD_ID,
                "captured_at": f"SNAPSHOT#{now.isoformat()}",
                "items": [{"name": name} for name in ingredient_names],
                "ttl": _ttl_epoch(SNAPSHOT_TTL_DAYS),
            }
        )

    def merge_into_latest_snapshot(self, new_names: list[str]) -> None:
        """既存の最新スナップショットに新しい食材名を追加(union)して新スナップショットを書き込む。"""
        current = set(self.get_latest_ingredients())
        merged = sorted(current | set(new_names))
        self.put_snapshot(merged)

    def consume_ingredients(self, names_to_remove: list[str]) -> None:
        """既存の最新スナップショットから指定した食材名を除去して新スナップショットを書き込む。"""
        current = set(self.get_latest_ingredients())
        remaining = sorted(current - set(names_to_remove))
        self.put_snapshot(remaining)

    def get_slack_cursor(self) -> Optional[str]:
        response = self._table.get_item(
            Key={"household_id": HOUSEHOLD_ID, "captured_at": "SLACK_CURSOR"}
        )
        item = response.get("Item")
        return item["last_processed_ts"] if item else None

    def put_slack_cursor(self, ts: str) -> None:
        self._table.put_item(
            Item={
                "household_id": HOUSEHOLD_ID,
                "captured_at": "SLACK_CURSOR",
                "last_processed_ts": ts,
                "updated_at": _now().isoformat(),
            }
        )

    def get_pending_recipe_messages(self) -> list[RecipeMessageRecord]:
        response = self._table.query(
            KeyConditionExpression=Key("household_id").eq(HOUSEHOLD_ID)
            & Key("captured_at").begins_with("RECIPE_MSG#"),
            FilterExpression=Attr("consumed").eq(False),
        )
        return [
            RecipeMessageRecord(
                message_ts=item["captured_at"].removeprefix("RECIPE_MSG#"),
                ingredients_used=item["ingredients_used"],
                recipe_titles=item.get("recipe_titles", []),
                consumed=item["consumed"],
            )
            for item in response.get("Items", [])
        ]

    def put_recipe_message(self, record: RecipeMessageRecord) -> None:
        self._table.put_item(
            Item={
                "household_id": HOUSEHOLD_ID,
                "captured_at": f"RECIPE_MSG#{record.message_ts}",
                "ingredients_used": record.ingredients_used,
                "recipe_titles": record.recipe_titles,
                "consumed": record.consumed,
                "ttl": _ttl_epoch(RECIPE_MSG_TTL_DAYS),
            }
        )

    def mark_recipe_message_consumed(self, message_ts: str) -> None:
        # "consumed"はDynamoDBの予約語のためExpressionAttributeNamesでエイリアスする
        self._table.update_item(
            Key={"household_id": HOUSEHOLD_ID, "captured_at": f"RECIPE_MSG#{message_ts}"},
            UpdateExpression="SET #consumed = :true",
            ExpressionAttributeNames={"#consumed": "consumed"},
            ExpressionAttributeValues={":true": True},
        )
