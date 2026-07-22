import os
import traceback
from typing import Any

from agentcore_client import invoke_recipe_agent
from dynamo_store import DynamoStore, RecipeMessageRecord
from ingredient_normalizer import normalize_ingredients
from slack_client import SlackClient, get_bot_token

REGION = os.environ["AWS_REGION"]
TABLE_NAME = os.environ["TABLE_NAME"]
AGENT_RUNTIME_ARN = os.environ["AGENT_RUNTIME_ARN"]
SLACK_BOT_TOKEN_PARAM = os.environ["SLACK_BOT_TOKEN_PARAM"]
SLACK_CHANNEL_ID = os.environ["SLACK_CHANNEL_ID"]
INGREDIENT_MODEL_ID = os.environ.get("INGREDIENT_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")

MADE_IT_REACTION = "fried_egg"
PROCESSED_REACTION = "white_check_mark"


def format_slack_message(recipes: list[dict]) -> str:
    blocks = ["Good morning! Here are a couple of breakfast ideas using what you have."]
    for recipe in recipes:
        lines = [f"\n*{recipe['title']}*"]
        lines.extend(f"- {step}" for step in recipe["steps"])
        lines.append(f"Source: <{recipe['source_url']}|{recipe['source_title']}>")
        blocks.append("\n".join(lines))
    blocks.append(
        "\nMade one of these? React to this message with :fried_egg: and "
        "I'll update your ingredient list tomorrow morning."
    )
    return "\n".join(blocks)


def lambda_handler(event: dict, context: Any) -> dict:
    store = DynamoStore(TABLE_NAME, REGION)

    try:
        bot_token = get_bot_token(SLACK_BOT_TOKEN_PARAM, REGION)
    except Exception:
        print(traceback.format_exc())
        return {"statusCode": 500, "body": "failed to get slack bot token"}

    slack = SlackClient(bot_token=bot_token, channel_id=SLACK_CHANNEL_ID)

    try:
        # ① 前回提案への反応チェック・消費反映
        for record in store.get_pending_recipe_messages():
            reactions = slack.get_reactions(record.message_ts)
            if MADE_IT_REACTION in reactions:
                store.consume_ingredients(record.ingredients_used)
                store.mark_recipe_message_consumed(record.message_ts)

        # ② 新着メッセージ取り込み・食材追加
        cursor = store.get_slack_cursor()
        messages = slack.fetch_new_messages(oldest_ts=cursor)
        newest_ts = cursor
        for msg in messages:
            try:
                extracted = normalize_ingredients(msg["text"], INGREDIENT_MODEL_ID, REGION)
            except Exception:
                print(traceback.format_exc())
                continue  # このメッセージはカーソルを進めず、翌回リトライする
            if extracted:
                store.merge_into_latest_snapshot(extracted)
            slack.add_reaction(msg["ts"], PROCESSED_REACTION)
            newest_ts = msg["ts"]
        if newest_ts != cursor:
            store.put_slack_cursor(newest_ts)

        # ③ 食材スナップショット確定
        ingredients = store.get_latest_ingredients()
        if not ingredients:
            slack.post_message(
                "Good morning! No ingredients have been registered yet, "
                "so I don't know what's for breakfast today."
            )
            return {"statusCode": 200, "body": "no ingredients"}

        # ④ AgentCore Runtime呼び出し・レシピ提案生成(構造化)
        recipes = invoke_recipe_agent(AGENT_RUNTIME_ARN, REGION, ingredients)

        # ⑤ Slack投稿・今回の提案メッセージts記録
        text = format_slack_message(recipes)
        message_ts = slack.post_message(text)
        used = sorted({name for recipe in recipes for name in recipe["ingredients_used"]})
        store.put_recipe_message(RecipeMessageRecord(
            message_ts=message_ts,
            ingredients_used=used,
            recipe_titles=[recipe["title"] for recipe in recipes],
        ))
        return {"statusCode": 200, "body": "ok"}

    except Exception:
        print(traceback.format_exc())
        try:
            slack.post_message(
                "Good morning! Something went wrong while generating today's "
                "breakfast suggestion. Please check the logs."
            )
        except Exception:
            print(traceback.format_exc())
        return {"statusCode": 500, "body": "error"}
