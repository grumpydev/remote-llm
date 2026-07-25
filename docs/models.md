# Model routing

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

Add an alias after adding its key to the root-owned deployment environment:

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

The native GGUF source and context target are operational facts, not managed
downloads:

```text
source: unsloth/GLM-4.7-Flash-GGUF:UD-Q4_K_XL
requested context: 65536
```

