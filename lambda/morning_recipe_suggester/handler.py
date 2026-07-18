import os
import traceback

import boto3
from boto3.dynamodb.conditions import Key

from agentcore_client import invoke_recipe_agent
from slack_notifier import get_slack_webhook_url, post_to_slack

REGION = os.environ["AWS_REGION"]
TABLE_NAME = os.environ["TABLE_NAME"]
AGENT_RUNTIME_ARN = os.environ["AGENT_RUNTIME_ARN"]
SLACK_WEBHOOK_PARAM = os.environ["SLACK_WEBHOOK_PARAM"]
HOUSEHOLD_ID = "default"

dynamodb = boto3.resource("dynamodb", region_name=REGION)


def _get_latest_ingredients() -> list[str]:
    table = dynamodb.Table(TABLE_NAME)
    response = table.query(
        KeyConditionExpression=Key("household_id").eq(HOUSEHOLD_ID),
        ScanIndexForward=False,
        Limit=1,
    )
    items = response.get("Items", [])
    if not items:
        return []
    return [item["name"] for item in items[0].get("items", [])]


def lambda_handler(event, context):
    try:
        webhook_url = get_slack_webhook_url(SLACK_WEBHOOK_PARAM, REGION)
    except Exception:
        print(traceback.format_exc())
        return {"statusCode": 500, "body": "failed to get slack webhook url"}

    try:
        ingredients = _get_latest_ingredients()
        if not ingredients:
            post_to_slack(webhook_url, "Good morning! No ingredients have been registered yet, so I don't know what's for breakfast today.")
            return {"statusCode": 200, "body": "no ingredients"}

        recipe_text = invoke_recipe_agent(AGENT_RUNTIME_ARN, REGION, ingredients)
        post_to_slack(webhook_url, recipe_text)
        return {"statusCode": 200, "body": "ok"}

    except Exception:
        error_detail = traceback.format_exc()
        print(error_detail)
        post_to_slack(webhook_url, "Good morning! Something went wrong while generating today's breakfast suggestion. Please check the logs.")
        return {"statusCode": 500, "body": "error"}
