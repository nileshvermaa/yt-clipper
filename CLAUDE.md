# yt-clipper: notes for AI assistants

- Read `docs/PLAYBOOK.md` before picking clips, writing scripts, reviewing or changing the pipeline.
- Scheduled runs follow `docs/tasks/daily-production.md`, `daily-upload.md`, `weekly-compilation.md`.
- Always use `.venv\Scripts\python.exe -m clipper ...` from `G:\gta6`. In PowerShell refresh PATH first:
  `$env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")`
- No Anthropic API key: the assistant itself writes `picks.json` and explainer scripts.
- Uploads stay Private; never make a video public, never delete videos.
- Keep CPU load low: GPU decode/encode, `CPU_THREADS=3`, long jobs in the background, one run at a time.
- Pinned: `ctranslate2==4.5.0`, `onnxruntime-gpu==1.19.2`; `kokoro-onnx` installed with `--no-deps`.
- After code changes: `ruff check .`, `pytest -q`, update the playbook/task files, commit, push.
- Never commit `.env`, `secrets/`, `workspace/`, `channels.txt`, model files.
