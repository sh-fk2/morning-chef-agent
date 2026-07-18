"""AgentCore Gateway(Web Search Tool)のセットアップスクリプト。

Gateway Service Role(IAM)、Gateway本体、Web Search Toolターゲットを作成する。
アカウントID・リージョンはハードコードせず、boto3の認証情報と環境変数から取得する。

前提: 実行前に `aws sso login` 等で有効な認証情報が設定されていること。

環境変数:
    AWS_REGION (省略可、デフォルト: us-east-1)
    GATEWAY_NAME (省略可、デフォルト: recipe-search-gateway)
    GATEWAY_ROLE_NAME (省略可、デフォルト: morning-agent-gateway-service-role)
"""
import json
import os
import time

import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")
GATEWAY_NAME = os.environ.get("GATEWAY_NAME", "recipe-search-gateway")
GATEWAY_ROLE_NAME = os.environ.get("GATEWAY_ROLE_NAME", "morning-agent-gateway-service-role")
POLL_INTERVAL_SECONDS = 5
POLL_MAX_ATTEMPTS = 30


def _account_id(session: boto3.Session) -> str:
    return session.client("sts").get_caller_identity()["Account"]


def _create_or_get_gateway_role(session: boto3.Session, account_id: str) -> str:
    iam = session.client("iam")
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowAgentCoreToAssumeRole",
                "Effect": "Allow",
                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account_id},
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:bedrock-agentcore:{REGION}:{account_id}:gateway/*"
                    },
                },
            }
        ],
    }
    permission_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "InvokeGateway",
                "Effect": "Allow",
                "Action": "bedrock-agentcore:InvokeGateway",
                "Resource": f"arn:aws:bedrock-agentcore:{REGION}:{account_id}:gateway/*",
            },
            {
                "Sid": "InvokeWebSearch",
                "Effect": "Allow",
                "Action": "bedrock-agentcore:InvokeWebSearch",
                "Resource": f"arn:aws:bedrock-agentcore:{REGION}:aws:tool/web-search.v1",
            },
        ],
    }

    try:
        role = iam.create_role(
            RoleName=GATEWAY_ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
        )
        role_arn = role["Role"]["Arn"]
        print(f"Created IAM role: {role_arn}")
    except iam.exceptions.EntityAlreadyExistsException:
        role_arn = iam.get_role(RoleName=GATEWAY_ROLE_NAME)["Role"]["Arn"]
        print(f"Reusing existing IAM role: {role_arn}")

    iam.put_role_policy(
        RoleName=GATEWAY_ROLE_NAME,
        PolicyName="GatewayWebSearchAccess",
        PolicyDocument=json.dumps(permission_policy),
    )
    return role_arn


def _wait_until_ready(get_status_fn, resource_label: str) -> None:
    for attempt in range(1, POLL_MAX_ATTEMPTS + 1):
        status = get_status_fn()
        print(f"[{attempt}] {resource_label} status: {status}")
        if status == "READY":
            return
        if status == "FAILED":
            raise RuntimeError(f"{resource_label} creation failed")
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"{resource_label} did not become READY in time")


def main() -> None:
    session = boto3.Session(region_name=REGION)
    account_id = _account_id(session)
    role_arn = _create_or_get_gateway_role(session, account_id)

    client = session.client("bedrock-agentcore-control")

    gateway = client.create_gateway(
        name=GATEWAY_NAME,
        roleArn=role_arn,
        protocolType="MCP",
        authorizerType="AWS_IAM",
        description="Gateway for morning recipe suggester agent web search",
    )
    gateway_id = gateway["gatewayId"]
    print(f"Created gateway: {gateway_id}")
    print(f"Gateway URL: {gateway['gatewayUrl']}")

    _wait_until_ready(
        lambda: client.get_gateway(gatewayIdentifier=gateway_id)["status"],
        "Gateway",
    )

    target = client.create_gateway_target(
        gatewayIdentifier=gateway_id,
        name="web-search-tool",
        targetConfiguration={
            "mcp": {
                "connector": {
                    "source": {"connectorId": "web-search"},
                    "configurations": [{"name": "WebSearch", "parameterValues": {}}],
                }
            }
        },
        credentialProviderConfigurations=[{"credentialProviderType": "GATEWAY_IAM_ROLE"}],
    )
    target_id = target["targetId"]
    print(f"Created gateway target: {target_id}")

    _wait_until_ready(
        lambda: client.get_gateway_target(gatewayIdentifier=gateway_id, targetId=target_id)["status"],
        "Gateway target",
    )

    print("\nSetup complete.")
    print(f"GATEWAY_MCP_ENDPOINT={gateway['gatewayUrl']}")
    print(f"Gateway ARN={gateway['gatewayArn']}")
    print("\nNext: grant the recipe_agent execution role bedrock-agentcore:InvokeGateway on the Gateway ARN above.")


if __name__ == "__main__":
    main()
