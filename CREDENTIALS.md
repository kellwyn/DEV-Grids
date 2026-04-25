# CREDENTIALS.md — Keyring Vault Setup

Passwords are stored in Windows Credential Manager via `keyring`.
Never put passwords in `.env` or source files.

## Store credentials once

```bash
python -c "import keyring; keyring.set_password('mt5', 'metaquotes_password', 'YOUR_PASSWORD')"
python -c "import keyring; keyring.set_password('mt5', 'blackbull_password',  'YOUR_PASSWORD')"
```

## Verify

```bash
python -c "import keyring; print(keyring.get_password('mt5', 'metaquotes_password'))"
```

## Key names used in this project

| Service | Key                   | Description              |
|---------|-----------------------|--------------------------|
| `mt5`   | `metaquotes_password` | MetaQuotes demo account  |
| `mt5`   | `blackbull_password`  | BlackBull live account   |
| `mt5`   | `default_password`    | Default MT5 profile      |

## Non-sensitive config

Non-secret settings (symbol, server name, login number) go in `.env`.
See `.env.example` for the full list.
