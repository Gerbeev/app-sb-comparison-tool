# Промпт для агентного ИИ: устранение зависания тулы при старте в изолированном окружении

> **Как пользоваться:** скопируй весь блок «ЗАДАЧА ДЛЯ АГЕНТА» ниже целиком в агентный кодинг-ИИ (Claude Code / аналог), запущенный в корне репозитория `app-sb-comparison-tool`. Раздел «Результаты аудита» — это уже проверенные факты; агент НЕ должен их перепроверять, чтобы не жечь токены.

---

## Результаты аудита (уже проверено — НЕ повторять)

Аудит стартового пути тулы выполнен. Ключевые факты:

1. **Внешних рантайм-зависимостей у Python-пакета НЕТ.** В `pyproject.toml`: `dependencies = []`. Все импорты во всём пакете `stonebranch_graph/` — только стандартная библиотека (`argparse`, `json`, `csv`, `hashlib`, `subprocess`, `pathlib`, `importlib.resources`, `tkinter`, `msvcrt`, `termios`/`tty` и т.п.). Ни `requests`, ни `urllib`, ни `httpx`, ни `pip install` в рантайме нет.
2. **Прямых сетевых вызовов в коде нет.** Grep по `urllib|requests|http|socket|urlopen|cdn|jsdelivr|unpkg|download` даёт ноль сетевых обращений (единственное совпадение `subprocess` — это запуск PowerShell для нативного диалога, см. ниже).
3. **JS-рантайм графа (Cytoscape) уже локальный.** `stonebranch_graph/assets/cytoscape.min.js` + `cytoscape.LICENSE` бандлятся в пакет (`package-data` в `pyproject.toml`) и физически копируются рядом со сгенерированным HTML (`html_graph.py`, функции `export_graph_html` / `_copy_runtime_assets`, строки ~247–270). Сгенерированный `graph.html` ссылается на `cytoscape.min.js` **локальным относительным путём**, CDN не используется.
4. **Офлайн-сборка работает.** Прогон `python -m stonebranch_graph.cli build-stonebranch examples/stonebranch --output <tmp>` в полностью изолированном окружении отрабатывает за секунды: `nodes=26 edges=29`, генерируются `graph.html`, `graph-data.js`, `cytoscape.min.js` и пр. В итоговом HTML — **ноль** `http(s)://` ссылок.
5. **Импорт пакета быстрый** (~0.6 c, `python -X importtime`), на импорте ничего не качается и не блокируется.

**Вывод:** гипотеза «тула качает внешние зависимости при старте» в части Python-кода **не подтвердилась**. Тула не тянет пакеты из PyPI и не ходит в CDN. Причина зависания — другая (ниже), и она действительно связана с обращением наружу, но не пакетов Python, а .NET-сборок Windows.

---

## Корневая причина зависания (root cause)

Зависание возникает в подсистеме **нативных диалогов выбора файла/папки** — `stonebranch_graph/native_dialogs.py`.

Поток вызова (воспроизводится «как при старте», потому что выбор папки — первое действие пользователя в TUI):

```
run_tui() → TerminalUi.run() → пункт меню «Build …»
  → tui.py: pick_folder_setting(...)               (строки ~210/222/234)
  → tui_prompts.py: печатает "Opening system folder picker..." → pick_directory(...)
  → native_dialogs.py: _windows_folder_dialog(...)
  → subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", <script>], timeout=120)
        внутри скрипта:  Add-Type -AssemblyName System.Windows.Forms
```

Почему виснет именно в изолированной сети:

- `Add-Type -AssemblyName System.Windows.Forms` загружает подписанную .NET-сборку и запускает **on-the-fly компиляцию**. При загрузке/верификации подписанной сборки .NET Framework выполняет **проверку отзыва сертификата (Authenticode / CRL / OCSP)** — обращение к `crl.microsoft.com`, `ctldl.windowsupdate.com` и т.п.
- В окружении без интернета эти обращения не отвергаются мгновенно, а **висят до таймаута ОС** (обычно ~15–30 c на попытку, иногда дольше). Пользователь видит «зависло, будто что-то качает» — это и есть «скачивание внешней зависимости при старте», только на уровне Windows/.NET, а не Python.
- В коде стоит `timeout=120`, поэтому один вызов диалога может морозить UI **до 2 минут**, прежде чем упасть в fallback.

Дополнительные (второстепенные) точки, дающие мелкие подвисания/спавн процессов на каждом кадре:
- `tui_rendering.py: enable_windows_ansi()` → `os.system("")` (спавн `cmd.exe` на старте).
- `tui_rendering.py: clear_screen()` → `os.system("cls")` (спавн `cmd.exe` на каждой перерисовке экрана).

---

## ЗАДАЧА ДЛЯ АГЕНТА

Ты работаешь в корне репозитория `app-sb-comparison-tool`. Цель: сделать так, чтобы тула **гарантированно стартовала и работала в полностью изолированном окружении без интернета, без зависаний**. Сетевые/внешние обращения при старте и при выборе файлов/папок должны быть исключены либо иметь короткий предсказуемый таймаут с мгновенным офлайн-fallback.

Факты из раздела «Результаты аудита» считай **проверенными** — не переаудируй весь репозиторий, не запускай `pip`, не ходи в сеть. Вноси **точечные** правки только в перечисленные файлы.

### Задача 1 — устранить .NET/CRL-зависание в нативных диалогах (главный фикс)
Файл: `stonebranch_graph/native_dialogs.py`

1. В функции `_run_powershell_dialog(...)` уменьши `timeout` со `120` до `20` секунд, чтобы даже при худшем сценарии UI не морозило дольше 20 c и он падал в tkinter-fallback.
2. Отключи сетевую проверку отзыва сертификатов у дочернего PowerShell/.NET-процесса. Реализуй оба уровня защиты:
   - Передавай в `subprocess.run(...)` параметр `env`, скопировав `os.environ` и добавив:
     - `DOTNET_CLI_TELEMETRY_OPTOUT=1`
     - `POWERSHELL_TELEMETRY_OPTOUT=1`
     - `DOTNET_GENERATE_ASPNET_CERTIFICATE=false`
   - В начало PowerShell-скрипта (в обеих функциях `_windows_folder_dialog` и `_windows_file_dialog`, до `Add-Type`) добавь строки, отключающие онлайн-проверку издателя/отзыва:
     ```powershell
     [System.Net.ServicePointManager]::CheckCertificateRevocationList = $false
     $ErrorActionPreference = 'Stop'
     ```
3. Добавь возможность полностью выключить нативный PowerShell-диалог через переменную окружения (для строго изолированных стендов): если задана `SB_TOOL_NO_NATIVE_DIALOG=1`, функции `pick_directory` / `pick_file` должны **сразу** уходить в `_tk_*`-fallback (или в ручной текстовый ввод пути), минуя PowerShell целиком.

### Задача 2 — сделать выбор пути надёжным без GUI
Файл: `stonebranch_graph/tui_prompts.py` (функции `pick_folder_setting`, `pick_file_setting`)

- Если нативный диалог вернул `None` (отменён/недоступен/выключен через env), не оставляй пользователя без выбора: добавь **текстовый fallback-ввод пути** через `input(...)` с валидацией существования (папки — через `Path.is_dir()`, файла — через `Path.is_file()`), и с возможностью оставить текущее значение (для `allow_empty=True`). Сообщение «Opening system folder picker...» показывай только когда GUI реально будет вызываться.

### Задача 3 — убрать лишние спавны shell на старте/перерисовке
Файл: `stonebranch_graph/tui_rendering.py`

- `enable_windows_ansi()`: замени `os.system("")` на включение ANSI через WinAPI без спавна процесса — вызовом `ctypes.windll.kernel32.SetConsoleMode(...)` с флагом `ENABLE_VIRTUAL_TERMINAL_PROCESSING (0x0004)` для хэндла STDOUT; оберни в `try/except` (не Windows / нет прав → тихо пропустить).
- `clear_screen()`: замени `os.system("cls"/"clear")` на печать ANSI-escape `"\033[2J\033[H"` в `sys.stdout` (без спавна `cmd.exe`); сохранить текущее условие «только если `TERM` задан и вывод — tty».

### Задача 4 — застраховать пакет от отсутствующего README при сборке
Файл: `pyproject.toml` (+ корень репозитория)

- `pyproject.toml` объявляет `readme = "README.md"`, но файла `README.md` в репозитории нет. Это ломает `pip install .` / сборку wheel в изолированном окружении (частая причина падения «установки» на офлайн-стенде). Создай минимальный `README.md` (название, назначение, команды запуска: `python -m stonebranch_graph.cli tui` и `run_terminal_ui.cmd`, требование Python ≥ 3.11, явное указание «работает офлайн, интернет не требуется»).

### Задача 5 — верификация (обязательно, один прогон, офлайн)
Проверь правки без выхода в сеть:

1. `python -m stonebranch_graph.cli --help` — код возврата 0, мгновенно.
2. `python -m stonebranch_graph.cli build-stonebranch examples/stonebranch --output <tmp>` — код 0, в выводе `nodes=26 edges=29`.
3. Проверь, что в сгенерированном HTML нет удалённых ссылок: `grep -rE "https?://" <tmp>/*.html` — должно быть пусто.
4. `python -c "import ast,sys; ast.parse(open('stonebranch_graph/native_dialogs.py').read())"` (и то же для `tui_rendering.py`, `tui_prompts.py`) — синтаксис валиден.
5. Не запускай интерактивный `tui` в CI (он ждёт stdin) — достаточно проверить импортируемость: `python -c "import stonebranch_graph.tui, stonebranch_graph.native_dialogs, stonebranch_graph.tui_rendering"`.

### Критерии приёмки
- При старте и при первом выборе папки тула не обращается в сеть и не морозит UI дольше ~20 c даже без интернета.
- Есть рабочий путь выбора файла/папки без GUI (env-флаг + текстовый fallback).
- Офлайн-сборка графа и генерация self-contained HTML по-прежнему работают.
- `pip install .` не падает из-за отсутствующего README.

---

## Рамки кост-эффективности агента (важно — соблюдать)

Чтобы агент не сжёг лишние токены/шаги:

- **Не переоткрывай весь репозиторий.** Трогай только 5 файлов: `native_dialogs.py`, `tui_prompts.py`, `tui_rendering.py`, `pyproject.toml`, новый `README.md`. Раздел «Результаты аудита» уже содержит проверенные факты — не повторяй grep/аудит всего кода.
- **Никакой сети и pip.** Не запускай `pip install`, не обновляй зависимости, не ходи в интернет — окружение изолированное, любые сетевые вызовы = зависание.
- **Минимальный дифф.** Точечные правки перечисленных функций, без рефакторинга архитектуры, без переименований, без переформатирования файлов целиком (иначе раздуется дифф и ревью).
- **Один цикл верификации.** Выполни блок «Задача 5» ровно один раз в конце; не гоняй полную test-suite повторно после каждой мелкой правки.
- **Не читай `__pycache__`, `.git`, бинарники и `assets/*.js`** — там нет ничего для правки.
- **Не трогай парсеры/доменную логику** (`parsers/`, `core.py`, `compare.py`, `skeleton*`, `html_graph.py`) — они офлайн-чистые, изменения там вне задачи.
- Если правка выходит за рамки 5 файлов — **остановись и сообщи**, не расширяй скоуп самостоятельно.

---

## Приложение: краткая карта задействованных файлов и строк

| Файл | Что там | Действие |
|---|---|---|
| `pyproject.toml` | `dependencies = []`, `readme = "README.md"`, `package-data` cytoscape | Задача 4 (README) |
| `stonebranch_graph/native_dialogs.py` | PowerShell `Add-Type WinForms`, `subprocess.run(timeout=120)` | Задача 1 (главный фикс) |
| `stonebranch_graph/tui_prompts.py` | `pick_folder_setting` / `pick_file_setting` → `pick_directory` | Задача 2 (текстовый fallback) |
| `stonebranch_graph/tui_rendering.py` | `enable_windows_ansi()`→`os.system("")`, `clear_screen()`→`os.system("cls")` | Задача 3 (без спавна shell) |
| `stonebranch_graph/assets/cytoscape.min.js` | локальный JS-рантайм графа | не трогать (уже офлайн) |
