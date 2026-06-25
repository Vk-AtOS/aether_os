import boto3
import json
import logging
import os
import time
from typing import Optional
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

class BedrockClient:
    """
    Client for generating patches via AWS Bedrock using the Converse API.

    Converse API is model-agnostic — works with Meta Llama, Mistral, Amazon Nova,
    and others without per-model request format changes.
    Default: Meta Llama3 70B (strong code reasoning, no billing instrument required).
    """

    def __init__(self):
        self.region = os.environ.get("AWS_REGION", "ap-south-1")
        # Meta Llama3 70B — code-capable, no cross-region prefix needed in ap-south-1.
        self.model_id = os.environ.get("BEDROCK_MODEL_ID", "meta.llama3-70b-instruct-v1:0")
        self.client = boto3.client(
            service_name="bedrock-runtime",
            region_name=self.region,
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        )

    def validate_response(self, text: str) -> bool:
        """Checks if the response contains a valid unified diff."""
        if not text:
            return False
        return "---" in text or "@@" in text

    def generate_patch(self, system_prompt: str, user_prompt: str, max_retries: int = 3) -> Optional[str]:
        """
        Generate a repair patch using Bedrock Converse API with retries on throttling.
        Converse API handles system/user message structure for all supported models.
        """
        for attempt in range(max_retries):
            try:
                response = self.client.converse(
                    modelId=self.model_id,
                    system=[{"text": system_prompt}],
                    messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                    inferenceConfig={"maxTokens": 2048, "temperature": 0.1},
                )
                content = response.get("output", {}).get("message", {}).get("content", [])
                if content:
                    text = content[0].get("text", "")
                    if self.validate_response(text):
                        return text
                    logger.warning("Invalid diff format from Bedrock on attempt %d", attempt + 1)

            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                if error_code == "ThrottlingException" and attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning("ThrottlingException, retrying in %ss…", wait_time)
                    time.sleep(wait_time)
                else:
                    logger.error("Bedrock invocation failed: %s", e)
                    return None
            except Exception as e:
                logger.error("Unexpected error during Bedrock generation: %s", e)
                return None

        return None
