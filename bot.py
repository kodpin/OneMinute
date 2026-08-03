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

user_states = {}

print(f"Bot started! Admin IDs: {ADMIN_IDS}")
print(f"Repo: {REPO_OWNER}/{REPO_NAME}")

# ============== GitHub ==============
def get_github_file():
    url = f'https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}'
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json'
    }
    print(f"GET {url}")
    response = requests.get(url, headers=headers)
    print(f"Response: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        content = base64.b64decode(data['content']).decode('utf-8')
        return json.loads(content), data['sha']
    else:
        print(f"Error: {response.text}")
    return None, None

def save_github_file(data, sha=None):
    url = f'https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}'
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json'
    }
    content = json.dumps(data, ensure_ascii=False, indent=2)
    encoded = base64.b64encode(content.encode('utf-8')).decode('utf-8')
    payload = {
        'message': 'Update via bot',
        'content': encoded
    }
    if sha:
        payload['sha'] = sha
    
    print(f"PUT {url}")
    response = requests.put(url, headers=headers, json=payload)
    print(f"Response: {response.status_code}")
    if response.status_code not in [200, 201]:
        print(f"Error: {response.text}")
    
    return response.status_code in [200, 201]

# ============== Telegram ==============
def send_message(chat_id, text, reply_markup=None):
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML'
    }
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    
    print(f"Sending message to {chat_id}")
    response = requests.post(url, json=payload)
    print(f"Message response: {response.status_code}")
    if response.status_code != 200:
        print(f"Error: {response.text}")

def send_photo(chat_id, photo_url, caption=None, reply_markup=None):
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto'
    payload = {
        'chat_id': chat_id,
        'photo': photo_url,
        'parse_mode': 'HTML'
    }
    if caption:
        payload['caption'] = caption
    if reply_markup:
        payload['reply_markup'] = json.dumps(reply_markup)
    
    print(f"Sending photo to {chat_id}")
    response = requests.post(url, json=payload)
    print(f"Photo response: {response.status_code}")
    if response.status_code != 200:
        print(f"Error: {response.text}")

def answer_callback(callback_id, text=None):
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery'
    payload = {'callback_query_id': callback_id}
    if text:
        payload['text'] = text
    requests.post(url, json=payload)

# ============== Клавиатуры ==============
def main_menu_kb():
    return {
        "inline_keyboard": [
            [{"text": "➕ Добавить товар", "callback_data": "add_product"}],
            [{"text": "📋 Список товаров", "callback_data": "list_products"}],
            [{"text": "⚙️ Настройки", "callback_data": "settings_menu"}],
            [{"text": "🌐 Открыть сайт", "url": f"https://{REPO_OWNER}.github.io/{REPO_NAME}/"}]
        ]
    }

def cancel_kb():
    return {
        "inline_keyboard": [[{"text": "❌ Отмена", "callback_data": "cancel_add"}]]
    }

def category_kb():
    return {
        "inline_keyboard": [
            [
                {"text": "⌚ Smart", "callback_data": "cat_smart"},
                {"text": "🎩 Classic", "callback_data": "cat_classic"},
                {"text": "💎 Luxury", "callback_data": "cat_luxury"}
            ],
            [{"text": "❌ Отмена", "callback_data": "cancel_add"}]
        ]
    }

def confirm_kb():
    return {
        "inline_keyboard": [
            [{"text": "✅ Подтвердить", "callback_data": "confirm_product"}],
            [{"text": "🔄 Заново", "callback_data": "add_product"}],
            [{"text": "❌ Отмена", "callback_data": "cancel_add"}]
        ]
    }

def settings_kb():
    return {
        "inline_keyboard": [
            [{"text": "📝 Изменить ИП", "callback_data": "edit_ip"}],
            [{"text": "📱 Изменить QR-код", "callback_data": "edit_qr"}],
            [{"text": "🔗 Изменить ссылку оплаты", "callback_data": "edit_link"}],
            [{"text": "👤 Изменить менеджера", "callback_data": "edit_manager"}],
            [{"text": "🔙 Назад", "callback_data": "main_menu"}]
        ]
    }

# ============== Обработка ==============
def process_update(update):
    print(f"Update received: {json.dumps(update, indent=2)[:500]}")
    
    # Callback query
    if 'callback_query' in update:
        callback = update['callback_query']
        chat_id = callback['message']['chat']['id']
        data = callback['data']
        
        print(f"Callback from {chat_id}: {data}")
        
        if chat_id not in ADMIN_IDS:
            answer_callback(callback['id'], 'Нет доступа')
            return
        
        answer_callback(callback['id'])
        
        if data == 'main_menu':
            send_main_menu(chat_id)
        elif data == 'add_product':
            start_add_product(chat_id)
        elif data == 'cancel_add':
            cancel_action(chat_id)
        elif data.startswith('cat_'):
            set_category(chat_id, data.replace('cat_', ''))
        elif data == 'confirm_product':
            save_product(chat_id)
        elif data == 'list_products':
            show_products(chat_id)
        elif data.startswith('delete_'):
            delete_product(chat_id, int(data.replace('delete_', '')))
        elif data == 'settings_menu':
            show_settings(chat_id)
        elif data == 'edit_ip':
            start_edit(chat_id, 'ip_info', '📝 Введите информацию об ИП:')
        elif data == 'edit_qr':
            start_edit(chat_id, 'payment_qr', '📱 Отправьте ссылку на QR-код:')
        elif data == 'edit_link':
            start_edit(chat_id, 'payment_link', '🔗 Отправьте ссылку для оплаты:')
        elif data == 'edit_manager':
            start_edit(chat_id, 'manager_telegram', '👤 Отправьте ссылку на менеджера:')
        
        return
    
    # Message
    if 'message' not in update:
        return
    
    message = update['message']
    chat_id = message['chat']['id']
    
    print(f"Message from {chat_id}: {message.get('text', '[photo]')[:100]}")
    
    if chat_id not in ADMIN_IDS:
        send_message(chat_id, '🚫 Нет доступа')
        return
    
    state = user_states.get(chat_id)
    
    # Обработка фото
    if 'photo' in message:
        if state and state.get('action') == 'waiting_photo':
            handle_photo(chat_id, message)
        else:
            send_message(chat_id, 'Сначала начните добавление товара', main_menu_kb())
        return
    
    # Обработка текста
    text = message.get('text', '')
    
    if text == '/start':
        send_main_menu(chat_id)
    elif state and state.get('action') == 'waiting_text':
        handle_text(chat_id, text)
    else:
        send_main_menu(chat_id)

# ============== Меню ==============
def send_main_menu(chat_id):
    send_message(chat_id, '🎯 <b>OneMinute — Панель управления</b>\n\nВыберите действие:', main_menu_kb())

# ============== Добавление ==============
def start_add_product(chat_id):
    user_states[chat_id] = {
        'action': 'waiting_text',
        'step': 'name',
        'data': {}
    }
    send_message(chat_id, '➕ <b>Шаг 1/5:</b> Введите <b>название</b> товара:', cancel_kb())

def handle_text(chat_id, text):
    state = user_states.get(chat_id)
    if not state:
        return
    
    step = state['step']
    
    if step == 'name':
        state['data']['name'] = text
        state['step'] = 'price'
        send_message(chat_id, f'✅ <b>{text}</b>\n\n💰 <b>Шаг 2/5:</b> Введите <b>цену</b> (только цифры):', cancel_kb())
    
    elif step == 'price':
        try:
            price = int(text.replace(' ', '').replace('₽', ''))
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
    if not state:
        return
    
    state['data']['category'] = category
    state['action'] = 'waiting_photo'
    
    send_message(chat_id, f'✅ Категория: <b>{category}</b>\n\n📸 <b>Шаг 5/5:</b> Отправьте <b>фото</b> товара:', cancel_kb())

def handle_photo(chat_id, message):
    state = user_states.get(chat_id)
    if not state:
        return
    
    print("Processing photo...")
    
    try:
        # Получаем фото
        photo = message['photo']
        file_id = photo[-1]['file_id']
        print(f"File ID: {file_id}")
        
        # Получаем URL
        get_file_url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}'
        response = requests.get(get_file_url)
        
        if response.status_code != 200:
            print(f"GetFile error: {response.text}")
            send_message(chat_id, '❌ Ошибка получения фото. Попробуйте ещё раз.')
            return
        
        file_path = response.json()['result']['file_path']
        photo_url = f'https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}'
        print(f"Photo URL: {photo_url}")
        
        state['data']['image'] = photo_url
        state['action'] = 'confirm'
        
        # Показываем подтверждение
        caption = f"""
📋 <b>Проверьте товар:</b>

📱 <b>Название:</b> {state['data']['name']}
💰 <b>Цена:</b> {state['data']['price']:,} ₽
📝 <b>Описание:</b> {state['data']['description']}
🏷 <b>Категория:</b> {state['data']['category']}

Всё верно?
        """
        send_photo(chat_id, photo_url, caption, confirm_kb())
        print("Confirmation sent")
        
    except Exception as e:
        print(f"Photo error: {traceback.format_exc()}")
        send_message(chat_id, f'❌ Ошибка обработки фото. Попробуйте ещё раз.', cancel_kb())

def save_product(chat_id):
    state = user_states.get(chat_id)
    if not state:
        return
    
    print("Saving product...")
    print(f"Product data: {json.dumps(state['data'], ensure_ascii=False)}")
    
    try:
        data, sha = get_github_file()
        
        if data is None:
            print("Failed to get file!")
            send_message(chat_id, '❌ Ошибка доступа к базе данных')
            return
        
        new_id = max([p['id'] for p in data.get('products', [])], default=0) + 1
        
        new_product = {
            'id': new_id,
            'name': state['data']['name'],
            'price': state['data']['price'],
            'description': state['data']['description'],
            'image': state['data']['image'],
            'category': state['data']['category']
        }
        
        if 'products' not in data:
            data['products'] = []
        
        data['products'].append(new_product)
        
        if save_github_file(data, sha):
            print("Product saved!")
            text = f"""
✅ <b>Товар добавлен!</b>

🆔 ID: <b>{new_id}</b>
📱 <b>{new_product['name']}</b>
💰 <b>{new_product['price']:,} ₽</b>
🏷 <b>{new_product['category']}</b>

🌐 Сайт обновится через 1-2 минуты
            """
            send_photo(chat_id, new_product['image'], text, main_menu_kb())
        else:
            print("Failed to save!")
            send_message(chat_id, '❌ Ошибка сохранения', main_menu_kb())
    
    except Exception as e:
        print(f"Save error: {traceback.format_exc()}")
        send_message(chat_id, f'❌ Ошибка: {e}', main_menu_kb())
    
    finally:
        if chat_id in user_states:
            del user_states[chat_id]

# ============== Список ==============
def show_products(chat_id):
    data, _ = get_github_file()
    
    if not data or not data.get('products'):
        send_message(chat_id, '📋 Товаров пока нет', main_menu_kb())
        return
    
    products = data['products']
    text = f'📋 <b>Товары ({len(products)}):</b>\n\n'
    
    keyboard = []
    for p in products:
        text += f"🆔 {p['id']} | {p['name']} | {p['price']:,}₽\n"
        keyboard.append([{"text": f"❌ Удалить: {p['name']}", "callback_data": f"delete_{p['id']}"}])
    
    keyboard.append([{"text": "🔙 Назад", "callback_data": "main_menu"}])
    
    send_message(chat_id, text, {"inline_keyboard": keyboard})

def delete_product(chat_id, product_id):
    data, sha = get_github_file()
    
    if not data:
        send_message(chat_id, '❌ Ошибка')
        return
    
    product = next((p for p in data['products'] if p['id'] == product_id), None)
    if not product:
        send_message(chat_id, '❌ Товар не найден')
        return
    
    data['products'] = [p for p in data['products'] if p['id'] != product_id]
    
    if save_github_file(data, sha):
        send_message(chat_id, f'✅ <b>{product["name"]}</b> удалён!')
        show_products(chat_id)
    else:
        send_message(chat_id, '❌ Ошибка сохранения')

# ============== Настройки ==============
def show_settings(chat_id):
    data, _ = get_github_file()
    s = data.get('settings', {}) if data else {}
    
    text = f"""
⚙️ <b>Настройки</b>

📝 ИП: {s.get('ip_info', '-')[:100]}
📱 QR: {s.get('payment_qr', '-')[:50]}
🔗 Ссылка: {s.get('payment_link', '-')[:50]}
👤 Менеджер: {s.get('manager_telegram', '-')[:50]}
    """
    send_message(chat_id, text, settings_kb())

def start_edit(chat_id, key, prompt):
    user_states[chat_id] = {
        'action': 'waiting_text',
        'step': 'edit_setting',
        'setting_key': key
    }
    send_message(chat_id, prompt, cancel_kb())

def save_setting(chat_id, value):
    state = user_states.get(chat_id)
    if not state:
        return
    
    key = state['setting_key']
    data, sha = get_github_file()
    
    if not data:
        send_message(chat_id, '❌ Ошибка')
        return
    
    if 'settings' not in data:
        data['settings'] = {}
    
    data['settings'][key] = value
    
    if save_github_file(data, sha):
        send_message(chat_id, f'✅ Настройка обновлена!', main_menu_kb())
    else:
        send_message(chat_id, '❌ Ошибка сохранения')
    
    del user_states[chat_id]

def cancel_action(chat_id):
    if chat_id in user_states:
        del user_states[chat_id]
    send_message(chat_id, '❌ Отменено', main_menu_kb())

# ============== Webhook ==============
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.is_json:
        update = request.get_json()
        process_update(update)
    return jsonify({'status': 'ok'})

@app.route('/')
def index():
    return 'Bot is running! Check logs on Render.'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))