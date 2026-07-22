"""DynamoDBの食材リストテーブルに、直近の食材リストを手動投入するスクリプト。

食材の自動取り込みは、iPhoneのLive Text(テキスト認識表示)でレシートをOCRし
Slackに投稿する運用+Bedrockでの正規化(ingredient_normalizer.py)が担う。
このスクリプトは手動オーバーライド用(デモ・デバッグ・初回投入・状態リセット)
として残しており、既存の食材リストを"上書き"する点に注意(自動取り込みは追加=union)。

環境変数:
    TABLE_NAME (必須): CDKでデプロイしたDynamoDBテーブル名
    AWS_REGION (省略可、デフォルト: us-east-1)
"""
import datetime
import os
import sys

import boto3

TABLE_NAME = os.environ["TABLE_NAME"]
REGION = os.environ.get("AWS_REGION", "us-east-1")
HOUSEHOLD_ID = "default"
TTL_DAYS = 14


def seed(ingredient_names: list[str]) -> None:
    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    table = dynamodb.Table(TABLE_NAME)

    now = datetime.datetime.now(datetime.timezone.utc)
    ttl_epoch = int((now + datetime.timedelta(days=TTL_DAYS)).timestamp())

    table.put_item(
        Item={
            "household_id": HOUSEHOLD_ID,
            "captured_at": f"SNAPSHOT#{now.isoformat()}",
            "items": [{"name": name} for name in ingredient_names],
            "ttl": ttl_epoch,
        }
    )
    print(f"Seeded {len(ingredient_names)} ingredients into {TABLE_NAME}: {ingredient_names}")


if __name__ == "__main__":
    names = sys.argv[1:] or ["egg", "bread", "bacon", "tomato"]
    seed(names)
