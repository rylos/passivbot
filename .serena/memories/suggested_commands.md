# Passivbot - Suggested Commands

## Development Setup
```bash
# Clone repository
git clone https://github.com/enarjord/passivbot.git
cd passivbot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Build Rust extensions (optional - auto-compiled)
cd passivbot-rust
maturin develop --release
cd ..

# Setup API keys
cp api-keys.json.example api-keys.json
# Edit api-keys.json with your exchange credentials
```

## Running the Bot
```bash
# Run with default settings
python3 src/main.py -u {account_name_from_api-keys.json}

# Run with custom config
python3 src/main.py path/to/config.json

# Run with template config
python3 src/main.py configs/template.json
```

## Development Tools
```bash
# Code quality check
prospector

# Launch Jupyter Lab
python3 -m jupyter lab

# Build documentation
mkdocs serve
mkdocs build
```

## Backtesting & Optimization
```bash
# Run backtest
python3 src/backtest.py config.json

# Run optimization
python3 src/optimize.py config.json

# Download historical data
python3 src/downloader.py
```

## Rust Development
```bash
# Manual Rust compilation
cd passivbot-rust
maturin develop --release
cd ..

# Check Rust compilation
cargo check --manifest-path passivbot-rust/Cargo.toml
```

## Production Deployment
```bash
# Using tmux sessions
./start_tmuxp1.sh  # Starts bybit session
./start_tmuxp2.sh  # Starts additional session
./start_tmuxp3.sh  # Starts third session

# Check running sessions
./check_tmuxp1.sh
```

## Testing
```bash
# Run tests (limited test suite)
python3 -m pytest tests/

# Run specific test
python3 -m pytest tests/test_ohlcvs_downloader.py
```

## System Commands (Linux/Arch)
```bash
# Process monitoring
ps aux | grep python
htop

# File operations
find . -name "*.py" | grep -v __pycache__
ls -la src/
tree -I "__pycache__|*.pyc"

# Git operations
git status
git log --oneline
git diff
```