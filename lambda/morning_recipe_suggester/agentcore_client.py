import json

import boto3
from botocore.config import Config

# Web Search Tool呼び出し込みでBedrock推論が60秒を超える場合があるため、
# botocoreデフォルトのread_timeout(60秒)より長く設定する。
_BOTO_CONFIG = Config(read_timeout=120, connect_timeout=10)


def invoke_recipe_agent(agent_runtime_arn: str, region_name: str, ingredients: list[str]) -> list[dict]:
    """recipe_agent(AgentCore Runtime)を呼び出し、構造化されたレシピ提案リストを返す。

    recipe_agent側が{"recipes": [], "error": "..."}を返した場合(構造化出力の
    生成に失敗した場合)は例外を送出し、呼び出し元でフォールバック処理させる。
    """
    client = boto3.client("bedrock-agentcore", region_name=region_name, config=_BOTO_CONFIG)
    payload = json.dumps({"ingredients": ingredients}).encode()

    response = client.invoke_agent_runtime(
        agentRuntimeArn=agent_runtime_arn,
        payload=payload,
    )
    body = json.loads(response["response"].read())

    if body.get("error"):
        raise RuntimeError(f"recipe_agent failed to produce structured output: {body['error']}")

    return body["recipes"]
