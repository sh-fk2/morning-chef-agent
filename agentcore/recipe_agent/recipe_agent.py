import os
from typing import Any, AsyncIterator

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient

app = BedrockAgentCoreApp()

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
GATEWAY_MCP_ENDPOINT = os.environ["GATEWAY_MCP_ENDPOINT"]
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")

SYSTEM_PROMPT = """You are a breakfast recipe assistant for a morning notification bot.
You will be given a list of ingredients that are available at home right now.

Use the web search tool to look up current, popular recipes that use these
ingredients, then suggest 2 to 3 breakfast dishes that can be made today,
each with a short list of steps.

For every recipe you suggest, cite the source using the "url" field returned
by the search tool. Always include the actual URL, not just the site name.

Write the entire response in English. The output will be posted directly to
a Slack channel via an Incoming Webhook, which renders Slack's "mrkdwn"
syntax, NOT standard Markdown. Follow these formatting rules strictly:
- Use *single asterisks* for bold text. Never use Markdown's **double
  asterisks**.
- Never use Markdown headings such as #, ##, or ###. Use a bold line
  (e.g. *Bacon and Egg Sandwich*) or an emoji instead of a heading.
- Format every link as <https://example.com|display text>, always including
  display text after the pipe character. Never write a bare link like
  <https://example.com> with no display text, and never use Markdown's
  [display text](https://example.com) syntax.
- Never use inline code (backticks), horizontal rules or separators of any
  kind (---, ___, ***, or repeated dashes), blockquotes (>), or Markdown
  tables.
- Keep lists simple: one item per line, prefixed with "-" or a number
  followed by a period. Do not use nested Markdown list syntax.

Keep the tone warm and concise, suitable for a quick morning read."""


@app.entrypoint
async def invoke_agent(payload: dict[str, Any], context: Any) -> AsyncIterator[Any]:
    ingredients: list[str] = payload.get("ingredients", [])
    prompt = (
        f"Here are the ingredients I have on hand: {', '.join(ingredients)}\n"
        "Please search for current, popular breakfast recipes that use these "
        "ingredients and suggest some for me."
    )

    model = BedrockModel(model_id=MODEL_ID, region_name=AWS_REGION, temperature=0.3)
    mcp = MCPClient(lambda: aws_iam_streamablehttp_client(
        endpoint=GATEWAY_MCP_ENDPOINT,
        aws_region=AWS_REGION,
        aws_service="bedrock-agentcore",
    ))

    with mcp:
        agent = Agent(model=model, system_prompt=SYSTEM_PROMPT, tools=mcp.list_tools_sync())
        stream = agent.stream_async(prompt)
        async for event in stream:
            yield event


app.run()
