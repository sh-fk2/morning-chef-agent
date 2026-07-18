"""朝ごはん提案エージェント用スタック。

EventBridge Scheduler(cron, JST 07:00) → Lambda → DynamoDB(食材リスト取得)
→ AgentCore Runtime(recipe_agent, Web Search Tool経由でレシピ検索)
→ Slack Incoming Webhook 投稿、という出力フローのみを構築する。
AgentCore Runtime/Gateway自体は bedrock-agentcore CLI で別途デプロイ済み。
"""
from pathlib import Path

from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_scheduler as scheduler
from constructs import Construct

LAMBDA_DIR = Path(__file__).parent.parent.parent / "lambda" / "morning_recipe_suggester"
LAMBDA_TIMEOUT_SECONDS = 150


class MorningAgentStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        recipe_agent_runtime_arn: str,
        slack_webhook_param_name: str,
        schedule_cron: str,
        schedule_timezone: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        table = dynamodb.TableV2(
            self,
            "IngredientsTable",
            partition_key=dynamodb.Attribute(name="household_id", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="captured_at", type=dynamodb.AttributeType.STRING),
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.DESTROY,
        )

        suggester_fn = lambda_.Function(
            self,
            "MorningRecipeSuggesterFn",
            runtime=lambda_.Runtime.PYTHON_3_13,
            architecture=lambda_.Architecture.ARM_64,
            handler="handler.lambda_handler",
            code=lambda_.Code.from_asset(str(LAMBDA_DIR)),
            timeout=Duration.seconds(LAMBDA_TIMEOUT_SECONDS),
            memory_size=256,
            environment={
                "TABLE_NAME": table.table_name,
                "AGENT_RUNTIME_ARN": recipe_agent_runtime_arn,
                "SLACK_WEBHOOK_PARAM": slack_webhook_param_name,
            },
        )

        table.grant_read_data(suggester_fn)

        suggester_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock-agentcore:InvokeAgentRuntime"],
                resources=[
                    recipe_agent_runtime_arn,
                    f"{recipe_agent_runtime_arn}/runtime-endpoint/*",
                ],
            )
        )

        suggester_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter{slack_webhook_param_name}"
                ],
            )
        )
        suggester_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["kms:Decrypt"],
                resources=[f"arn:aws:kms:{self.region}:{self.account}:key/*"],
                conditions={
                    "StringEquals": {
                        "kms:ViaService": f"ssm.{self.region}.amazonaws.com",
                    }
                },
            )
        )

        scheduler_role = iam.Role(
            self,
            "SchedulerInvokeRole",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
        )
        suggester_fn.grant_invoke(scheduler_role)

        scheduler.CfnSchedule(
            self,
            "MorningRecipeSchedule",
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(mode="OFF"),
            schedule_expression=schedule_cron,
            schedule_expression_timezone=schedule_timezone,
            target=scheduler.CfnSchedule.TargetProperty(
                arn=suggester_fn.function_arn,
                role_arn=scheduler_role.role_arn,
            ),
        )
