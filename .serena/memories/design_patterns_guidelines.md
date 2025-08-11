# Passivbot - Design Patterns and Guidelines

## Architecture Patterns

### 1. Hybrid Python-Rust Architecture
- **Python**: Main logic, API integrations, configuration management
- **Rust**: CPU-intensive calculations (backtesting, optimization)
- **PyO3 Bindings**: Seamless integration between Python and Rust
- **Automatic Compilation**: `main.py` handles Rust compilation transparently

### 2. Exchange Abstraction Pattern
- **Base Interface**: Common methods across all exchanges
- **Exchange-Specific**: Individual implementations in `/src/exchanges/`
- **CCXT Integration**: Standardized exchange communication
- **Async Operations**: Non-blocking API calls and WebSocket handling

### 3. Configuration-Driven Design
- **JSON Configuration**: Centralized settings management
- **Template System**: `configs/template.json` as base
- **Overrides**: Coin-specific and user-specific overrides
- **Environment Separation**: Different configs for backtest/live/optimize

### 4. Grid Trading Strategy Implementation
- **Entry Grid**: Martingale-inspired position sizing
- **Close Grid**: Profit-taking at multiple levels
- **Trailing Orders**: Dynamic order placement based on price movement
- **Risk Management**: Exposure limits and unstucking mechanisms

## Code Organization Principles

### 1. Separation of Concerns
- **Pure Functions**: `pure_funcs.py` for stateless utilities
- **Procedures**: `procedures.py` for stateful operations
- **Exchange Logic**: Isolated in exchange-specific modules
- **Performance Critical**: Moved to Rust when needed

### 2. Async-First Design
- **Main Bot Loop**: Async event-driven architecture
- **WebSocket Handling**: Real-time market data processing
- **API Calls**: Non-blocking exchange interactions
- **Concurrent Operations**: Multiple symbols/exchanges simultaneously

### 3. Data-Driven Configuration
- **JSON Schema**: Structured configuration validation
- **Bounds Definition**: Optimization parameter ranges
- **Coin Filtering**: Dynamic symbol selection
- **Risk Parameters**: Configurable safety limits

## Development Guidelines

### 1. Performance Considerations
- **Rust for Speed**: Move CPU-intensive code to Rust
- **Numba Optimization**: Use `@njit` decorators for numerical functions
- **Memory Efficiency**: Careful handling of large datasets
- **Caching**: Avoid redundant calculations

### 2. Error Handling
- **Exchange Errors**: Graceful handling of API failures
- **Network Issues**: Retry mechanisms and fallbacks
- **Data Validation**: Input sanitization and type checking
- **Logging**: Comprehensive error tracking

### 3. Testing Strategy
- **Integration Tests**: Focus on exchange connectivity
- **Backtest Validation**: Historical data accuracy
- **Configuration Testing**: JSON schema validation
- **Limited Unit Tests**: Due to complex dependencies

### 4. Documentation Standards
- **MkDocs**: User-facing documentation
- **Code Comments**: Inline documentation for complex logic
- **Configuration Examples**: Template and example files
- **Jupyter Notebooks**: Interactive analysis and tutorials

## Anti-Patterns to Avoid

### 1. Blocking Operations
- Avoid synchronous API calls in main loop
- Don't block on file I/O operations
- Use async/await consistently

### 2. Hardcoded Values
- Use configuration files for all parameters
- Avoid magic numbers in trading logic
- Make exchange-specific values configurable

### 3. Tight Coupling
- Keep exchange implementations independent
- Separate trading logic from data processing
- Avoid circular dependencies between modules

### 4. Resource Leaks
- Properly close WebSocket connections
- Clean up temporary files and locks
- Monitor memory usage in long-running processes