import json
import os
import requests
import base64
from flask import Flask, request, jsonify

app = Flask(__name__)

# Конфигурация
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
REPO_OWNER = os.environ.get('GITHUB_REPOSITORY', '').split('/')[0] if '/' in os.environ.get('GITHUB_REPOSITORY', '') else 'kodpin'
REPO_NAME = 'OneMinute'
FILE_PATH = 'data/products.json'
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
ADMIN_IDS = [int(id) for id in os.environ.get('ADMIN_IDS', '').split(',')]

user_states = {}

# ============== GitHub API ==============
def get_github_file():
    url = f'https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}'
    headers = {'Authorization': f'token {GITHUB_TOKEN}'}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        content = base64.b64decode(response.json()['content']).decode('utf-8')
        return json.loads(content), response.json()['sha']
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
    return response.status_code in [200, 201]

# ============== Telegram API ==============
def send_message(chat_id, text, reply_markup=None):
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
    if reply_markup:
        payload['reply_markup'] = reply_markup
    requests.post(url, json=payload)

def send_photo(chat_id, photo_url, caption=None, reply_markup=None):
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto'
    payload = {'chat_id': chat_id, 'photo': photo_url}
    if caption:
        payload['caption'] = caption
        payload['parse_mode'] = 'HTML'
    if reply_markup:
        payload['reply_markup'] = reply_markup
    requests.post(url, json=payload)

def edit_message(chat_id, message_id, text, reply_markup=None):
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/editMessageText'
    payload = {
        'chat_id': chat_id,
        'message_id': message_id,
        'text': text,
        'parse_mode': 'HTML'
    }
    if reply_markup:
        payload['reply_markup'] = reply_markup
    requests.post(url, json=payload)

def delete_message(chat_id, message_id):
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/deleteMessage'
    requests.post(url, json={'chat_id': chat_id, 'message_id': message_id})

def answer_callback(callback_id, text=None, show_alert=False):
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery'
    payload = {'callback_query_id': callback_id}
    if text:
        payload['text'] = text
        payload['show_alert'] = show_alert
    requests.post(url, json=payload)

# ============== Клавиатуры ==============
def main_menu_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "➕ Добавить товар", "callback_data": "add_product"}],
            [{"text": "📋 Список товаров", "callback_data": "list_products"}],
            [{"text": "⚙️ Настройки", "callback_data": "settings_menu"}],
            [{"text": "🌐 Открыть сайт", "url": f"https://{REPO_OWNER}.github.io/{REPO_NAME}/"}]
        ]
    }

def back_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "🔙 Назад в меню", "callback_data": "main_menu"}]
        ]
    }

def category_keyboard():
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

def confirm_keyboard():
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Подтвердить", "callback_data": "confirm_product"},
                {"text": "❌ Отмена", "callback_data": "cancel_add"}
            ]
        ]
    }

def settings_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "📝 Изменить ИП", "callback_data": "edit_ip"}],
            [{"text": "📱 Изменить QR-код", "callback_data": "edit_qr"}],
            [{"text": "🔗 Изменить ссылку оплаты", "callback_data": "edit_link"}],
            [{"text": "👤 Изменить менеджера", "callback_data": "edit_manager"}],
            [{"text": "🔙 Назад", "callback_data": "main_menu"}]
        ]
    }

def products_list_keyboard(products):
    keyboard = []
    for p in products:
        keyboard.append([
            {"text": f"❌ {p['name']} - {p['price']}₽", "callback_data": f"delete_{p['id']}"}
        ])
    keyboard.append([{"text": "🔙 Назад", "callback_data": "main_menu"}])
    return {"inline_keyboard": keyboard}

# ============== Обработка сообщений ==============
def process_update(update):
    # Callback query (нажатие на кнопку)
    if 'callback_query' in update:
        process_callback(update['callback_query'])
        return
    
    # Обычное сообщение
    if 'message' not in update:
        return
    
    message = update['message']
    chat_id = message['chat']['id']
    
    if chat_id not in ADMIN_IDS:
        send_message(chat_id, '🚫 У вас нет доступа к управлению.', main_menu_keyboard())
        return
    
    # Проверяем состояние пользователя
    state = user_states.get(chat_id)
    
    if state:
        if state['action'] == 'waiting_text':
            handle_waiting_text(chat_id, message)
            return
        elif state['action'] == 'waiting_photo':
            handle_waiting_photo(chat_id, message)
            return
    
    # Обычные команды
    text = message.get('text', '')
    if text == '/start':
        send_main_menu(chat_id)
    else:
        send_main_menu(chat_id)

def process_callback(callback):
    chat_id = callback['message']['chat']['id']
    message_id = callback['message']['message_id']
    data = callback['data']
    
    if chat_id not in ADMIN_IDS:
        answer_callback(callback['id'], '🚫 Нет доступа', True)
        return
    
    # Главное меню
    if data == 'main_menu':
        send_main_menu(chat_id)
    
    # Добавление товара
    elif data == 'add_product':
        start_add_product(chat_id)
    
    elif data == 'cancel_add':
        cancel_action(chat_id)
    
    elif data.startswith('cat_'):
        category = data.replace('cat_', '')
        set_category(chat_id, category)
    
    elif data == 'confirm_product':
        save_product(chat_id)
    
    # Список товаров
    elif data == 'list_products':
        show_products_list(chat_id)
    
    elif data.startswith('delete_'):
        product_id = int(data.replace('delete_', ''))
        delete_product(chat_id, product_id)
    
    # Настройки
    elif data == 'settings_menu':
        show_settings(chat_id)
    
    elif data == 'edit_ip':
        start_edit_setting(chat_id, 'ip_info', '📝 Введите новую информацию об ИП:')
    
    elif data == 'edit_qr':
        start_edit_setting(chat_id, 'payment_qr', '📱 Отправьте URL нового QR-кода:')
    
    elif data == 'edit_link':
        start_edit_setting(chat_id, 'payment_link', '🔗 Отправьте новую ссылку для оплаты:')
    
    elif data == 'edit_manager':
        start_edit_setting(chat_id, 'manager_telegram', '👤 Отправьте ссылку на Telegram менеджера:')
    
    answer_callback(callback['id'])

# ============== Главное меню ==============
def send_main_menu(chat_id):
    text = """
🎯 <b>OneMinute — Панель управления</b>

Добро пожаловать! Выберите действие:
    """
    send_message(chat_id, text, main_menu_keyboard())

# ============== Добавление товара ==============
def start_add_product(chat_id):
    user_states[chat_id] = {
        'action': 'waiting_text',
        'step': 'name',
        'data': {}
    }
    
    text = """
➕ <b>Добавление нового товара</b>

<b>Шаг 1/5:</b> Введите <b>название</b> товара:

<i>Или нажмите кнопку для отмены</i>
    """
    send_message(chat_id, text, {
        "inline_keyboard": [[{"text": "❌ Отмена", "callback_data": "cancel_add"}]]
    })

def handle_waiting_text(chat_id, message):
    state = user_states.get(chat_id)
    if not state:
        return
    
    text = message.get('text', '')
    step = state['step']
    
    if step == 'name':
        state['data']['name'] = text
        state['step'] = 'price'
        send_message(chat_id, f'✅ Название: <b>{text}</b>\n\n<b>Шаг 2/5:</b> Введите <b>цену</b> в рублях:\n<i>Только цифры, например: 79900</i>', {
            "inline_keyboard": [[{"text": "❌ Отмена", "callback_data": "cancel_add"}]]
        })
    
    elif step == 'price':
        try:
            price = int(text.replace(' ', '').replace('₽', ''))
            state['data']['price'] = price
            state['step'] = 'description'
            send_message(chat_id, f'✅ Цена: <b>{price:,} ₽</b>\n\n<b>Шаг 3/5:</b> Введите <b>описание</b> товара:', {
                "inline_keyboard": [[{"text": "❌ Отмена", "callback_data": "cancel_add"}]]
            })
        except:
            send_message(chat_id, '❌ Введите цену цифрами!\n<i>Например: 79900</i>')
    
    elif step == 'description':
        state['data']['description'] = text
        state['step'] = 'category'
        send_message(chat_id, f'✅ Описание сохранено\n\n<b>Шаг 4/5:</b> Выберите <b>категорию</b>:', category_keyboard())
    
    elif step == 'edit_setting':
        save_setting(chat_id, text)

def set_category(chat_id, category):
    state = user_states.get(chat_id)
    if not state:
        return
    
    category_names = {
        'smart': '⌚ Smart',
        'classic': '🎩 Classic',
        'luxury': '💎 Luxury'
    }
    
    state['data']['category'] = category
    state['action'] = 'waiting_photo'
    
    send_message(chat_id, f'✅ Категория: <b>{category_names.get(category, category)}</b>\n\n<b>Шаг 5/5:</b> Отправьте <b>фото</b> товара:', {
        "inline_keyboard": [[{"text": "❌ Отмена", "callback_data": "cancel_add"}]]
    })

def handle_waiting_photo(chat_id, message):
    state = user_states.get(chat_id)
    if not state:
        return
    
    photo = message.get('photo')
    if not photo:
        send_message(chat_id, '❌ Отправьте именно фото (картинку)!')
        return
    
    # Получаем URL фото
    file_id = photo[-1]['file_id']
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile?file_id={file_id}'
    response = requests.get(url)
    
    if response.status_code != 200:
        send_message(chat_id, '❌ Ошибка загрузки. Попробуйте ещё раз.')
        return
    
    file_path = response.json()['result']['file_path']
    photo_url = f'https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}'
    state['data']['image'] = photo_url
    state['action'] = 'confirm'
    
    # Показываем превью
    caption = f"""
📋 <b>Проверьте товар:</b>

📱 <b>Название:</b> {state['data']['name']}
💰 <b>Цена:</b> {state['data']['price']:,} ₽
📝 <b>Описание:</b> {state['data']['description']}
🏷 <b>Категория:</b> {state['data']['category']}

Подтверждаете добавление?
    """
    send_photo(chat_id, photo_url, caption, confirm_keyboard())

def save_product(chat_id):
    state = user_states.get(chat_id)
    if not state:
        return
    
    product_data = state['data']
    
    try:
        data, sha = get_github_file()
        if data is None:
            send_message(chat_id, '❌ Ошибка доступа к данным')
            return
        
        new_id = max([p['id'] for p in data['products']], default=0) + 1
        
        new_product = {
            'id': new_id,
            'name': product_data['name'],
            'price': product_data['price'],
            'description': product_data['description'],
            'image': product_data['image'],
            'category': product_data['category']
        }
        
        data['products'].append(new_product)
        
        if save_github_file(data, sha):
            text = f"""
✅ <b>Товар успешно добавлен!</b>

🆔 ID: <b>{new_id}</b>
📱 Название: <b>{product_data['name']}</b>
💰 Цена: <b>{product_data['price']:,} ₽</b>
🏷 Категория: <b>{product_data['category']}</b>

<i>🌐 Сайт обновится через 1-2 минуты</i>
            """
            send_photo(chat_id, product_data['image'], text, main_menu_keyboard())
        else:
            send_message(chat_id, '❌ Ошибка сохранения', main_menu_keyboard())
    
    except Exception as e:
        send_message(chat_id, f'❌ Ошибка: {e}', main_menu_keyboard())
    
    finally:
        if chat_id in user_states:
            del user_states[chat_id]

# ============== Список товаров ==============
def show_products_list(chat_id):
    data, _ = get_github_file()
    
    if not data or not data.get('products'):
        send_message(chat_id, '📋 <b>Список товаров пуст</b>\n\nДобавьте первый товар!', main_menu_keyboard())
        return
    
    products = data['products']
    text = f'📋 <b>Всего товаров: {len(products)}</b>\n\n'
    
    for p in products:
        text += f"🆔 <b>{p['id']}</b> | 📱 {p['name']}\n"
        text += f"💰 {p['price']:,} ₽ | 🏷 {p['category']}\n"
        text += f"📝 {p['description'][:50]}...\n\n"
    
    text += "<i>Нажмите на товар чтобы удалить:</i>"
    
    send_message(chat_id, text, products_list_keyboard(products))

def delete_product(chat_id, product_id):
    data, sha = get_github_file()
    
    if not data:
        send_message(chat_id, '❌ Ошибка доступа')
        return
    
    product = next((p for p in data['products'] if p['id'] == product_id), None)
    if not product:
        send_message(chat_id, '❌ Товар не найден')
        return
    
    data['products'] = [p for p in data['products'] if p['id'] != product_id]
    
    if save_github_file(data, sha):
        send_message(chat_id, f'✅ Товар <b>{product["name"]}</b> удалён!\n\n<i>Сайт обновится через 1-2 минуты</i>')
        show_products_list(chat_id)
    else:
        send_message(chat_id, '❌ Ошибка сохранения')

# ============== Настройки ==============
def show_settings(chat_id):
    data, _ = get_github_file()
    
    if not data:
        send_message(chat_id, '❌ Ошибка доступа')
        return
    
    s = data.get('settings', {})
    text = f"""
⚙️ <b>Текущие настройки</b>

📝 <b>Информация ИП:</b>
{s.get('ip_info', 'Не задана')}

📱 <b>QR-код оплаты:</b>
{s.get('payment_qr', 'Не задан')}

🔗 <b>Ссылка оплаты:</b>
{s.get('payment_link', 'Не задана')}

👤 <b>Менеджер:</b>
{s.get('manager_telegram', 'Не задан')}

<i>Выберите что изменить:</i>
    """
    send_message(chat_id, text, settings_keyboard())

def start_edit_setting(chat_id, key, prompt):
    user_states[chat_id] = {
        'action': 'waiting_text',
        'step': 'edit_setting',
        'setting_key': key
    }
    
    send_message(chat_id, prompt, {
        "inline_keyboard": [[{"text": "🔙 Назад к настройкам", "callback_data": "settings_menu"}]]
    })

def save_setting(chat_id, value):
    state = user_states.get(chat_id)
    if not state:
        return
    
    key = state['setting_key']
    data, sha = get_github_file()
    
    if not data:
        send_message(chat_id, '❌ Ошибка доступа')
        return
    
    data['settings'][key] = value
    
    if save_github_file(data, sha):
        send_message(chat_id, f'✅ Настройка обновлена!', settings_keyboard())
    else:
        send_message(chat_id, '❌ Ошибка сохранения')
    
    del user_states[chat_id]

def cancel_action(chat_id):
    if chat_id in user_states:
        del user_states[chat_id]
    send_message(chat_id, '❌ Действие отменено', main_menu_keyboard())

# ============== Webhook ==============
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.is_json:
        update = request.get_json()
        process_update(update)
    return jsonify({'status': 'ok'})

@app.route('/')
def index():
    return 'OneMinute Bot is running'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))