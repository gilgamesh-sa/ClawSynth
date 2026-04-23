import asyncio
import time
import os
from pathlib import Path
from openai import AsyncOpenAI

# 加载项目根目录 .env
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
# 初始化异步的 OpenAI 客户端
client = AsyncOpenAI(
    api_key=api_key,
    base_url=base_url
)

async def make_request(request_id: int, model: str):
    """
    发起单个 OpenAI 请求
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
        print(f"[Request {request_id}] 成功 | 耗时: {latency:.2f}s | 响应: {reply.replace(chr(10), ' ')}")
        return True, latency
    except Exception as e:
        end_time = time.time()
        latency = end_time - start_time
        print(f"[Request {request_id}] 失败 | 耗时: {latency:.2f}s | 错误: {str(e)}")
        return False, latency

async def test_concurrency(num_requests: int, model: str):
    """
    测试并发调用
    """
    print(f"=== 开始并发测试 ===")
    print(f"并发请求数: {num_requests}")
    print(f"测试模型: {model}")
    print(f"API Base URL: {base_url}\n")
    
    start_time = time.time()
    
    # 创建所有的任务
    tasks = [make_request(i, model) for i in range(num_requests)]
    
    # 并发执行并等待所有任务完成
    results = await asyncio.gather(*tasks)
    
    total_time = time.time() - start_time
    
    # 统计成功与失败的次数
    successful_requests = sum(1 for success, _ in results if success)
    failed_requests = sum(1 for success, _ in results if not success)
    print("=== 测试统计结果 ===")
    print(f"总请求数: {num_requests}")
    print(f"成功: {successful_requests}")
    print(f"失败: {failed_requests}")
    print(f"测试总耗时: {total_time:.2f}")
    
    if successful_requests > 0:
        times = [latency for success, latency in results if success]
        print(f"成功请求平均耗时: {sum(times)/len(times):.2f}s")
        print(f"成功请求最小耗时: {min(times):.2f}s")
        print(f"成功请求最大耗时: {max(times):.2f}s")

if __name__ == "__main__":
    CONCURRENT_REQUESTS = 5     # 并发数量，可以根据需要调整
    asyncio.run(test_concurrency(num_requests=CONCURRENT_REQUESTS, model=model_name))
