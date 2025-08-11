# Passivbot - Code Style and Conventions

## Code Quality Tools
- **Prospector**: Tool principale per linting (configurato in `.prospector.yml`)
- **Strictness**: Medium level
- **Max Line Length**: 140 caratteri

## Enabled Linters
### PyFlakes
- Attivo con disabilitazione di F405 (import * warnings)

### PEP8
- Attivo ma non full mode
- Disabilitati: N803, N806, N812 (naming conventions)

### Pylint
- Attivo con diverse disabilitazioni:
  - too-many-locals, too-many-arguments
  - missing-module-docstring
  - no-else-return, inconsistent-return-statements

### PEP257 (Docstrings)
- Attivo con disabilitazioni:
  - D203, D212, D213 (docstring formatting)
  - D107 (missing __init__ docstring)
  - D205 (blank line requirements)

## Naming Conventions
- **Snake_case**: Per variabili e funzioni
- **PascalCase**: Per classi (es. `Passivbot`)
- **UPPER_CASE**: Per costanti (es. `ONE_MIN_MS`, `RUST_SOURCE_DIR`)

## File Structure Patterns
- **Main modules**: `src/main.py`, `src/passivbot.py`
- **Exchange modules**: `src/exchanges/{exchange}.py`
- **Utility modules**: `src/pure_funcs.py`, `src/procedures.py`
- **Rust integration**: Automatic compilation management in `main.py`

## Type Hints
- Utilizzati ma non obbligatori
- Presenti principalmente nelle funzioni principali

## Documentation
- **MkDocs**: Per documentazione del progetto
- **Jupyter Notebooks**: Per analisi e esempi
- **Docstrings**: Seguono PEP257 con eccezioni configurate

## Import Style
- Imports standard all'inizio
- Wildcard imports utilizzati per moduli interni (es. backtest functions)