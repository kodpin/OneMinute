import json
import os
import requests
import base64
import traceback
from flask import Flask, request, jsonify

app = Flask(__name__)

# Конфигурация
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
REPO = os.environ.get('GITHUB_REPOSITORY', 'kodpin/OneMinute')
REPO_OWNER = REPO.split('/')[0]
REPO_NAME = REPO.split('/')[1] if '/' in REPO else 'OneMinute'
FILE_PATH = 'data/products.json'
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
ADMIN_IDS_STR = os.environ.get('ADMIN_IDS', '')
ADMIN_IDS = [int(id.strip()) for id in ADMIN_IDS_STR.split(',') if id.strip()]

CLOUDINARY_CLOUD_NAME = os.environ.get('CLOUDINARY_CLOUD_NAME', '')
CLOUDINARY_UPLOAD_PRESET = os.environ.get('CLOUDINARY_UPLOAD_PRESET', 'oneminute_upload')

print(f"Cloudinary: name={CLOUDINARY_CLOUD_NAME}, preset={CLOUDINARY_UPLOAD_PRESET}")
user_states = {}

# ============== GitHub API ==============
def get_github_file():
    url = f'https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}'
    headers = {'Authorization': f'token {GITHUB_TOKEN}'}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        content = base64.b64decode(data['content']).decode('utf-8')
        return json.loads(content), data['sha']
    print(f"GitHub get error: {response.status_code} {response.text}")
    return None, None

def save_github_file(data, sha=None):
    url = f'https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}'
    headers = {'Authorization': f'token {GITHUB_TOKEN}'}
    content = json.dumps(data, ensure_ascii=False, indent=2)
    encoded = base64.b64encode(content.encode('utf-8')).decode('utf-8')
    payload = {'message': 'Update via bot', 'content': encoded}
    if sha:
        payload['sha'] = sha
    response = requests.put(url, headers=headers, json=payload)
    if response.status_code not in [200, 201]:
        print(f"GitHub save error: {response.status_code} {response.text}")
    return response.status_code in [200, 201]

# ============== Telegram API ==============
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

def answer_callback(callback_id, text=None, show_alert=False):
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery'
    payload = {'callback_query_id': callback_id}
    if text:
        payload['text'] = text
        payload['show_alert'] = show_alert
    requests.post(url, json=payload)

# ============== Cloudinary Upload ==============
def upload_to_cloudinary(photo_url):
    if not CLOUDINARY_CLOUD_NAME:
        print("Cloudinary not configured, using Telegram URL")
        return photo_url

    print(f"Downloading from Telegram: {photo_url[:80]}...")
    try:
        file_response = requests.get(photo_url, timeout=15)
        if file_response.status_code != 200:
            print(f"Failed to download photo: {file_response.status_code}")
            return photo_url
    except Exception as e:
        print(f"Download error: {e}")
        return photo_url

    upload_url = f'https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/image/upload'
    files = {'file': ('image.jpg', file_response.content, 'image/jpeg')}
    data = {'upload_preset': CLOUDINARY_UPLOAD_PRESET}

    print(f"Uploading to Cloudinary with preset {CLOUDINARY_UPLOAD_PRESET}")
    try:
        response = requests.post(upload_url, files=files, data=data, timeout=20)
        print(f"Cloudinary response: {response.status_code} {response.text[:200]}")
        if response.status_code == 200:
            result = response.json()
            secure_url = result.get('secure_url')
            if secure_url:
                print(f"Success! Cloudinary URL: {secure_url}")
                return secure_url
    except Exception as e:
        print(f"Cloudinary upload error: {e}")
    return photo_url

# ============== Клавиатуры ==============
def main_menu_kb():
    return {"inline_keyboard": [
        [{"text": "➕ Добавить товар", "callback_data": "add_product"}],
        [{"text": "📋 Список товаров", "callback_data": "list_products"}],
        [{"text": "⚙️ Настройки", "callback_data": "settings_menu"}]
    ]}

def cancel_kb():
    return {"inline_keyboard": [[{"text": "❌ Отмена", "callback_data": "cancel_add"}]]}

def category_kb():
    return {"inline_keyboard": [
        [{"text": "Тактические", "callback_data": "cat_tactical"}, {"text": "Для путешествий", "callback_data": "cat_travel"}],
        [{"text": "Для бега", "callback_data": "cat_running"}, {"text": "Для дайвинга", "callback_data": "cat_diving"}],
        [{"text": "❌ Отмена", "callback_data": "cancel_add"}]
    ]}

def confirm_kb():
    return {"inline_keyboard": [
        [{"text": "✅ Сохранить", "callback_data": "confirm_product"}],
        [{"text": "🔄 Заново", "callback_data": "add_product"}],
        [{"text": "❌ Отмена", "callback_data": "cancel_add"}]
    ]}

def settings_kb():
    return {"inline_keyboard": [
        [{"text": "📝 Изменить ИП", "callback_data": "edit_ip"}],
        [{"text": "📱 Изменить QR-код", "callback_data": "edit_qr"}],
        [{"text": "🔗 Изменить ссылку оплаты", "callback_data": "edit_link"}],
        [{"text": "👤 Изменить менеджера", "callback_data": "edit_manager"}],
        [{"text": "🔙 Назад", "callback_data": "main_menu"}]
    ]}

def products_list_kb(products):
    keyboard = [[{"text": f"❌ {p['name']} - {p['price']:,}₽", "callback_data": f"delete_{p['id']}"}] for p in products]
    keyboard.append([{"text": "🔙 Назад", "callback_data": "main_menu"}])
    return {"inline_keyboard": keyboard}

# ============== Обработка ==============
def process_update(update):
    if 'callback_query' in update:
        callback = update['callback_query']
        chat_id = callback['message']['chat']['id']
        data = callback['data']
        if chat_id not in ADMIN_IDS:
            answer_callback(callback['id'], '🚫 Нет доступа', True)
            return
        answer_callback(callback['id'])
        if data == 'main_menu': send_main_menu(chat_id)
        elif data == 'add_product': start_add_product(chat_id)
        elif data == 'cancel_add': cancel_action(chat_id)
        elif data == 'list_products': show_products(chat_id)
        elif data == 'settings_menu': show_settings(chat_id)
        elif data.startswith('cat_'): set_category(chat_id, data.replace('cat_', ''))
        elif data == 'confirm_product': save_product(chat_id)
        elif data.startswith('delete_'): delete_product(chat_id, int(data.replace('delete_', '')))
        elif data == 'edit_ip': start_edit(chat_id, 'ip_info', '📝 Введите информацию об ИП:')
        elif data == 'edit_qr': start_edit(chat_id, 'payment_qr', '📱 Отправьте ссылку на QR-код:')
        elif data == 'edit_link': start_edit(chat_id, 'payment_link', '🔗 Отправьте ссылку для оплаты:')
        elif data == 'edit_manager': start_edit(chat_id, 'manager_telegram', '👤 Отправьте ссылку на менеджера:')
        return

    if 'message' not in update: return
    message = update['message']
    chat_id = message['chat']['id']
    if chat_id not in ADMIN_IDS: return

    if 'photo' in message:
        state = user_states.get(chat_id)
        if state and state.get('step') == 'photo':
            handle_photo(chat_id, message)
        else:
            send_message(chat_id, 'Сначала начните добавление товара командой /add')
        return

    text = message.get('text', '')
    state = user_states.get(chat_id)
    if text == '/start':
        send_main_menu(chat_id)
    elif state and state.get('action') == 'waiting_text':
        handle_text_step(chat_id, text)
    else:
        send_main_menu(chat_id)

def send_main_menu(chat_id):
    send_message(chat_id, '🎯 <b>OneMinute — Панель управления</b>\nВыберите действие:', main_menu_kb())

def start_add_product(chat_id):
    user_states[chat_id] = {'action': 'waiting_text', 'step': 'name', 'data': {}}
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
    send_message(chat_id, f'✅ Категория: <b>{category}</b>\n\n📸 <b>Шаг 5/5:</b> Отправьте <b>фото</b> товара:', cancel_kb())

def handle_photo(chat_id, message):
    state = user_states.get(chat_id)
    if not state: return
    try:
        photo = message['photo']
        file_id = photo[-1]['file_id']
        get_url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}'
        resp = requests.get(get_url).json()
        if not resp.get('ok'):
            print(f"getFile error: {resp}")
            send_message(chat_id, '❌ Ошибка получения фото.')
            return
        file_path = resp['result']['file_path']
        telegram_photo_url = f'https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}'
        print(f"Telegram photo URL: {telegram_photo_url}")

        send_message(chat_id, '☁️ Загружаю фото в облако...')
        cloud_url = upload_to_cloudinary(telegram_photo_url)
        print(f"Final photo URL: {cloud_url}")
        state['data']['image'] = cloud_url

        caption = f"📋 <b>Проверьте товар:</b>\n📱 {state['data']['name']}\n💰 {state['data']['price']:,} ₽\n📝 {state['data']['description']}\n🏷 {state['data']['category']}\n🖼 Фото загружено"
        send_photo(chat_id, cloud_url, caption, confirm_kb())
    except Exception as e:
        print(f"handle_photo error: {traceback.format_exc()}")
        send_message(chat_id, f'❌ Ошибка обработки фото: {e}')

def save_product(chat_id):
    state = user_states.get(chat_id)
    if not state: return
    print(f"Saving product: {state['data']}")
    try:
        data, sha = get_github_file()
        if data is None:
            send_message(chat_id, '❌ Ошибка доступа к базе.')
            return
        if 'products' not in data: data['products'] = []
        new_id = max([p['id'] for p in data['products']], default=0) + 1
        new_product = {
            'id': new_id,
            'name': state['data']['name'],
            'price': state['data']['price'],
            'description': state['data']['description'],
            'image': state['data']['image'],
            'category': state['data']['category']
        }
        data['products'].append(new_product)
        if save_github_file(data, sha):
            send_message(chat_id, f'✅ Товар <b>{new_product["name"]}</b> добавлен!\nID: {new_id}\nЦена: {new_product["price"]:,} ₽')
        else:
            send_message(chat_id, '❌ Ошибка сохранения.')
    except Exception as e:
        print(f"save_product error: {traceback.format_exc()}")
        send_message(chat_id, f'❌ Ошибка: {e}')
    finally:
        if chat_id in user_states: del user_states[chat_id]

def show_products(chat_id):
    data, _ = get_github_file()
    if not data or not data.get('products'):
        send_message(chat_id, '📋 Товаров пока нет.')
        return
    prods = data['products']
    text = f'📋 <b>Товары ({len(prods)}):</b>\n\n'
    for p in prods:
        text += f"🆔 {p['id']} | {p['name']} | {p['price']:,}₽\n"
    send_message(chat_id, text, products_list_kb(prods))

def delete_product(chat_id, pid):
    data, sha = get_github_file()
    if not data: return
    product = next((p for p in data['products'] if p['id'] == pid), None)
    if not product:
        send_message(chat_id, '❌ Товар не найден')
        return
    data['products'] = [p for p in data['products'] if p['id'] != pid]
    if save_github_file(data, sha):
        send_message(chat_id, f'✅ <b>{product["name"]}</b> удалён!')
        show_products(chat_id)
    else:
        send_message(chat_id, '❌ Ошибка сохранения')

def show_settings(chat_id):
    data, _ = get_github_file()
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
    data, sha = get_github_file()
    if not data: return
    if 'settings' not in data: data['settings'] = {}
    data['settings'][key] = value
    if save_github_file(data, sha):
        send_message(chat_id, '✅ Настройка обновлена!')
    else:
        send_message(chat_id, '❌ Ошибка сохранения')
    if chat_id in user_states: del user_states[chat_id]

def cancel_action(chat_id):
    if chat_id in user_states: del user_states[chat_id]
    send_message(chat_id, '❌ Отменено', main_menu_kb())

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