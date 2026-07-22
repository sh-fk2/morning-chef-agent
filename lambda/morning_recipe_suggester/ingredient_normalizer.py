"""レシートOCRテキスト(iPhone Live Text経由、日本語想定)を英語の食材名リストに
正規化する。Bedrock Converse APIでtoolChoiceによるツール呼び出しを強制し、
フリーフォーマットJSONのパース失敗リスクを避ける。
"""
import boto3
from botocore.config import Config

_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})
_MAX_INGREDIENTS = 50

SYSTEM_PROMPT = """You will receive OCR'd text from a Japanese grocery receipt
(captured via iPhone Live Text, so it may contain minor OCR glitches).
The text mixes food line items with noise: store name, date, subtotal/tax
lines, prices, loyalty-point notices. Ignore all non-food lines.

For each actual food/ingredient line item:
- Strip quantity/pack-count/unit suffixes (e.g. "10個入", "1パック", "2本", "300g").
- Strip brand names and product-line names where a generic ingredient name exists.
- Normalize to a common, singular, lowercase English grocery ingredient name.
- Deduplicate.

Examples:
"たまご10個入 258円" -> "egg"
"サッポロ 牛乳 1L" -> "milk"
"国産キャベツ 1/2カット" -> "cabbage"
"小計" -> (ignore, not a food item)

If no food items are found, return an empty list. Call the
extract_ingredients tool exactly once with the final result."""

_TOOL_CONFIG = {
    "tools": [{
        "toolSpec": {
            "name": "extract_ingredients",
            "description": "Return the normalized English ingredient names extracted from receipt text.",
            "inputSchema": {"json": {
                "type": "object",
                "properties": {
                    "ingredients": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Canonical singular English ingredient names, lowercase.",
                    }
                },
                "required": ["ingredients"],
            }},
        }
    }],
    "toolChoice": {"tool": {"name": "extract_ingredients"}},
}


def normalize_ingredients(receipt_text: str, model_id: str, region_name: str) -> list[str]:
    client = boto3.client("bedrock-runtime", region_name=region_name, config=_CONFIG)
    response = client.converse(
        modelId=model_id,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": [{"text": receipt_text}]}],
        inferenceConfig={"maxTokens": 512, "temperature": 0},
        toolConfig=_TOOL_CONFIG,
    )
    content_blocks = response["output"]["message"]["content"]
    tool_use_block = next(block for block in content_blocks if "toolUse" in block)
    raw_ingredients = tool_use_block["toolUse"]["input"].get("ingredients", [])

    # モデル出力は未検証の入力として扱い、型・長さを検証してから利用する。
    return [
        name.strip().lower()
        for name in raw_ingredients
        if isinstance(name, str) and name.strip()
    ][:_MAX_INGREDIENTS]
