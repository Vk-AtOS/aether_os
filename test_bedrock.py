"""
Standalone AWS Bedrock connection test for AetherOS.

Usage:
    python test_bedrock.py

Requires AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_REGION in .env
or as environment variables. Also requires BEDROCK_ENABLED=true.
"""
import os
import sys

def load_env():
    """Load .env file without dotenv dependency."""
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        print("No .env file found")
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

load_env()

def check_credentials():
    key_id = os.environ.get("AWS_ACCESS_KEY_ID", "")
    secret  = os.environ.get("AWS_SECRET_ACCESS_KEY", "")
    region  = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    enabled = os.environ.get("BEDROCK_ENABLED", "false").lower() == "true"

    print("=== AWS Bedrock Configuration ===")
    print(f"  AWS_ACCESS_KEY_ID    : {'SET (' + key_id[:8] + '...)' if key_id else 'NOT SET ❌'}")
    print(f"  AWS_SECRET_ACCESS_KEY: {'SET' if secret else 'NOT SET ❌'}")
    print(f"  AWS_REGION           : {region}")
    print(f"  BEDROCK_ENABLED      : {'true ✓' if enabled else 'false ❌ (must be true)'}")

    heavy = os.environ.get("BEDROCK_MODEL_HEAVY", "us.anthropic.claude-sonnet-4-6")
    light = os.environ.get("BEDROCK_MODEL_LIGHT", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
    print(f"  BEDROCK_MODEL_HEAVY  : {heavy}")
    print(f"  BEDROCK_MODEL_LIGHT  : {light}")
    print()

    if not key_id or not secret:
        print("❌ AWS credentials missing. Add AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY to .env")
        return False
    if not enabled:
        print("❌ BEDROCK_ENABLED is not set to true. Add BEDROCK_ENABLED=true to .env")
        return False
    return True, region, heavy, light

def test_bedrock(region, model_id):
    try:
        import boto3
    except ImportError:
        print("❌ boto3 not installed. Run: pip install boto3")
        sys.exit(1)

    print(f"Testing model: {model_id}  (region: {region})")
    client = boto3.client(
        "bedrock-runtime",
        region_name=region,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )

    try:
        resp = client.converse(
            modelId=model_id,
            system=[{"text": "You are a helpful assistant."}],
            messages=[{"role": "user", "content": [{"text": "Reply with exactly: BEDROCK_OK"}]}],
            inferenceConfig={"maxTokens": 16},
        )
        text = resp["output"]["message"]["content"][0]["text"]
        usage = resp.get("usage", {})
        print(f"  Response  : {text.strip()}")
        print(f"  Tokens    : {usage.get('inputTokens', '?')} in / {usage.get('outputTokens', '?')} out")
        print(f"  ✅ Model {model_id} is working!")
        return True
    except Exception as e:
        err = str(e)
        print(f"  ❌ Error: {err}")
        if "AccessDeniedException" in err:
            print("     → Model not enabled. Go to AWS Console → Bedrock → Model access → enable Claude")
        elif "InvalidClientTokenId" in err or "AuthFailure" in err:
            print("     → Bad AWS credentials. Check your key ID and secret.")
        elif "UnrecognizedClientException" in err:
            print("     → Invalid credentials format.")
        elif "ResourceNotFoundException" in err:
            print("     → Model ID not found in this region. Check BEDROCK_MODEL_HEAVY value.")
        elif "InvalidPaymentInstrument" in err or "invalidpaymentinstrument" in err.lower():
            print("     → No payment method on AWS account. Add a credit card or use AWS credits.")
        return False

if __name__ == "__main__":
    result = check_credentials()
    if result is False:
        sys.exit(1)

    _, region, heavy, light = result
    print("=== Testing Models ===")
    heavy_ok = test_bedrock(region, heavy)
    print()
    if heavy != light:
        light_ok = test_bedrock(region, light)
    else:
        light_ok = heavy_ok

    print()
    print("=== Summary ===")
    print(f"  Heavy model ({heavy}): {'✅ OK' if heavy_ok else '❌ FAIL'}")
    print(f"  Light model ({light}): {'✅ OK' if light_ok else '❌ FAIL'}")

    if heavy_ok and light_ok:
        print()
        print("✅ Bedrock is fully configured! Set PRIMARY_LLM=bedrock in .env to use it.")
    else:
        sys.exit(1)
