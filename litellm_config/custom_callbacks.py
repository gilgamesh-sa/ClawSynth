# custom_callbacks.py

from litellm.integrations.custom_logger import CustomLogger
import json
import aiofiles
from datetime import datetime

# This file includes the custom callbacks for LiteLLM Proxy
# Once defined, these can be passed in proxy_config.yaml
class MyCustomHandler(CustomLogger):
    def __init__(self, log_file_path="success_events.jsonl"):
        super().__init__()
        self.log_file_path = log_file_path

    def _get_daily_log_path(self):
        date_str = "all"
        base = self.log_file_path
        if base.endswith(".jsonl"):
            return base[:-6] + f"_{date_str}.jsonl"
        return base + f"_{date_str}"

    async def _async_append_to_jsonl(self, data):
        """Append data to JSONL file (asynchronous version)"""
        try:
            daily_path = self._get_daily_log_path()
            async with aiofiles.open(daily_path, 'a', encoding='utf-8') as f:
                await f.write(json.dumps(data, ensure_ascii=False, default=str) + '\n')
        except Exception as e:
            print(f"Error writing to JSONL file: {e}")

    @staticmethod
    def _obj_to_dict(obj):
        if isinstance(obj, dict):
            return obj
        elif isinstance(obj, list):
            return [MyCustomHandler._obj_to_dict(item) for item in obj]
        elif hasattr(obj, '__dict__'):
            return {k: MyCustomHandler._obj_to_dict(v) for k, v in obj.__dict__.items()}
        else:
            return str(obj)

    def log_pre_api_call(self, model, messages, kwargs):
        pass

    def log_post_api_call(self, kwargs, response_obj, start_time, end_time):
        pass

    def log_success_event(self, kwargs, response_obj, start_time, end_time):
        pass

    def log_failure_event(self, kwargs, response_obj, start_time, end_time):
        pass

    async def _async_log_success_event_internal(self, kwargs, response_obj, start_time, end_time):
        try:
            model = kwargs.get("model", None)
            messages = kwargs.get("messages", None)

            litellm_params = kwargs.get("litellm_params", {})
            metadata = litellm_params.get("metadata", {})

            # Anthropic 协议：system prompt 和 tools 在 optional_params 中
            optional_params = kwargs.get("optional_params", {})
            system = optional_params.get("system") or litellm_params.get("system")
            tools = optional_params.get("tools")

            log_data = {
                "model": model,
                "system": system,
                "messages": messages,
                "tools": tools,
                "response_obj": self._obj_to_dict(response_obj),
                "metadata": metadata,
                "start_time": start_time.isoformat() if hasattr(start_time, 'isoformat') else str(start_time),
                "duration": (end_time - start_time).total_seconds() if hasattr(end_time, '__sub__') else None
            }

            log_data = {k: v for k, v in log_data.items() if v is not None}

            await self._async_append_to_jsonl(log_data)

        except Exception as e:
            print(f"Error in _async_log_success_event_internal: {e}")

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        await self._async_log_success_event_internal(kwargs, response_obj, start_time, end_time)
        return

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        pass

proxy_handler_instance = MyCustomHandler("success_events.jsonl")

# Set litellm.callbacks = [proxy_handler_instance] on the proxy
# need to set litellm.callbacks = [proxy_handler_instance] # on the proxy