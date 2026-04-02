# hiLife Sound Wave Utility (`hlsw`)

CLI to generate door unlock sound waves for [hiLife](https://www.hilife.sg/) smart communities. Reverse-engineered from hiLife2 v5.6.2. For personal and educational use only.

## Usage

```bash
# Install uv if you don't have it (https://docs.astral.sh/uv/)
# curl -LsSf https://astral.sh/uv/install.sh | sh

# Login (cached for subsequent runs)
uv run hlsw.py auth --account you@email.com --password yourpass

# Download your owner wave — permanent, unlimited use, tied to your unit
# Outputs the mp3 file path to stdout (saves to cwd by default, -o to override)
uv run hlsw.py generate owner

# Create a visitor wave — temporary, limited uses, shareable with guests
# Duration format: 30m, 4h, 2d. Outputs the mp3 file path to stdout
uv run hlsw.py generate visitor --duration 4h --count 3 --remark "John"

# List and manage existing visitor waves
uv run hlsw.py visitor list
uv run hlsw.py visitor delete <wave_id>
```

See [notes.md](notes.md) for how it works and reverse engineering findings.
