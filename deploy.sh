#!/bin/bash
# Деплой MS2 на сервер gorbatkaru.ru
# Использование: ./deploy.sh

SERVER="root@89.104.67.14"
REMOTE_DIR="/var/www/ms"

echo "Загружаю файлы..."
scp /Users/tihonov/MS2/index.html "$SERVER:$REMOTE_DIR/"
scp /Users/tihonov/MS2/server.py   "$SERVER:$REMOTE_DIR/"

echo "Перезапускаю сервер..."
ssh "$SERVER" "systemctl restart ms"

echo "Готово! https://gorbatkaru.ru"
