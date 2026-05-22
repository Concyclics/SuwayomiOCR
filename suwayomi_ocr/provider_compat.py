"""Cross-provider compatibility helpers.

Different OpenAI-compatible vendors expose chain-of-thought differently.
We send the union of every known "disable thinking" field at once; each
provider silently ignores fields it doesn't recognise, so this is
zero-config and safe for non-thinking models too.

Recognised formats:

  | Provider                                  | Field |
  |-------------------------------------------|-------|
  | DeepSeek v4-flash / v4-pro (api.deepseek.com) | `thinking: {type: "disabled"}` |
  | Doubao / Volcano Ark thinking models      | `thinking: {type: "disabled"}` |
  | Anthropic via OpenAI-compat proxy         | `thinking: {type: "disabled"}` |
  | SGLang serving Qwen3 chat template        | `chat_template_kwargs: {enable_thinking: false}` |
  | vLLM serving Qwen3 chat template          | `chat_template_kwargs: {enable_thinking: false}` |
  | DashScope Qwen3-* native field            | `enable_thinking: false` |
  | OpenAI o-series / GPT-5                   | `reasoning_effort: "minimal"` |

For an unusual provider, set `OCR_EXTRA_BODY` / `TRANSLATION_EXTRA_BODY`
to a JSON object — that replaces the default bundle entirely.
"""

import json
import os

_DISABLE_THINKING_BUNDLE = {
    "thinking": {"type": "disabled"},
    "chat_template_kwargs": {"enable_thinking": False},
    "enable_thinking": False,
    "reasoning_effort": "minimal",
}


def disable_thinking_extra(env_var: str = "") -> dict:
    """Return an extra_body dict that disables thinking on every known provider.

    If `env_var` names an environment variable holding a JSON object, that
    object is returned instead — letting users target an unknown provider.
    """
    if env_var:
        raw = os.environ.get(env_var)
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                print(f"[!] {env_var} is not valid JSON ({exc}); ignoring override")
    return dict(_DISABLE_THINKING_BUNDLE)
