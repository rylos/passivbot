# Passivbot - Task Completion Checklist

## Before Committing Code Changes

### 1. Code Quality
```bash
# Run prospector for linting
prospector

# Check for common issues
python3 -m py_compile src/*.py
```

### 2. Rust Components
```bash
# If Rust code was modified, recompile
cd passivbot-rust
maturin develop --release
cd ..

# Verify Rust compilation
cargo check --manifest-path passivbot-rust/Cargo.toml
```

### 3. Testing
```bash
# Run available tests
python3 -m pytest tests/ -v

# Test basic imports
python3 -c "import src.passivbot; print('Import successful')"
```

### 4. Configuration Validation
```bash
# Validate config files if modified
python3 -c "import json; json.load(open('configs/template.json'))"

# Check API keys template
python3 -c "import json; json.load(open('api-keys.json.example'))"
```

### 5. Documentation
```bash
# If docs were modified, build and check
mkdocs build
mkdocs serve  # Check locally

# Update version in README.md if needed
```

### 6. Dependencies
```bash
# If new dependencies added, update requirements
pip freeze > requirements-new.txt
# Review and merge into appropriate requirements file
```

## Before Production Deployment

### 1. Backtest Validation
```bash
# Run backtest with new configuration
python3 src/backtest.py configs/your_config.json
```

### 2. Configuration Review
- Verify `api-keys.json` has correct credentials
- Check `live` section in config for proper settings
- Validate `approved_coins` lists
- Review risk parameters (`total_wallet_exposure_limit`, etc.)

### 3. System Resources
```bash
# Check available disk space
df -h

# Check memory usage
free -h

# Verify tmux is available for production
tmux --version
```

### 4. Monitoring Setup
- Ensure log directories exist
- Verify tmux session configurations
- Test restart scripts (`start_tmuxp*.sh`)

## Post-Deployment Verification
```bash
# Check running processes
ps aux | grep python

# Monitor logs
tail -f logs/passivbot.log

# Check tmux sessions
tmux list-sessions
```