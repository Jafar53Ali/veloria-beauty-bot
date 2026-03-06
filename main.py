import telebot
import psycopg2 
from telebot import types
import urllib.parse
import os
from flask import Flask
from threading import Thread
import time 

# --- إعداد سيرفر Keep-alive ---
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

# المعرفات الأساسية (المالك)
OWNER_ID = 1112769561
ADMIN_IDS = [1426422446, OWNER_ID] 

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
    if user_id in ADMIN_IDS: return True
    # التحقق إذا كان موظف (الموظف له صلاحيات إدارة المنتجات)
    with get_cursor() as cur:
        cur.execute("SELECT id FROM staff WHERE telegram_id = %s", (str(user_id),))
        return cur.fetchone() is not None

# --- لوحة التحكم ---
@bot.message_handler(func=lambda message: message.text == "⚙️ لوحة التحكم")
def admin_panel(message):
    if is_admin(message.from_user.id):
        markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
        markup.add("➕ إضافة منتج", "🗑️ حذف منتج")
        markup.add("✏️ تعديل منتج", "👥 إدارة الموظفين")
        markup.add("🔙 الرجوع للقائمة الرئيسية")
        bot.send_message(message.chat.id, "🛠️ لوحة تحكم الإدارة وصلاحيات الموظفين:", reply_markup=markup)

# --- نظام إدارة الموظفين ---
@bot.message_handler(func=lambda message: message.text == "👥 إدارة الموظفين")
def staff_mgmt(message):
    if message.from_user.id == OWNER_ID: # المالك فقط يدير الموظفين
        markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
        markup.add("➕ إضافة موظف مبيعات", "🗑️ حذف موظف")
        markup.add("✏️ تعديل موظف", "🔙 الرجوع للقائمة الرئيسية")
        bot.send_message(message.chat.id, "إدارة فريق المبيعات:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "➕ إضافة موظف مبيعات")
def ask_staff_type(message):
    if message.from_user.id == OWNER_ID:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🟢 واتساب", callback_data="add_staff_whatsapp"),
                   types.InlineKeyboardButton("🔵 تليجرام", callback_data="add_staff_telegram"))
        bot.send_message(message.chat.id, "اختار نوع الموظف:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("add_staff_"))
def process_staff_add(call):
    stype = call.data.split("_")[2]
    user_states[call.message.chat.id] = f"waiting_staff_add_{stype}"
    msg = "أرسل بيانات الموظف بالترتيب:\nالاسم | الرقم أو المعرف | معرف التليجرام الرقمي (للصلاحيات)"
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
    markup = types.ReplyKeyboardMarkup(row_width=4, resize_keyboard=True) # تم التعديل لـ 4
    buttons = [types.KeyboardButton(p[0]) for p in products]
    markup.add(*buttons)
    markup.add("🔙 الرجوع للقائمة الرئيسية")
    bot.send_message(message.chat.id, "👇 اختاري منتجاً:", reply_markup=markup)

# --- معالج الرسائل العام ---
@bot.message_handler(content_types=['text', 'photo'])
def handle_all_messages(message):
    chat_id = message.chat.id
    state = user_states.get(chat_id)

    # معالجة إضافة موظف
    if state and state.startswith("waiting_staff_add_"):
        stype = state.split("_")[3]
        try:
            parts = [i.strip() for i in message.text.split('|')]
            with get_cursor() as cur:
                cur.execute("INSERT INTO staff (name, contact, type, telegram_id) VALUES (%s,%s,%s,%s)", 
                            (parts[0], parts[1], stype, parts[2]))
            bot.send_message(chat_id, f"✅ تم إضافة الموظف {parts[0]} بنجاح!")
            user_states[chat_id] = None
        except:
            bot.send_message(chat_id, "❌ خطأ في التنسيق! (الاسم | التواصل | المعرف الرقمي)")
        return

    # معالجة طلب الهاتف وإتمام الطلب
    if state == "waiting_phone":
        phone = message.text
        order = temp_orders.get(chat_id)
        if order:
            final_summary = f"طلب جديد من بوت ڤِلوريا:\n👤 الزبون: {order['customer']}\n📞 هاتف: {phone}\n📋 التفاصيل:\n{order['details']}\n💰 المجموع: {order['total']} ج.س"
            
            # جلب الموظفين من القاعدة
            with get_cursor() as cur:
                cur.execute("SELECT name, contact, type FROM staff")
                staff_list = cur.fetchall()
            
            if not staff_list:
                bot.send_message(chat_id, "عذراً، لا يوجد موظفين متاحين حالياً.")
                return

            markup = types.InlineKeyboardMarkup()
            enc = urllib.parse.quote(final_summary)
            for s in staff_list:
                label = f"إرسال لـ {s[0]} ({'واتساب' if s[2]=='whatsapp' else 'تليجرام'})"
                url = f"https://wa.me/{s[1]}?text={enc}" if s[2]=='whatsapp' else f"https://t.me/{s[1]}?text={enc}"
                markup.add(types.InlineKeyboardButton(label, url=url))
            
            bot.send_message(chat_id, "✅ تم تسجيل طلبك! اختاري الموظف لإرسال التفاصيل كاملة له:", reply_markup=markup)
            user_carts[chat_id] = []; user_states[chat_id] = None
        return

    # باقي الوظائف (تعديل منتج، حذف، الخ) كما هي في الكود الأصلي...
    if message.text == "🔙 الرجوع للقائمة الرئيسية": show_main_menu(message)
    elif message.text == "🛒 عرض السلة / إتمام الطلب": show_cart(message)
    elif message.text == "➕ إضافة منتج": ask_add(message)
    
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM products WHERE name = %s", (message.text,))
        product = cursor.fetchone()
    if product: display_product_from_db(message, product)

# --- الدوال المساعدة ---
def show_main_menu(message):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add("🛍️ تصفح المنتجات", "🔍 بحث عن منتج")
    markup.add("✨ فحص نوع البشرة (الخبير الآلي)", "🛒 عرض السلة / إتمام الطلب")
    markup.add("☎️ تواصل مع المبيعات", "👨‍💻 مطور النظام")
    if is_admin(message.from_user.id): markup.add("⚙️ لوحة التحكم")
    bot.send_message(message.chat.id, "✨ مرحباً بكِ في ڤِلوريا بيوتي ✨", reply_markup=markup)

def show_cart(message):
    cart = user_carts.get(message.chat.id, [])
    if not cart: bot.send_message(message.chat.id, "سلتك فارغة حالياً. 🌸"); return
    total = sum(item['price'] for item in cart)
    items_text = "🛍️ **محتويات سلتك:**\n\n"
    markup = types.InlineKeyboardMarkup(row_width=1)
    for index, item in enumerate(cart):
        items_text += f"{index+1}. {item['name']} ({item['price']} ج.س)\n"
    items_text += f"\n💰 **الإجمالي: {total} ج.س**"
    markup.add(types.InlineKeyboardButton("✅ تأكيد وإرسال الطلب", callback_data="confirm_order"))
    bot.send_message(message.chat.id, items_text, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "confirm_order")
def confirm_order_step(call):
    chat_id = call.message.chat.id
    cart = user_carts.get(chat_id, [])
    if cart:
        total = sum(item['price'] for item in cart)
        details = "\n".join([f"- {i['name']} ({i['price']} ج.س)" for i in cart])
        user = f"@{call.from_user.username}" if call.from_user.username else call.from_user.first_name
        temp_orders[chat_id] = {"details": details, "total": total, "customer": user}
        user_states[chat_id] = "waiting_phone"
        bot.send_message(chat_id, "📱 أرسلي رقم هاتف الواتساب الخاص بكِ:")

def display_product_from_db(message, item):
    cap = f"🌸 **المنتج:** {item[1]}\n\n📝 **الوصف:** {item[2]}\n💰 **السعر:** {item[3]} ج.س\n✅ **الحالة:** {item[4]}"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("➕ إضافة للسلة", callback_data=f"add_{item[1]}"))
    try: bot.send_photo(message.chat.id, item[5], caption=cap, reply_markup=markup, parse_mode="Markdown")
    except: bot.send_message(message.chat.id, cap, reply_markup=markup, parse_mode="Markdown")

def ask_add(message):
    if is_admin(message.from_user.id):
        msg = bot.send_message(message.chat.id, "أرسل البيانات بالترتيب: الاسم | الوصف | السعر | الحالة")
        bot.register_next_step_handler(msg, ask_for_photo_wrapper)

def ask_for_photo_wrapper(message):
    try:
        data = [i.strip() for i in message.text.split('|')]
        temp_product_data[message.chat.id] = data
        bot.send_message(message.chat.id, f"✅ أرسل صورة المنتج:")
        bot.register_next_step_handler(message, save_product_final_wrapper)
    except: bot.send_message(message.chat.id, "خطأ في التنسيق")

def save_product_final_wrapper(message):
    data = temp_product_data.get(message.chat.id)
    photo_id = message.photo[-1].file_id
    with get_cursor() as cursor:
        cursor.execute("INSERT INTO products (name, description, price, availability, image_url) VALUES (%s,%s,%s,%s,%s)", 
                       (data[0], data[1], int(data[2]), data[3], photo_id))
    bot.send_message(message.chat.id, "تم الإضافة!")

# --- تشغيل البوت ---
if __name__ == "__main__":
    keep_alive() 
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            time.sleep(5)
