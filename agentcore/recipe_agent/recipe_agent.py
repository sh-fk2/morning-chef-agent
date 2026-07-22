import os
import traceback
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
from pydantic import BaseModel, Field, ValidationError
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient

app = BedrockAgentCoreApp()

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
GATEWAY_MCP_ENDPOINT = os.environ["GATEWAY_MCP_ENDPOINT"]
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")

RESEARCH_SYSTEM_PROMPT = """You are a breakfast recipe research assistant.
You will be given a list of ingredients that are available at home right now.

Use the web search tool to look up current, popular recipes that use these
ingredients, then identify 2 to 3 breakfast dishes that can be made today
using them. For each, note the source URL and site name, and a short list
of cooking steps.

When listing which ingredients a recipe uses, copy the ingredient names
exactly as given in the input list (verbatim string match) - do not
paraphrase, pluralize, translate, or invent new names."""


class RecipeSuggestion(BaseModel):
    title: str = Field(description="Recipe title, plain text, no markdown.")
    steps: list[str] = Field(description="Ordered short cooking steps.")
    ingredients_used: list[str] = Field(
        description=(
            "Subset of the input ingredient list actually used in this recipe. "
            "Each value MUST be copied verbatim (exact string) from the provided "
            "ingredient list - do not paraphrase, pluralize, or rename."
        )
    )
    source_url: str = Field(description="URL of the recipe source.")
    source_title: str = Field(description="Display name of the recipe source site.")


class RecipeSuggestions(BaseModel):
    recipes: list[RecipeSuggestion] = Field(min_length=2, max_length=3)


@app.entrypoint
async def invoke_agent(payload: dict[str, Any], context: Any) -> dict[str, Any]:
    ingredients: list[str] = payload.get("ingredients", [])
    prompt = (
        f"Here are the ingredients I have on hand: {', '.join(ingredients)}\n"
        "Search for current, popular breakfast recipes that use these ingredients."
    )

    model = BedrockModel(model_id=MODEL_ID, region_name=AWS_REGION, temperature=0.3)
    mcp = MCPClient(lambda: aws_iam_streamablehttp_client(
        endpoint=GATEWAY_MCP_ENDPOINT,
        aws_region=AWS_REGION,
        aws_service="bedrock-agentcore",
    ))

    with mcp:
        agent = Agent(model=model, system_prompt=RESEARCH_SYSTEM_PROMPT, tools=mcp.list_tools_sync())

        try:
            result = await agent.invoke_async(prompt, structured_output_model=RecipeSuggestions)
        except (ValueError, ValidationError) as e:
            # structured_output_modelはtool_choiceを強制するため、モデルがツール呼び出しに
            # 失敗するとValueErrorを、スキーマ制約(min_length等)に違反するとValidationErrorを
            # 投げる。呼び出し元(Lambda)はこの形を見てフォールバック処理する。
            traceback.print_exc()
            return {"recipes": [], "error": str(e)}

    return result.structured_output.model_dump()


app.run()
