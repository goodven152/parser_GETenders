python -m venv venv
source venv/Script/activate
pip install -r -requirements.txt

# PIP version needed 24

python -m pip install "pip==24"

# Start the program:

<!-- python -m ge_parser_tenders.cli --reset-cache --no-headless --max-pages [n] -->

python -m ge_parser_tenders.cli --config config.json

# первый запуск Stanza – скачиваем грузинскую модель

python -c "import stanza; stanza.download('ka')"
