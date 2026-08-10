import json
import os
import requests
import base64
import csv
import io
import time
from datetime import datetime
from io import BytesIO
from PIL import Image
from flask import Flask, request, jsonify

app = Flask(__name__)

GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
DATA_REPO = 'kodpin/OneMinute-data'        # ← замените kodpin на свой логин при необходимости
SITE_REPO = os.environ.get('GITHUB_REPOSITORY', 'kodpin/OneMinute')
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
ADMIN_IDS = [int(id.strip()) for id in os.environ.get('ADMIN_IDS', '').split(',') if id.strip()]

user_states = {}

# ---------- Telegram helpers ----------
def send_message(chat_id, text, reply_markup=None):
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    requests.post(url, json=payload)

def send_photo(chat_id, photo_url, caption=None, reply_markup=None):
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto'
    payload = {'chat_id': chat_id, 'photo': photo_url}
    if caption:
        payload['caption'] = caption
        payload['parse_mode'] = 'HTML'
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    requests.post(url, json=payload)

def send_document(chat_id, file_data, filename):
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument'
    files = {'document': (filename, file_data, 'text/csv')}
    data = {'chat_id': chat_id}
    requests.post(url, files=files, data=data)

def answer_callback(callback_id, text=None):
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery'
    payload = {'callback_query_id': callback_id}
    if text:
        payload['text'] = text
    requests.post(url, json=payload)

# ---------- GitHub API ----------
def get_data():
    owner, repo = DATA_REPO.split('/')
    url = f'https://api.github.com/repos/{owner}/{repo}/contents/products.json'
    headers = {'Authorization': f'token {GITHUB_TOKEN}'}
    resp = requests.get(url, headers=headers)
    if resp.status_code == 200:
        data = resp.json()
        content = base64.b64decode(data['content']).decode('utf-8')
        return json.loads(content), data['sha']
    return None, None

def save_data(data, sha=None):
    owner, repo = DATA_REPO.split('/')
    url = f'https://api.github.com/repos/{owner}/{repo}/contents/products.json'
    headers = {'Authorization': f'token {GITHUB_TOKEN}'}
    content = json.dumps(data, ensure_ascii=False, indent=2)
    encoded = base64.b64encode(content.encode('utf-8')).decode('utf-8')
    payload = {'message': 'Update via bot', 'content': encoded}
    if sha:
        payload['sha'] = sha
    resp = requests.put(url, headers=headers, json=payload)
    return resp

def upload_image_to_site(image_bytes, filename):
    """Загружает сжатое фото в SITE_REPO/images/ и возвращает публичную ссылку"""
    owner, repo = SITE_REPO.split('/')
    path = f'images/{filename}'
    url = f'https://api.github.com/repos/{owner}/{repo}/contents/{path}'
    headers = {'Authorization': f'token {GITHUB_TOKEN}'}
    encoded_content = base64.b64encode(image_bytes).decode('utf-8')
    payload = {'message': f'Upload {filename}', 'content': encoded_content}
    for attempt in range(2):
        resp = requests.put(url, headers=headers, json=payload)
        if resp.status_code in [200, 201]:
            return f'https://{owner}.github.io/{repo}/{path}'
        time.sleep(1)
    return None

def compress_image(image_bytes, max_width=800):
    try:
        img = Image.open(BytesIO(image_bytes))
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        width, height = img.size
        if width > max_width:
            new_height = int(height * max_width / width)
            img = img.resize((max_width, new_height), Image.LANCZOS)
        output = BytesIO()
        img.save(output, format='JPEG', quality=85, optimize=True)
        return output.getvalue()
    except Exception:
        return image_bytes

# ---------- Клавиатуры ----------
def main_reply_kb():
    return {
        "keyboard": [
            ["➕ Добавить товар", "📋 Список товаров"],
            ["✏️ Редактировать товар", "⚙️ Настройки"],
            ["🏠 Главное меню"]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

def cancel_kb():
    return {"inline_keyboard": [[{"text": "❌ Отмена", "callback_data": "cancel_add"}]]}

def category_kb():
    """Динамически формирует клавиатуру категорий из настроек"""
    data, _ = get_data()
    cats = data.get('settings', {}).get('categories', ["tactical", "travel", "running", "diving"])
    # Группируем по две в строке
    buttons = []
    row = []
    for cat in cats:
        row.append({"text": cat.capitalize(), "callback_data": f"cat_{cat}"})
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([{"text": "❌ Отмена", "callback_data": "cancel_add"}])
    return {"inline_keyboard": buttons}

def photo_step_kb():
    return {"inline_keyboard": [
        [{"text": "✅ Завершить", "callback_data": "confirm_product"}],
        [{"text": "❌ Отмена", "callback_data": "cancel_add"}]
    ]}

def edit_photo_step_kb():
    return {"inline_keyboard": [
        [{"text": "✅ Завершить", "callback_data": "confirm_edit_photo"}],
        [{"text": "❌ Отмена", "callback_data": "cancel_add"}]
    ]}

def settings_kb():
    return {"inline_keyboard": [
        [{"text": "📝 Изменить ИП", "callback_data": "edit_ip"}],
        [{"text": "📱 Изменить QR-код", "callback_data": "edit_qr"}],
        [{"text": "🔗 Изменить ссылку оплаты", "callback_data": "edit_link"}],
        [{"text": "👤 Изменить менеджера", "callback_data": "edit_manager"}],
        [{"text": "🗂 Управление категориями", "callback_data": "manage_categories"}],
        [{"text": "🔙 Назад", "callback_data": "main_menu"}]
    ]}

def products_list_kb(products):
    keyboard = [[{"text": f"❌ {p['name']} - {p['price']:,}₽", "callback_data": f"delete_{p['id']}"}] for p in products]
    keyboard.append([{"text": "🔙 Назад", "callback_data": "main_menu"}])
    return {"inline_keyboard": keyboard}

# ---------- Главный обработчик ----------
def process_update(update):
    if 'callback_query' in update:
        cb = update['callback_query']
        chat_id = cb['message']['chat']['id']
        data = cb['data']
        if chat_id not in ADMIN_IDS:
            answer_callback(cb['id'], 'Нет доступа')
            return
        answer_callback(cb['id'])
        if data == 'main_menu': send_main_menu(chat_id)
        elif data == 'add_product': start_add_product(chat_id)
        elif data == 'cancel_add': cancel_action(chat_id)
        elif data == 'list_products': show_products(chat_id)
        elif data == 'settings_menu': show_settings(chat_id)
        elif data.startswith('cat_'): set_category(chat_id, data.replace('cat_', ''))
        elif data == 'confirm_product': save_product(chat_id)
        elif data == 'confirm_edit_photo': confirm_edit_photo(chat_id)
        elif data.startswith('delete_'): delete_product(chat_id, int(data.replace('delete_', '')))
        elif data == 'edit_ip': start_edit(chat_id, 'ip_info', '📝 Введите информацию об ИП:')
        elif data == 'edit_qr': start_edit(chat_id, 'payment_qr', '📱 Отправьте ссылку на QR-код:')
        elif data == 'edit_link': start_edit(chat_id, 'payment_link', '🔗 Отправьте ссылку для оплаты:')
        elif data == 'edit_manager': start_edit(chat_id, 'manager_telegram', '👤 Отправьте ссылку на менеджера:')
        elif data == 'export_csv': export_csv(chat_id)
        elif data == 'import_csv': prompt_import(chat_id)
        elif data == 'mass_price': start_mass_price(chat_id)
        elif data.startswith('massprice_'):
            cat = data.replace('massprice_', '')
            ask_mass_price_percent(chat_id, cat)
        elif data.startswith('masspct_'):
            pct = float(data.replace('masspct_', ''))
            apply_mass_price(chat_id, pct)
        elif data == 'edit_product': start_edit_product(chat_id)
        elif data.startswith('edit_') and data[5:].isdigit():
            pid = int(data.split('_')[1])
            start_edit_field(chat_id, pid)
        elif data == 'edit_product_back': start_edit_product(chat_id)
        elif data.startswith('edit_field_'):
            field = data.replace('edit_field_', '')
            if chat_id in user_states and user_states[chat_id].get('action') == 'edit_product':
                handle_edit_field(chat_id, field)
            else:
                send_message(chat_id, '⚠️ Сессия редактирования устарела. Начните заново.')
        elif data == 'manage_categories': manage_categories(chat_id)
        elif data == 'add_category': add_category_prompt(chat_id)
        elif data == 'delete_category': delete_category_prompt(chat_id)
        elif data.startswith('delcat_'):
            cat_to_del = data.replace('delcat_', '')
            delete_category(chat_id, cat_to_del)
        return

    if 'message' not in update: return
    msg = update['message']
    chat_id = msg['chat']['id']
    if chat_id not in ADMIN_IDS: return

    if 'document' in msg and not msg['document'].get('mime_type', '').startswith('image/'):
        handle_csv_import(chat_id, msg['document'])
        return

    # Фото (при добавлении или редактировании)
    if 'photo' in msg or (msg.get('document') and msg['document'].get('mime_type', '').startswith('image/')):
        state = user_states.get(chat_id)
        if state:
            if state.get('action') == 'edit_product_photo':
                handle_edit_photo(chat_id, msg)
            elif state.get('step') == 'photo':
                handle_photo(chat_id, msg)
            else:
                send_message(chat_id, '📸 Сейчас фото не ожидается.')
        else:
            send_message(chat_id, '📸 Начните добавление или редактирование товара.')
        return

    text = msg.get('text', '')
    state = user_states.get(chat_id)

    # Активные состояния
    if state:
        if state.get('action') == 'waiting_text':
            handle_text_step(chat_id, text)
            return
        elif state.get('action') == 'edit_product' and state.get('step') == 'edit_value':
            save_edit(chat_id, text)
            return
        elif state.get('action') == 'add_category':
            save_new_category(chat_id, text)
            return
        elif state.get('action') == 'mass_price_percent':
            try:
                pct = float(text.replace(',', '.'))
                apply_mass_price(chat_id, pct)
            except:
                send_message(chat_id, '❌ Введите число (например, 10 или -5).')
            return

    # Кнопки меню
    if text == '/start' or text == '🏠 Главное меню':
        send_main_menu(chat_id)
    elif text == '➕ Добавить товар':
        start_add_product(chat_id)
    elif text == '📋 Список товаров':
        show_products(chat_id)
    elif text == '✏️ Редактировать товар':
        start_edit_product(chat_id)
    elif text == '⚙️ Настройки':
        show_settings(chat_id)
    else:
        send_main_menu(chat_id)

def send_main_menu(chat_id):
    send_message(chat_id, '🎯 <b>OneMinute — Панель управления</b>', main_reply_kb())

# ---------- Добавление товара ----------
def start_add_product(chat_id):
    user_states[chat_id] = {'action': 'waiting_text', 'step': 'name', 'data': {}, 'photos': []}
    send_message(chat_id, '➕ <b>Шаг 1/5:</b> Введите <b>название</b> товара:', cancel_kb())

def handle_text_step(chat_id, text):
    state = user_states.get(chat_id)
    if not state: return
    step = state['step']
    if step == 'name':
        state['data']['name'] = text
        state['step'] = 'price'
        send_message(chat_id, f'✅ <b>{text}</b>\n\n💰 <b>Шаг 2/5:</b> Введите <b>цену</b> (только цифры):', cancel_kb())
    elif step == 'price':
        try:
            price = int(text.replace(' ', '').replace('₽', '').replace(',', ''))
            state['data']['price'] = price
            state['step'] = 'description'
            send_message(chat_id, f'✅ <b>{price:,} ₽</b>\n\n📝 <b>Шаг 3/5:</b> Введите <b>описание</b>:', cancel_kb())
        except:
            send_message(chat_id, '❌ Введите цену цифрами!')
    elif step == 'description':
        state['data']['description'] = text
        state['step'] = 'category'
        send_message(chat_id, '🏷 <b>Шаг 4/5:</b> Выберите <b>категорию</b>:', category_kb())
    elif step == 'edit_setting':
        save_setting(chat_id, text)

def set_category(chat_id, category):
    state = user_states.get(chat_id)
    if not state: return
    state['data']['category'] = category
    state['step'] = 'photo'
    state['action'] = 'waiting_photo'
    send_message(chat_id, f'✅ Категория: <b>{category}</b>\n\n📸 <b>Шаг 5/5:</b> Отправьте <b>фото</b> (можно несколько по одному).\nКогда закончите, нажмите <b>✅ Завершить</b>.', photo_step_kb())

def handle_photo(chat_id, message):
    state = user_states.get(chat_id)
    if not state: return
    try:
        if 'photo' in message:
            file_id = message['photo'][-1]['file_id']
        else:
            file_id = message['document']['file_id']
        get_url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}'
        resp = requests.get(get_url).json()
        if not resp.get('ok'):
            send_message(chat_id, '❌ Не удалось получить файл от Telegram.')
            return
        file_path = resp['result']['file_path']
        img_url = f'https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}'
        img_data = requests.get(img_url).content

        compressed = compress_image(img_data, max_width=800)
        filename = f"watch_{int(time.time())}.jpg"
        github_url = upload_image_to_site(compressed, filename)

        if github_url:
            state.setdefault('photos', []).append(github_url)
            send_message(chat_id, f'✅ Фото добавлено ({len(state["photos"])} шт.).\nОтправьте ещё или нажмите <b>✅ Завершить</b>.', photo_step_kb())
        else:
            send_message(chat_id, '❌ Не удалось загрузить фото в репозиторий. Проверьте GITHUB_TOKEN или папку images.', photo_step_kb())
    except Exception as e:
        send_message(chat_id, f'❌ Ошибка обработки фото: {e}')

def save_product(chat_id):
    state = user_states.get(chat_id)
    if not state: return
    photos = state.get('photos', [])
    if not photos:
        send_message(chat_id, '❌ Нужно хотя бы одно фото.')
        return
    try:
        data, sha = get_data()
        if data is None:
            data = {"products": [], "settings": {}}
            sha = None
        if 'products' not in data: data['products'] = []
        new_id = max([p['id'] for p in data['products']], default=0) + 1
        new_product = {
            'id': new_id,
            'name': state['data']['name'],
            'price': state['data']['price'],
            'description': state['data']['description'],
            'image': photos if len(photos) > 1 else photos[0],
            'category': state['data']['category'],
            'discount_percent': 0,
            'discount_end': ''
        }
        data['products'].append(new_product)
        resp = save_data(data, sha)
        if resp.status_code in [200, 201]:
            send_message(chat_id, f'✅ Товар <b>{new_product["name"]}</b> добавлен!\nID: {new_id}\nЦена: {new_product["price"]:,} ₽\nФото: {len(photos)} шт.', main_reply_kb())
        else:
            send_message(chat_id, f'❌ Ошибка сохранения!\nКод: {resp.status_code}\nОтвет: {resp.text[:300]}')
    except Exception as e:
        send_message(chat_id, f'❌ Ошибка: {e}')
    finally:
        if chat_id in user_states: del user_states[chat_id]

# ---------- Редактирование фото (новое) ----------
def handle_edit_field(chat_id, field):
    state = user_states.get(chat_id)
    if not state: return
    if field == 'image':
        # Переход в режим загрузки фото
        state['action'] = 'edit_product_photo'
        state['edit_photos'] = []
        send_message(chat_id, '📸 Отправьте новое фото (можно несколько). Нажмите <b>✅ Завершить</b>, когда закончите.', edit_photo_step_kb())
        return
    state['edit_field'] = field
    prompts = {
        'name': '📱 Введите новое название:',
        'price': '💰 Введите новую цену (цифры):',
        'description': '📝 Введите новое описание:',
        'discount_percent': '🏷 Введите процент скидки (0-100):',
        'discount_end': '📅 Введите дату окончания скидки в формате ГГГГ-ММ-ДД (например, 2026-12-31):',
        'category': None
    }
    if field == 'category':
        send_message(chat_id, '🏷 Выберите новую категорию:', category_kb())
        state['step'] = 'edit_category'
        return
    send_message(chat_id, prompts.get(field, 'Введите значение:'), cancel_kb())
    state['step'] = 'edit_value'

def handle_edit_photo(chat_id, message):
    state = user_states.get(chat_id)
    if not state: return
    try:
        if 'photo' in message:
            file_id = message['photo'][-1]['file_id']
        else:
            file_id = message['document']['file_id']
        get_url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}'
        resp = requests.get(get_url).json()
        if not resp.get('ok'):
            send_message(chat_id, '❌ Не удалось получить файл от Telegram.')
            return
        file_path = resp['result']['file_path']
        img_url = f'https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}'
        img_data = requests.get(img_url).content

        compressed = compress_image(img_data, max_width=800)
        filename = f"watch_{int(time.time())}.jpg"
        github_url = upload_image_to_site(compressed, filename)

        if github_url:
            state.setdefault('edit_photos', []).append(github_url)
            send_message(chat_id, f'✅ Фото добавлено ({len(state["edit_photos"])} шт.).\nОтправьте ещё или нажмите <b>✅ Завершить</b>.', edit_photo_step_kb())
        else:
            send_message(chat_id, '❌ Не удалось загрузить фото в репозиторий. Проверьте GITHUB_TOKEN или папку images.', edit_photo_step_kb())
    except Exception as e:
        send_message(chat_id, f'❌ Ошибка обработки фото: {e}')

def confirm_edit_photo(chat_id):
    state = user_states.get(chat_id)
    if not state: return
    photos = state.get('edit_photos', [])
    if not photos:
        send_message(chat_id, '❌ Нужно хотя бы одно фото.')
        return
    # Применяем как изменение поля image
    image_value = photos if len(photos) > 1 else photos[0]
    # Восстанавливаем состояние редактирования
    state['action'] = 'edit_product'
    state['edit_field'] = 'image'
    # Вызываем стандартное сохранение редактирования
    save_edit(chat_id, image_value)
    # Удаляем временные данные
    state.pop('edit_photos', None)

# ---------- Список товаров и удаление ----------
def show_products(chat_id):
    data, _ = get_data()
    if not data or not data.get('products'):
        send_message(chat_id, '📋 Товаров пока нет.', main_reply_kb())
        return
    prods = data['products']
    text = f'📋 <b>Товары ({len(prods)}):</b>\n\n'
    for p in prods:
        text += f"🆔 {p['id']} | {p['name']} | {p['price']:,}₽\n"
    send_message(chat_id, text, products_list_kb(prods))

def delete_product(chat_id, pid):
    data, sha = get_data()
    if not data: return
    product = next((p for p in data['products'] if p['id'] == pid), None)
    if not product:
        send_message(chat_id, '❌ Товар не найден')
        return
    data['products'] = [p for p in data['products'] if p['id'] != pid]
    resp = save_data(data, sha)
    if resp.status_code in [200, 201]:
        send_message(chat_id, f'✅ <b>{product["name"]}</b> удалён!', main_reply_kb())
        show_products(chat_id)
    else:
        send_message(chat_id, f'❌ Ошибка удаления!\nКод: {resp.status_code}\nОтвет: {resp.text[:300]}')

# ---------- Настройки ----------
def show_settings(chat_id):
    data, _ = get_data()
    s = data.get('settings', {}) if data else {}
    text = f"⚙️ <b>Настройки</b>\n\n📝 ИП: {s.get('ip_info','-')[:100]}\n📱 QR: {s.get('payment_qr','-')[:50]}\n🔗 Ссылка: {s.get('payment_link','-')[:50]}\n👤 Менеджер: {s.get('manager_telegram','-')[:50]}"
    send_message(chat_id, text, settings_kb())

def start_edit(chat_id, key, prompt):
    user_states[chat_id] = {'action': 'waiting_text', 'step': 'edit_setting', 'setting_key': key}
    send_message(chat_id, prompt, cancel_kb())

def save_setting(chat_id, value):
    state = user_states.get(chat_id)
    if not state: return
    key = state['setting_key']
    data, sha = get_data()
    if not data: return
    if 'settings' not in data: data['settings'] = {}
    data['settings'][key] = value
    resp = save_data(data, sha)
    if resp.status_code in [200, 201]:
        send_message(chat_id, '✅ Настройка обновлена!', main_reply_kb())
    else:
        send_message(chat_id, f'❌ Ошибка сохранения настройки!\nКод: {resp.status_code}\nОтвет: {resp.text[:300]}')
    if chat_id in user_states: del user_states[chat_id]

def cancel_action(chat_id):
    if chat_id in user_states: del user_states[chat_id]
    send_message(chat_id, '❌ Отменено', main_reply_kb())

# ---------- Редактирование товара (остальные поля) ----------
def start_edit_product(chat_id):
    data, _ = get_data()
    if not data or not data.get('products'):
        send_message(chat_id, '📋 Нет товаров для редактирования.', main_reply_kb())
        return
    prods = data['products']
    keyboard = [[{"text": f"✏️ {p['name']} (ID {p['id']})", "callback_data": f"edit_{p['id']}"}] for p in prods]
    keyboard.append([{"text": "🔙 Назад", "callback_data": "main_menu"}])
    send_message(chat_id, '✏️ Выберите товар для редактирования:', {"inline_keyboard": keyboard})

def start_edit_field(chat_id, product_id):
    product = get_product_by_id(product_id)
    if not product:
        send_message(chat_id, '❌ Товар не найден.')
        return
    user_states[chat_id] = {'action': 'edit_product', 'product_id': product_id, 'product': product}
    show_edit_menu(chat_id, product)

def show_edit_menu(chat_id, product):
    keyboard = [
        [{"text": "📱 Название", "callback_data": "edit_field_name"}],
        [{"text": "💰 Цена", "callback_data": "edit_field_price"}],
        [{"text": "📝 Описание", "callback_data": "edit_field_description"}],
        [{"text": "🏷 Категория", "callback_data": "edit_field_category"}],
        [{"text": "🖼 Фото", "callback_data": "edit_field_image"}],
        [{"text": "🏷 Скидка (%)", "callback_data": "edit_field_discount_percent"}],
        [{"text": "📅 Окончание скидки", "callback_data": "edit_field_discount_end"}],
        [{"text": "🔙 Назад", "callback_data": "edit_product"}]
    ]
    send_message(chat_id, f'✏️ Редактирование: <b>{product["name"]}</b>\nВыберите поле:', {"inline_keyboard": keyboard})

def save_edit(chat_id, new_value):
    state = user_states.get(chat_id)
    if not state: return
    pid = state['product_id']
    field = state.get('edit_field')
    if not field:
        send_message(chat_id, '❌ Ошибка: не выбрано поле.')
        return
    data, sha = get_data()
    if not data: return
    product = next((p for p in data['products'] if p['id'] == pid), None)
    if not product: return
    if field == 'price':
        try:
            new_value = int(new_value.replace(' ', '').replace('₽', ''))
        except:
            send_message(chat_id, '❌ Неверная цена.')
            return
    elif field == 'image':
        # new_value уже список или строка
        pass
    elif field == 'discount_percent':
        try:
            new_value = int(new_value)
            if new_value < 0 or new_value > 100:
                raise ValueError
        except:
            send_message(chat_id, '❌ Процент скидки должен быть числом от 0 до 100.')
            return
    elif field == 'discount_end':
        try:
            datetime.strptime(new_value, '%Y-%m-%d')
        except ValueError:
            send_message(chat_id, '❌ Неверный формат даты. Используйте ГГГГ-ММ-ДД.')
            return
    product[field] = new_value
    if save_data(data, sha):
        send_message(chat_id, f'✅ Поле <b>{field}</b> обновлено!')
        show_edit_menu(chat_id, product)
    else:
        send_message(chat_id, '❌ Ошибка сохранения.')
        show_edit_menu(chat_id, product)

def get_product_by_id(pid):
    data, _ = get_data()
    if data:
        return next((p for p in data['products'] if p['id'] == pid), None)
    return None

# ---------- Экспорт CSV ----------
def export_csv(chat_id):
    data, _ = get_data()
    if not data or not data.get('products'):
        send_message(chat_id, '📋 Нет товаров для экспорта.')
        return
    prods = data['products']
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['id', 'name', 'price', 'description', 'image', 'category', 'discount_percent', 'discount_end'])
    for p in prods:
        writer.writerow([
            p.get('id', ''),
            p.get('name', ''),
            p.get('price', ''),
            p.get('description', ''),
            p.get('image', ''),
            p.get('category', ''),
            p.get('discount_percent', 0),
            p.get('discount_end', '')
        ])
    csv_content = output.getvalue()
    send_document(chat_id, csv_content.encode('utf-8-sig'), 'products.csv')
    output.close()

# ---------- Импорт CSV ----------
def prompt_import(chat_id):
    send_message(chat_id, '📤 Отправьте CSV-файл с товарами.')

def handle_csv_import(chat_id, document):
    file_id = document['file_id']
    get_url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}'
    resp = requests.get(get_url).json()
    if not resp.get('ok'):
        send_message(chat_id, '❌ Ошибка получения файла.')
        return
    file_path = resp['result']['file_path']
    file_url = f'https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}'
    file_resp = requests.get(file_url)
    if file_resp.status_code != 200:
        send_message(chat_id, '❌ Не удалось скачать файл.')
        return
    try:
        content = file_resp.content.decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(content))
        data, sha = get_data()
        if data is None:
            data = {"products": [], "settings": {}}
            sha = None
        if 'products' not in data: data['products'] = []
        updated = added = 0
        for row in reader:
            pid = row.get('id', '').strip()
            name = row.get('name', '').strip()
            price = row.get('price', '').strip()
            description = row.get('description', '').strip()
            image = row.get('image', '').strip()
            category = row.get('category', '').strip()
            discount_percent = row.get('discount_percent', '0').strip()
            discount_end = row.get('discount_end', '').strip()
            if not name or not price: continue
            price = int(price)
            discount_percent = int(discount_percent) if discount_percent else 0
            if pid and pid.isdigit():
                existing = next((p for p in data['products'] if p['id'] == int(pid)), None)
                if existing:
                    existing.update({
                        'name': name, 'price': price, 'description': description,
                        'image': image, 'category': category,
                        'discount_percent': discount_percent, 'discount_end': discount_end
                    })
                    updated += 1
                    continue
            new_id = max([p['id'] for p in data['products']], default=0) + 1
            data['products'].append({
                'id': new_id, 'name': name, 'price': price, 'description': description,
                'image': image, 'category': category,
                'discount_percent': discount_percent, 'discount_end': discount_end
            })
            added += 1
        if save_data(data, sha):
            send_message(chat_id, f'✅ Импорт завершён! Добавлено: {added}, обновлено: {updated}.')
        else:
            send_message(chat_id, '❌ Ошибка сохранения.')
    except Exception as e:
        send_message(chat_id, f'❌ Ошибка обработки CSV: {e}')

# ---------- Массовое изменение цен ----------
def start_mass_price(chat_id):
    data, _ = get_data()
    cats = data.get('settings', {}).get('categories', ["tactical", "travel", "running", "diving"])
    buttons = [[{"text": "Все товары", "callback_data": "massprice_all"}]]
    row = []
    for cat in cats:
        row.append({"text": cat.capitalize(), "callback_data": f"massprice_{cat}"})
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([{"text": "🔙 Отмена", "callback_data": "main_menu"}])
    send_message(chat_id, '📊 <b>Выберите категорию товаров</b> для изменения цен:', {"inline_keyboard": buttons})

def ask_mass_price_percent(chat_id, category):
    user_states[chat_id] = {'action': 'mass_price_percent', 'mass_price_category': category}
    send_message(chat_id, '📊 Введите процент изменения (например, <b>10</b> для повышения на 10%, <b>-5</b> для понижения на 5%):', cancel_kb())

def apply_mass_price(chat_id, percent):
    state = user_states.get(chat_id)
    if not state: return
    cat = state.get('mass_price_category')
    data, sha = get_data()
    if not data: return
    if 'products' not in data: data['products'] = []
    count = 0
    for p in data['products']:
        if cat == 'all' or p.get('category') == cat:
            p['price'] = max(0, int(p['price'] * (1 + percent / 100)))
            count += 1
    if count > 0:
        if save_data(data, sha):
            word = 'повышены' if percent > 0 else 'понижены'
            send_message(chat_id, f'✅ Цены {word} на {abs(percent)}% для {count} товаров.', main_reply_kb())
        else:
            send_message(chat_id, '❌ Ошибка сохранения.')
    else:
        send_message(chat_id, 'ℹ️ Нет товаров в выбранной категории.')
    if chat_id in user_states: del user_states[chat_id]

# ---------- Управление категориями ----------
def manage_categories(chat_id):
    data, _ = get_data()
    cats = data.get('settings', {}).get('categories', ["tactical", "travel", "running", "diving"])
    text = "🗂 <b>Текущие категории:</b>\n" + "\n".join([f"• {c}" for c in cats])
    keyboard = [
        [{"text": "➕ Добавить", "callback_data": "add_category"}],
        [{"text": "❌ Удалить", "callback_data": "delete_category"}],
        [{"text": "🔙 Назад", "callback_data": "settings_menu"}]
    ]
    send_message(chat_id, text, {"inline_keyboard": keyboard})

def add_category_prompt(chat_id):
    user_states[chat_id] = {'action': 'add_category'}
    send_message(chat_id, '🗂 Введите название категории (латиницей, без пробелов):', cancel_kb())

def save_new_category(chat_id, name):
    name = name.strip().lower()
    data, sha = get_data()
    if not data: return
    cats = data.setdefault('settings', {}).setdefault('categories', ["tactical", "travel", "running", "diving"])
    if name in cats:
        send_message(chat_id, '❌ Такая категория уже есть.')
    else:
        cats.append(name)
        if save_data(data, sha):
            send_message(chat_id, f'✅ Категория <b>{name}</b> добавлена!', main_reply_kb())
        else:
            send_message(chat_id, '❌ Ошибка сохранения.')
    del user_states[chat_id]

def delete_category_prompt(chat_id):
    data, _ = get_data()
    cats = data.get('settings', {}).get('categories', [])
    keyboard = [[{"text": f"❌ {c}", "callback_data": f"delcat_{c}"}] for c in cats]
    keyboard.append([{"text": "🔙 Назад", "callback_data": "manage_categories"}])
    send_message(chat_id, '❌ Выберите категорию для удаления:', {"inline_keyboard": keyboard})

def delete_category(chat_id, cat_name):
    data, sha = get_data()
    if not data: return
    cats = data.get('settings', {}).get('categories', [])
    if cat_name in cats:
        cats.remove(cat_name)
        if save_data(data, sha):
            send_message(chat_id, f'✅ Категория <b>{cat_name}</b> удалена!', main_reply_kb())
        else:
            send_message(chat_id, '❌ Ошибка.')
    manage_categories(chat_id)

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.is_json:
        process_update(request.get_json())
    return jsonify({'status': 'ok'})

@app.route('/')
def index():
    return 'Bot is running!'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))