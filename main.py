import telebot
import psycopg2 
from telebot import types
import urllib.parse
import os
from flask import Flask
from threading import Thread
import time 

# --- إعداد سيرفر لاستقبال طلبات الـ Cron-job (Keep-alive) ---
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

ADMIN_IDS = [1426422446, 1112769561] 
# تم تحويل الموظفين لقاعدة بيانات لاحقاً، لكن سنبقي القيم الافتراضية هنا للطوارئ
WHATSAPP_STAFF = ["249908787018", "249126335052", "249118739777"]

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
        db_conn = psycopg2.connect(DATABASE_URL)
        db_conn.autocommit = True
        return db_conn.cursor()

def init_db():
    with get_cursor() as cursor:
        cursor.execute('''CREATE TABLE IF NOT EXISTS products 
                          (id SERIAL PRIMARY KEY, name TEXT, description TEXT, price INTEGER, availability TEXT, image_url TEXT)''')
        # جدول الموظفين الجديد
        cursor.execute('''CREATE TABLE IF NOT EXISTS staff 
                          (id SERIAL PRIMARY KEY, name TEXT, contact TEXT, type TEXT)''')

init_db()

def is_admin(user_id):
    return user_id in ADMIN_IDS

# --- 3. لوحة التحكم المحدثة ---

@bot.message_handler(func=lambda message: message.text == "⚙️ لوحة التحكم")
def admin_panel(message):
    if is_admin(message.from_user.id):
        markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
        markup.add("➕ إضافة منتج", "🗑️ حذف منتج")
        markup.add("✏️ تعديل منتج", "👥 إدارة الموظفين")
        markup.add("🔙 الرجوع للقائمة الرئيسية")
        bot.send_message(message.chat.id, "🛠️ لوحة تحكم الإدارة:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "👥 إدارة الموظفين")
def staff_management(message):
    if is_admin(message.from_user.id):
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("➕ إضافة موظف", callback_data="staff_add"),
            types.InlineKeyboardButton("🗑️ حذف موظف", callback_data="staff_view_delete")
        )
        bot.send_message(message.chat.id, "👥 إدارة فريق المبيعات:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("staff_"))
def staff_callbacks(call):
    if call.data == "staff_add":
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🟢 واتساب", callback_data="staff_type_wa"),
                   types.InlineKeyboardButton("🔵 تليجرام", callback_data="staff_type_tg"))
        bot.edit_message_text("اختار نوع الموظف:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    
    elif call.data.startswith("staff_type_"):
        stype = "whatsapp" if "wa" in call.data else "telegram"
        temp_staff_data[call.message.chat.id] = {"type": stype}
        msg = bot.send_message(call.message.chat.id, "أرسل بيانات الموظف (الاسم | المعرف أو الرقم):")
        bot.register_next_step_handler(msg, save_staff)

    elif call.data == "staff_view_delete":
        with get_cursor() as cur:
            cur.execute("SELECT id, name, type FROM staff")
            all_staff = cur.fetchall()
        if not all_staff:
            bot.answer_callback_query(call.id, "لا يوجد موظفين حالياً")
            return
        markup = types.InlineKeyboardMarkup()
        for s in all_staff:
            markup.add(types.InlineKeyboardButton(f"❌ حذف: {s[1]} ({s[2]})", callback_data=f"staff_del_{s[0]}"))
        bot.edit_message_text("اختار الموظف لحذفه:", call.message.chat.id, call.message.message_id, reply_markup=markup)

    elif call.data.startswith("staff_del_"):
        sid = call.data.split("_")[2]
        with get_cursor() as cur:
            cur.execute("DELETE FROM staff WHERE id = %s", (sid,))
        bot.answer_callback_query(call.id, "✅ تم حذف الموظف")
        bot.delete_message(call.message.chat.id, call.message.message_id)

def save_staff(message):
    try:
        name, contact = [i.strip() for i in message.text.split('|')]
        stype = temp_staff_data[message.chat.id]['type']
        with get_cursor() as cur:
            cur.execute("INSERT INTO staff (name, contact, type) VALUES (%s, %s, %s)", (name, contact, stype))
        bot.send_message(message.chat.id, f"✅ تم إضافة الموظف {name} بنجاح!")
    except:
        bot.send_message(message.chat.id, "❌ خطأ! التنسيق: الاسم | الرقم")

# --- 4. الوظائف الأساسية ---

@bot.message_handler(commands=['start'])
def start(message):
    user_carts[message.chat.id] = []
    show_main_menu(message)

def show_main_menu(message):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add("🛍️ تصفح المنتجات", "🔍 بحث عن منتج")
    markup.add("✨ فحص نوع البشرة (الخبير الآلي)", "🛒 عرض السلة / إتمام الطلب")
    markup.add("☎️ تواصل مع المبيعات", "👨‍💻 مطور النظام")
    if is_admin(message.from_user.id): markup.add("⚙️ لوحة التحكم")
    bot.send_message(message.chat.id, "✨ مرحباً بكِ في ڤِلوريا بيوتي ✨", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "🔙 الرجوع للقائمة الرئيسية")
def back_home(message): show_main_menu(message)

@bot.message_handler(func=lambda message: message.text == "🛍️ تصفح المنتجات")
def list_products(message):
    with get_cursor() as cursor:
        cursor.execute("SELECT name FROM products")
        products = cursor.fetchall()
    
    if not products:
        bot.send_message(message.chat.id, "المتجر فارغ.")
        return

    # ترتيب ذكي للأزرار: الأسماء القصيرة (أقل من 10 حروف) 3 في الصف، الطويلة 1 أو 2
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    row = []
    for p in products:
        name = p[0]
        row.append(types.KeyboardButton(name))
        # إذا الاسم قصير (أقل من 12 حرف) نضع 3 في الصف، لو طويل نكتفي بـ 2
        limit = 3 if len(name) < 12 else 2
        if len(row) >= limit:
            markup.add(*row)
            row = []
    if row: markup.add(*row)
    markup.add(types.KeyboardButton("🔙 الرجوع للقائمة الرئيسية"))
    
    bot.send_message(message.chat.id, "👇 اختاري منتجاً من القائمة:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "☎️ تواصل مع المبيعات")
def contact_sales(message):
    with get_cursor() as cur:
        cur.execute("SELECT name, contact, type FROM staff")
        staff_list = cur.fetchall()
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    if not staff_list:
        # قيم افتراضية في حال عدم وجود موظفين في القاعدة
        markup.add(types.InlineKeyboardButton("👩‍💼 تليجرام المبيعات", url="https://t.me/Julie_53"))
    else:
        for s in staff_list:
            label = f"{'🟢' if s[2]=='whatsapp' else '🔵'} {s[0]}"
            link = f"https://wa.me/{s[1]}" if s[2]=='whatsapp' else f"https://t.me/{s[1].replace('@','')}"
            markup.add(types.InlineKeyboardButton(label, url=link))
            
    bot.send_message(message.chat.id, "فريق المبيعات جاهز لخدمتك:", reply_markup=markup)

# بقية الدوال (إضافة منتج، حذف منتج، سلة التسوق) تبقى كما هي بدون تغيير
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

@bot.message_handler(func=lambda message: message.text == "🛒 عرض السلة / إتمام الطلب")
def cart_handler(message):
    show_cart(message)

# معالج الرسائل العام
@bot.message_handler(content_types=['text', 'photo'])
def handle_all_messages(message):
    chat_id = message.chat.id
    state = user_states.get(chat_id)

    if state == "waiting_phone":
        phone = message.text
        order = temp_orders.get(chat_id)
        if order:
            final_summary = f"طلب جديد:\n👤 الزبون: {order['customer']}\n📞 هاتف: {phone}\n📋 الطلبات:\n{order['details']}\n💰 المجموع: {order['total']} ج.س"
            for admin_id in ADMIN_IDS:
                try: bot.send_message(admin_id, f"🔔 طلب جديد!\n\n{final_summary}")
                except: continue
            bot.send_message(chat_id, "✅ تم تسجيل طلبك بنجاح! فريق المبيعات سيتواصل معكِ.")
            user_carts[chat_id] = []; user_states[chat_id] = None
        return

    # فحص إذا كان النص هو اسم منتج لعرضه
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM products WHERE name = %s", (message.text,))
        product = cursor.fetchone()
    if product: display_product_from_db(message, product)

def show_cart(message):
    cart = user_carts.get(message.chat.id, [])
    if not cart: 
        bot.send_message(message.chat.id, "سلتك فارغة حالياً. 🌸")
        return
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

@bot.callback_query_handler(func=lambda call: True)
def handle_general_callbacks(call):
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
        user_states[chat_id] = "waiting_phone"
        bot.send_message(chat_id, "📱 أرسلي رقم هاتف الواتساب الخاص بكِ لإتمام الطلب:")

if __name__ == "__main__":
    keep_alive() 
    print("Server is running...")
    time.sleep(2)
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)
