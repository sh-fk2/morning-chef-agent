import json

import boto3
from botocore.config import Config

# Web Search Tool呼び出し込みでBedrock推論が60秒を超える場合があるため、
# botocoreデフォルトのread_timeout(60秒)より長く設定する。
_BOTO_CONFIG = Config(read_timeout=120, connect_timeout=10)


def invoke_recipe_agent(agent_runtime_arn: str, region_name: str, ingredients: list[str]) -> str:
    """recipe_agent(AgentCore Runtime)を呼び出し、SSEストリームをテキストに変換して返す。"""
    client = boto3.client("bedrock-agentcore", region_name=region_name, config=_BOTO_CONFIG)
    payload = json.dumps({"ingredients": ingredients}).encode()

    response = client.invoke_agent_runtime(
        agentRuntimeArn=agent_runtime_arn,
        payload=payload,
    )

    buffer = ""
    for line in response["response"].iter_lines():
        if not line or not line.decode("utf-8").startswith("data: "):
            continue

        data = line.decode("utf-8")[6:]
        if data.startswith('"') or data.startswith("'"):
            continue

        event = json.loads(data)

        if "data" in event and isinstance(event["data"], str):
            buffer += event["data"]
        elif "event" in event and "contentBlockDelta" in event["event"]:
            buffer += event["event"]["contentBlockDelta"]["delta"].get("text", "")

    return buffer
