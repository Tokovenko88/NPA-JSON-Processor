# Проект NPA-JSON-Processor

## Назначение

NPA-JSON-Processor — это Python-приложение для автоматизированной обработки нормативных правовых актов (НПА) Законодательного Собрания Севастополя. Приложение выполняет две основные функции:

1. **Парсинг HTML → JSON**: преобразует HTML-документы законов и постановлений в структурированный JSON-формат с иерархией глав, статей, пунктов, подпунктов, приложений и таблиц.
2. **Внесение изменений в НПА**: на основе второго НПА (изменяющего) применяет изменения к первому (изменяемому) с помощью 5-этапного AI-пайплайна с локальными LLM (Ollama).

## Архитектура проекта

```
E:\NPA-JSON-Processor/
├── npa_processor/
│   ├── __init__.py
│   ├── __main__.py                    # Точка входа CLI
│   ├── _bootstrap.py                  # Единый bootstrap sys.path
│   ├── constants.py                   # Общие константы (пути, TYPE_TO_RUSSIAN, промпты)
│   ├── config.py                      # Конфигурация (SSH, DB, Ollama)
│   ├── core/                          # Парсинг и работа с MODX
│   │   ├── html_parser.py             # Парсинг HTML → JSON (NpaToJsonGenerator)
│   │   ├── modx_processor.py          # Пакетная обработка через MODX (MODXHTMLProcessor)
│   │   └── modx_gui.py                # GUI для MODX (MODXProcessorGUI)
│   ├── processing/                    # Обработка изменений НПА
│   │   ├── revision_utils.py          # Фасад утилит (обратная совместимость)
│   │   │   ├── text_utils.py          # Нормализация текста и номеров
│   │   │   ├── html_utils.py          # Очистка и извлечение HTML
│   │   │   ├── ai_utils.py            # Взаимодействие с Ollama API
│   │   │   ├── json_utils.py          # Загрузка/сохранение JSON
│   │   │   ├── tree_utils.py          # Работа с деревом документа
│   │   │   └── ui_utils.py            # Диалоги и UI-хелперы
│   │   ├── revision_engine.py         # Фасад движка изменений (обратная совместимость)
│   │   │   ├── element_finder.py      # Поиск элементов
│   │   │   ├── change_applier.py      # Применение изменений
│   │   │   └── revision_builder.py    # Построение ревизий
│   │   ├── revision_processor.py      # GUI приложения (App)
│   │   │   ├── gui_builder.py         # Создание виджетов (GuiBuilderMixin)
│   │   │   ├── ai_pipeline.py         # 5-этапный AI-пайплайн (AiPipelineMixin)
│   │   │   └── file_ops.py            # Файловые операции (FileOpsMixin)
│   │   ├── prompts/                   # Промпты для ИИ
│   │   │   ├── prompt_1.txt           # Анализ утраты силы
│   │   │   ├── prompt_2.txt           # Анализ дат вступления
│   │   │   ├── prompt_3.txt           # Извлечение изменений
│   │   │   └── prompt_4.txt           # Расчёт HTML-координат
│   │   ├── last_paths.json            # Состояние UI (последние пути)
│   │   └── stage_answers.json         # Кэш ответов ИИ
│   ├── ui/                            # Диалоговые окна
│   │   ├── manual_mapping_dialog.py   # Ручной выбор элемента
│   │   └── source_mapping_dialog.py   # Выбор источника изменения
│   └── docs/
│       └── json_structure.md          # Спецификация JSON-формата НПА
├── tests/
│   ├── test_config.py
│   ├── test_imports.py
│   └── test_revision_utils.py
├── requirements.txt
└── modx_processor.log
```

## Ключевые компоненты

### 1. Парсинг HTML → JSON (`core/`)

**NpaToJsonGenerator** (`html_parser.py`) — ядро парсера.
- Принимает HTML НПА с сайта sevzakon.ru
- Возвращает иерархический JSON с метаданными, структурными элементами и контентом
- Обрабатывает: дублирующиеся номера (`number_revisions`), таблицы с ручной структурой (`structured_table`), preamble, toc_items
- Использует BeautifulSoup + lxml для парсинга

**MODXHTMLProcessor** (`modx_processor.py`) — пакетная обработка через MODX CMS.
- SSH/SFTP подключение к серверу
- Загрузка JSON через SFTP
- Обновление MySQL базы данных (TV параметры)
- Кэширование ресурсов с TTL

**MODXProcessorGUI** (`modx_gui.py`) — GUI для браузинга ресурсов MODX.
- Отображает список законов и постановлений
- Очередь обработки с прогресс-баром
- Локальное сохранение результатов

### 2. Обработка изменений (`processing/`)

#### 5-этапный AI-пайплайн

**Этап 1 — Анализ утраты силы** (`_stage1_deletion_analysis`)
- Анализирует заключительные положения изменяющего НПА
- Определяет, утрачивает ли закон силу полностью или отдельные элементы

**Этап 2 — Анализ дат** (`_stage2_dates_analysis`)
- Находит особые даты вступления в силу
- Обнаруживает ретроактивные clauses

**Этап 3 — Извлечение изменений** (`_stage3_changes_extraction`)
- Извлекает структурированные изменения из текста изменяющего НПА
- Типы изменений: `new_redaction`, `add`, `delete`, `change`
- Использует промпт 3 (465 строк строгого форматирования)

**Этап 4 — Расчёт координат** (встроен в `apply_grouped_changes`)
- Для текстовых изменений вызывает ИИ с промптом 4
- ИИ возвращает HTML с подсветками добавлений/удалений

**Этап 5 — Перестройка** (`_stage5_rebuild`)
- Создаёт новые ревизии с `valid_from`/`valid_to`
- Сохраняет `child_ref` ссылки
- Генерирует highlights (previous_edition/current_edition)

#### Движок изменений (`revision_engine/`)

**element_finder** — поиск элементов:
- `find_element_and_parent` — поиск по ID
- `find_item_by_revision_number` — поиск по пути ревизии
- `_resolve_modified_by_ids` — разрешение ссылок на изменённые элементы
- `narrow_source_id_to_subpoint` — уточнение элемента до подпункта

**change_applier** — применение изменений:
- `apply_grouped_changes` — применение группы изменений к элементу
- `apply_change` — применение одного изменения
- Обработка `new_redaction`, текстовых изменений, удаления, добавления

**revision_builder** — история ревизий:
- Создание/закрытие ревизий
- Синхронизация `child_ref` в теле родителя
- Объединение подсветок

### 3. Утилиты (`processing/`)

**text_utils** — работа с текстом:
- `normalize_number_string` — нормализация номеров
- `clean_head_text` — очистка заголовков
- `safe_re_sub` — безопасная обёртка regex
- `adjust_last_item_punctuation` — технические правки пунктуации

**html_utils** — работа с HTML:
- `extract_paragraphs_by_indices` — извлечение абзацев по диапазону
- `split_html_to_paragraphs` — разбивка HTML на абзацы
- `parse_ai_response_for_prompt4` — парсинг ответа ИИ
- `clean_description_html` — очистка HTML от служебных тегов

**ai_utils** — работа с ИИ:
- `ask_ollama` — отправка промптов к Ollama с retry-логикой
- `load_prompt_from_file` — загрузка промптов
- `strip_thinking_tags` — удаление тегов рассуждений ИИ

**tree_utils** — работа с деревом:
- `find_item_by_id` — поиск элемента по ID
- `clean_number` — очистка номера
- `parse_revision_number_to_path` — разбор пути ревизии
- `get_active_revision` — получение активной ревизии

**ui_utils** — интерфейс:
- Диалоговые окна, контекстные меню, горячие клавиши

### 4. Интерфейс (`processing/revision_processor.py` + `ui/`)

**App** — главный класс приложения (MVC-подобная архитектура):
- Наследует `GuiBuilderMixin`, `AiPipelineMixin`, `FileOpsMixin`
- Управляет очередями сообщений (`message_queue`, `answer_queue`)
- Обрабатывает события Tkinter в главном потоке
- Запускает длительные операции в отдельных потоках

**ManualMappingDialog** — диалог ручного выбора элемента при неоднозначности.
**SourceMappingDialog** — диалог выбора источника изменения.

## Данные

### Входные данные
- HTML с sevzakon.ru (законы/постановления Севастополя)
- JSON исходного НПА
- JSON изменяющего НПА

### Выходные данные
- JSON с иерархической структурой НПА (для парсера)
- Модифицированный JSON с историей ревизий (для обработчика изменений)

### Промежуточные данные
- `prompts/*.txt` — промпты для 4 этапов AI-пайплайна
- `last_paths.json` — состояние UI
- `stage_answers.json` — кэш ответов ИИ

## Зависимости

- **beautifulsoup4, lxml** — парсинг HTML
- **requests** — HTTP-запросы к Ollama
- **paramiko** — SSH/SFTP подключение
- **pymysql** — работа с MySQL
- **tkinter** — графический интерфейс
- **json5, json-repair** — работа с JSON
- **ollama** (локально) — LLM для анализа изменений

## Запуск

```bash
# Режим парсинга HTML → JSON
python -m npa_processor --html-to-json

# Режим внесения изменений в НПА
python -m npa_processor
```

## Тестирование

```bash
python -m unittest discover -s tests -v
```

## Документация

- `docs/json_structure.md` — детальная спецификация JSON-формата НПА
- `prompts/*.txt` — промпты для 4 этапов AI-пайплайна
- Модульные docstrings — описание каждого модуля и класса

---

## 16. Детальная документация модулей и функций

### 16.1 Точка входа и бутстрэп

#### `__main__.py`

| Функция | Назначение |
|---------|-----------|
| `bootstrap_project_root()` | Добавляет корень проекта в `sys.path`. |
| `run_revision_app()` | Запускает GUI для внесения изменений (`App`). |
| `run_html_to_json_app()` | Запускает GUI для парсинга HTML→JSON. |
| `main()` | Маршрутизация: `--html-to-json` → парсинг, иначе → изменения. |

#### `_bootstrap.py`

| Функция | Назначение |
|---------|-----------|
| `_bootstrap_project_root()` | Рекурсивно ищет корень проекта и добавляет в `sys.path`. |

### 16.2 Конфигурация и константы

#### `config.py`

| Объект/Функция | Назначение |
|----------------|-----------|
| `_ModxSettings` (namedtuple) | SSH, DB, Ollama параметры. |
| `get_settings()` | Читает переменные окружения с дефолтами. |
| `get_modx_db_config()` | Параметры подключения к MySQL. |

**Переменные окружения**: `MODX_SSH_HOST/PORT/USERNAME/PASSWORD`, `MODX_BASE_PATH`, `MODX_DB_HOST/PORT/USER/PASSWORD/NAME/CHARSET`, `OLLAMA_DEFAULT_MODEL`, `OLLAMA_BASE_URL`.

#### `constants.py`

| Объект/Функция | Назначение |
|----------------|-----------|
| `settings` | Глобальный экземпляр конфигурации MODX/Ollama. |
| `CONFIG_DIR` | Путь к `npa_processor/`. |
| `PROMPTS_DIR` | Путь к `npa_processor/prompts/`. |
| `LAST_PATHS_FILE` | Путь к `last_paths.json`. |
| `STAGE_ANSWERS_FILE` | Путь к `stage_answers.json`. |
| `DEFAULT_EXTRA_OPTIONS` | `temperature=0.0`, `top_p=0.1`. |
| `TYPE_TO_RUSSIAN` | Маппинг типов (`article→Статья`, `chapter→Глава` и т.д.). |
| `PLURAL_TO_SINGULAR` | Множественное → единственное (`части→часть`). |
| `DEFAULT_OLLAMA_MODEL` | Модель по умолчанию (`gemini-1.5-flash`). |
| `_ollama_base_url` | URL Ollama API. |
| `_user_retry_callback` | Callback для запроса retry у пользователя. |
| `load_prompt_from_file(filename)` | Загружает промпт из `prompts/`. |
| `PROMPT_1..4` | Тексты промптов для 4 этапов. |

### 16.3 Модуль `core/` — Парсинг HTML и MODX

#### `html_parser.py` — `NpaToJsonGenerator`

| Метод | Назначение |
|-------|-----------|
| `__init__(...)` | Инициализация: BeautifulSoup, логирование, стеки, кэши, `extract_metadata()`. |
| `sup_digits_to_unicode(text)` | `<sup>N</sup>` → Unicode-надстрочные цифры. |
| `_wrap_table_html(html_text)` | Оборачивает `border="1"` таблицы в `div.double-scroll`. |
| `_normalize_number_string(num_str)` | Нормализует номера (убирает `<sup>`, римские в верхний регистр). |
| `_get_unique_item_id(...)` | Генерирует `item_id` с `_double_N` при дублировании. |
| `_filter_out_table_children(tags)` | Исключает теги внутри `div.double-scroll`. |
| `_is_structural_table_row(row_tag)` | Определяет структурную строку таблицы. |
| `_parse_table_row_as_candidate(...)` | Парсит строку таблицы как кандидат (section/point/subpoint). |
| `_process_structured_table(table_tag, i, all_tags)` | Обрабатывает таблицу с явной структурой, строит иерархию. |
| `_add_structured_table_child(child_item, parent_item)` | Рекурсивно добавляет дочерний элемент в `structured_table`. |
| `_process_table(tag, i, all_tags)` | Определяет тип таблицы и обрабатывает. |
| `_add_orphan_content(html)` | Добавляет изолированный HTML как `paragraph`. |
| `_parse_table_row_candidate(tr_tag)` | Парсит строку таблицы по ячейкам. |
| `_para_quote_state(text)` | Анализирует баланс кавычек «». |
| `_is_starting_number(number_str)` | Проверяет начальный номер («1»/«а»). |
| `_open_enumeration(parent_item, candidate)` | Открывает контекст перечисления. |
| `_close_enumeration()` | Закрывает текущий уровень перечисления. |
| `_close_enumeration_if_needed()` | Закрывает при точке и `;`. |
| `_get_no_name_parent_id()` | Ищет родителя для элементов без «Раздел». |
| `_sync_enum_stack()` | Синхронизирует стек перечислений. |
| `_log_stack_state(context)` | Логирует стек элементов. |
| `_safe_pop()` | Безопасно извлекает из стека (не трогает фрагментные цели). |
| `parse_element_path_from_id(element_id)` | Разбирает `item_id` на путь (тип, номер). |
| `reconstruct_initial_stack(element_id)` | Восстанавливает стек для фрагментной обработки. |
| `process_fragment(fragment_html, element_id)` | Обрабатывает HTML-фрагмент элемента (перестройка). |
| `extract_metadata()` | Извлекает метаданные (тип, номер, даты, подписант). |
| `extract_law_metadata()` | Метаданные для закона (заголовок, дата принятия, подпись губернатора). |
| `extract_regulation_metadata()` | Метаданные для постановления (номер, дата, созыв, сессия). |
| `parse_element_candidate(text, tag)` | Определяет тип элемента по тексту. |
| `generate_toc()` | Полный цикл парсинга HTML → JSON. |
| `convert_to_new_format(items, level)` | Конвертирует в финальный JSON с `revisions`, `head_revisions`. |
| `build_element_id(element_type, item_number, stack)` | Строит `item_id` по шаблону. |
| `get_display_text(...)` | Формирует отображаемый текст. |
| `extract_text(tag)` | Чистый текст из тега BeautifulSoup. |
| `is_centered_tag(tag)` | Проверка центрирования тега. |
| `find_appendix_title(all_tags, start_idx)` | Ищет заголовок приложения. |
| `_ask_user_appendix_title(title)` | Запрашивает подтверждение заголовка у пользователя. |
| `normalize_text(text)` | Нормализует текст (`&nbsp;`, пробелы). |
| `parse_russian_date(date_str)` | Парсит русскоязычную дату. |
| `find_governor_signature(all_tags, start_idx)` | Ищет блок подписи губернатора. |

**Основной цикл парсинга**:
1. Извлечение метаданных.
2. Итерация по тегам (`p`, `h1`-`h6`, `div`, `table`).
3. Распознавание структурных элементов по regex.
4. Управление стеком вложенности (`self.stack`).
5. Обработка таблиц (структурных/неструктурных).
6. Обработка перечислений (`enum_stack`).
7. Конвертация в финальный JSON.

#### `modx_processor.py` — `MODXHTMLProcessor`

| Метод | Назначение |
|-------|-----------|
| `__init__(log_queue)` | Инициализация: конфиг, пул DB, логирование. |
| `_init_db_pool()` | Создаёт пул из 2 MySQL-соединений. |
| `get_db_connection()` | Берёт соединение из пула. |
| `release_db_connection(conn)` | Возвращает соединение в пул. |
| `close_db_pool()` | Закрывает все соединения. |
| `clear_cache()` | Очищает кэш и LRU. |
| `get_resource_basic_cached(resource_id)` | Базовые поля ресурса с LRU-кэшем. |
| `get_resource_with_params_cached(resource_id)` | Ресурс с TV-параметрами (TTL 5 мин). |
| `load_resources_list_optimized(...)` | Оптимизированная загрузка списка с фильтрами. |
| `get_all_resources_optimized(...)` | Все ресурсы с JOIN по TV, включая дочерние. |
| `get_resources_by_law_number(law_number)` | По номеру закона. |
| `get_resources_by_resolution_number(resolution_number)` | По номеру постановления. |
| `_format_resources_list(resources_data, doc_type)` | Форматирование для отображения. |
| `get_resource_with_params_fast(resource_id)` | Агрегированные TV одним запросом. |
| `get_parent_resource_params(parent_id)` | TV-параметры родителя. |
| `get_first_child_publish_tv(container_id)` | TV `publish` первого дочернего. |
| `connect_ssh()` | SSH/SFTP подключение (2 попытки). |
| `execute_ssh_command(command, timeout)` | Выполнение команды на сервере. |
| `create_structure(doc_type, year)` | Создание директорий `/assets/json/{doc_type}/{year}/`. |
| `upload_json_via_sftp(resource_id, year, json_data, doc_type)` | Загрузка JSON, права `644`. |
| `update_tv_parameter(resource_id, tv_value)` | Обновление TV `172` (путь к JSON). |

#### `modx_gui.py` — `MODXProcessorGUI`

| Метод | Назначение |
|-------|-----------|
| `__init__()` | Инициализация Tkinter, `MODXHTMLProcessor`. |
| `_remove_empty(data)` | Рекурсивное удаление пустых значений. |
| `_normalize_text(text)` | Нормализация текста. |
| `_normalize_signer_name(name)` | Нормализация ФИО. |
| `ask_ambiguity(candidate_text, adjacent_text)` | Диалог неоднозначной иерархии. |
| `ask_appendix_title_confirmation(appendix_title)` | Диалог заголовка приложения. |
| `setup_ui()` | Создание интерфейса. |
| `copy_log_selection(event)` | Копирование лога. |
| `show_log_context_menu(event)` | Контекстное меню лога. |
| `log_message(message, level)` | Вывод в лог с цветом. |
| `display_resources(resources)` | Отображение списка ресурсов. |
| `filter_resources(event)` | Фильтр по году/типу. |
| `reset_filters()` | Сброс фильтров. |
| `select_all_resources()` / `deselect_all_resources()` | Выделение. |
| `get_selected_resource_ids()` | ID из Listbox. |
| `get_manual_resource_ids()` | Парсинг ID из поля. |
| `check_queue()` | Проверка очереди сообщений. |
| `process_message(message)` | Обработка сообщений. |
| `processing_done(success)` | Завершение обработки. |
| `load_resources_complete(resources, error)` | Завершение загрузки. |
| `start_processing_selected()` | Обработка выбранных. |
| `start_processing_manual()` | Обработка по ID. |
| `start_processing_with_ids(resource_ids, custom_id)` | Фоновый поток. |
| `stop_processing()` | Остановка, закрытие SSH/DB. |
| `process_resources(resource_ids, custom_id)` | Итерация по ресурсам. |
| `format_date(date_str)` | Форматирование даты. |
| `process_single_resource(resource_id, custom_id)` | Полный цикл одного ресурса. |
| `load_resources_list()` | Фоновая загрузка списка. |
| `_load_resources_background_optimized(...)` | Загрузка через `MODXHTMLProcessor`. |
| `run()` | Запуск `mainloop()`. |

### 16.4 Модуль `processing/` — Обработка изменений

#### Фасады

- `revision_utils.py` — реэкспорт утилит (`text_utils`, `html_utils`, `ai_utils`, `json_utils`, `tree_utils`, `ui_utils`).
- `revision_engine.py` — реэкспорт движка (`element_finder`, `change_applier`, `revision_builder`).

#### `text_utils.py`

| Функция | Назначение |
|---------|-----------|
| `strip_thinking_tags(text)` | Удаляет `<thinking>`/`<think>`. |
| `sup_digits_to_unicode(text)` | `<sup>N</sup>` → Unicode-надстрочные. |
| `safe_re_sub(pattern, repl, string, ...)` | Безопасная обёртка `re.sub`. |
| `normalize_number_string(num_str)` | Нормализация номера (убирает `<sup>`, HTML, римские). |
| `clean_head_text(head_text, item_type, item_number)` | Очистка заголовка от служебных слов. |
| `normalize_item_number(item_type, number)` | Нормализация номера (добавляет `)`). |
| `normalize_text_for_search(text)` | Нормализация для поиска. |
| `_ends_with(element, char)` | Окончание текста активной ревизии на символ. |
| `adjust_last_item_punctuation(parent, new_item, ...)` | Меняет `.` на `;` у предпоследнего. |
| `adjust_punctuation_after_deletion(parent, deleted_item, ...)` | Меняет `;` на `.` у нового последнего. |
| `normalize_structural(s)` | «статьи»→«статья» и т.д. |
| `parse_num(s)` | Парсит номер в кортеж (`"1.2"` → `(1, 2)`). |
| `clean_html_text(html)` | Убирает теги, схлопывает пробелы. |
| `get_active_revision(element, use_original)` | Активная ревизия (`valid_to=None` или последняя). |
| `get_element_text(element)` | Текст из активной ревизии. |
| `shift_highlight_index(pos_str, threshold, delta)` | Сдвиг индекса подсветки при добавлении/удалении абзацев. |
| `clean_number(num_str)` | Очистка номера (латиница→кириллица, римские→арабские). |

#### `html_utils.py`

| Функция | Назначение |
|---------|-----------|
| `clean_and_unwrap_html(html_text, is_table_child)` | Убирает пустые `<p>`, для таблиц возвращает `<tr>`. |
| `_extract_quoted_html(html, log_callback)` | Извлекает блок во внешних кавычках «...». |
| `extract_paragraphs_by_indices(html, range_str, log_callback)` | Извлечение абзацев по диапазону/цитатам. |
| `extract_leading_number(html)` | Ведущий номер первого абзаца. |
| `extract_html_for_added_element(source_html, range_str, child_number, ...)` | HTML для добавляемого элемента с проверкой номера. |
| `remove_leading_number_from_html(html, item_number)` | Убирает ведущий номер. |
| `clean_description_html(html)` | Очистка HTML-описания. |
| `split_html_to_paragraphs(html_text)` | Разбивка на `<p>...</p>`. |
| `split_html_by_leading_number(html_str, numbers)` | Разбивка по ведущим номерам (диапазоны). |
| `build_search_pattern(original_data)` | Regex для поиска номера НПА. |
| `get_clean_text_from_block(block)` | Чистый текст блока. |
| `strip_number_from_element_html(html, item_number, item_type)` | Убирает номер из начала HTML. |
| `strip_leading_number_from_html_if_needed(...)` | Условное удаление номера. |
| `_correct_table_highlights(old_html, new_html, highlights, ...)` | Коррекция подсветки для таблиц через `difflib`. |
| `parse_ai_response_for_prompt4(response_text, ...)` | Парсит ответ этапа 4: HTML + `highlights`. |
| `add_number_to_paragraph_html(html_text, item_number, item_type)` | Добавляет номер в первый абзац. |
| `parse_structural_tokens(structural)` | Разбирает путь на `[(type, number), ...]`. |
| `format_structural_number(number, is_header, has_title)` | Форматирует номер для отображения. |
| `get_item_html_recursive(item, all_items_map, include_header)` | Рекурсивно собирает полный HTML элемента. |
| `extract_html_from_element(element)` | Обёртка над `get_item_html_recursive`. |
| `get_full_element_html(element, ...)` | Полный HTML элемента (с/без заголовка). |
| `extract_text_from_revision(rev)` | Текст из редакции. |
| `extract_text_from_element(element)` | Рекурсивный текст элемента. |
| `get_active_prefix_text(element)` | Активный префикс приложения. |
| `get_current_head(element)` | Текущий заголовок элемента. |
| `create_element_skeleton(...)` | Создаёт скелет нового элемента с уникальным `item_id`. |

#### `ai_utils.py`

| Функция | Назначение |
|---------|-----------|
| `ask_ollama(prompt, model, log_callback, extra_options, stop_event, max_retries, retry_delay, change_info)` | Отправка промпта в Ollama с retry (3×30с), логированием, callback пользователя. |

#### `json_utils.py`

| Функция | Назначение |
|---------|-----------|
| `load_json(file_path, default)` | Загрузка JSON или `default`. |
| `save_json(file_path, data)` | Сохранение с `ensure_ascii=False, indent=2`. |
| `extract_html_from_json_response(text, log_callback)` | Извлечение HTML из JSON-ответа ИИ. |

#### `tree_utils.py`

| Функция | Назначение |
|---------|-----------|
| `find_item_by_id(data, item_id)` | Рекурсивный поиск по `item_id`. |
| `parse_number_word(word)` | «первый»→1, «второй»→2 и т.д. |
| `parse_revision_number_to_path(rev_number, log_callback)` | Строка ревизии → список номеров. |
| `insert_child_ref_in_body(parent, new_child_id, log_callback)` | Вставляет `child_ref` в body, сохраняя порядок. |
| `adjust_highlights_for_paragraph_change(...)` | Корректирует подсветки при изменении абзаца. |
| `_find_element_by_revision_path(root_element, revision_number)` | Поиск по пути ревизии. |
| `find_child_by_type_and_number(parent, child_type, child_number, ...)` | Поиск ребёнка по типу и номеру. |
| `find_element_in_chapters_or_sections(parent, target_type, target_number, ...)` | Поиск в главах/разделах. |
| `find_target_element(change_data, original_data, log_callback, doc_type)` | Поиск целевого элемента по ключевым словам. |
| `find_target_element_via_ai(...)` | Поиск через ИИ по тексту. |
| `find_appendix_by_number(data, app_number)` | Поиск приложения по номеру. |

#### `ui_utils.py`

| Функция | Назначение |
|---------|-----------|
| `normalize_ru_type(ru_type)` | Нормализация типа к единственному числу. |
| `normalize_item_number(item_type, number)` | Нормализация номера. |
| `collect_item_ids(item, ids_set)` | Сбор всех `item_id` в множество. |
| `add_context_menu(widget, allow_edit)` | Контекстное меню (копировать/вставить). |
| `add_hotkeys(widget, allow_edit)` | Ctrl+A/C/V/X. |
| `extract_json_from_text(text)` | Извлечение JSON из текста ответа ИИ. |
| `split_range_changes(changes, log_callback)` | Разбиение диапазона («пункты 1-3») на отдельные изменения. |
| `_correct_change_description(ch, change_data, ...)` | Проверка/исправление описания, поиск источника, сохранение `_quoted_html`. |
| `_fetch_source_html_for_change(change, change_data, ...)` | Получение HTML-источника по `revision_number`. |
| `_child_with_key_exists_in_new_tree(...)` | Проверка existence в новом дереве. |
| `_item_id_exists_in_new_tree(item_id, new_element)` | Проверка `item_id` в новом дереве. |
| `_transfer_structural_state(old_child, new_child, ...)` | Перенос истории и pending со старого на нового при смене родителя. |
| `sync_structural_element_recursive(old_element, new_element, ...)` | Рекурсивная синхронизация: закрытие старых ревизий, создание новых, перенос детей, `number_revisions`, объединение body. |
| `expand_range_in_new_field(change, log_callback, ...)` | Разбиение диапазона в поле `new` («пункты 1-3»). |
| `ensure_path(data, tokens, valid_from, ...)` | Обеспечение существования пути (создание отсутствующих). |
| `_find_existing_element_flexible(data, structural, ...)` | Гибкий поиск по структурному пути. |
| `_find_deepest_existing_ancestor(data, structural, ...)` | Самый глубокий существующий предок (для отложенного `add`). |
| `_resolve_add_parent_and_deferred(...)` | Для `add`: поиск предка + deferred tokens. |
| `_add_new_element(parent_element, sys_type, child_num, ...)` | Добавление нового элемента в дерево. |
| `_close_revision(head_rev, valid_to_str)` | Закрытие ревизии. |
| `_make_new_revision(element, new_body, mod_type, ...)` | Создание новой ревизии. |
| `create_new_parent_revision(parent, old_rev, new_body, ...)` | Новая ревизия родителя. |
| `build_new_body_preserving_child_refs(old_rev, answer_html)` | Новый body из ответа ИИ с сохранением `child_ref`. |
| `clean_number_for_filename(number)` | Очистка номера для имени файла. |
| `get_date_for_filename(data, doc_type)` | Дата для имени файла. |
| `is_highlights_empty(highlights)` | Проверка пустоты подсветки. |
| `_normalize_highlights_positions(highlights)` | Нормализация позиций подсветки. |
| `parse_add_new_field(new_str)` | Парсинг `new` («пункт 7») → `(ru_type, number_str)`. |

#### `element_finder.py`

| Функция | Назначение |
|---------|-----------|
| `find_element_and_parent(data, target_id)` | Элемент и родитель по `item_id`. |
| `find_item_id_by_element_string(data, structural, ...)` | `item_id` по структурному пути. |
| `_find_element_by_type_and_number(data, item_type, item_number, ...)` | По типу и номеру. |
| `find_item_by_revision_number(change_data, rev_number, context_root)` | `item_id` по строке ревизии. |
| `_resolve_modified_by_ids(rev_number, change_data, ...)` | Разрешение `modified_by_id` по `revision_number`. |
| `narrow_source_id_to_subpoint(coarse_id, structural_element, ...)` | Уточнение до подпункта по скорингу. |
| `_extract_paragraph_order(structural)` | Номер абзаца из структурного пути. |

#### `change_applier.py`

| Функция | Назначение |
|---------|-----------|
| `apply_grouped_changes(element, changes, valid_from, ...)` | Группа изменений: `new_redaction` → pending HTML, текстовые → ИИ (prompt 4), абзацные операции. |
| `apply_change(change, data, change_data, law_ref, ...)` | Единая точка входа: маршрутизация по `_resolved_item_id` (наименование, преамбула, корень, add, контент). |
| `_apply_change_to_appendix_prefix(...)` | Изменение префикса приложения. |
| `_apply_change_to_head(change, data, ...)` | Изменение `npa_head` (наименование документа). |
| `_apply_change_to_element_head(change, data, ...)` | Изменение наименования элемента (статья, глава, раздел, приложение). |
| `_apply_change_to_element_content(target_element, ch_type, ...)` | Контентные изменения: `delete`→закрытие ревизии, `add`→`_add_new_element`, `change`→ИИ, `new_redaction`→pending HTML. Для табличных детей (`_is_table_child`) работает с `table_fragment`. |
| `build_new_body_preserving_child_refs(old_rev, answer_html)` | Новый body из ответа ИИ с сохранением `child_ref`. |
| `parse_add_new_field(new_str)` | Парсинг `new` → `(ru_type, number_str)`. |

#### `revision_builder.py`

| Функция | Назначение |
|---------|-----------|
| `extract_child_refs_from_revision(rev)` | Извлечение `child_ref` из body. |
| `sync_parent_body_with_children(parent_item, log_callback)` | Синхронизация `child_ref` с текущими детьми. |
| `remove_empty_children(data)` | Удаление `None` из `item_children`. |
| `_merge_highlights_with_paragraph_prefix(existing_highlights, new_highlights, paragraph_num)` | Объединение подсветок с префиксом абзаца. |

### 16.5 Модуль `ui/` — Диалоговые окна

#### `manual_mapping_dialog.py` — `ManualMappingDialog`

Диалог ручного сопоставления при неоднозначности/отсутствии элемента.

| Метод | Назначение |
|-------|-----------|
| `__init__(...)` | Создание окна с деревом, полями редактирования, кнопками. |
| `destroy()` | Закрытие окна. |
| `_add_hotkeys(w)` | Ctrl+C/V/X/A. |
| `_is_item_active(item)` | Проверка активности элемента. |
| `_get_paragraphs_for_element(element)` | Preview абзацев. |
| `_populate_tree()` | Заполнение `Treeview` структурой. |
| `_add_items(items, parent, path_sofar)` | Рекурсивное добавление. |
| `_select_first_item()` | Первый выбор. |
| `_on_select(event)` | Обновление пути. |
| `_on_choose()` | Подтверждение выбора. |
| `_on_ignore()` | Игнор (None). |
| `_on_stop()` | Остановка процесса. |

#### `source_mapping_dialog.py` — `SourceMappingDialog`

Диалог выбора источника или разрешения неоднозначности.

| Метод | Назначение |
|-------|-----------|
| `__init__(...)` | Создание окна с деревом изменяющего НПА. |
| `_is_item_active(item)` | Проверка активности. |
| `_create_widgets()` | Labels + Treeview + кнопки. |
| `_populate_tree()` | Заполнение деревом, пометка дубликатов позицией. |
| `_on_choose()` | Возврат `item_id`. |
| `_on_ignore()` / `_on_cancel()` / `_on_stop()` | Отмена/остановка. |

### 16.6 Главное приложение (`processing/revision_processor.py`)

#### Класс `App(GuiBuilderMixin, AiPipelineMixin, FileOpsMixin)`

| Атрибут/Метод | Назначение |
|---------------|-----------|
| `__init__(root)` | Инициализация UI, загрузка `last_paths`/`stage_answers`, фетчинг моделей, retry callback. |
| `_ask_user_retry(error_message)` | Диалог retry/stop. |
| `_fetch_ollama_models()` | Фоновый запрос `/api/tags`. |
| `fetch_model_parameters(model_name)` | Параметры модели через `/api/show`. |
| `load_model_params()` | Загрузка параметров в `extra_options`. |
| `_validate_html_marker(html, item_type, item_number, change_info)` | Проверка ведущего маркера HTML. |
| `resolve_ambiguous_element(...)` | `SourceMappingDialog` для неоднозначности. |
| `_extract_parent_for_paragraph(structural)` | Родитель и номер абзаца. |
| `resolve_revision_manually(...)` | Ручной выбор источника. |
| `resolve_target_element_manually(change_data, stop_event)` | Ручной выбор целевого элемента. |
| `load_stage_answers()` | Загрузка ответов этапов 1-3. |
| `_normalize_text(text)` | Нормализация для сравнения. |
| `_extract_paragraphs_from_html(html)` | Абзацы с нормализацией. |
| `_split_ai_answer_into_paragraphs(ai_answer_text)` | Разбиение ответа ИИ. |
| `_assemble_html_from_ai_answer(...)` | Сборка HTML из ответа ИИ. |
| `resolve_change_manually(change, original_data, stop_event)` | `ManualMappingDialog`. |
| `check_queue()` | Проверка очереди. |
| `process_message(msg)` | Обработка: логи, вопросы, статусы. |
| `ask_appendix_title_confirmation(appendix_title)` | Диалог заголовка приложения. |
| `ask_ambiguity(candidate_text, adjacent_text)` | Диалог иерархии. |
| `processing_done(success)` | Завершение. |
| `load_resources_complete(resources, error)` | Завершение загрузки. |
| `cancel()` | Остановка. |

#### mixin `GuiBuilderMixin` (`processing/gui_builder.py`)

| Метод | Назначение |
|-------|-----------|
| `create_widgets()` | Интерфейс: поля JSON, реквизиты, модель, параметры, notebook этапов 1-3, кнопки, лог. |
| `save_stage_answers()` | Сохранение в `stage_answers.json`. |
| `reset_extra_options()` | Сброс параметров LLM. |
| `show_model_dropdown()` / `on_model_selected(model)` | Выпадающий список моделей. |
| `refresh_models()` | Обновление списка. |
| `browse_original()` | Выбор оригинального JSON, извлечение номера. |
| `browse_change()` | Выбор JSON изменений, извлечение реквизитов/даты. |
| `log(message, tag)` | Вывод в лог с цветом. |

#### mixin `AiPipelineMixin` (`processing/ai_pipeline.py`)

| Метод | Назначение |
|-------|-----------|
| `_stage1_deletion_analysis(...)` | Этап 1: `PROMPT_1` → парсинг `delete`/`null`. |
| `_stage2_dates_analysis(...)` | Этап 2: `PROMPT_2` → особые даты. |
| `_stage3_changes_extraction(...)` | Этап 3: `PROMPT_3` → изменения. Фильтрация, исправление, разбиение диапазонов. |
| `_process_element_for_changes(element, ...)` | Обработка одного элемента (elementwise mode). |
| `_stage5_rebuild(result_data, rebuild_ids, general_valid_from, change_data)` | Этап 5: перестройка через `rebuild_element_with_history` (два прохода). |
| `_group_changes(remaining_changes, ...)` | Группировка по `target_id` + `valid_from`. Разрешение путей, `наименование`, `преамбула`, `абзац`, deferred `add`. Объединение `change`. |
| `_apply_changes(groups_by_target_id, ...)` | Применение групп: head changes → body changes → delete → add. |

#### mixin `FileOpsMixin` (`processing/file_ops.py`)

| Метод | Назначение |
|-------|-----------|
| `_save_result(result_data, orig_file, change_data)` | Сохранение результата в `<orig>_izm_<change>.json`, очистка `valid_from` из `head_revisions`, обработка `PermissionError`. |

### 16.7 Промпты (`prompts/`)

| Файл | Этап | Назначение |
|------|------|-----------|
| `prompt_1.txt` | 1 | Анализ утраты силы (заключительные положения). Возвращает `delete` или `null`. |
| `prompt_2.txt` | 2 | Анализ дат вступления в силу, ретроактивные clauses. |
| `prompt_3.txt` | 3 | Извлечение изменений (465 строк). Типы: `new_redaction`, `add`, `delete`, `change`. Поля: `structural_element`, `type`, `description`, `revision_number`, `valid_from`. |
| `prompt_4.txt` | 4 | Расчёт HTML-координат. Возвращает HTML + `highlights` (`previous_edition`/`current_edition`). |

### 16.8 Паттерны и особенности

#### Отложенные изменения (pending pattern)

1. **Применение**: изменение → `_pending_*` поля + `rebuild_ids`.
2. **Перестройка**: `rebuild_element_with_history` → `NpaToJsonGenerator.process_fragment()` → `sync_structural_element_recursive()`.

#### Дублирующиеся номера (`_double_N`)

`_get_unique_item_id` добавляет суффикс. `number_revisions` фиксирует смену номера без изменения `item_id`.

#### Структурированные таблицы (`structured_table`)

Иерархия `section`/`point`/`subpoint` с `table_fragment`. При перестройке `_is_table_child=True` → работа с `<tr>`.

#### Enumeration stack

Стек перечислений для вложенных списков с `;`. Закрытие при точке.

#### Thread-safe UI

Длинные операции → фоновые потоки. Общение через `queue.Queue` + `root.after()`.

#### Retry и пользовательский ввод

- 3 попытки Ollama (30с интервал).
- Диалог retry/stop.
- Вставка ответов ИИ вручную (stage answers).
- Ручное сопоставление при неоднозначности.

---

## 17. Полный пайплайн обработки изменений

```
1. Выбор файлов и параметров:
   - Оригинальный JSON (изменяемый НПА)
   - JSON изменяющего НПА
   - Модель Ollama, temperature/top_p
   - Режим: целый документ / поэлементно

2. Этап 1 — Анализ утраты силы (_stage1_deletion_analysis)
   PROMPT_1 → Ollama → парсинг → список delete / null

3. Этап 2 — Анализ дат (_stage2_dates_analysis)
   PROMPT_2 → Ollama → особые даты, ретроактивные clauses

4. Этап 3 — Извлечение изменений (_stage3_changes_extraction)
   PROMPT_3 → Ollama → список changes
   └── Фильтрация, _correct_change_description, split_range_changes

5. Группировка (_group_changes)
   └── По target_id + valid_from
   └── Разрешение путей, ручное сопоставление, deferred add

6. Применение (_apply_changes)
   └── Для каждой группы:
       ├── apply_change()
       │   ├── new_redaction → _pending_new_redaction_html
       │   ├── add → _add_new_element() → _pending_*
       │   ├── delete → закрытие ревизии
       │   ├── change → prompt 4 → ИИ → _pending_*
       │   └── наименование/преамбула → отдельные хендлеры
       └── rebuild_ids.append(element_id)

7. Этап 5 — Перестройка (_stage5_rebuild)
   └── rebuild_element_with_history()
       ├── Извлечение _pending_*
       ├── Восстановление заголовка/префикса
       ├── NpaToJsonGenerator.process_fragment()
       ├── sync_structural_element_recursive()
       │   ├── Закрытие старых ревизий
       │   ├── Создание новых ревизий
       │   ├── Перенос детей (_transfer_structural_state)
       │   ├── number_revisions
       │   └── Объединение body + child_ref
       └── Второй проход для deferred pending

8. Сохранение (_save_result)
   └── Очистка head_revisions от valid_from
   └── <orig_num>_<orig_date>_izm_<change_num>_<change_date>.json
```
