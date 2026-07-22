#!/usr/bin/env python3
"""CDK アプリのエントリポイント。

すべての環境固有パラメータは環境変数で指定する(GitHub公開を前提にハードコードを避ける)。
"""
import os

import aws_cdk as cdk

from stacks.morning_agent_stack import MorningAgentStack

app = cdk.App()

deploy_region = os.environ.get("DEPLOY_REGION", "us-east-1")
recipe_agent_runtime_arn = os.environ["RECIPE_AGENT_RUNTIME_ARN"]
slack_bot_token_param_name = os.environ.get("SLACK_BOT_TOKEN_PARAM_NAME", "/morning-agent/slack-bot-token")
slack_channel_id = os.environ["SLACK_CHANNEL_ID"]
ingredient_model_id = os.environ.get("INGREDIENT_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
schedule_cron = os.environ.get("SCHEDULE_CRON", "cron(0 7 * * ? *)")
schedule_timezone = os.environ.get("SCHEDULE_TIMEZONE", "UTC")

MorningAgentStack(
    app,
    "MorningRecipeAgent",
    recipe_agent_runtime_arn=recipe_agent_runtime_arn,
    slack_bot_token_param_name=slack_bot_token_param_name,
    slack_channel_id=slack_channel_id,
    ingredient_model_id=ingredient_model_id,
    schedule_cron=schedule_cron,
    schedule_timezone=schedule_timezone,
    env=cdk.Environment(region=deploy_region),
)

app.synth()
