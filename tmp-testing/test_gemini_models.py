import os
import asyncio
from google import genai

# Configuration — uses Application Default Credentials (ADC), no API key needed.
PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "project-28637a4a-011d-427f-9da")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

MODELS_TO_TEST = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
]

PARALLEL_TEST_MODEL = "gemini-2.5-flash"
PARALLEL_REQUEST_COUNT = 3
PROMPT = "What is your knowledge cutoff?"


async def test_model_single(client, model_name):
    print(f"Testing {model_name}...")
    try:
        response = await client.aio.models.generate_content(
            model=model_name,
            contents=PROMPT
        )
        print(f"OK: {response.text.strip()[:100]}...")
    except Exception as e:
        print(f"FAIL: {e}")
    print("-" * 30)


async def test_parallel_requests(client, model_name, count):
    print(f"Running {count} parallel requests for {model_name}...")

    async def single_req():
        try:
            await client.aio.models.generate_content(
                model=model_name,
                contents=PROMPT
            )
            return True
        except Exception:
            return False

    results = await asyncio.gather(*[single_req() for _ in range(count)])
    success_count = sum(1 for r in results if r)
    print(f"Parallel Test Results: {success_count} / {count} succeeded.")
    return success_count


async def main():
    try:
        client = genai.Client(
            vertexai=True,
            project=PROJECT,
            location=LOCATION,
        )
    except Exception as e:
        print(f"Error: Failed to initialize Vertex AI client: {e}")
        print("Ensure ADC is configured: gcloud auth application-default login")
        return

    for model_name in MODELS_TO_TEST:
        await test_model_single(client, model_name)

    await test_parallel_requests(client, PARALLEL_TEST_MODEL, PARALLEL_REQUEST_COUNT)


if __name__ == "__main__":
    asyncio.run(main())
