# Install and relocate

Source: https://github.com/Kandecho/Video-Reader. Original code is MIT licensed; third-party notices remain in effect. Core 0.10.0rc6 and host adapters 0.5.5 are the current source prerelease.

The supported installation baseline is Windows x64 with Python 3.12 and PowerShell 7. This release is validated in a clean isolated directory on the same machine; no other-machine or other-OS validation is implied. Models, credentials, FFmpeg, Node and Python environments are not bundled.

## Source candidate versus current documentation

The current source candidate takes its README, license and notices directly from the maintained source. See [release notes](../RELEASE_NOTES.md) for scope and limitations. Earlier installation records apply to their dated versions; the rc6 release acceptance is recorded separately in the source repository's validation/release-20261104 directory. A successful older candidate does not verify later behavior.

## Prerequisites

- Python 3.11+ (3.12 for the locked Windows runtime), or uv with permission to obtain Python.
- FFmpeg and ffprobe on PATH for local media. They are external binaries, not copied into this source distribution.
- Node on PATH for the existing yt-dlp JavaScript runtime path, particularly YouTube. Basic local video/caption reading does not require Node.
- Internet for initial Python dependency installation and platform access. Cached/local reading stays local.

PowerShell 7, from any working directory:

```powershell
& 'D:\tools\Video Reader\bootstrap.ps1'
& 'D:\tools\Video Reader\run.ps1' doctor
```

The path is an example. Use your actual extracted folder, including spaces or Chinese characters. Bootstrap creates a local `.venv`, installs base + MCP + vision extras, creates config.json only if absent, and generates both host plugins from the actual installation root. It never overwrites existing configuration or downloads speech models.

`-Features mcp` skips optional OCR; `-Features mcp,vision,asr` adds Whisper dependencies. `-FullRuntime` uses the observed Windows dependency lock. An already installed environment is reused. The original installation's environment, models and auth are not copied into another environment.

Without uv, create a venv with Python, install the selected package extras with pip, copy config.example.json to a new config.json and run tools/build_plugins.py with that venv's Python. Use the root launch.py/launch_mcp.py scripts or installed entry points. Do not add a developer checkout to PYTHONPATH.

## Configuration and private data

Precedence: CLI `--config`, then VIDEO_READER_CONFIG, then VIDEO_READER_HOME/config.json. A source checkout otherwise uses its own config.json; a wheel installation otherwise uses the per-user VideoReader data directory. Relative cache/model/auth/cookie/runtime paths resolve against the configuration file directory, never the caller's working directory.

Keep configuration, credentials, models and generated data outside a candidate/source archive. `cache_dir`, `preview.directory`, `bilibili_auth.directory`, model paths and `platforms.youtube.cookies_file` can point to separate drives. Relative paths are preferable when moving a whole private installation; absolute external paths remain valid until their owner moves them. Rebuild host adapters after moving the core.

Moving an existing cache does not rewrite historical source/image references automatically. Portable sharing is the explicit `export` operation: copy the entire exported folder. Historical cache migration is separate from installing clean source.

Bilibili uses its own QR login store. YouTube supports importing a user-exported, short-lived Netscape cookie file for access while it remains valid. Long-term login-state maintenance is currently unavailable. Check current validity with `youtube-status`; no fixed access duration is guaranteed. After expiry, the user must export and replace the file. A disposable copy protects the original during yt-dlp operations. A failed network check is unknown status. Credentials are never bundled.

## Optional models and runtime

Whisper: obtain a compatible faster-whisper CTranslate2 model from its publisher, retain the publisher revision/license and SHA-256 inventory, and configure `asr.model_path`. No model is needed for native captions. Without a configured local model, the reader reports unavailable speech rather than fabricated silence. CPU/int8 remains the default.

Qwen is explicit `source=qwen`, not a fallback. Configure local ASR and aligner model paths and `qwen.runtime_dir` (new default `runtimes/qwen`). Use a separate Python environment with the same Python major/minor as Reader, qwen-asr and its compatible GPU dependencies. Availability is a file check, not a claim that CUDA works. Existing installations with the old component-owned research runtime retain that exact path/profile unless explicitly configured otherwise; there is no research-source dependency for new installs.

The validated optional environment used Python 3.12, qwen-asr 0.0.6, torch/torchaudio 2.10.0+cu128, transformers 4.57.6 and accelerate 1.12.0. Create `runtimes/qwen` with `uv venv --python 3.12 runtimes/qwen`; install the CUDA 12.8 torch/torchaudio wheels from the official PyTorch cu128 index, then those pinned qwen-asr/transformers/accelerate packages into that environment. Download the ASR and ForcedAligner model directories from their publishers and set `qwen.model_path` / `qwen.aligner_path`. This GPU option needs a compatible NVIDIA driver and enough VRAM; the basic Reader does not. The live check covered a 20-second Chinese window, not every GPU or a fresh full GPU installation. Keep an existing validated runtime until a replacement passes a short local Qwen request.

The local model provenance inventory is separate from model weights. Verify downloaded weights against immutable publisher revisions and hashes before enabling them. Run offline with models already present; HF_HUB_OFFLINE is enabled and no fallback fetch/provider is attempted.

The candidate includes `docs/models/faster-whisper-medium.json`: the installed publisher revision and verified file hashes, without weights or private paths. Obtain each named file from that model's publisher at the exact upstream_revision (Hugging Face resolve URL: `https://huggingface.co/MODEL/resolve/REVISION/FILENAME`). Then run `python tools/check_models.py docs/models/faster-whisper-medium.json YOUR_MODEL_DIRECTORY`. A mismatch or missing file fails the check. The checker makes no network requests and changes no model files. Other selected models require their own reviewed provenance; do not silently use these hashes for another revision.

## Candidate checks

Run `python -m unittest discover -s tests -v`. Build an allowlisted candidate with `python tools/build_candidate.py NEW_FOLDER`; it refuses an existing destination. Candidate contents exclude live config, credentials, data, models, Python environments, research, personal plans and generated host plugin paths. `candidate-manifest.json` records hashes. Bootstrap generates plugins for that installation rather than shipping another user's absolute paths.

The built-in optional cloud path remains disabled. Installing, moving or testing this component does not create a scheduler or authorize messages. Scroll's daily selection/delivery rules remain separately configured.
