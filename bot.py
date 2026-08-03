import json
import os
import requests
import base64
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

# ============== GitHub API ==============
def get_github_file():
    url = f'https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}'
    headers = {'Authorization': f'token {GITHUB_TOKEN}'}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        data = response.json()
        content = base64.b64decode(data['content']).decode('utf-8')
        return json.loads(content), data['sha']
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
            [{"text": "✅ Сохранить", "callback_data": "confirm_product"}],
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

def products_list_kb(products):
    keyboard = []
    for p in products:
        keyboard.append([
            {"text": f"❌ {p['name']} - {p['price']:,}₽", "callback_data": f"delete_{p['id']}"}
        ])
    keyboard.append([{"text": "🔙 Назад", "callback_data": "main_menu"}])
    return {"inline_keyboard": keyboard}

# ============== Обработка обновлений ==============
def process_update(update):
    # Callback query (нажатие кнопок)
    if 'callback_query' in update:
        callback = update['callback_query']
        chat_id = callback['message']['chat']['id']
        data = callback['data']
        
        if chat_id not in ADMIN_IDS:
            answer_callback(callback['id'], '🚫 Нет доступа', True)
            return
        
        answer_callback(callback['id'])
        
        # Навигация
        if data == 'main_menu':
            send_main_menu(chat_id)
        elif data == 'add_product':
            start_add_product(chat_id)
        elif data == 'cancel_add':
            cancel_action(chat_id)
        elif data == 'list_products':
            show_products(chat_id)
        elif data == 'settings_menu':
            show_settings(chat_id)
        
        # Категории
        elif data.startswith('cat_'):
            set_category(chat_id, data.replace('cat_', ''))
        
        # Сохранение товара
        elif data == 'confirm_product':
            save_product(chat_id)
        
        # Удаление
        elif data.startswith('delete_'):
            product_id = int(data.replace('delete_', ''))
            delete_product(chat_id, product_id)
        
        # Настройки
        elif data == 'edit_ip':
            start_edit(chat_id, 'ip_info', '📝 Введите новую информацию об ИП:\n\n<i>Можно с переносом строк</i>')
        elif data == 'edit_qr':
            start_edit(chat_id, 'payment_qr', '📱 Отправьте прямую ссылку на QR-код:\n\n<i>Ссылка должна заканчиваться на .jpg или .png</i>')
        elif data == 'edit_link':
            start_edit(chat_id, 'payment_link', '🔗 Отправьте ссылку для оплаты:')
        elif data == 'edit_manager':
            start_edit(chat_id, 'manager_telegram', '👤 Отправьте ссылку на менеджера:\n\n<i>Например: https://t.me/username</i>')
        
        return
    
    # Текстовое сообщение
    if 'message' not in update:
        return
    
    message = update['message']
    chat_id = message['chat']['id']
    text = message.get('text', '')
    
    if chat_id not in ADMIN_IDS:
        send_message(chat_id, '🚫 У вас нет доступа.', main_menu_kb())
        return
    
    state = user_states.get(chat_id)
    
    # Обработка по состоянию
    if state and state.get('action') == 'waiting_text':
        handle_step(chat_id, text)
        return
    
    # Команды
    if text == '/start':
        send_main_menu(chat_id)
    else:
        send_main_menu(chat_id)

# ============== Главное меню ==============
def send_main_menu(chat_id):
    text = """
🎯 <b>OneMinute — Панель управления</b>

Добро пожаловать! Выберите действие:
    """
    send_message(chat_id, text, main_menu_kb())

# ============== Добавление товара (пошагово) ==============
def start_add_product(chat_id):
    user_states[chat_id] = {
        'action': 'waiting_text',
        'step': 'name',
        'data': {}
    }
    send_message(chat_id, """
➕ <b>Добавление товара</b>

<b>Шаг 1/6:</b> Введите <b>название</b> товара:

<i>Например: Apple Watch Ultra 2</i>
    """, cancel_kb())

def handle_step(chat_id, text):
    state = user_states.get(chat_id)
    if not state:
        send_main_menu(chat_id)
        return
    
    step = state['step']
    
    # Шаг 1: Название
    if step == 'name':
        state['data']['name'] = text
        state['step'] = 'price'
        send_message(chat_id, f'✅ Название: <b>{text}</b>\n\n💰 <b>Шаг 2/6:</b> Введите <b>цену</b> в рублях:\n<i>Например: 79900</i>', cancel_kb())
    
    # Шаг 2: Цена
    elif step == 'price':
        try:
            price = int(text.replace(' ', '').replace('₽', '').replace(',', ''))
            state['data']['price'] = price
            state['step'] = 'description'
            send_message(chat_id, f'✅ Цена: <b>{price:,} ₽</b>\n\n📝 <b>Шаг 3/6:</b> Введите <b>описание</b> товара:\n<i>Кратко, 1-2 предложения</i>', cancel_kb())
        except:
            send_message(chat_id, '❌ Введите только цифры! Например: 79900', cancel_kb())
    
    # Шаг 3: Описание
    elif step == 'description':
        state['data']['description'] = text
        state['step'] = 'category'
        send_message(chat_id, f'✅ Описание сохранено\n\n🏷 <b>Шаг 4/6:</b> Выберите <b>категорию</b>:', category_kb())
    
    # Шаг 4: Категория (обрабатывается через callback)
    
    # Шаг 5: Ссылка на фото
    elif step == 'image':
        # Проверяем что это похоже на ссылку
        if not text.startswith('http'):
            send_message(chat_id, '❌ Отправьте прямую ссылку (начинается с http).\n\n<i>Загрузите фото на imgur.com или другой хостинг</i>', cancel_kb())
            return
        
        state['data']['image'] = text
        state['step'] = 'confirm'
        
        # Показываем подтверждение
        caption = f"""
📋 <b>Проверьте товар:</b>

📱 <b>Название:</b> {state['data']['name']}
💰 <b>Цена:</b> {state['data']['price']:,} ₽
📝 <b>Описание:</b> {state['data']['description']}
🏷 <b>Категория:</b> {state['data']['category']}
🖼 <b>Фото:</b> {text[:50]}...

Всё верно?
        """
        try:
            send_photo(chat_id, text, caption, confirm_kb())
        except:
            # Если фото не грузится — просто текст
            send_message(chat_id, caption + '\n\n⚠️ Не удалось загрузить превью фото', confirm_kb())
    
    # Редактирование настроек
    elif step == 'edit_setting':
        save_setting(chat_id, text)

def set_category(chat_id, category):
    state = user_states.get(chat_id)
    if not state:
        return
    
    category_names = {'smart': '⌚ Smart', 'classic': '🎩 Classic', 'luxury': '💎 Luxury'}
    state['data']['category'] = category
    state['step'] = 'image'
    
    send_message(chat_id, f'✅ Категория: <b>{category_names.get(category, category)}</b>\n\n🖼 <b>Шаг 5/6:</b> Отправьте <b>прямую ссылку</b> на фото товара:\n\n<i>Загрузите фото на imgur.com и скопируйте ссылку</i>', cancel_kb())

def save_product(chat_id):
    state = user_states.get(chat_id)
    if not state:
        return
    
    try:
        data, sha = get_github_file()
        
        if data is None:
            send_message(chat_id, '❌ Ошибка доступа к базе данных. Проверьте GITHUB_TOKEN.', main_menu_kb())
            return
        
        if 'products' not in data:
            data['products'] = []
        
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
            success_text = f"""
✅ <b>Товар успешно добавлен!</b>

🆔 <b>ID:</b> {new_id}
📱 <b>Название:</b> {new_product['name']}
💰 <b>Цена:</b> {new_product['price']:,} ₽
🏷 <b>Категория:</b> {new_product['category']}

🌐 <b>Сайт обновится через 1-2 минуты</b>
<a href="https://{REPO_OWNER}.github.io/{REPO_NAME}/">Открыть сайт</a>
            """
            # Пробуем отправить с фото
            try:
                send_photo(chat_id, new_product['image'], success_text, main_menu_kb())
            except:
                send_message(chat_id, success_text, main_menu_kb())
        else:
            send_message(chat_id, '❌ Ошибка сохранения. Проверьте GITHUB_TOKEN.', main_menu_kb())
    
    except Exception as e:
        send_message(chat_id, f'❌ Ошибка: {str(e)}', main_menu_kb())
    
    finally:
        if chat_id in user_states:
            del user_states[chat_id]

# ============== Список товаров ==============
def show_products(chat_id):
    data, _ = get_github_file()
    
    if not data or not data.get('products'):
        send_message(chat_id, '📋 <b>Товаров пока нет</b>\n\nНажмите "➕ Добавить товар" чтобы создать первый!', main_menu_kb())
        return
    
    products = data['products']
    text = f'📋 <b>Товары ({len(products)}):</b>\n\n'
    
    for p in products:
        text += f"🆔 <b>{p['id']}</b> | 📱 {p['name']}\n"
        text += f"💰 {p['price']:,} ₽ | 🏷 {p['category']}\n"
        text += f"📝 {p['description'][:60]}...\n\n"
    
    text += "<i>Нажмите на товар чтобы удалить:</i>"
    
    send_message(chat_id, text, products_list_kb(products))

def delete_product(chat_id, product_id):
    data, sha = get_github_file()
    
    if not data:
        send_message(chat_id, '❌ Ошибка доступа')
        return
    
    product = next((p for p in data['products'] if p['id'] == product_id), None)
    if not product:
        send_message(chat_id, '❌ Товар не найден')
        return
    
    product_name = product['name']
    data['products'] = [p for p in data['products'] if p['id'] != product_id]
    
    if save_github_file(data, sha):
        send_message(chat_id, f'✅ <b>{product_name}</b> удалён!\n\n🌐 Сайт обновится через 1-2 минуты')
        show_products(chat_id)
    else:
        send_message(chat_id, '❌ Ошибка сохранения')

# ============== Настройки ==============
def show_settings(chat_id):
    data, _ = get_github_file()
    
    if not data:
        send_message(chat_id, '❌ Ошибка загрузки настроек', main_menu_kb())
        return
    
    s = data.get('settings', {})
    text = f"""
⚙️ <b>Текущие настройки</b>

📝 <b>Информация ИП:</b>
{s.get('ip_info', 'Не задана')}

📱 <b>QR-код:</b>
{s.get('payment_qr', 'Не задан')[:80]}

🔗 <b>Ссылка оплаты:</b>
{s.get('payment_link', 'Не задана')}

👤 <b>Менеджер:</b>
{s.get('manager_telegram', 'Не задан')}

<i>Выберите что изменить:</i>
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
        send_message(chat_id, '❌ Ошибка доступа', main_menu_kb())
        return
    
    if 'settings' not in data:
        data['settings'] = {}
    
    # Старое значение автоматически заменяется новым
    data['settings'][key] = value
    
    if save_github_file(data, sha):
        setting_names = {
            'ip_info': 'Информация ИП',
            'payment_qr': 'QR-код',
            'payment_link': 'Ссылка оплаты',
            'manager_telegram': 'Менеджер'
        }
        send_message(chat_id, f'✅ <b>{setting_names.get(key, key)}</b> обновлено!', main_menu_kb())
    else:
        send_message(chat_id, '❌ Ошибка сохранения', main_menu_kb())
    
    if chat_id in user_states:
        del user_states[chat_id]

def cancel_action(chat_id):
    if chat_id in user_states:
        del user_states[chat_id]
    send_message(chat_id, '❌ Действие отменено', main_menu_kb())

# ============== Webhook ==============
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.is_json:
        update = request.get_json()
        process_update(update)
    return jsonify({'status': 'ok'})

@app.route('/')
def index():
    return 'OneMinute Bot is running!'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))