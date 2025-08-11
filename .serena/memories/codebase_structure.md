# Passivbot - Codebase Structure

## Main Directories

### `/src/` - Core Python Code
- **`main.py`**: Entry point with Rust compilation management
- **`passivbot.py`**: Main bot class and trading logic
- **`backtest.py`**: Backtesting engine
- **`optimize.py`**: Optimization algorithms using evolutionary approach
- **`downloader.py`**: Historical data downloader
- **`pure_funcs.py`**: Pure utility functions
- **`procedures.py`**: Trading procedures and helpers
- **`config_utils.py`**: Configuration management
- **`plotting.py`**: Visualization utilities

### `/src/exchanges/` - Exchange Integrations
- **`binance.py`**: Binance exchange implementation
- **`bybit.py`**: Bybit exchange implementation  
- **`okx.py`**: OKX exchange implementation
- **`bitget.py`**: Bitget exchange implementation
- **`gateio.py`**: GateIO exchange implementation
- **`hyperliquid.py`**: Hyperliquid exchange implementation
- **`kucoin.py`**: KuCoin exchange implementation
- **`defx.py`**: DefX exchange implementation

### `/src/tools/` - Utility Tools
- **`generate_mcap_list.py`**: Market cap list generator
- **`event_loop_policy.py`**: Async event loop utilities

### `/passivbot-rust/` - Rust Performance Components
- **`Cargo.toml`**: Rust project configuration
- **`src/lib.rs`**: Main Rust library entry point
- **`src/backtest.rs`**: High-performance backtesting functions
- **`src/entries.rs`**: Entry order calculations
- **`src/closes.rs`**: Close order calculations
- **`src/trailing_flip.rs`**: Trailing order logic
- **`src/types.rs`**: Rust type definitions
- **`src/utils.rs`**: Rust utility functions
- **`src/constants.rs`**: Rust constants
- **`src/python.rs`**: Python binding utilities

### `/configs/` - Configuration Files
- **`template.json`**: Main configuration template
- **`approved_coins_*.json`**: Whitelisted coins by market cap
- **`examples/`**: Example configurations

### `/docs/` - Documentation
- **MkDocs structure**: Markdown documentation
- **`images/`**: Logo and visual assets

### `/notebooks/` - Jupyter Analysis
- **Analysis notebooks**: For data exploration and strategy development

### `/tests/` - Test Suite
- **`conftest.py`**: Test configuration
- **`test_ohlcvs_downloader.py`**: Downloader tests
- **Limited test coverage**: Mainly integration tests

## Key Files in Root
- **`requirements*.txt`**: Python dependencies (main, rust, live)
- **`setup.py`**: Python package setup with Rust extensions
- **`api-keys.json.example`**: API keys template
- **`*.yaml`**: Tmux session configurations
- **`*.sh`**: Shell scripts for production deployment
- **`.prospector.yml`**: Code quality configuration
- **`mkdocs.yml`**: Documentation configuration
- **`Dockerfile*`**: Container configurations

## Data Flow Architecture
1. **Entry Point**: `main.py` handles Rust compilation and launches bot
2. **Bot Core**: `passivbot.py` contains main trading logic
3. **Exchange Layer**: Exchange-specific implementations in `/exchanges/`
4. **Performance Layer**: Rust components for CPU-intensive calculations
5. **Configuration**: JSON-based config system with overrides
6. **Data**: Historical data management and real-time feeds