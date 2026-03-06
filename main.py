import telebot
import psycopg2 
from telebot import types
import urllib.parse
import os
from flask import Flask
from threading import Thread
import time  # إضافة بسيطة لضمان التوقيت

# --- إعداد سيرفر لاستقبال طلبات الـ Cron-job (Keep-alive) ---
app = Flask('')

@app.route('/')
def home():
    return "I am alive! Veloria Beauty Bot is running."

def run_flask():
    # Render بيحدد المنفذ تلقائياً عبر متغير PORT أو نستخدم 8080 بناءً على طلبك
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True # تعديل لضمان استمرارية السيرفر مع البرنامج
    t.start()

# 1. إعدادات البوت والمسؤولين
API_TOKEN = '8408686144:AAGy8jf4_fkJCjTCWMRLUJ69mD6qgjX563A'
bot = telebot.TeleBot(API_TOKEN)

DATABASE_URL = "postgresql://neondb_owner:npg_GVlwd8kbrTz6@ep-red-king-ai5otk5k.c-4.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"

ADMIN_IDS = [1426422446, 1112769561] 
WHATSAPP_STAFF = ["249908787018", "249126335052", "249118739777"]

user_carts = {} 
user_states = {} 
temp_orders = {} 
temp_product_data = {} 

# --- تحسين السرعة: إدارة الاتصال الدائم ---
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
    except psycopg2.InterfaceError:
        db_conn = psycopg2.connect(DATABASE_URL)
        db_conn.autocommit = True
        return db_conn.cursor()

def init_db():
    with get_cursor() as cursor:
        cursor.execute('''CREATE TABLE IF NOT EXISTS products 
                          (id SERIAL PRIMARY KEY, 
                           name TEXT, description TEXT, price INTEGER, 
                           availability TEXT, image_url TEXT)''')

init_db()

def is_admin(user_id):
    return user_id in ADMIN_IDS

# --- 3. لوحة التحكم ---

@bot.message_handler(func=lambda message: message.text == "⚙️ لوحة التحكم")
def admin_panel(message):
    if is_admin(message.from_user.id):
        markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
        markup.add(types.KeyboardButton("➕ إضافة منتج"), types.KeyboardButton("🗑️ حذف منتج"))
        markup.add(types.KeyboardButton("✏️ تعديل منتج"), types.KeyboardButton("🔙 الرجوع للقائمة الرئيسية"))
        bot.send_message(message.chat.id, "🛠️ لوحة تحكم الإدارة:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "➕ إضافة منتج")
def ask_add(message):
    if is_admin(message.from_user.id):
        msg = bot.send_message(message.chat.id, "أرسل البيانات بالترتيب:\nالاسم | الوصف | السعر | الحالة")
        bot.register_next_step_handler(msg, ask_for_photo)

def ask_for_photo(message):
    try:
        data = [i.strip() for i in message.text.split('|')]
        if len(data) < 4: raise ValueError
        temp_product_data[message.chat.id] = data
        msg = bot.send_message(message.chat.id, f"✅ تمام، هسي أرسل (صورة) المنتج '{data[0]}':")
        bot.register_next_step_handler(msg, save_product_final)
    except:
        bot.send_message(message.chat.id, "❌ خطأ! تأكد من التنسيق واستخدام الفاصل |")

def save_product_final(message):
    if message.content_type != 'photo':
        bot.send_message(message.chat.id, "❌ لازم ترسل صورة!")
        return
    try:
        data = temp_product_data.get(message.chat.id)
        photo_id = message.photo[-1].file_id
        with get_cursor() as cursor:
            cursor.execute("INSERT INTO products (name, description, price, availability, image_url) VALUES (%s,%s,%s,%s,%s)", 
                           (data[0], data[1], int(data[2]), data[3], photo_id))
        bot.send_message(message.chat.id, f"✅ تم إضافة {data[0]} بنجاح!")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ حدث خطأ: {e}")

@bot.message_handler(func=lambda message: message.text == "🗑️ حذف منتج")
def ask_delete(message):
    if is_admin(message.from_user.id):
        with get_cursor() as cursor:
            cursor.execute("SELECT name FROM products")
            prods = cursor.fetchall()
        if not prods: bot.send_message(message.chat.id, "المتجر فارغ."); return
        markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
        for p in prods: markup.add(types.KeyboardButton(f"❌ حذف: {p[0]}"))
        markup.add(types.KeyboardButton("🔙 الرجوع للقائمة الرئيسية"))
        bot.send_message(message.chat.id, "اختار المنتج للحذف:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text.startswith("❌ حذف: "))
def confirm_delete(message):
    if is_admin(message.from_user.id):
        p_name = message.text.replace("❌ حذف: ", "")
        with get_cursor() as cursor:
            cursor.execute("DELETE FROM products WHERE name = %s", (p_name,))
        bot.send_message(message.chat.id, f"🗑️ تم الحذف.")
        admin_panel(message)

@bot.message_handler(func=lambda message: message.text == "✏️ تعديل منتج")
def ask_edit_name(message):
    if is_admin(message.from_user.id):
        with get_cursor() as cursor:
            cursor.execute("SELECT name FROM products")
            prods = cursor.fetchall()
        if not prods: bot.send_message(message.chat.id, "المتجر فارغ."); return
        markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
        for p in prods: markup.add(types.KeyboardButton(f"📝 تعديل: {p[0]}"))
        markup.add(types.KeyboardButton("🔙 الرجوع للقائمة الرئيسية"))
        bot.send_message(message.chat.id, "اختار المنتج الذي تريد تعديله:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text.startswith("📝 تعديل: "))
def show_edit_options(message):
    p_name = message.text.replace("📝 تعديل: ", "")
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM products WHERE name = %s", (p_name,))
        item = cursor.fetchone()
    if item:
        temp_product_data[message.chat.id] = list(item)
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🏷️ الاسم", callback_data="edit_val_1"),
            types.InlineKeyboardButton("📝 الوصف", callback_data="edit_val_2"),
            types.InlineKeyboardButton("💰 السعر", callback_data="edit_val_3"),
            types.InlineKeyboardButton("✅ الحالة", callback_data="edit_val_4"),
            types.InlineKeyboardButton("🖼️ الصورة", callback_data="edit_val_5"),
            types.InlineKeyboardButton("💾 حفظ التعديلات", callback_data="save_edits")
        )
        info = f"🛠️ **تعديل المنتج:** {item[1]}\n\n1. الاسم: {item[1]}\n2. الوصف: {item[2]}\n3. السعر: {item[3]}\n4. الحالة: {item[4]}"
        bot.send_message(message.chat.id, info, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("edit_val_"))
def prompt_edit_field(call):
    field_idx = int(call.data.split("_")[2])
    field_names = ["", "الاسم", "الوصف", "السعر", "الحالة", "الصورة"]
    user_states[call.message.chat.id] = f"waiting_edit_{field_idx}"
    bot.send_message(call.message.chat.id, f"أرسل القيمة الجديدة لـ ({field_names[field_idx]}):")

@bot.callback_query_handler(func=lambda call: call.data == "save_edits")
def final_save_edit(call):
    data = temp_product_data.get(call.message.chat.id)
    if data:
        with get_cursor() as cursor:
            cursor.execute("UPDATE products SET name=%s, description=%s, price=%s, availability=%s, image_url=%s WHERE id=%s", 
                           (data[1], data[2], data[3], data[4], data[5], data[0]))
        bot.answer_callback_query(call.id, "✅ تم الحفظ بنجاح!")
        bot.send_message(call.message.chat.id, "✅ تم تحديث بيانات المنتج بنجاح.")

# --- 4. الوظائف الأساسية ---

@bot.message_handler(commands=['start'])
def start(message):
    user_carts[message.chat.id] = []
    show_main_menu(message)

def show_main_menu(message):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(types.KeyboardButton("🛍️ تصفح المنتجات"), types.KeyboardButton("🔍 بحث عن منتج"))
    markup.add(types.KeyboardButton("✨ فحص نوع البشرة (الخبير الآلي)"), types.KeyboardButton("🛒 عرض السلة / إتمام الطلب"))
    markup.add(types.KeyboardButton("☎️ تواصل مع المبيعات"), types.KeyboardButton("👨‍💻 مطور النظام"))
    if is_admin(message.from_user.id): markup.add(types.KeyboardButton("⚙️ لوحة التحكم"))
    bot.send_message(message.chat.id, "✨ مرحباً بكِ في ڤِلوريا بيوتي ✨", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "🔙 الرجوع للقائمة الرئيسية")
def back_home(message): show_main_menu(message)

@bot.message_handler(func=lambda message: message.text == "🛒 عرض السلة / إتمام الطلب")
def cart_handler(message):
    show_cart(message)

@bot.message_handler(func=lambda message: message.text == "✨ فحص نوع البشرة (الخبير الآلي)")
def skin_expert(message):
    bot.send_message(message.chat.id, "🚧 هذه الميزة قيد التطوير حالياً، سيتم إطلاقها قريباً في تحديث ڤِلوريا القادم! 🌸")

@bot.message_handler(func=lambda message: message.text == "☎️ تواصل مع المبيعات")
def contact_sales(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("👩‍💼 تليجرام", url="https://t.me/Julie_53"),
               types.InlineKeyboardButton("🟢 واتساب 1", url=f"https://wa.me/{WHATSAPP_STAFF[0]}"),
               types.InlineKeyboardButton("🟢 واتساب 2", url=f"https://wa.me/{WHATSAPP_STAFF[1]}"),
               types.InlineKeyboardButton("🟢 واتساب 3", url=f"https://wa.me/{WHATSAPP_STAFF[2]}"))
    bot.send_message(message.chat.id, "فريق المبيعات جاهز لخدمتك:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "👨‍💻 مطور النظام")
def contact_dev(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💬 مراسلة المطور", url="https://t.me/Gafar53_bot"))
    bot.send_message(message.chat.id, "للاستفسارات التقنية وتطوير الأنظمة:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "🛍️ تصفح المنتجات")
def list_products(message):
    with get_cursor() as cursor:
        cursor.execute("SELECT name FROM products")
        products = cursor.fetchall()
    if not products: bot.send_message(message.chat.id, "المتجر فارغ."); return
    # تم التعديل هنا ليكون عرض الصف 4 منتجات
    markup = types.ReplyKeyboardMarkup(row_width=4, resize_keyboard=True)
    for p in products: markup.add(types.KeyboardButton(p[0]))
    markup.add(types.KeyboardButton("🔙 الرجوع للقائمة الرئيسية"))
    bot.send_message(message.chat.id, "👇 اختاري منتجاً:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "🔍 بحث عن منتج")
def search_prompt(message):
    user_states[message.chat.id] = "searching"
    bot.send_message(message.chat.id, "🔎 أرسلي اسم المنتج للبحث:")

# --- 5. معالج الرسائل العام ---
@bot.message_handler(content_types=['text', 'photo'])
def handle_all_messages(message):
    chat_id = message.chat.id
    state = user_states.get(chat_id)

    if state and state.startswith("waiting_edit_"):
        idx = int(state.split("_")[2])
        if idx == 5:
            if message.content_type == 'photo':
                temp_product_data[chat_id][idx] = message.photo[-1].file_id
                bot.send_message(chat_id, "✅ تم استلام الصورة. اضغط 'حفظ'.")
            else: bot.send_message(chat_id, "❌ أرسل صورة!")
        else:
            temp_product_data[chat_id][idx] = message.text
            bot.send_message(chat_id, f"✅ تم التحديث مؤقتاً لـ ({message.text}).")
        user_states[chat_id] = None
        return

    if state == "waiting_phone":
        phone = message.text
        order = temp_orders.get(chat_id)
        if order:
            final_summary = f"طلب جديد:\n👤 الزبون: {order['customer']}\n📞 هاتف: {phone}\n📋 الطلبات:\n{order['details']}\n💰 المجموع: {order['total']} ج.س"
            for admin_id in ADMIN_IDS:
                try: bot.send_message(admin_id, f"🔔 طلب جديد!\n\n{final_summary}")
                except: continue
            enc = urllib.parse.quote(final_summary)
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(types.InlineKeyboardButton("🟢 واتساب (عمران)", url=f"https://wa.me/{WHATSAPP_STAFF[0]}?text={enc}"),
                       types.InlineKeyboardButton("🟢 واتساب (جعفر)", url=f"https://wa.me/{WHATSAPP_STAFF[1]}?text={enc}"),
                       types.InlineKeyboardButton("🟢 واتساب (ريان)", url=f"https://wa.me/{WHATSAPP_STAFF[2]}?text={enc}"))
            bot.send_message(chat_id, "✅ تم تسجيل طلبك! أرسله للموظف:", reply_markup=markup)
            user_carts[chat_id] = []; user_states[chat_id] = None
        return

    if state == "searching":
        query = message.text.lower()
        with get_cursor() as cursor:
            cursor.execute("SELECT * FROM products WHERE LOWER(name) LIKE %s", ('%' + query + '%',))
            items = cursor.fetchall()
        if items:
            for item in items: display_product_from_db(message, item)
        else: bot.send_message(chat_id, "❌ لم يتم العثور عليه.")
        user_states[chat_id] = None; return

    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM products WHERE name = %s", (message.text,))
        product = cursor.fetchone()
    if product: display_product_from_db(message, product)

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    chat_id = call.message.chat.id
    if call.data.startswith("add_"):
        p_name = call.data.replace("add_", "")
        with get_cursor() as cur:
            cur.execute("SELECT price FROM products WHERE name = %s", (p_name,))
            price = cur.fetchone()
        if price:
            if chat_id not in user_carts: user_carts[chat_id] = []
            user_carts[chat_id].append({'name': p_name, 'price': price[0]})
            bot.answer_callback_query(call.id, f"✅ تمت إضافة {p_name}")
    elif call.data.startswith("remove_"):
        idx = int(call.data.split("_")[1])
        if chat_id in user_carts and len(user_carts[chat_id]) > idx:
            user_carts[chat_id].pop(idx)
            bot.delete_message(chat_id, call.message.message_id)
            show_cart(call.message)
    elif call.data == "confirm_order":
        cart = user_carts.get(chat_id, [])
        if cart:
            total = sum(item['price'] for item in cart)
            details = "\n".join([f"- {i['name']} ({i['price']})" for i in cart])
            user = f"@{call.from_user.username}" if call.from_user.username else call.from_user.first_name
            temp_orders[chat_id] = {"details": details, "total": total, "customer": user}
            user_states[chat_id] = "waiting_phone"
            bot.edit_message_text("📱 أرسلي رقم هاتف الواتساب الخاص بكِ:", chat_id, call.message.message_id)

def show_cart(message):
    cart = user_carts.get(message.chat.id, [])
    if not cart: bot.send_message(message.chat.id, "سلتك فارغة حالياً. 🌸"); return
    total = sum(item['price'] for item in cart)
    items_text = "🛍️ **محتويات سلتك:**\n\n"
    markup = types.InlineKeyboardMarkup(row_width=1)
    for index, item in enumerate(cart):
        items_text += f"{index+1}. {item['name']} ({item['price']} ج.س)\n"
        markup.add(types.InlineKeyboardButton(f"❌ حذف {item['name']}", callback_data=f"remove_{index}"))
    items_text += f"\n💰 **الإجمالي: {total} ج.س**"
    markup.add(types.InlineKeyboardButton("✅ تأكيد وإرسال الطلب", callback_data="confirm_order"))
    bot.send_message(message.chat.id, items_text, reply_markup=markup, parse_mode="Markdown")

def display_product_from_db(message, item):
    cap = f"🌸 **المنتج:** {item[1]}\n\n📝 **الوصف:** {item[2]}\n💰 **السعر:** {item[3]} ج.س\n✅ **الحالة:** {item[4]}"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("➕ إضافة للسلة", callback_data=f"add_{item[1]}"))
    try: bot.send_photo(message.chat.id, item[5], caption=cap, reply_markup=markup, parse_mode="Markdown")
    except: bot.send_message(message.chat.id, cap, reply_markup=markup, parse_mode="Markdown")

# --- التعديل الذكي لمنع Render من إغلاق البوت ---
if __name__ == "__main__":
    # 1. تشغيل السيرفر المساعد أولاً لفتح المنفذ لـ Render
    keep_alive() 
    print("Keep-alive server is running on port 8080...")
    
    # 2. مهلة قصيرة لضمان استقرار السيرفر قبل بدء البوت
    time.sleep(2)
    
    # 3. تشغيل البوت في حلقة (Loop) لضمان عدم توقفه نهائياً
    while True:
        try:
            bot.infinity_polling(timeout=10, long_polling_timeout=5)
        except Exception as e:
            print(f"Error occurred: {e}. Restarting bot in 5 seconds...")
            time.sleep(5)
