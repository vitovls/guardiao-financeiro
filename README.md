# Guardião Financeiro

Bot de organização financeira para Telegram. 

## Requisitos

- Python 3.10+
- Token de bot do Telegram ([@BotFather](https://t.me/BotFather))
- Chave de API do Google Gemini

## Configuração

1. Clone o repositório e crie o ambiente virtual:

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. Copie o arquivo de exemplo e preencha as variáveis:

```bash
cp .env.example .env
```

```env
BOT_TOKEN=seu_token_aqui
GEMINI_API_KEY=sua_chave_aqui
```

3. Crie a pasta de armazenamento temporário de imagens:

```bash
mkdir fotos
```

## Rodando

```bash
python main.py
```
