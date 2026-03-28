import os
import asyncio
from google import genai

# Configuration
API_KEY = os.environ.get("GOOGLE_API_KEY")

MODELS_TO_TEST = [
    "gemini-3.1-flash-lite-preview",
    "gemini-3-flash-preview",
    "gemini-3.1-pro-preview"
]

PARALLEL_TEST_MODEL = "gemini-3.1-flash-lite-preview"
PARALLEL_REQUEST_COUNT = 3
PROMPT = "what is your knowledge cutoff"

async def test_model_single(client, model_name):
    print(f"Testing {model_name}...")
    try:
        response = await client.aio.models.generate_content(
            model=model_name,
            contents=PROMPT
        )
        print(f"✅ Success: {response.text.strip()[:100]}...")
    except Exception as e:
        print(f"❌ Failed: {e}")
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

    tasks = [single_req() for _ in range(count)]
    results = await asyncio.gather(*tasks)
    
    success_count = sum(1 for r in results if r)
    print(f"Parallel Test Results: {success_count} / {count} succeeded.")
    return success_count

async def main():
    if not API_KEY:
        print("Error: GOOGLE_API_KEY environment variable not set.")
        print("Please run the script as: GOOGLE_API_KEY=your_key_here python test_gemini_models.py")
        return

    # Initialize client
    client = genai.Client(api_key=API_KEY)
    
    # Run individual tests sequentially
    for model_name in MODELS_TO_TEST:
        await test_model_single(client, model_name)

    # Run the parallel rate limit test
    await test_parallel_requests(client, PARALLEL_TEST_MODEL, PARALLEL_REQUEST_COUNT)

if __name__ == "__main__":
    asyncio.run(main())
