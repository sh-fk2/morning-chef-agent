import json
import urllib.request

import boto3


def get_slack_webhook_url(parameter_name: str, region_name: str) -> str:
    ssm = boto3.client("ssm", region_name=region_name)
    response = ssm.get_parameter(Name=parameter_name, WithDecryption=True)
    return response["Parameter"]["Value"]


def post_to_slack(webhook_url: str, text: str) -> None:
    body = json.dumps({"text": text}).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        response.read()
