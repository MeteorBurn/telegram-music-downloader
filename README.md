# 🎵 Telegram Music Downloader

Инструмент командной строки для скачивания аудиофайлов и музыки из Telegram-каналов и групп.
Поддерживает параллельную загрузку, гибкую фильтрацию, возобновление прерванных сессий и
отдельное отслеживание загрузок для каждого канала.

---

## ✨ Возможности

- 📥 **Загрузка музыки** из публичных и приватных каналов/групп Telegram
- ⚡ **Параллельные загрузки** — до 5 файлов одновременно с rate limiting
- 🔍 **Гибкая фильтрация** по типу, формату, размеру и дате сообщения
- 📁 **Организация по каналам** — отдельная папка и трекеры на каждый канал
- 🔄 **Возобновление** — продолжает с последнего обработанного сообщения
- 🏷️ **Нормализация названий треков** — очистка имён файлов после загрузки (опционально)
- 📝 **Логирование** — в консоль и в файл с ротацией

---

## 🛠️ Требования

- Python **3.9+**
- Telegram API credentials — `api_id` и `api_hash` с [my.telegram.org](https://my.telegram.org)
- Доступ к целевым каналам/группам

---

## 📦 Установка

```bash
# 1. Клонировать репозиторий
git clone https://github.com/MeteorBurn/telegram-music-downloader.git
cd telegram-music-downloader

# 2. Создать виртуальное окружение
python -m venv venv

# 3. Активировать окружение
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

# 4. Установить зависимости
pip install -r requirements.txt
```

### Зависимости

| Пакет | Версия | Назначение |
|---|---|---|
| `telethon` | 1.32.1 | Telegram API клиент |
| `pyyaml` | 6.0.1 | Чтение YAML-конфигов |
| `python-dateutil` | 2.8.2 | Разбор дат |
| `humanize` | 4.8.0 | Человекочитаемые размеры файлов |
| `aiofiles` | 23.2.1 | Асинхронная работа с файлами |
| `cryptg` | 0.4.0 | Ускорение шифрования Telegram |

---

## ⚙️ Настройка

### Шаг 1 — API credentials

Получите `api_id` и `api_hash` на [my.telegram.org](https://my.telegram.org).

Создайте файл `src/local_config.yaml` (он не попадёт в git):

```yaml
telegram:
  api_id: 1234567
  api_hash: "your_api_hash_here"
```

> `src/local_config.yaml` переопределяет любые значения из `src/config.yaml`.

### Шаг 2 — Основной конфиг

Откройте `src/config.yaml` и настройте нужные параметры:

```yaml
telegram:
  api_id: 12345678           # из my.telegram.org
  api_hash: "your_api_hash"  # из my.telegram.org
  session_name: "session"    # имя файла сессии в data/sessions/
  two_factor_auth: true      # включить, если у вас настроена 2FA

channels:
  - -1001234567890   # числовой ID приватного канала / группы
  - "@musicchannel"  # юзернейм публичного канала

download:
  output_dir: "./data/downloads"
  timeout_between_messages: 0.3  # пауза между сообщениями, сек
  max_files_per_run: 100         # 0 = без ограничений
  concurrent_downloads: 3        # воркеры (1–5)
  max_queue_size: 100
  worker_timeout: 300
  rate_limit:
    requests_per_second: 2
    burst_size: 5

naming:
  template: "{original_name}__{message_id}"  # шаблон имени файла
  date_format: "%Y%m%d_%H%M%S"

normalize_track_names: false  # true — очищать имена треков после загрузки

filters:
  file_types: ["audio", "document"]
  formats: [".flac", ".wav", ".aiff", ".m4a", ".mp3"]
  size:
    min_mb: 1
    max_mb: 500
  date:
    from: "2025-01-01"  # YYYY-MM-DD или null
    to: null

logging:
  level: "INFO"   # DEBUG | INFO | WARNING | ERROR
  file: "./data/logs/downloader.log"
  console: true
```

### Шаблоны имён файлов

В поле `naming.template` доступны переменные:

| Переменная | Описание |
|---|---|
| `{original_name}` | Оригинальное имя файла без расширения |
| `{message_id}` | ID сообщения в Telegram |
| `{publish_date}` | Дата публикации сообщения |
| `{download_date}` | Дата и время загрузки |
| `{file_size}` | Размер файла в байтах |
| `{artist}` | Исполнитель (из Telegram аудио-метаданных) |
| `{title}` | Название трека (из Telegram аудио-метаданных) |

---

## 🔑 Как узнать ID канала или группы

1. Перешлите любое сообщение из нужного канала боту `@ShowJsonBot`
2. Бот ответит JSON — найдите в нём `"chat":{"id":-1001234567890}`
3. Скопируйте число целиком (включая знак минус)

> **Публичные каналы** можно указывать по юзернейму: `@channelname`.  
> **Приватные каналы и группы** требуют числового ID.

---

## 🚀 Запуск

Запускайте из корня репозитория:

```bash
# Обычная загрузка
python src/main.py

# Указать конфиг явно
python src/main.py --config src/config.yaml

# Ограничить количество файлов
python src/main.py --max-files 20

# Задать число воркеров
python src/main.py --workers 5

# Показать статистику без загрузки
python src/main.py --stats

# Очистить трекер от записей с удалёнными файлами
python src/main.py --cleanup

# Показать прогресс текущей сессии
python src/main.py --progress
```

### 📋 Все параметры CLI

| Параметр | Короткий | Тип | По умолчанию | Описание |
|---|---|---|---|---|
| `--config` | `-c` | `str` | `src/config.yaml` | Путь к файлу конфигурации |
| `--max-files` | `-m` | `int` | `0` | Максимум файлов за запуск (0 = без лимита) |
| `--workers` | `-w` | `int` | из конфига | Количество параллельных воркеров (1–5) |
| `--stats` | `-s` | флаг | — | Показать статистику и выйти (без загрузки) |
| `--cleanup` | — | флаг | — | Удалить из трекера записи об отсутствующих файлах |
| `--progress` | `-p` | флаг | — | Вывести текущий прогресс загрузки |

---

## 📂 Организация загрузок

Каждый канал получает собственную папку внутри `output_dir`:

```
data/
  downloads/
    MusicChannel_-1001234567890/      ← папка канала
      message_tracker.json            ← обработанные сообщения
      file_tracker.json               ← загруженные файлы (хеши)
      downloads/
        track1.flac
        track2.mp3
    PublicMusic_@musicchannel/
      message_tracker.json
      file_tracker.json
      downloads/
        ...
```

**Именование папок:** `{ОчищенноеНазвание}_{id_из_config.yaml}`

- Название канала транслитерируется и очищается от спецсимволов
- ID канала используется ровно так, как указан в `config.yaml`

Примеры:

| config.yaml | Папка |
|---|---|
| `-1002006273817` | `MusicChannel_-1002006273817` |
| `@publicmusic` | `PublicMusic_@publicmusic` |

---

## 🔄 Первый запуск и авторизация

При первом запуске (или если сессия не существует) приложение попросит:

1. **Номер телефона** — в международном формате, например `+79001234567`
2. **Код подтверждения** — из Telegram
3. **Пароль 2FA** — если включена двухфакторная аутентификация

После успешного входа сессия сохраняется в `data/sessions/` — при следующих запусках авторизация не потребуется.

---

## ⚠️ Известные особенности

- `--progress` отображает прогресс один раз и завершается — это не фоновый монитор
- `--stats` и `--cleanup` работают только с трекерами, инициализированными в текущем запуске
- Параллельность реализована через `asyncio`-задачи, а не системные потоки

---

## 🔧 Решение проблем

| Проблема | Решение |
|---|---|
| Telegram просит авторизацию | Введите телефон, код и пароль 2FA в терминале |
| Превышены лимиты API | Уменьшите `--workers` или снизьте `requests_per_second` |
| Нестабильное соединение | Запустите с `--workers 1` |
| Файлы не скачиваются | Проверьте логи: `data/logs/downloader.log` |
| Папки/трекеры не создаются | Убедитесь, что `output_dir` доступен для записи |

---

## 🔐 Безопасность

- Не коммитьте `src/local_config.yaml` с реальными credentials
- Не коммитьте `*.session` файлы
- Не коммитьте `data/logs/` и загруженные файлы

---

## 📁 Структура проекта

```
telegram-music-downloader/
├── README.md
├── AGENTS.md
├── requirements.txt
├── src/
│   ├── main.py                  # точка входа, CLI, оркестровка
│   ├── config.yaml              # основной конфиг
│   ├── local_config.yaml        # локальные секреты (не в git)
│   ├── config_loader.py         # загрузка и мерж конфигов
│   ├── client.py                # авторизация и Telegram-клиент
│   ├── session_manager.py       # управление файлами сессий
│   ├── message_parser.py        # обход сообщений и извлечение медиа
│   ├── media_filter.py          # фильтрация по типу, формату, размеру, дате
│   ├── downloader.py            # загрузка файлов и именование
│   ├── download_queue.py        # приоритетная очередь + rate limiter
│   ├── download_worker.py       # воркеры (asyncio-задачи)
│   ├── download_coordinator.py  # координация воркеров и очереди
│   ├── download_monitor.py      # отображение прогресса
│   ├── tracker.py               # JSON-трекеры сообщений и файлов
│   ├── channel_utils.py         # именование и пути папок каналов
│   ├── normalizer.py            # нормализация имён треков
│   └── logger.py                # настройка логирования с ротацией
└── data/                        # runtime-данные (не в git)
    ├── downloads/
    ├── logs/
    └── sessions/
```

---

## 📄 Лицензия

MIT
