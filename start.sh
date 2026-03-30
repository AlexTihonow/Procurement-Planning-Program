#!/bin/bash
# Запуск сервера заметок MS2
# После запуска открыть: http://<IP-компьютера>:5000

cd "$(dirname "$0")"

# Устанавливаем зависимости если нужно
python3 -m pip install -r requirements.txt -q

# Запускаем сервер
python3 server.py
