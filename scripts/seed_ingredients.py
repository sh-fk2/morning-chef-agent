"""DynamoDBの食材リストテーブルに、直近の食材リストを手動投入するスクリプト。

レシート画像解析(Bedrock Vision)による自動投入は将来の拡張とし、
現時点ではこのスクリプトで手動投入する運用とする。

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
            "captured_at": now.isoformat(),
            "items": [{"name": name} for name in ingredient_names],
            "ttl": ttl_epoch,
        }
    )
    print(f"Seeded {len(ingredient_names)} ingredients into {TABLE_NAME}: {ingredient_names}")


if __name__ == "__main__":
    names = sys.argv[1:] or ["egg", "bread", "bacon", "tomato"]
    seed(names)
