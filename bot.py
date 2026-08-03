import json
import os
import requests
import base64
from flask import Flask, request, jsonify

app = Flask(__name__)

# Конфигурация из переменных окружения
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
REPO_OWNER = os.environ.get('GITHUB_REPOSITORY', '').split('/')[0] if '/' in os.environ.get('GITHUB_REPOSITORY', '') else 'kodpin'
REPO_NAME = 'OneMinute'
FILE_PATH = 'data/products.json'
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
ADMIN_IDS = [int(id) for id in os.environ.get('ADMIN_IDS', '').split(',')]

def get_github_file():
    """Получает содержимое файла с GitHub"""
    url = f'https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}'
    headers = {'Authorization': f'token {GITHUB_TOKEN}'}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        content = base64.b64decode(response.json()['content']).decode('utf-8')
        return json.loads(content), response.json()['sha']
    return None, None

def save_github_file(data, sha=None):
    """Сохраняет файл на GitHub"""
    url = f'https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{FILE_PATH}'
    headers = {'Authorization': f'token {GITHUB_TOKEN}'}
    
    content = json.dumps(data, ensure_ascii=False, indent=2)
    content_bytes = content.encode('utf-8')
    encoded_content = base64.b64encode(content_bytes).decode('utf-8')
    
    payload = {
        'message': 'Update products via bot',
        'content': encoded_content
    }
    if sha:
        payload['sha'] = sha
    
    response = requests.put(url, headers=headers, json=payload)
    return response.status_code in [200, 201]

def send_telegram_message(chat_id, text, reply_markup=None):
    """Отправляет сообщение в Telegram"""
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': text,
        'parse_mode': 'HTML'
    }
    if reply_markup:
        payload['reply_markup'] = reply_markup
    
    requests.post(url, json=payload)

def process_telegram_update(update):
    """Обрабатывает обновление от Telegram"""
    if 'message' not in update:
        return
    
    message = update['message']
    chat_id = message['chat']['id']
    
    # Проверка прав администратора
    if chat_id not in ADMIN_IDS:
        send_telegram_message(chat_id, '❌ У вас нет доступа к управлению ботом.')
        return
    
    text = message.get('text', '')
    
    if text == '/start':
        send_main_menu(chat_id)
    elif text == '/add':
        send_add_instructions(chat_id)
    elif text.startswith('/add '):
        add_product(chat_id, text[5:])
    elif text == '/list':
        list_products_cmd(chat_id)
    elif text.startswith('/delete '):
        delete_product(chat_id, text[8:])
    elif text == '/settings':
        show_settings(chat_id)
    elif text.startswith('/set_ip '):
        update_setting(chat_id, 'ip_info', text[8:])
    elif text.startswith('/set_qr '):
        update_setting(chat_id, 'payment_qr', text[10:])
    elif text.startswith('/set_link '):
        update_setting(chat_id, 'payment_link', text[10:])
    elif text.startswith('/set_manager '):
        update_setting(chat_id, 'manager_telegram', text[13:])
    else:
        send_telegram_message(chat_id, 'Неизвестная команда. Используйте /start для меню.')

def send_main_menu(chat_id):
    """Главное меню"""
    menu_text = """
🎯 <b>Панель управления OneMinute</b>

<b>Товары:</b>
/add - Добавить товар
/list - Список товаров
/delete ID - Удалить товар

<b>Настройки:</b>
/settings - Посмотреть настройки
/set_ip ТЕКСТ - Изменить инфо ИП
/set_qr URL - Изменить QR-код
/set_link URL - Изменить ссылку оплаты
/set_manager URL - Изменить менеджера

<b>Пример добавления товара:</b>
/add Название | Цена | Описание | URL_фото | Категория
    """
    send_telegram_message(chat_id, menu_text)

def send_add_instructions(chat_id):
    """Инструкция по добавлению товара"""
    text = """
➕ <b>Добавление товара</b>

Отправьте команду в формате:
<code>/add Название | Цена | Описание | URL_фото | Категория</code>

<b>Пример:</b>
<code>/add Apple Watch | 79900 | Отличные часы | https://example.com/watch.jpg | smart</code>

<b>Важно:</b>
• Цена в рублях, БЕЗ пробелов
• Категории: smart, classic, luxury
• Разделитель - вертикальная черта |
    """
    send_telegram_message(chat_id, text)

def add_product(chat_id, params):
    """Добавляет товар"""
    try:
        parts = [p.strip() for p in params.split('|')]
        if len(parts) != 5:
            raise ValueError("Неверное количество параметров")
        
        name, price_str, description, image, category = parts
        price = int(price_str)
        
        data, sha = get_github_file()
        if data is None:
            send_telegram_message(chat_id, '❌ Ошибка доступа к файлу данных')
            return
        
        new_id = max([p['id'] for p in data['products']], default=0) + 1
        
        new_product = {
            'id': new_id,
            'name': name,
            'price': price,
            'description': description,
            'image': image,
            'category': category
        }
        
        data['products'].append(new_product)
        
        if save_github_file(data, sha):
            send_telegram_message(chat_id, f'✅ Товар <b>{name}</b> успешно добавлен!\nID: {new_id}\nЦена: {price} ₽')
        else:
            send_telegram_message(chat_id, '❌ Ошибка при сохранении')
            
    except Exception as e:
        send_telegram_message(chat_id, f'❌ Ошибка: {str(e)}\nИспользуйте /add для инструкции')

def list_products_cmd(chat_id):
    """Список товаров"""
    data, _ = get_github_file()
    if data is None or not data.get('products'):
        send_telegram_message(chat_id, '📋 Список товаров пуст')
        return
    
    text = '📋 <b>Список товаров:</b>\n\n'
    for p in data['products']:
        text += f"ID: {p['id']}\n"
        text += f"📱 {p['name']}\n"
        text += f"💰 {p['price']} ₽\n"
        text += f"📝 {p['description'][:50]}...\n"
        text += "➖➖➖➖➖➖➖\n"
    
    send_telegram_message(chat_id, text)

def delete_product(chat_id, product_id_str):
    """Удаляет товар"""
    try:
        product_id = int(product_id_str)
        data, sha = get_github_file()
        
        if data is None:
            send_telegram_message(chat_id, '❌ Ошибка доступа к файлу')
            return
        
        product = next((p for p in data['products'] if p['id'] == product_id), None)
        if not product:
            send_telegram_message(chat_id, f'❌ Товар с ID {product_id} не найден')
            return
        
        data['products'] = [p for p in data['products'] if p['id'] != product_id]
        
        if save_github_file(data, sha):
            send_telegram_message(chat_id, f'✅ Товар <b>{product["name"]}</b> удалён!')
        else:
            send_telegram_message(chat_id, '❌ Ошибка при сохранении')
            
    except ValueError:
        send_telegram_message(chat_id, '❌ Неверный ID. Используйте: /delete ID')

def show_settings(chat_id):
    """Показывает настройки"""
    data, _ = get_github_file()
    if data is None:
        send_telegram_message(chat_id, '❌ Ошибка доступа к настройкам')
        return
    
    s = data.get('settings', {})
    text = f"""
⚙️ <b>Текущие настройки:</b>

<b>Информация ИП:</b>
{s.get('ip_info', 'Не задана')}

<b>QR-код:</b>
{s.get('payment_qr', 'Не задан')}

<b>Ссылка оплаты:</b>
{s.get('payment_link', 'Не задана')}

<b>Менеджер:</b>
{s.get('manager_telegram', 'Не задан')}
    """
    send_telegram_message(chat_id, text)

def update_setting(chat_id, key, value):
    """Обновляет настройку"""
    data, sha = get_github_file()
    if data is None:
        send_telegram_message(chat_id, '❌ Ошибка доступа')
        return
    
    data['settings'][key] = value
    
    if save_github_file(data, sha):
        send_telegram_message(chat_id, f'✅ Настройка обновлена!')
    else:
        send_telegram_message(chat_id, '❌ Ошибка при сохранении')

@app.route('/webhook', methods=['POST'])
def webhook():
    """Webhook для Telegram"""
    if request.is_json:
        update = request.get_json()
        process_telegram_update(update)
    return jsonify({'status': 'ok'})

@app.route('/')
def index():
    return 'OneMinute Bot is running'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))