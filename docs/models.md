# Model routing

## Native model catalogue

Current llama.cpp versions support router mode: requests are routed by model
name. The first catalogue entry is preloaded during boot and additional models
are loaded on demand. This appliance sets `--models-max 1`, so a single-GPU
host can retain several selectable models on disk without trying to keep them
all in VRAM.

Enable router mode once:

```bash
sudo ai-model enable
```

This installs a systemd drop-in that replaces only the service's `ExecStart`.
The original unit, launcher, model cache, API key, and GGUF are retained. The
initial catalogue contains GLM 4.7 Flash.

Add another Hugging Face GGUF quantization:

```bash
sudo ai-model add \
  --alias qwen-coder \
  --source owner/model-GGUF:Q4_K_M \
  --display-name "Qwen Coder" \
  --context 32768 \
  --output-tokens 8192 \
  --parallel 1
```

The source uses llama.cpp's `OWNER/REPOSITORY:QUANT` syntax. It must be a GGUF
repository and quantization supported by the installed llama.cpp. Check the
publisher, model card, architecture support, licence, expected RAM/VRAM, and
context requirements before adding it.

```bash
ai-model list
ai-model status
sudo ai-model remove --alias qwen-coder
```

Adding and removing update llama.cpp, LiteLLM, Open WebUI's visible model list,
and the generated OpenCode catalogue together. A failed update restores both
catalogues. Removing an entry deliberately retains its cached GGUF; cache
deletion is a separate manual storage operation.

The stable alias is also the native router preset name. The Hugging Face source
is stored inside that preset, so clients never need to send repository names or
quantization tags as model identifiers.

Each model defaults to one inference slot (`parallel = 1`), which avoids
reserving resources for unused concurrent requests on a self-hosted appliance.
Set `--parallel N` while adding a model when concurrent inference is required.
The first catalogue entry defaults to `load-on-startup = true`; explicitly
setting `load_on_startup` in the JSON catalogue overrides that behaviour.
Preloading moves the wait into the boot sequence but does not make the model
file itself load faster. `ai-status --model` reports readiness while it loads.

`ai-model add` uses llama.cpp's authenticated `POST /models` endpoint and waits
for the download to appear in its cache before publishing the alias. Large
models can therefore keep the command running for some time. The first request
then loads the cached model into VRAM. Switching aliases unloads the current
model when necessary because the router is limited to one loaded model.

Router state is stored in root/group-readable files:

```text
/etc/ai-appliance/llama-models.json
/etc/llama-server.models.ini
```

`ai-model enable` requires a llama.cpp build whose help includes
`--models-preset`. It refuses to modify the service otherwise.
The rendered INI contains no credentials and is group-readable by the existing
`llama` service account; the JSON catalogue remains restricted to appliance
administrators.

The initial stable client alias is `glm-4.7-flash`. LiteLLM maps it to:

```yaml
model: openai/glm-4.7-flash
api_base: http://host.docker.internal:8080/v1
api_key: os.environ/LLAMA_API_KEY
```

The Linux host-gateway mapping is explicit in Compose. Provider requests use a
900-second timeout and one retry. Conservative retries reduce the risk that an
agent action is duplicated after an ambiguous timeout. Prompt/message logging is
disabled and API-key information is redacted.

For a non-native OpenAI-compatible endpoint, add a routing-only alias after
adding its key to the root-owned deployment environment:

```bash
sudo scripts/add-model \
  --alias coder-stable \
  --provider-model openai/provider-model-id \
  --api-base http://host.docker.internal:8080/v1 \
  --api-key-env LLAMA_API_KEY \
  --timeout 900 \
  --max-retries 1
```

Remove a non-required alias:

```bash
sudo scripts/remove-model --alias coder-stable
```

Both commands validate names, URL, environment-variable name, timeout, rendered
configuration, and Compose before restarting only LiteLLM. They run the live
runtime doctor before reporting success. The required initial alias cannot be
removed.

The initial native GGUF source and context are:

```text
source: unsloth/GLM-4.7-Flash-GGUF:UD-Q4_K_XL
requested context: 65536
```
