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
            types.InlineKeyboardButton("🗑️ حذف موظف", callback_data="staff_view_delete"),
            types.InlineKeyboardButton("✏️ تعديل موظف", callback_data="staff_view_edit")
        )
        bot.send_message(message.chat.id, "👥 إدارة فريق المبيعات:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("staff_"))
def staff_callbacks(call):
    if call.data == "staff_add":
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🟢 واتساب", callback_data="staff_type_wa"),
                   types.InlineKeyboardButton("🔵 تليجرام", callback_data="staff_type_tg"))
        bot.edit_message_text("اختار نوع الموظف الجديد:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    
    elif call.data.startswith("staff_type_"):
        stype = "whatsapp" if "wa" in call.data else "telegram"
        temp_staff_data[call.message.chat.id] = {"type": stype}
        msg = bot.send_message(call.message.chat.id, "أرسل بيانات الموظف بالتنسيق التالي:\nالاسم | المعرف أو الرقم")
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
            markup.add(types.InlineKeyboardButton(f"❌ حذف: {s[1]}", callback_data=f"staff_del_{s[0]}"))
        bot.edit_message_text("اختار الموظف لحذفه:", call.message.chat.id, call.message.message_id, reply_markup=markup)

    elif call.data == "staff_view_edit":
        with get_cursor() as cur:
            cur.execute("SELECT id, name, contact, type FROM staff")
            all_staff = cur.fetchall()
        if not all_staff:
            bot.answer_callback_query(call.id, "لا يوجد موظفين لتعديلهم")
            return
        markup = types.InlineKeyboardMarkup()
        for s in all_staff:
            markup.add(types.InlineKeyboardButton(f"✏️ تعديل: {s[1]}", callback_data=f"staff_edit_{s[0]}"))
        bot.edit_message_text("اختار الموظف لتعديل بياناته:", call.message.chat.id, call.message.message_id, reply_markup=markup)

    elif call.data.startswith("staff_edit_"):
        sid = call.data.split("_")[2]
        with get_cursor() as cur:
            cur.execute("SELECT name, contact, type FROM staff WHERE id=%s", (sid,))
            s = cur.fetchone()
        temp_staff_data[call.message.chat.id] = {"id": sid, "old_n": s[0], "old_c": s[1], "old_t": s[2]}
        msg = bot.send_message(call.message.chat.id, f"تعديل الموظف ({s[0]}).\nأرسل البيانات الجديدة (الاسم | الرقم | النوع) أو اكتب '-' للبيانات التي لا تود تغييرها:")
        bot.register_next_step_handler(msg, update_staff_db)

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

def update_staff_db(message):
    try:
        sd = temp_staff_data[message.chat.id]
        parts = [i.strip() for i in message.text.split('|')]
        new_name = parts[0] if parts[0] != '-' else sd['old_n']
        new_contact = parts[1] if len(parts)>1 and parts[1] != '-' else sd['old_c']
        new_type = parts[2] if len(parts)>2 and parts[2] != '-' else sd['old_t']
        
        with get_cursor() as cur:
            cur.execute("UPDATE staff SET name=%s, contact=%s, type=%s WHERE id=%s", (new_name, new_contact, new_type, sd['id']))
        bot.send_message(message.chat.id, "✅ تم تحديث بيانات الموظف بنجاح!")
    except:
        bot.send_message(message.chat.id, "❌ خطأ! التنسيق: الاسم | الرقم | النوع")

# --- 4. الوظائف الأساسية ---

@bot.message_handler(commands=['start'])
def start(message):
    user_carts[message.chat.id] = []
    user_states[message.chat.id] = None
    show_main_menu(message)

def show_main_menu(message):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add("🛍️ تصفح المنتجات", "🔍 بحث عن منتج")
    markup.add("✨ فحص نوع البشرة (الخبير الآلي)", "🛒 عرض السلة / إتمام الطلب")
    markup.add("☎️ تواصل مع المبيعات", "👨‍💻 مطور النظام")
    if is_admin(message.from_user.id): markup.add("⚙️ لوحة التحكم")
    bot.send_message(message.chat.id, "✨ مرحباً بكِ في ڤِلوريا بيوتي ✨", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "🔙 الرجوع للقائمة الرئيسية")
def back_home(message): 
    user_states[message.chat.id] = None
    show_main_menu(message)

@bot.message_handler(func=lambda message: message.text == "👨‍💻 مطور النظام")
def developer_info(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💬 تواصل مع المطور", url="https://t.me/Veloria_Admin_Bot")) # استبدل بـ username بوتك
    bot.send_message(message.chat.id, "👨‍💻 تم تطوير هذا النظام لتوفير أفضل تجربة تسوق.\nيمكنك التواصل مع المطور عبر البوت الرسمي:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "✨ فحص نوع البشرة (الخبير الآلي)")
def skin_expert(message):
    bot.send_message(message.chat.id, "⏳ جاري تحضير الخبير الآلي لفحص البشرة... هذه الميزة ستتوفر قريباً بشكل كامل.")

@bot.message_handler(func=lambda message: message.text == "🔍 بحث عن منتج")
def search_product_start(message):
    user_states[message.chat.id] = "searching"
    bot.send_message(message.chat.id, "🔍 أرسلي اسم المنتج الذي تبحثين عنه:")

@bot.message_handler(func=lambda message: message.text == "🗑️ حذف منتج")
def delete_product_start(message):
    if is_admin(message.from_user.id):
        with get_cursor() as cur:
            cur.execute("SELECT name FROM products")
            prods = cur.fetchall()
        if not prods:
            bot.send_message(message.chat.id, "المتجر فارغ")
            return
        markup = types.InlineKeyboardMarkup()
        for p in prods:
            markup.add(types.InlineKeyboardButton(f"❌ حذف {p[0]}", callback_data=f"pdel_{p[0]}"))
        bot.send_message(message.chat.id, "اختار المنتج المراد حذفه:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "✏️ تعديل منتج")
def edit_product_start(message):
    if is_admin(message.from_user.id):
        with get_cursor() as cur:
            cur.execute("SELECT name, description, price, availability FROM products")
            prods = cur.fetchall()
        markup = types.InlineKeyboardMarkup()
        for p in prods:
            markup.add(types.InlineKeyboardButton(f"✏️ تعديل {p[0]}", callback_data=f"pedit_{p[0]}"))
        bot.send_message(message.chat.id, "اختار المنتج لتعديله:", reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "🛍️ تصفح المنتجات")
def list_products(message):
    user_states[message.chat.id] = "browsing"
    with get_cursor() as cursor:
        cursor.execute("SELECT name FROM products")
        products = cursor.fetchall()
    
    if not products:
        bot.send_message(message.chat.id, "المتجر فارغ.")
        return

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    row = []
    for p in products:
        name = p[0]
        row.append(types.KeyboardButton(name))
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
    
    # جلب تفاصيل الطلب إذا وجد
    order = temp_orders.get(message.chat.id)
    msg_text = "فريق المبيعات جاهز لخدمتك:"
    
    whatsapp_text = ""
    if order:
        whatsapp_text = f"مرحباً، أود إتمام طلبي:\n👤 الزبون: {order['customer']}\n📞 الهاتف: {order['phone']}\n📋 المنتجات:\n{order['details']}\n💰 الإجمالي: {order['total']} ج.س"
        encoded_text = urllib.parse.quote(whatsapp_text)
        msg_text = "✨ تم تجهيز تفاصيل طلبك! اختاري موظفاً لإرسال الطلب إليه عبر واتساب:"

    if not staff_list:
        markup.add(types.InlineKeyboardButton("👩‍💼 تليجرام المبيعات", url="https://t.me/Julie_53"))
    else:
        for s in staff_list:
            label = f"{'🟢' if s[2]=='whatsapp' else '🔵'} {s[0]}"
            if s[2] == 'whatsapp':
                # الرابط يدعم إرسال النص التلقائي
                link = f"https://wa.me/{s[1]}?text={encoded_text}" if order else f"https://wa.me/{s[1]}"
            else:
                link = f"https://t.me/{s[1].replace('@','')}"
            markup.add(types.InlineKeyboardButton(label, url=link))
            
    bot.send_message(message.chat.id, msg_text, reply_markup=markup)

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

# --- معالج الرسائل العام المطور ---
@bot.message_handler(content_types=['text', 'photo'])
def handle_all_messages(message):
    chat_id = message.chat.id
    state = user_states.get(chat_id)

    if state == "waiting_phone" and message.text:
        phone = message.text
        order = temp_orders.get(chat_id)
        if order:
            order['phone'] = phone # حفظ الرقم في بيانات الطلب
            final_summary = f"طلب جديد:\n👤 الزبون: {order['customer']}\n📞 هاتف: {phone}\n📋 الطلبات:\n{order['details']}\n💰 المجموع: {order['total']} ج.س"
            for admin_id in ADMIN_IDS:
                try: bot.send_message(admin_id, f"🔔 طلب جديد!\n\n{final_summary}")
                except: continue
            
            user_carts[chat_id] = []
            user_states[chat_id] = None 
            contact_sales(message) # عرض الموظفين مع رابط الواتساب الجاهز
        return

    if state == "searching" and message.text:
        with get_cursor() as cur:
            cur.execute("SELECT * FROM products WHERE name ILIKE %s", (f"%{message.text}%",))
            product = cur.fetchone()
        if product:
            display_product_from_db(message, product)
        else:
            bot.send_message(chat_id, "❌ عذراً، لم أجد منتجاً بهذا الاسم.")
        user_states[chat_id] = None
        return

    with get_cursor() as cursor:
        cursor.execute("SELECT * FROM products WHERE name = %s", (message.text,))
        product = cursor.fetchone()
    if product: 
        display_product_from_db(message, product)
        return

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
            
    elif call.data.startswith("pdel_"):
        name = call.data.replace("pdel_", "")
        with get_cursor() as cur:
            cur.execute("DELETE FROM products WHERE name = %s", (name,))
        bot.answer_callback_query(call.id, f"✅ تم حذف المنتج {name}")
        bot.delete_message(chat_id, call.message.message_id)

    elif call.data.startswith("pedit_"):
        name = call.data.replace("pedit_", "")
        with get_cursor() as cur:
            cur.execute("SELECT name, description, price, availability FROM products WHERE name=%s", (name,))
            p = cur.fetchone()
        temp_product_data[chat_id] = {"old_name": name, "old_desc": p[1], "old_price": p[2], "old_avail": p[3]}
        msg = bot.send_message(chat_id, f"تعديل المنتج ({name}).\nأرسل البيانات الجديدة (الاسم | الوصف | السعر | الحالة) أو اكتب '-' للبيانات التي لا تود تغييرها:")
        bot.register_next_step_handler(msg, update_product_db)

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
            bot.send_message(chat_id, "📱 أرسلي رقم هاتف الواتساب الخاص بكِ لإتمام الطلب:")
        bot.answer_callback_query(call.id)
    elif call.data.startswith("staff_"):
        staff_callbacks(call)

def update_product_db(message):
    try:
        pd = temp_product_data[message.chat.id]
        parts = [i.strip() for i in message.text.split('|')]
        # إذا أدخل '-' نستخدم القيمة القديمة
        new_name = parts[0] if parts[0] != '-' else pd['old_name']
        new_desc = parts[1] if len(parts)>1 and parts[1] != '-' else pd['old_desc']
        new_price = int(parts[2]) if len(parts)>2 and parts[2] != '-' else pd['old_price']
        new_avail = parts[3] if len(parts)>3 and parts[3] != '-' else pd['old_avail']
        
        with get_cursor() as cur:
            cur.execute("UPDATE products SET name=%s, description=%s, price=%s, availability=%s WHERE name=%s", 
                        (new_name, new_desc, new_price, new_avail, pd['old_name']))
        bot.send_message(message.chat.id, "✅ تم تحديث المنتج بنجاح!")
    except:
        bot.send_message(message.chat.id, "❌ خطأ في التعديل! تأكد من التنسيق.")

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
