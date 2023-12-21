# LlamaCpp Horde Bridge

This software enables you to join your [llama.cpp](https://github.com/ggerganov/llama.cpp) server to the [KoboldAI Horde](https://github.com/db0/AI-Horde) and make it into a Scribe worker, performing distributed text generation.

It is a fork of [KoboldAI-Horde-Bridge](https://raw.githubusercontent.com/db0/KoboldAI-Horde-Bridge).

# Why llama.cpp and not koboldcpp?

See [this reddit post](https://www.reddit.com/r/LocalLLaMA/comments/18helbs/how_to_run_mixtral_8x7b_gguf_on_tesla_p40_without/), using this trick older Pascal GPUs (GTX 10x0, P40, K80) are almost twice as fast!

Compile [llama.cpp](https://github.com/ggerganov/llama.cpp) with `make LLAMA_CUBLAS=1 LLAMA_CUDA_FORCE_MMQ=1` to get a Pascal-optimized `server` binary.

# Instructions

- Launch llama.cpp server, something like: `server -m /path/to/model.gguf -ngl 100 -c 2048`
- Copy `clientData_template.py` to `clientData.py`
- Set `kai_url` to your server endpoint (default usually OK), `kai_name` to your Horde worker name and `api_key` to your Hode API key
- Run `bridge.py`
