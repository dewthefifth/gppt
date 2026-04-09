# GPPT — Push-to-Talk для Discord / Vesktop (GNOME, Wayland)

*English: [README.md](README.md)*

Расширение для **GNOME Shell 45–50**: пока клавиша **не** зажата, захват микрофона в Discord / Vesktop принудительно **заглушается** на стороне PipeWire/PulseAudio; при удержании клавиши — **размучивается**. Работает на **Wayland** за счёт чтения событий из **evdev** (`/dev/input/*`), а не через X11/Wayland-клиент.

**UUID расширения:** `discord-ptt@vimax.example.com`

---

## Как это устроено

| Слой | Роль |
|------|------|
| **Расширение** (`extension.js`) | Иконка в панели, меню «вкл/выкл PTT», запуск и остановка демона, реакция на настройки GSettings |
| **Настройки** (`prefs.js`) | Окно параметров: выбор клавиши (захват с любой клавиатуры/мыши), звук клика, мастер-переключатель |
| **Демон** (`daemon/discord_ptt.py`) | Асинхронный процесс: слушает **все** доступные устройства ввода, по коду клавиши evdev вызывает `pactl set-source-output-mute` для потоков Discord / Vesktop и родственных клиентов |

Важно:

- Демон не общается с расширением по сокету: конфиг передаётся **аргументами командной строки**; смена настроек **перезапускает** демон (с небольшой задержкой).
- Учитывается **несколько клавиатур/устройств**: микрофон заглушается только когда клавиша отпущена **на всех** устройствах, где она была нажата; при отключении USB-устройства зажатая клавиша сбрасывается в «отпущено» для этого устройства.
- Пока PTT выключен в меню, демон не запущен — размут при выходе выполняется обработчиком сигналов демона.

Подробности для разработчиков см. в [CLAUDE.md](CLAUDE.md).

---

## Требования

- **GNOME Shell** 45–50 (Wayland или X11 — демон всё равно через evdev).
- **Python 3** и пакет **python-evdev** (модуль `evdev`).
- **PipeWire** или PulseAudio с утилитами **`pactl`** и **`paplay`**.
- Доступ к устройствам ввода: пользователь в группе **`input`** или настроенные **udev**-правила (иначе демон не откроет `/dev/input/...`).

---

## Установка зависимостей (система)

**Arch / CachyOS:**

```bash
sudo pacman -S python-evdev pipewire-pulse
```

**Debian / Ubuntu:**

```bash
sudo apt install python3-evdev pipewire-pulseaudio
```

Альтернатива только для Python-модуля:

```bash
pip install --user evdev
```

---

## Подготовка и «сборка»

Отдельной компиляции нет: нужно один раз сгенерировать звуки (по желанию они уже могут лежать в `sounds/`) и скомпилировать схему GSettings.

```bash
cd /path/to/gppt

# Звуки нажатия/отпускания (один раз, только стандартная библиотека Python)
python3 daemon/generate_sounds.py

# Скомпилировать схему настроек (обязательно после изменений в schemas/*.xml)
glib-compile-schemas schemas/
```

---

## Установка расширения

```bash
cp -r /path/to/gppt ~/.local/share/gnome-shell/extensions/discord-ptt@vimax.example.com/
glib-compile-schemas ~/.local/share/gnome-shell/extensions/discord-ptt@vimax.example.com/schemas/
```

Включить расширение:

```bash
gnome-extensions enable discord-ptt@vimax.example.com
```

Либо приложение **«Расширения»** / **Extensions** → найти **Discord Push-to-Talk** → включить.

Если иконка не появилась: выйти из сеанса и войти снова (на Wayland иногда нужен полный перезапуск сессии).

---

## Подключение и первая настройка

1. **Группа `input`** (если демон пишет, что нет доступа к устройствам):

   ```bash
   sudo usermod -aG input "$USER"
   ```

   Затем **перелогиниться**.

2. В меню расширения (иконка микрофона на панели) включить **Enable PTT**.

3. **Настройки** → **Capture Key** — нажать нужную клавишу или кнопку мыши. Код сохраняется как **evdev** (внутри: GDK `hardware_keycode − 8`).

4. Запустить **Discord** или **Vesktop**, зайти в **голосовой канал** — иначе PipeWire может не создать нужный `source-output`, и демон временно не к чему применить mute.

5. По желанию включить/выключить **PTT Click Sound** в настройках.

---

## Обновление расширения

Снова скопировать каталог поверх установленного (как при установке), выполнить `glib-compile-schemas` в каталоге расширения, затем перезапустить расширение:

```bash
gnome-extensions disable discord-ptt@vimax.example.com
gnome-extensions enable discord-ptt@vimax.example.com
```

Или выключить и включить **Enable PTT** в меню индикатора — перезапустится только демон (для смены JS после обновления файлов всё равно нужен disable/enable расширения или перелогин).

---

## Отладка

Логи **GNOME Shell** (ошибки расширения, запуск демона):

```bash
journalctl -f /usr/bin/gnome-shell
```

Демон вручную (с подробным логом):

```bash
python3 ~/.local/share/gnome-shell/extensions/discord-ptt@vimax.example.com/daemon/discord_ptt.py \
  --key 58 \
  --sound-on .../sounds/ptt_on.wav \
  --sound-off .../sounds/ptt_off.wav \
  -v
```

Ключ `--key` — evdev-код (по умолчанию в настройках часто **58**, Caps Lock).

---

## Ограничения

- Определение «голосового» потока Discord идёт по свойствам PipeWire (`application.name`, путь к бинарнику и т.д.). Экзотические сборки или другие клиенты могут потребовать доработки списка в `daemon/discord_ptt.py`.
- Принудительное завершение демона **`kill -9`** не вызывает обработчик размута — лучше выключать PTT через меню или `SIGINT`/`SIGTERM`.
