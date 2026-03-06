import telebot
import psycopg2 
from telebot import types
import urllib.parse
import os
from flask import Flask
from threading import Thread
import time 

# --- إعداد سيرفر الـ Keep-alive ---
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

# 1. إعدادات البوت
API_TOKEN = '8408686144:AAGy8jf4_fkJCjTCWMRLUJ69mD6qgjX563A'
bot = telebot.TeleBot(API_TOKEN)

DATABASE_URL = "postgresql://neondb_owner:npg_GVlwd8kbrTz6@ep-red-king-ai5otk5k.c-4.us-east-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
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
        db_conn = psycopg2.connect(DATABASE_URL)
        db_conn.autocommit = True
        return db_conn.cursor()

def init_db():
    with get_cursor() as cursor:
        cursor.execute('''CREATE TABLE IF NOT EXISTS products 
                          (id SERIAL PRIMARY KEY, name TEXT, description TEXT, price INTEGER, availability TEXT, image_url TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS staff 
                          (id SERIAL PRIMARY KEY, name TEXT, contact TEXT, type TEXT)''')
init_db()

def is_admin(user_id):
    return user_id in ADMIN_IDS

# --- 2. الدوال الأساسية وواجهة المستخدم ---

@bot.message_handler(commands=['start'])
def start(message):
    user_carts[message.chat.id] = []
    user_states[message.chat.id] = None # تصفير الحالة عند البداية
    show_main_menu(message)

def show_main_menu(message):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add("🛍️ تصفح المنتجات", "🔍 بحث عن منتج")
    markup.add("✨ فحص نوع البشرة (الخبير الآلي)", "🛒 عرض السلة / إتمام الطلب")
    markup.add("☎️ تواصل مع المبيعات", "👨‍💻 مطور النظام")
    if is_admin(message.from_user.id): markup.add("⚙️ لوحة التحكم")
    bot.send_message(message.chat.id, "✨ مرحباً بكِ في ڤِلوريا بيوتي ✨\nكيف يمكننا مساعدتك اليوم؟", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "🔙 الرجوع للقائمة الرئيسية")
def back_home(message):
    user_states[message.chat.id] = None
    show_main_menu(message)

# --- 3. تصفح المنتجات بتنسيق ذكي ---
@bot.message_handler(func=lambda message: message.text == "🛍️ تصفح المنتجات")
def list_products(message):
    user_states[message.chat.id] = "browsing" # تحديد حالة التصفح
    with get_cursor() as cursor:
        cursor.execute("SELECT name FROM products")
        products = cursor.fetchall()
    
    if not products:
        bot.send_message(message.chat.id, "المتجر فارغ حالياً.")
        return

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    row = []
    for p in products:
        name = p[0]
        row.append(types.KeyboardButton(name))
        # ترتيب ذكي: لو الاسم قصير (أقل من 12 حرف) حط 3، لو طويل حط 2
        limit = 3 if len(name) < 12 else 2
        if len(row) >= limit:
            markup.add(*row)
            row = []
    if row: markup.add(*row)
    markup.add("🔙 الرجوع للقائمة الرئيسية")
    bot.send_message(message.chat.id, "👇 اختاري منتجاً لعرض تفاصيله:", reply_markup=markup)

# --- 4. معالج الرسائل النصية الشامل (تم إصلاحه) ---
@bot.message_handler(func=lambda message: True, content_types=['text'])
def handle_texts(message):
    chat_id = message.chat.id
    text = message.text
    state = user_states.get(chat_id)

    # 1. إذا كان المستخدم في حالة إدخال رقم الهاتف لإتمام الطلب
    if state == "waiting_phone":
        order = temp_orders.get(chat_id)
        if order:
            final_summary = f"📦 طلب جديد من ڤِلوريا:\n👤 الزبون: {order['customer']}\n📞 هاتف: {text}\n📋 الأصناف:\n{order['details']}\n💰 الإجمالي: {order['total']} ج.س"
            
            # إرسال للمشرفين
            for admin_id in ADMIN_IDS:
                try: bot.send_message(admin_id, f"🔔 {final_summary}")
                except: continue
            
            # عرض موظفي البيع للزبون بعد إرسال الطلب
            user_carts[chat_id] = [] # تفريغ السلة
            user_states[chat_id] = None # إنهاء الحالة
            
            bot.send_message(chat_id, "✅ تم تسجيل طلبك بنجاح!")
            contact_sales(message) # عرض الموظفين فوراً ليراسلهم
        return

    # 2. إذا كان المستخدم يضغط على اسم منتج
    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM products WHERE name = %s", (text,))
        product = cursor.fetchone()
    
    if product:
        display_product_from_db(message, product)
        return

    # 3. الأوامر الأخرى
    if text == "🛒 عرض السلة / إتمام الطلب":
        show_cart(message)
    elif text == "☎️ تواصل مع المبيعات":
        contact_sales(message)
    elif text == "⚙️ لوحة التحكم":
        admin_panel(message)
    elif text == "➕ إضافة منتج":
        ask_add(message)
    elif text == "👥 إدارة الموظفين":
        staff_management(message)

# --- 5. وظائف الطلبات والسلة ---

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
            bot.answer_callback_query(call.id, f"✅ تمت إضافة {p_name} للسلة")

    elif call.data == "confirm_order":
        cart = user_carts.get(chat_id, [])
        if not cart:
            bot.answer_callback_query(call.id, "السلة فارغة!")
            return
        total = sum(item['price'] for item in cart)
        details = "\n".join([f"- {i['name']} ({i['price']})" for i in cart])
        user = f"@{call.from_user.username}" if call.from_user.username else call.from_user.first_name
        temp_orders[chat_id] = {"details": details, "total": total, "customer": user}
        
        user_states[chat_id] = "waiting_phone"
        bot.send_message(chat_id, "📱 لطفا، أرسلي رقم هاتف الواتساب الخاص بكِ لإكمال الطلب:")
        bot.answer_callback_query(call.id)

    elif call.data.startswith("remove_"):
        idx = int(call.data.split("_")[1])
        if chat_id in user_carts and len(user_carts[chat_id]) > idx:
            user_carts[chat_id].pop(idx)
            bot.delete_message(chat_id, call.message.message_id)
            show_cart(call.message)

    # معالجة كولباك الموظفين
    elif call.data.startswith("staff_"):
        handle_staff_callbacks(call)

def contact_sales(message):
    with get_cursor() as cur:
        cur.execute("SELECT name, contact, type FROM staff")
        staff_list = cur.fetchall()
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    if not staff_list:
        markup.add(types.InlineKeyboardButton("👩‍💼 تليجرام المبيعات الرسمي", url="https://t.me/Julie_53"))
    else:
        for s in staff_list:
            label = f"{'🟢 واتساب' if s[2]=='whatsapp' else '🔵 تليجرام'}: {s[0]}"
            link = f"https://wa.me/{s[1]}" if s[2]=='whatsapp' else f"https://t.me/{s[1].replace('@','')}"
            markup.add(types.InlineKeyboardButton(label, url=link))
    bot.send_message(message.chat.id, "يرجى اختيار موظف لمتابعة طلبك أو للاستفسار:", reply_markup=markup)

def display_product_from_db(message, item):
    cap = f"🌸 **المنتج:** {item[1]}\n\n📝 **الوصف:** {item[2]}\n💰 **السعر:** {item[3]} ج.س\n✅ **الحالة:** {item[4]}"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("➕ إضافة للسلة", callback_data=f"add_{item[1]}"))
    try:
        bot.send_photo(message.chat.id, item[5], caption=cap, reply_markup=markup, parse_mode="Markdown")
    except:
        bot.send_message(message.chat.id, cap, reply_markup=markup, parse_mode="Markdown")

# --- 6. لوحة التحكم (تم الإبقاء عليها كاملة) ---
def admin_panel(message):
    if is_admin(message.from_user.id):
        markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
        markup.add("➕ إضافة منتج", "🗑️ حذف منتج", "✏️ تعديل منتج", "👥 إدارة الموظفين", "🔙 الرجوع للقائمة الرئيسية")
        bot.send_message(message.chat.id, "🛠️ لوحة تحكم الإدارة:", reply_markup=markup)

def staff_management(message):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("➕ إضافة موظف", callback_data="staff_add"),
               types.InlineKeyboardButton("🗑️ حذف موظف", callback_data="staff_view_delete"))
    bot.send_message(message.chat.id, "👥 إدارة الموظفين:", reply_markup=markup)

def handle_staff_callbacks(call):
    if call.data == "staff_add":
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🟢 واتساب", callback_data="staff_type_wa"),
                   types.InlineKeyboardButton("🔵 تليجرام", callback_data="staff_type_tg"))
        bot.edit_message_text("اختار نوع الموظف:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    elif call.data.startswith("staff_type_"):
        stype = "whatsapp" if "wa" in call.data else "telegram"
        temp_staff_data[call.message.chat.id] = {"type": stype}
        msg = bot.send_message(call.message.chat.id, "أرسل: الاسم | الرقم (أو المعرف)")
        bot.register_next_step_handler(msg, save_staff)

def save_staff(message):
    try:
        name, contact = [i.strip() for i in message.text.split('|')]
        stype = temp_staff_data[message.chat.id]['type']
        with get_cursor() as cur:
            cur.execute("INSERT INTO staff (name, contact, type) VALUES (%s, %s, %s)", (name, contact, stype))
        bot.send_message(message.chat.id, f"✅ تم حفظ الموظف {name}")
    except:
        bot.send_message(message.chat.id, "❌ خطأ في التنسيق!")

# --- تشغيل البوت ---
if __name__ == "__main__":
    keep_alive()
    print("Veloria Bot is running...")
    while True:
        try:
            bot.infinity_polling(timeout=20, long_polling_timeout=10)
        except Exception as e:
            time.sleep(5)
