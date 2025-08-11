# Passivbot - Project Overview

## Purpose
Passivbot è un bot di trading per criptovalute scritto in Python e Rust, progettato per richiedere un intervento minimo dell'utente. Opera sui mercati dei derivati futures perpetui, creando e cancellando automaticamente ordini limit di acquisto e vendita.

## Key Features
- **Contrarian Market Maker**: Non predice i movimenti futuri dei prezzi, ma fornisce resistenza ai cambiamenti di prezzo in entrambe le direzioni
- **Grid Trading Strategy**: Ispirato alla strategia Martingale, fa piccoli entry iniziali e raddoppia sulle posizioni perdenti
- **Trailing Orders**: Supporta entry e close trailing per ottimizzare i profitti
- **Forager**: Sceglie dinamicamente i mercati più volatili
- **Unstucking Mechanism**: Gestisce posizioni sottoperformanti realizzando piccole perdite nel tempo
- **Multi-Exchange Support**: Bybit, OKX, Bitget, GateIO, Binance, Hyperliquid

## Tech Stack
- **Python**: Linguaggio principale (>= 3.8)
- **Rust**: Componenti ad alte prestazioni per backtesting e ottimizzazione
- **PyO3**: Binding Python-Rust
- **Key Libraries**:
  - ccxt: Connessioni exchange
  - pandas, numpy: Analisi dati
  - numba: Ottimizzazione numerica
  - aiohttp, websockets: Comunicazioni asincrone
  - matplotlib, plotly: Visualizzazione
  - deap: Algoritmi evolutivi per ottimizzazione

## Architecture
- **src/**: Codice Python principale
- **passivbot-rust/**: Componenti Rust per performance
- **configs/**: File di configurazione e template
- **docs/**: Documentazione MkDocs
- **notebooks/**: Jupyter notebooks per analisi
- **tests/**: Test suite (limitata)

## Version
v7.3.17 (dal README.md)