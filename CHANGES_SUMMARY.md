# Резюме изменений

## Дата: 2025-11-14

### Внесённые изменения

#### 1. Использование channel_id из config.yaml для именования папок

**Файлы:**
- `src/main.py`
- `src/message_parser.py`

**Суть изменения:**
- Теперь в названиях папок используется идентификатор канала из `config.yaml`, а не `entity.id` из Telegram API
- Channel ID форматируется (удаляются символы `-` и `@`) для использования в именах папок и tracker файлах

**До изменения:**
```
data/downloads/
└── ChannelTitle_123456789/  # entity.id из Telegram API
```

**После изменения:**
```
data/downloads/
└── ChannelTitle_1001234567890/  # ID из config.yaml (без минуса)
```

**Примеры:**

| config.yaml | Telegram entity.id | Название папки (ДО) | Название папки (ПОСЛЕ) |
|-------------|-------------------|---------------------|------------------------|
| `-1001234567890` | `-1001234567890` | `ChannelTitle_1001234567890` | `ChannelTitle_1001234567890` |
| `@musicchannel` | `-1009876543210` | `ChannelTitle_1009876543210` | `ChannelTitle_musicchannel` |

**Преимущества:**
- ✓ Консистентность с конфигурацией
- ✓ Предсказуемость названий папок
- ✓ Использование human-readable username'ов для публичных каналов

---

#### 2. Форматирование channel_id в tracker файлах

**Файлы:**
- `src/main.py` (импорт и использование `format_channel_id()`)

**Суть изменения:**
- `channel_id` в `message_tracker.json` и `file_tracker.json` теперь форматируется
- Удаляются символы `-` (минус) и `@` для единообразия с названиями папок

**До изменения:**
```json
{
  "channel_id": "-1001234567890",
  "processed_messages": [...]
}
```

**После изменения:**
```json
{
  "channel_id": "1001234567890",
  "processed_messages": [...]
}
```

**Примеры:**

| Значение в config.yaml | channel_id в tracker (ДО) | channel_id в tracker (ПОСЛЕ) |
|------------------------|---------------------------|------------------------------|
| `-1001234567890` | `-1001234567890` | `1001234567890` |
| `@musicchannel` | `@musicchannel` | `musicchannel` |
| `-123456789` | `-123456789` | `123456789` |

**Преимущества:**
- ✓ Консистентность между именами папок и tracker файлами
- ✓ Избежание проблем с минусом в разных контекстах
- ✓ Улучшенная читаемость

---

#### 3. Изменение приоритета скачивания файлов

**Файлы:**
- `src/download_queue.py`

**Суть изменения:**
- Изменён механизм приоритизации файлов в очереди скачивания
- **ДО:** Приоритет = размер файла (маленькие файлы скачивались первыми)
- **ПОСЛЕ:** Приоритет = message_id (файлы скачиваются в хронологическом порядке)

**До изменения:**
```python
# Приоритет по размеру файла
file_size_mb = task.media_info.get('file_size', 0) / (1024 * 1024)
task.priority = int(file_size_mb)  # Меньшие файлы - выше приоритет
```

**После изменения:**
```python
# Приоритет по ID сообщения
task.priority = task.media_info.get('message_id', 0)
```

**Пример работы:**

**ДО (приоритет по размеру):**
```
Порядок добавления:         Порядок скачивания:
  Message 100 (80 MB)  →      Message 109 (36 MB)  ← ПЕРВЫМ
  Message 101 (80 MB)  →      Message 108 (38 MB)
  Message 102 (76 MB)  →      Message 106 (41 MB)
  ...                         ...
  Message 108 (38 MB)  →      Message 100 (80 MB)  ← ПОСЛЕДНИМ
  Message 109 (36 MB)  →      Message 101 (80 MB)
```

**ПОСЛЕ (приоритет по message_id):**
```
Порядок добавления:         Порядок скачивания:
  Message 100 (80 MB)  →      Message 100 (80 MB)  ← ПЕРВЫМ
  Message 101 (80 MB)  →      Message 101 (80 MB)
  Message 102 (76 MB)  →      Message 102 (76 MB)
  ...                         ...
  Message 108 (38 MB)  →      Message 108 (38 MB)
  Message 109 (36 MB)  →      Message 109 (36 MB)  ← ПОСЛЕДНИМ
```

**Преимущества:**
- ✓ Предсказуемый порядок скачивания
- ✓ Соответствие хронологии публикаций
- ✓ Проще отслеживать прогресс
- ✓ Логичное продолжение после остановки

---

## Затронутые файлы

### Изменённые файлы

1. **src/main.py**
   - Добавлен импорт `format_channel_id` из `channel_utils`
   - Изменён метод `_process_channel_concurrent()`: использование `format_channel_id(channel_name)` вместо `str(entity.id)`
   - Изменён метод `_process_channel()`: аналогично
   - Передача `config_channel_id` в `parse_messages()`

2. **src/message_parser.py**
   - Добавлен параметр `config_channel_id` в метод `parse_messages()`
   - Использование `config_channel_id` если указан, иначе `entity.id`

3. **src/download_queue.py**
   - Изменена логика расчёта приоритета с `file_size_mb` на `message_id`

### Новые файлы (документация)

1. **TELEGRAM_ID_FORMAT.md**
   - Объяснение формата ID в Telegram
   - Почему `-` перед ID
   - Как ID используются в проекте

2. **DOWNLOAD_QUEUE_EXPLAINED.md**
   - Детальное объяснение работы очереди скачивания
   - Как работает приоритизация
   - Варианты настройки поведения

3. **CHANGES_SUMMARY.md** (этот файл)
   - Резюме всех изменений

---

## Миграция

### Влияние на существующие установки

**Важно:** Эти изменения могут привести к созданию новых папок для существующих каналов!

#### Сценарий 1: Канал указан по числовому ID

**config.yaml:**
```yaml
channels:
  - -1001234567890
```

**До изменений:**
- Папка: `data/downloads/ChannelTitle_1001234567890/`
- tracker: `"channel_id": "1001234567890"`

**После изменений:**
- Папка: `data/downloads/ChannelTitle_1001234567890/`
- tracker: `"channel_id": "1001234567890"`

**Результат:** ✓ Без изменений (если ID уже был без минуса в entity.id)

#### Сценарий 2: Канал указан по username

**config.yaml:**
```yaml
channels:
  - "@musicchannel"
```

**До изменений:**
- Папка: `data/downloads/ChannelTitle_1009876543210/` (использовался entity.id)
- tracker: `"channel_id": "1009876543210"`

**После изменений:**
- Папка: `data/downloads/ChannelTitle_musicchannel/` (используется username)
- tracker: `"channel_id": "musicchannel"`

**Результат:** ⚠️ Будет создана НОВАЯ папка, старая останется нетронутой

### Рекомендации по миграции

**Вариант 1: Переименовать папки вручную**

```bash
# Найти папки, которые нужно переименовать
cd data/downloads

# Переименовать папку канала
mv "ChannelTitle_1009876543210" "ChannelTitle_musicchannel"

# Обновить channel_id в tracker файлах
cd "ChannelTitle_musicchannel"
# Отредактировать message_tracker.json и file_tracker.json
```

**Вариант 2: Начать заново**

Система автоматически создаст новые папки и начнёт скачивание с места, указанного в конфигурации или с начала.

**Вариант 3: Использовать числовые ID вместо username**

В `config.yaml` указывайте числовые ID вместо `@username`:

```yaml
channels:
  - -1001234567890  # Вместо @musicchannel
```

Для получения числового ID:
1. Перешлите сообщение из канала боту [@ShowJsonBot](https://t.me/ShowJsonBot)
2. Найдите `"chat": {"id": -1001234567890}`
3. Используйте это значение в конфигурации

---

## Тестирование

### Как проверить изменения

1. **Проверить именование папок:**
   ```bash
   python src/main.py --config src/local_config.yaml --max-files 10
   ls -la data/downloads/
   ```

2. **Проверить channel_id в tracker'ах:**
   ```bash
   cat data/downloads/ChannelTitle_*/message_tracker.json | grep channel_id
   cat data/downloads/ChannelTitle_*/file_tracker.json | grep channel_id
   ```

3. **Проверить порядок скачивания:**
   ```bash
   python src/main.py --config src/local_config.yaml --max-files 20 --progress
   ```
   
   Наблюдайте за логами - файлы должны скачиваться в порядке их появления в логе "Queued for download".

### Ожидаемые результаты

**1. Название папок:**
- Для `-1001234567890`: `ChannelTitle_1001234567890/`
- Для `@musicchannel`: `ChannelTitle_musicchannel/`

**2. В tracker файлах:**
```json
{
  "channel_id": "1001234567890",  // Без минуса
  "processed_messages": [...]
}
```

**3. Порядок скачивания:**
```
2025-11-14 13:03:09 - INFO - Queued for download: File1.wav [80.2 MB]
2025-11-14 13:03:09 - INFO - Queued for download: File2.wav [80.1 MB]
2025-11-14 13:03:09 - INFO - Queued for download: File3.flac [41.4 MB]
...
2025-11-14 13:03:10 - INFO - ✓ Downloaded successfully: File1.wav [80.2 MB]  ← ПЕРВЫМ
2025-11-14 13:03:15 - INFO - ✓ Downloaded successfully: File2.wav [80.1 MB]
2025-11-14 13:03:17 - INFO - ✓ Downloaded successfully: File3.flac [41.4 MB]
```

---

## Откат изменений

Если необходимо вернуть старое поведение:

### Откат приоритизации по размеру файла

Изменить `src/download_queue.py`, строка 55:

```python
# Вернуть приоритет по размеру
file_size_mb = task.media_info.get('file_size', 0) / (1024 * 1024)
task.priority = int(file_size_mb)
```

### Откат использования entity.id для папок

Изменить `src/main.py`, строки 163 и 271:

```python
# Вернуть использование entity.id
channel_id = str(entity.id)
```

---

## Коммиты

```
5b9754a - Change download priority from file size to message ID
f84f4be - Format channel_id in trackers (remove '-' and '@' symbols)
4ddb8e5 - Use channel_id from config.yaml for folder naming
```

### Детали коммитов

**Коммит 1: Use channel_id from config.yaml for folder naming**
- Изменён `src/main.py`: использование `channel_name` вместо `entity.id`
- Изменён `src/message_parser.py`: добавлен параметр `config_channel_id`
- Теперь используется ID из конфигурации для именования папок

**Коммит 2: Format channel_id in trackers**
- Добавлен импорт `format_channel_id` в `src/main.py`
- Применяется форматирование для удаления `-` и `@`
- Консистентность между папками и tracker файлами

**Коммит 3: Change download priority from file size to message ID**
- Изменён `src/download_queue.py`: приоритет по `message_id`
- Файлы скачиваются в хронологическом порядке
- Более предсказуемое поведение

---

## Дополнительные ресурсы

- **TELEGRAM_ID_FORMAT.md** - подробности о форматах ID в Telegram
- **DOWNLOAD_QUEUE_EXPLAINED.md** - детали работы очереди скачивания
- **CONCURRENT_DOWNLOADS.md** - документация по многопоточному скачиванию
- **CHANNEL_STRUCTURE_UPDATE.md** - информация о структуре папок по каналам

---

## FAQ

**Q: Почему файлы теперь скачиваются медленнее?**

A: Скорость не изменилась. Раньше маленькие файлы скачивались первыми и создавалось впечатление быстрого прогресса. Теперь файлы скачиваются по порядку, включая большие файлы в начале.

**Q: Можно ли вернуть приоритет по размеру?**

A: Да, см. раздел "Откат изменений" выше.

**Q: Что делать со старыми папками?**

A: Можно переименовать вручную или оставить как есть. Система создаст новые папки для каналов с изменившимися именами.

**Q: Влияют ли изменения на уже скачанные файлы?**

A: Нет, скачанные файлы остаются нетронутыми. Изменения влияют только на новые загрузки.

**Q: Почему channel_id без минуса?**

A: Минус может вызывать проблемы в командной строке и некоторых ОС. Форматированный ID более универсален. См. TELEGRAM_ID_FORMAT.md для подробностей.

---

## Контакты

Для вопросов и предложений используйте Issues в репозитории GitHub.
