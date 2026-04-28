import asyncio
import time
import os
from pathlib import Path
from openai import AsyncOpenAI

# Load the project root .env file
_env_file = Path(__file__).resolve().parents[1] / ".env"
if _env_file.exists():
    with open(_env_file, "r", encoding="utf-8") as _f:
        for _raw in _f:
            _line = _raw.strip()
            if not _line or _line.startswith("#"):
                continue
            _k, _sep, _v = _line.partition("=")
            if _sep and _k.strip() and _k.strip() not in os.environ:
                os.environ[_k.strip()] = _v.strip().strip("'\"")

api_key = os.environ.get("GEN_QUERY_API_KEY", "")
base_url = os.environ.get("GEN_QUERY_API_BASE", "")
model_name = os.environ.get("GEN_QUERY_MODEL", "")
# Initialize the asynchronous OpenAI client
client = AsyncOpenAI(
    api_key=api_key,
    base_url=base_url
)

async def make_request(request_id: int, model: str):
    """
    Send a single OpenAI request.
    """
    start_time = time.time()
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": f"Hello, this is request {request_id}. Reply with a very short word."}
            ],
            max_tokens=200
        )
        end_time = time.time()
        latency = end_time - start_time
        reply = response.choices[0].message.content.strip()
        print(f"[Request {request_id}] Success | Latency: {latency:.2f}s | Response: {reply.replace(chr(10), ' ')}")
        return True, latency
    except Exception as e:
        end_time = time.time()
        latency = end_time - start_time
        print(f"[Request {request_id}] Failed | Latency: {latency:.2f}s | Error: {str(e)}")
        return False, latency

async def test_concurrency(num_requests: int, model: str):
    """
    Test concurrent requests.
    """
    print("=== Starting concurrency test ===")
    print(f"Concurrent requests: {num_requests}")
    print(f"Test model: {model}")
    print(f"API Base URL: {base_url}\n")
    
    start_time = time.time()
    
    # Create all tasks
    tasks = [make_request(i, model) for i in range(num_requests)]
    
    # Execute concurrently and wait for all tasks to finish
    results = await asyncio.gather(*tasks)
    
    total_time = time.time() - start_time
    
    # Count successful and failed requests
    successful_requests = sum(1 for success, _ in results if success)
    failed_requests = sum(1 for success, _ in results if not success)
    print("=== Test summary ===")
    print(f"Total requests: {num_requests}")
    print(f"Successful: {successful_requests}")
    print(f"Failed: {failed_requests}")
    print(f"Total test time: {total_time:.2f}")
    
    if successful_requests > 0:
        times = [latency for success, latency in results if success]
        print(f"Average latency for successful requests: {sum(times)/len(times):.2f}s")
        print(f"Minimum latency for successful requests: {min(times):.2f}s")
        print(f"Maximum latency for successful requests: {max(times):.2f}s")

if __name__ == "__main__":
    CONCURRENT_REQUESTS = 5     # Concurrency level; adjust as needed
    asyncio.run(test_concurrency(num_requests=CONCURRENT_REQUESTS, model=model_name))
