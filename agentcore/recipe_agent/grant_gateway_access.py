"""recipe_agentのAgentCore Runtime実行ロールにGateway呼び出し権限を付与するスクリプト。

setup_gateway.py実行後、および `agentcore launch` で実行ロールが作成された後に実行する。

環境変数:
    EXECUTION_ROLE_NAME (必須): recipe_agentのAgentCore Runtime実行ロール名
        (.bedrock_agentcore.yaml の aws.execution_role から確認できる)
    GATEWAY_ARN (必須): setup_gateway.py の出力に表示されるGateway ARN
"""
import json
import os

import boto3

EXECUTION_ROLE_NAME = os.environ["EXECUTION_ROLE_NAME"]
GATEWAY_ARN = os.environ["GATEWAY_ARN"]


def main() -> None:
    iam = boto3.client("iam")
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "InvokeGateway",
                "Effect": "Allow",
                "Action": "bedrock-agentcore:InvokeGateway",
                "Resource": GATEWAY_ARN,
            }
        ],
    }
    iam.put_role_policy(
        RoleName=EXECUTION_ROLE_NAME,
        PolicyName="InvokeGatewayAccess",
        PolicyDocument=json.dumps(policy),
    )
    print(f"Granted bedrock-agentcore:InvokeGateway on {GATEWAY_ARN} to role {EXECUTION_ROLE_NAME}")


if __name__ == "__main__":
    main()
