# Procurement Planning Program

Веб-приложение для планирования закупок и управления заявками. Ведите базу заметок с хэштег-параметрами, фильтруйте их, настраивайте автоматические email-рассылки по расписанию.

Живая демо: **https://gorbatkaru.ru**

---

## Возможности

- **Заметки** — создание, редактирование, удаление. Автосохранение через 0.6 сек после остановки ввода
- **Хэштег-параметры** — произвольные метки в формате `#Категория Значение` (например `#Организация КУМИ`, `#Товар Заказать`)
- **Автодополнение** — при вводе параметров система предлагает варианты из уже существующих записей; работает и в поле фильтра
- **Фильтрация** — быстрый поиск по одному или нескольким условиям одновременно (`#Товар Заказать #Организация КУМИ`), сохранение фильтров
- **Все параметры** — иерархический список всех параметров с навигацией по уровням, счётчиком заметок и удалением из всех заметок сразу
- **Рассылки** — автоматические email-рассылки по расписанию (раз в N дней в 9:00) с выборкой заметок по фильтру
- **Настройка почты** — SMTP-параметры вводятся прямо в интерфейсе, без правки конфигов
- **Печать** — вывод отфильтрованного списка заметок на печать
- **Многопользовательский режим** — авторизация, автосинхронизация каждые 30 секунд

---

## Технологии

- **Backend:** Python 3 + Flask + SQLite
- **Frontend:** Vanilla JS, без фреймворков — один файл `index.html`
- **Деплой:** Gunicorn + Nginx + systemd

---

## Быстрый старт

```bash
git clone https://github.com/AlexTihonow/Procurement-Planning-Program.git
cd Procurement-Planning-Program
pip install -r requirements.txt
python server.py
```

Откройте браузер: **http://localhost:8080**

Логин по умолчанию: `Admin`

---

## Деплой на сервер

```bash
./deploy.sh
```

Скрипт копирует файлы на сервер по SSH и перезапускает systemd-сервис.

### systemd (`/etc/systemd/system/ms.service`)

```ini
[Unit]
Description=Procurement Planning Program
After=network.target

[Service]
User=root
WorkingDirectory=/var/www/ms
Environment="PORT=3000"
ExecStart=/var/www/ms/venv/bin/gunicorn -w 2 -b 127.0.0.1:3000 server:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

### Nginx

```nginx
server {
    listen 443 ssl;
    server_name yourdomain.ru;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## Настройка email-рассылок

1. Перейдите в **Настройки → Настройка почты**
2. Введите параметры SMTP (хост, порт, логин, пароль) и нажмите **Тестировать**
3. Сохраните настройки
4. Перейдите в **Настройки → Рассылки**, создайте рассылку с фильтром и периодичностью

Рассылки отправляются автоматически в **9:00** каждые N дней.

---

## Структура проекта

```
├── index.html       # Весь фронтенд (SPA, Vanilla JS)
├── server.py        # Flask-сервер, REST API, планировщик рассылок
├── requirements.txt # Python-зависимости
├── deploy.sh        # Скрипт деплоя на сервер
└── start.sh         # Скрипт локального запуска
```

---

## REST API

| Метод | Endpoint | Описание |
|-------|----------|----------|
| POST | `/api/login` | Авторизация |
| POST | `/api/logout` | Выход |
| GET | `/api/notes` | Список заметок |
| POST | `/api/notes` | Создать заметку |
| PUT | `/api/notes/:id` | Обновить заметку |
| DELETE | `/api/notes/:id` | Удалить заметку |
| GET/POST | `/api/filters` | Сохранённые фильтры |
| DELETE | `/api/filters/:id` | Удалить фильтр |
| GET/POST | `/api/mailings` | Рассылки |
| DELETE | `/api/mailings/:id` | Удалить рассылку |
| POST | `/api/mailings/:id/test` | Тестовая отправка |
| GET/POST | `/api/settings/smtp` | Настройки SMTP |
| POST | `/api/settings/smtp/test` | Тест SMTP |

---

## Лицензия

MIT
