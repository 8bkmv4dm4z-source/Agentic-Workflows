# Quick Reference: LLM Inference Speed Cheat Sheet

## Installation Commands

```bash
# Ollama (macOS/Linux/Windows)
curl https://ollama.ai/install.sh | sh
ollama run mistral:7b

# LM Studio
# Download from https://lmstudio.ai

# vLLM
pip install vllm
python -m vllm.entrypoints.openai.api_server --model mistralai/Mistral-7B-Instruct-v0.2

# pytest plugins
pip install pytest-xdist
```

---

## Speed Benchmarks (2025-2026)

| Hardware | Model | Tool | Speed |
|----------|-------|------|-------|
| Mac M1 16GB | Mistral 7B | Ollama | 35-45 tok/s |
| Mac M4 16GB | Mistral 7B | Ollama | 60-80 tok/s |
| RTX 4090 | Mistral 7B | vLLM | 200+ tok/s |
| RTX 4070 | Mistral 7B | Ollama | 80-100 tok/s |
| CPU only | Phi 2.7B | Ollama | 5-8 tok/s |

---

## Model Recommendations

### For Speed (Fastest)
```
Phi 2.7B > Mistral 7B > Qwen 7B > Llama 13B > Qwen 72B
30-50 tok/s   40-80 tok/s   50-80 tok/s   20-40 tok/s   5-10 tok/s
```

### For Quality+Speed (Best Balance)
```
Mistral 7B Instruct (recommended)
Qwen 2.5 7B
Llama 3.1 8B
```

### For MacBook (Best for Metal)
```
Mistral 7B (40 tok/s with Metal)
Phi 2.7B (60+ tok/s, very capable)
Qwen 2.5 7B (35-40 tok/s)
```

---

## Quantization Quick Guide

| Format | Speed Gain | Quality Loss | Use When |
|--------|-----------|--------------|----------|
| FP16 | Baseline | None | Need max accuracy |
| Q8_0 | 1.2x | 1% | Safe default |
| Q5_K_M | 1.5-2x | 4% | Good balance |
| **Q4_K_M** | **1.8-2.2x** | **10%** | **Recommended** |
| Q3_K_M | 2.5x | 15% | ⚠️ Risk for knowledge |

---

## API Endpoints

```bash
# Ollama (default port)
curl http://localhost:11434/api/generate -d '{
  "model": "mistral:7b",
  "prompt": "What is AI?"
}'

# vLLM (OpenAI-compatible)
curl http://localhost:8000/v1/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "mistral-7b", "prompt": "What is AI?"}'

# LM Studio (OpenAI-compatible)
curl http://localhost:1234/v1/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "selected-model", "prompt": "What is AI?"}'
```

---

## Python Usage

### Ollama
```python
import requests

response = requests.post('http://localhost:11434/api/generate', json={
    'model': 'mistral:7b',
    'prompt': 'Write a function to sort an array',
    'stream': False
})
print(response.json()['response'])
```

### vLLM
```python
from openai import OpenAI

client = OpenAI(api_key="unused", base_url="http://localhost:8000/v1")
response = client.completions.create(
    model="mistral-7b",
    prompt="Write a function to sort an array"
)
print(response.choices[0].text)
```

### With Fallback
```python
def generate_with_fallback(prompt):
    try:
        # Try local
        return requests.post('http://localhost:11434/api/generate', json={
            'model': 'mistral:7b',
            'prompt': prompt,
            'stream': False
        }, timeout=5).json()['response']
    except:
        # Fallback to cloud
        from huggingface_hub import InferenceClient
        client = InferenceClient(api_key=os.getenv("HF_TOKEN"))
        return client.text_generation(prompt, max_new_tokens=100)
```

---

## Testing Speedups

### ScriptedProvider (100x faster tests)
```python
class ScriptedProvider:
    def __init__(self, script):
        self.script = script

    def complete(self, prompt):
        for key, response in self.script.items():
            if key in prompt:
                return response
        raise ValueError(f"No script for: {prompt}")

# Usage
provider = ScriptedProvider({
    "fibonacci": "def fib(n):\n    if n <= 1: return n",
    "sort": "[1, 2, 3, 4, 5]"
})

result = provider.complete("fibonacci")  # Instant!
```

### Test Markers
```python
@pytest.mark.unit
def test_parser():
    # Fast: no LLM calls
    action = parse_action('{"tool": "sort"}')

@pytest.mark.llm
def test_full_workflow():
    # Slow: uses real LLM
    result = agent.run("fibonacci")
```

```bash
pytest -m unit          # Run fast tests only (~30 sec)
pytest -m "not llm"     # Skip slow tests
pytest                  # Run all
```

### Parallel Execution
```bash
pip install pytest-xdist
pytest tests/ -n auto   # Auto-detect CPU count
pytest tests/ -n 4      # Use 4 workers
```

---

## Cost Comparison

### Monthly (Single Developer)

| Option | Cost | Speed | Setup |
|--------|------|-------|-------|
| Groq free tier | $0 (expires) | 200ms | 1 min |
| **Ollama local** | **$0** | **1-3 sec** | **5 min** |
| HuggingFace free | $0 (limited) | 2-5 sec | 2 min |
| vLLM + GPU | $0 | 100-500ms | 15 min |
| Groq paid | $20-200 | 200ms | 1 min |

### Annual Savings (vs Groq paid)
- Ollama + ScriptedProvider: **$240-2,400/year**

---

## Decision Tree

```
Do you need INSTANT feedback while coding?
├─ YES → Use local Ollama (1-3 sec) + caching
└─ NO → Continue...

Is the latency acceptable for your workflow?
├─ YES → Use Ollama (free)
└─ NO → Use vLLM (if GPU available)

Do you have GPU?
├─ YES → Ollama or vLLM (both free)
├─ NO (MacBook) → Ollama with Metal
└─ NO (CPU) → Phi 2.7B or backup to cloud

Is this for TESTING?
├─ YES → Use ScriptedProvider (instant)
└─ NO → Use any option above

Do you need BACKUP when local fails?
├─ YES → Use HuggingFace free tier + local
└─ NO → Local only
```

---

## Common Problems & Solutions

### Problem: Ollama is slow
**Solution:** Use Q4_K_M quantization
```bash
ollama run mistral:7b-q4_k_m
```

### Problem: Tests take too long
**Solution:** Add ScriptedProvider fixture (100x faster)
```python
# See ScriptedProvider section above
```

### Problem: Out of memory
**Solution:** Use smaller model or quantization
```bash
ollama run phi:2.7b              # Smaller model
ollama run mistral:7b-q4_k_m     # Quantized
```

### Problem: Can't install Ollama locally
**Solution:** Use HuggingFace or Together AI free tier
```python
from huggingface_hub import InferenceClient
client = InferenceClient(api_key="hf_xxxxx")
```

### Problem: API latency is unpredictable
**Solution:** Add caching layer
```python
from functools import lru_cache
@lru_cache(maxsize=128)
def cached_generate(prompt):
    return generate(prompt)  # Only called once per unique prompt
```

---

## GitHub Actions CI Optimization

### Free tier (public repos)
```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -e ".[dev]"
      - run: pytest -m unit  # Fast tests only (~30 sec)
```

### Cache models
```yaml
- uses: actions/cache@v4
  with:
    path: ~/.cache/huggingface
    key: hf-models-${{ runner.os }}
```

### Matrix testing (9x parallel)
```yaml
strategy:
  matrix:
    python-version: ['3.11', '3.12']
    test-group: ['unit', 'integration', 'sanity']
```

---

## Environment Setup

```bash
# .env
OLLAMA_API_BASE=http://localhost:11434
OLLAMA_MODEL=mistral:7b

# .env (backups)
HUGGINGFACE_API_KEY=hf_xxxxx
TOGETHER_API_KEY=xxx

# .env (optional: high-throughput)
VLLM_API_BASE=http://localhost:8000
VLLM_MODEL=mistralai/Mistral-7B-Instruct-v0.2
```

---

## Free Tier Limits

| Service | Limit | Best For |
|---------|-------|----------|
| HuggingFace | ~100 req/day | Backup |
| Together AI | 30 req/min, 1M tok/day | Testing |
| Replicate | ~$0.50-1.00 free | Experimentation |
| Local Ollama | Unlimited | Primary dev |

---

## Performance Tips

1. **Cache repeated prompts** → 10x faster for known questions
2. **Batch requests** → 5-6x higher throughput
3. **Use Q4_K_M** → 1.8x faster, 90% quality
4. **Use smaller models** → Phi 2.7B is surprisingly capable
5. **Stream responses** → Better UX, perceived latency lower
6. **Use ScriptedProvider in tests** → 100x faster test suite
7. **Run tests in parallel** → 4-8x faster full suite

---

## Recommended Setup (20 min setup)

```bash
# 1. Install Ollama
curl https://ollama.ai/install.sh | sh

# 2. Start serving (in background)
ollama serve &
ollama run mistral:7b

# 3. Update code to use local API
# Change from: groq_client.chat.completions.create()
# To: requests.post('http://localhost:11434/api/generate')

# 4. Add to tests/conftest.py
# ScriptedProvider fixture (see section above)

# 5. Add test markers and run fast tests
pytest -m unit

# Result: Instant local inference, 100x faster tests, $0 cost!
```

---

## Resources

- **Ollama:** https://ollama.ai
- **vLLM:** https://www.vllm.ai
- **LM Studio:** https://lmstudio.ai
- **HuggingFace:** https://huggingface.co/inference-api
- **Together AI:** https://www.together.ai
- **Full Guide:** See LOCAL_LLM_INFERENCE_GUIDE.md

---

**Last Updated:** March 2026
**Quick Ref Version:** 1.0
