import telebot
import psycopg2 
from telebot import types
import urllib.parse
import os
from flask import Flask
from threading import Thread
import time 

# --- إعداد سيرفر Keep-alive لـ Render ---
app = Flask('')

@app.route('/')
def home():
    return "I am alive! Veloria Beauty Bot is running."

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True 
    t.start()

# 1. إعدادات البوت والمسؤولين
API_TOKEN = '8408686144:AAGy8jf4_fkJCjTCWMRLUJ69mD6qgjX563A'
bot = telebot.TeleBot(API_TOKEN)

DATABASE_URL = "postgresql://neondb_owner:npg_GVlwd8kbrTz6@ep-red-king-ai5otk5k.c-4.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

# المعرفات الأساسية
ADMIN_IDS = [1426422446, 1112769561] 

user_carts = {} 
user_states = {} 
temp_orders = {} 
temp_product_data = {} 
temp_staff_data = {}

# --- إدارة قاعدة البيانات ---
db_conn = None

def get_db_connection():
    global db_conn
    if db_conn is None or db_conn.closed != 0:
        db_conn = psycopg2.connect(DATABASE_URL)
        db_conn.autocommit = True
    return db_conn

def get_cursor():
    conn = get_db_connection()
    try:
        return conn.cursor()
    except:
        return conn.cursor()

def is_admin(user_id):
    if user_id in ADMIN_IDS:
        return True
    try:
        with get_cursor() as cur:
            cur.execute("SELECT id FROM staff WHERE telegram_id = %s", (user_id,))
            return cur.fetchone() is not None
    except:
        return False

# --- أوامر البداية ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    user_carts[message.chat.id] = []
    show_main_menu(message)

# --- لوحة التحكم ---
@bot.message_handler(func=lambda message: message.text == "⚙️ لوحة التحكم")
def admin_panel(message):
    if is_admin(message.from_user.id):
        markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
        markup.add("➕ إضافة منتج", "🗑️ حذف منتج")
        markup.add("✏️ تعديل منتج", "👥 إدارة الموظفين")
        markup.add("🔙 الرجوع للقائمة الرئيسية")
        bot.send_message(message.chat.id, "🛠️ لوحة تحكم الإدارة:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "👥 إدارة الموظفين")
def staff_mgmt(message):
    if is_admin(message.from_user.id):
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("➕ إضافة موظف مبيعات", callback_data="add_staff_start"))
        bot.send_message(message.chat.id, "إدارة فريق العمل:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "add_staff_start")
def choose_staff_type(call):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🟢 واتساب", callback_data="stype_whatsapp"),
               types.InlineKeyboardButton("🔵 تليجرام", callback_data="stype_telegram"))
    bot.edit_message_text("اختار نوع موظف المبيعات:", call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("stype_"))
def ask_staff_info(call):
    stype = call.data.split("_")[1]
    temp_staff_data[call.message.chat.id] = {'type': stype}
    user_states[call.message.chat.id] = "waiting_staff_data"
    msg = "أرسلي بيانات الموظف (واتساب):\nالاسم | رقم الهاتف | المعرف الرقمي" if stype == "whatsapp" else \
          "أرسلي بيانات الموظف (تليجرام):\nالاسم | المعرف بدون @ | المعرف الرقمي"
    bot.send_message(call.message.chat.id, msg)

# --- عرض المنتجات (4 في الصف) ---
@bot.message_handler(func=lambda message: message.text == "🛍️ تصفح المنتجات")
def list_products(message):
    with get_cursor() as cursor:
        cursor.execute("SELECT name FROM products")
        products = cursor.fetchall()
    if not products:
        bot.send_message(message.chat.id, "المتجر فارغ.")
        return
    markup = types.ReplyKeyboardMarkup(row_width=4, resize_keyboard=True)
    buttons = [types.KeyboardButton(p[0]) for p in products]
    markup.add(*buttons)
    markup.add("🔙 الرجوع للقائمة الرئيسية")
    bot.send_message(message.chat.id, "👇 اختاري منتجاً:", reply_markup=markup)

# --- معالج الرسائل العام ---
@bot.message_handler(content_types=['text', 'photo'])
def handle_all_messages(message):
    chat_id = message.chat.id
    state = user_states.get(chat_id)

    if state == "waiting_staff_data":
        try:
            parts = [i.strip() for i in message.text.split('|')]
            s_type = temp_staff_data[chat_id]['type']
            with get_cursor() as cur:
                cur.execute("INSERT INTO staff (name, contact, type, telegram_id) VALUES (%s,%s,%s,%s)", 
                            (parts[0], parts[1], s_type, int(parts[2])))
            bot.send_message(chat_id, f"✅ تم إضافة {parts[0]} بنجاح!")
            user_states[chat_id] = None
        except:
            bot.send_message(chat_id, "❌ خطأ في التنسيق.")
        return

    if state == "waiting_phone":
        phone = message.text
        order = temp_orders.get(chat_id)
        if order:
            final_summary = f"طلب جديد:\n👤 الزبون: {order['customer']}\n📞 هاتف: {phone}\n📋 التفاصيل:\n{order['details']}\n💰 المجموع: {order['total']} ج.س"
            show_staff_options(message, final_summary)
            user_carts[chat_id] = []
            user_states[chat_id] = None
        return

    # التنقل الأساسي
    if message.text == "🔙 الرجوع للقائمة الرئيسية": show_main_menu(message)
    elif message.text == "🛒 عرض السلة / إتمام الطلب": show_cart(message)
    elif message.text == "➕ إضافة منتج": ask_add(message)
    elif message.text == "🗑️ حذف منتج": ask_delete(message)
    elif message.text == "☎️ تواصل مع المبيعات": contact_sales(message)
    elif message.text == "👨‍💻 مطور النظام": contact_dev(message)

    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM products WHERE name = %s", (message.text,))
        product = cursor.fetchone()
    if product: display_product_from_db(message, product)

# --- دوال الموظفين ---
def show_staff_options(message, summary):
    with get_cursor() as cur:
        cur.execute("SELECT name, contact, type FROM staff")
        staff_list = cur.fetchall()
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    enc_text = urllib.parse.quote(summary)
    for s in staff_list:
        url = f"https://wa.me/{s[1]}?text={enc_text}" if s[2]=='whatsapp' else f"https://t.me/{s[1]}?text={enc_text}"
        markup.add(types.InlineKeyboardButton(f"إرسال لـ {s[0]}", url=url))
    bot.send_message(message.chat.id, "✅ اختاري الموظف لإرسال الطلب:", reply_markup=markup)

def contact_sales(message):
    with get_cursor() as cur:
        cur.execute("SELECT name, contact, type FROM staff")
        staff_list = cur.fetchall()
    markup = types.InlineKeyboardMarkup(row_width=1)
    for s in staff_list:
        link = f"https://wa.me/{s[1]}" if s[2] == "whatsapp" else f"https://t.me/{s[1]}"
        markup.add(types.InlineKeyboardButton(f"👤 {s[0]}", url=link))
    bot.send_message(message.chat.id, "فريق المبيعات متاح:", reply_markup=markup)

def show_main_menu(message):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add("🛍️ تصفح المنتجات", "🔍 بحث عن منتج")
    markup.add("✨ فحص نوع البشرة (الخبير الآلي)", "🛒 عرض السلة / إتمام الطلب")
    markup.add("☎️ تواصل مع المبيعات", "👨‍💻 مطور النظام")
    if is_admin(message.from_user.id): markup.add("⚙️ لوحة التحكم")
    bot.send_message(message.chat.id, "✨ مرحباً بكِ في ڤِلوريا بيوتي ✨", reply_markup=markup)

def ask_add(message):
    if is_admin(message.from_user.id):
        msg = bot.send_message(message.chat.id, "أرسل: الاسم | الوصف | السعر | الحالة")
        bot.register_next_step_handler(msg, ask_for_photo_wrapper)

def ask_for_photo_wrapper(message):
    try:
        temp_product_data[message.chat.id] = [i.strip() for i in message.text.split('|')]
        bot.send_message(message.chat.id, "✅ أرسل صورة المنتج:")
        bot.register_next_step_handler(message, save_product_final)
    except: bot.send_message(message.chat.id, "❌ خطأ في التنسيق.")

def save_product_final(message):
    if message.content_type == 'photo':
        data = temp_product_data[message.chat.id]
        with get_cursor() as cursor:
            cursor.execute("INSERT INTO products (name, description, price, availability, image_url) VALUES (%s,%s,%s,%s,%s)", 
                           (data[0], data[1], int(data[2]), data[3], message.photo[-1].file_id))
        bot.send_message(message.chat.id, "✅ تم الإضافة!")

def ask_delete(message):
    with get_cursor() as cursor:
        cursor.execute("SELECT name FROM products")
        prods = cursor.fetchall()
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    for p in prods: markup.add(f"❌ حذف: {p[0]}")
    markup.add("🔙 الرجوع للقائمة الرئيسية")
    bot.send_message(message.chat.id, "اختار للمسح:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text.startswith("❌ حذف: "))
def confirm_delete(message):
    if is_admin(message.from_user.id):
        p_name = message.text.replace("❌ حذف: ", "")
        with get_cursor() as cursor:
            cursor.execute("DELETE FROM products WHERE name = %s", (p_name,))
        bot.send_message(message.chat.id, "🗑️ تم الحذف.")

def contact_dev(message):
    markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("المطور", url="https://t.me/Gafar53_bot"))
    bot.send_message(message.chat.id, "للاستفسارات التقنية:", reply_markup=markup)

def display_product_from_db(message, item):
    cap = f"🌸 **المنتج:** {item[1]}\n\n💰 **السعر:** {item[3]} ج.س\n✅ **الحالة:** {item[4]}"
    markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("➕ إضافة للسلة", callback_data=f"add_{item[1]}"))
    bot.send_photo(message.chat.id, item[5], caption=cap, reply_markup=markup, parse_mode="Markdown")

def show_cart(message):
    cart = user_carts.get(message.chat.id, [])
    if not cart: 
        bot.send_message(message.chat.id, "سلتك فارغة حالياً. 🌸")
        return
    total = sum(item['price'] for item in cart)
    items_text = "🛍️ **سلتك:**\n" + "\n".join([f"- {i['name']} ({i['price']})" for i in cart]) + f"\n\n💰 **المجموع: {total} ج.س**"
    markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("✅ تأكيد الطلب", callback_data="confirm_order"))
    bot.send_message(message.chat.id, items_text, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    chat_id = call.message.chat.id
    if call.data.startswith("add_"):
        p_name = call.data.replace("add_", "")
        with get_cursor() as cur:
            cur.execute("SELECT price FROM products WHERE name = %s", (p_name,))
            res = cur.fetchone()
        if res:
            if chat_id not in user_carts: user_carts[chat_id] = []
            user_carts[chat_id].append({'name': p_name, 'price': res[0]})
            bot.answer_callback_query(call.id, f"✅ تم إضافة {p_name}")
    elif call.data == "confirm_order":
        cart = user_carts.get(chat_id)
        if cart:
            total = sum(item['price'] for item in cart)
            details = "\n".join([f"- {i['name']} ({i['price']})" for i in cart])
            temp_orders[chat_id] = {"details": details, "total": total, "customer": call.from_user.first_name}
            user_states[chat_id] = "waiting_phone"
            bot.send_message(chat_id, "📱 أرسلي رقم هاتف الواتساب الخاص بكِ:")

if __name__ == "__main__":
    keep_alive() 
    while True:
        try:
            bot.infinity_polling(timeout=20)
        except Exception:
            time.sleep(5)
