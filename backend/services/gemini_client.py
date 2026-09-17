import os
import traceback

from google import genai
from google.genai import types


_api_key = (
    os.getenv("PPT_SURVEY_AI_API_KEY")
    or os.getenv("GEMINI_API_KEY")
    or os.getenv("GOOGLE_API_KEY")
)


def configure(api_key=None, **_kwargs):
    global _api_key
    _api_key = api_key or _api_key


def _create_client():
    if _api_key:
        return genai.Client(api_key=_api_key)
    return genai.Client()


def _normalize_model_name(model_name):
    model_name = (model_name or "").strip()
    if model_name.startswith("models/"):
        return model_name.removeprefix("models/")
    return model_name


class GenerativeModel:
    def __init__(self, model_name, system_instruction=None, **_kwargs):
        self.model_name = model_name
        self.system_instruction = system_instruction

    def generate_content(self, contents, generation_config=None, **_kwargs):
        config_data = dict(generation_config or {})
        if self.system_instruction:
            config_data["system_instruction"] = self.system_instruction
        config = types.GenerateContentConfig(**config_data) if config_data else None
        client = _create_client()
        try:
            return client.models.generate_content(
                model=_normalize_model_name(self.model_name),
                contents=contents,
                config=config,
            )
        except Exception:
            traceback.print_exc()
            raise
