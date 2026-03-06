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
def staff_management(message):
    if is_admin(message.from_user.id):
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("➕ إضافة موظف", callback_data="staff_add"),
            types.InlineKeyboardButton("🗑️ حذف موظف", callback_data="staff_view_delete"),
            types.InlineKeyboardButton("✏️ تعديل موظف", callback_data="staff_view_edit")
        )
        bot.send_message(message.chat.id, "👥 إدارة فريق المبيعات:", reply_markup=markup)

# --- نظام تعديل المنتج المطور بالأزرار ---

@bot.message_handler(func=lambda message: message.text == "✏️ تعديل منتج")
def edit_product_list(message):
    if is_admin(message.from_user.id):
        with get_cursor() as cur:
            cur.execute("SELECT id, name FROM products")
            prods = cur.fetchall()
        if not prods:
            bot.send_message(message.chat.id, "المتجر فارغ.")
            return
        markup = types.InlineKeyboardMarkup()
        for p in prods:
            markup.add(types.InlineKeyboardButton(f"✏️ {p[1]}", callback_data=f"edit_select_{p[0]}"))
        bot.send_message(message.chat.id, "اختار المنتج الذي تود تعديله:", reply_markup=markup)

def show_edit_menu(chat_id, product_id, message_id=None):
    with get_cursor() as cur:
        cur.execute("SELECT * FROM products WHERE id=%s", (product_id,))
        p = cur.fetchone()
    
    # تخزين البيانات الحالية في الذاكرة المؤقتة للتعديل
    if chat_id not in temp_product_data or temp_product_data[chat_id].get('id') != product_id:
        temp_product_data[chat_id] = {
            'id': p[0], 'name': p[1], 'desc': p[2], 'price': p[3], 'avail': p[4], 'img': p[5]
        }
    
    td = temp_product_data[chat_id]
    text = f"🛠️ **تعديل منتج:**\n\n" \
           f"🏷️ الاسم: {td['name']}\n" \
           f"📝 الوصف: {td['desc']}\n" \
           f"💰 السعر: {td['price']} ج.س\n" \
           f"✅ الحالة: {td['avail']}"
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📝 تعديل الاسم", callback_data=f"pedit_field_name_{product_id}"),
        types.InlineKeyboardButton("📄 تعديل الوصف", callback_data=f"pedit_field_desc_{product_id}"),
        types.InlineKeyboardButton("💰 تعديل السعر", callback_data=f"pedit_field_price_{product_id}"),
        types.InlineKeyboardButton("✅ تعديل الحالة", callback_data=f"pedit_field_avail_{product_id}"),
        types.InlineKeyboardButton("🖼️ تعديل الصورة", callback_data=f"pedit_field_img_{product_id}"),
        types.InlineKeyboardButton("💾 حفظ كل التعديلات", callback_data=f"pedit_save_{product_id}"),
        types.InlineKeyboardButton("❌ إلغاء", callback_data="pedit_cancel")
    )

    if message_id:
        try: bot.edit_message_caption(text, chat_id, message_id, reply_markup=markup, parse_mode="Markdown")
        except: bot.send_photo(chat_id, td['img'], caption=text, reply_markup=markup, parse_mode="Markdown")
    else:
        bot.send_photo(chat_id, td['img'], caption=text, reply_markup=markup, parse_mode="Markdown")

# --- الرد على مطور النظام ---
@bot.message_handler(func=lambda message: message.text == "👨‍💻 مطور النظام")
def developer_info(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💬 تواصل مع المطور", url="https://t.me/Gafar53_bot"))
    bot.send_message(message.chat.id, "👨‍💻 تم تطوير هذا النظام لتوفير أفضل تجربة تسوق.\nيمكنك التواصل مع المطور مباشرة عبر الرابط التالي:", reply_markup=markup)

# --- معالجة Callback Queries ---

@bot.callback_query_handler(func=lambda call: True)
def handle_all_callbacks(call):
    chat_id = call.message.chat.id
    
    # اختيار منتج للتعديل
    if call.data.startswith("edit_select_"):
        pid = call.data.split("_")[2]
        show_edit_menu(chat_id, pid)
        bot.delete_message(chat_id, call.message.message_id)

    # اختيار حقل معين لتعديله
    elif call.data.startswith("pedit_field_"):
        parts = call.data.split("_")
        field = parts[2]
        pid = parts[3]
        user_states[chat_id] = f"typing_{field}_{pid}"
        field_ar = {"name":"الاسم", "desc":"الوصف", "price":"السعر", "avail":"الحالة", "img":"الصورة"}
        bot.send_message(chat_id, f"أرسل {field_ar[field]} الجديد:")

    # حفظ التعديلات في القاعدة
    elif call.data.startswith("pedit_save_"):
        td = temp_product_data.get(chat_id)
        if td:
            with get_cursor() as cur:
                cur.execute("UPDATE products SET name=%s, description=%s, price=%s, availability=%s, image_url=%s WHERE id=%s",
                            (td['name'], td['desc'], td['price'], td['avail'], td['img'], td['id']))
            bot.answer_callback_query(call.id, "✅ تم حفظ التعديلات بنجاح!")
            bot.delete_message(chat_id, call.message.message_id)
            temp_product_data.pop(chat_id, None)

    elif call.data == "pedit_cancel":
        temp_product_data.pop(chat_id, None)
        bot.delete_message(chat_id, call.message.message_id)
        bot.send_message(chat_id, "تم إلغاء التعديل.")

    # باقي الـ Callbacks الأصلية
    elif call.data.startswith("add_"):
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
        bot.answer_callback_query(call.id, f"✅ تم حذف المنتج")
        bot.delete_message(chat_id, call.message.message_id)

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

# --- معالج الرسائل المطور لاستقبال مدخلات التعديل ---

@bot.message_handler(content_types=['text', 'photo'])
def handle_all_messages(message):
    chat_id = message.chat.id
    state = user_states.get(chat_id, "")

    # إذا كان المستخدم في حالة تعديل حقل معين
    if state.startswith("typing_"):
        parts = state.split("_")
        field = parts[1]
        pid = parts[2]
        
        if field == "img":
            if message.content_type == 'photo':
                temp_product_data[chat_id]['img'] = message.photo[-1].file_id
                bot.send_message(chat_id, "✅ تم استلام الصورة الجديدة.")
            else:
                bot.send_message(chat_id, "❌ الرجاء إرسال صورة!")
                return
        else:
            new_val = message.text
            if field == "price":
                try: new_val = int(new_val)
                except: 
                    bot.send_message(chat_id, "❌ السعر لازم يكون رقم!")
                    return
            
            # تحديث القيمة في الذاكرة المؤقتة
            key_map = {"name":"name", "desc":"desc", "price":"price", "avail":"avail"}
            temp_product_data[chat_id][key_map[field]] = new_val
            bot.send_message(chat_id, f"✅ تم تحديث {field} مؤقتاً.")

        user_states[chat_id] = None
        show_edit_menu(chat_id, pid) # العودة لقائمة التعديل
        return

    # معالجة الطلبات والبحث
    if state == "waiting_phone" and message.text:
        phone = message.text
        order = temp_orders.get(chat_id)
        if order:
            order['phone'] = phone
            final_summary = f"طلب جديد:\n👤 الزبون: {order['customer']}\n📞 هاتف: {phone}\n📋 الطلبات:\n{order['details']}\n💰 المجموع: {order['total']} ج.س"
            for admin_id in ADMIN_IDS:
                try: bot.send_message(admin_id, f"🔔 طلب جديد!\n\n{final_summary}")
                except: continue
            user_carts[chat_id] = []
            user_states[chat_id] = None 
            contact_sales(message)
        return

    # الأوامر العادية
    if message.text == "🔙 الرجوع للقائمة الرئيسية":
        show_main_menu(message)
    elif message.text == "🛍️ تصفح المنتجات":
        list_products(message)
    elif message.text == "🛒 عرض السلة / إتمام الطلب":
        show_cart(message)
    elif message.text == "➕ إضافة منتج":
        ask_add(message)
    # ... (باقي الشروط الأصلية للبحث والموظفين)

# --- دوال الموظفين والبدء المتبقية (لم تتغير) ---

def staff_callbacks(call):
    if call.data == "staff_add":
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🟢 واتساب", callback_data="staff_type_wa"),
                   types.InlineKeyboardButton("🔵 تليجرام", callback_data="staff_type_tg"))
        bot.edit_message_text("اختار نوع الموظف الجديد:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    # ... (تكملة دوال الموظفين كما في الكود السابق)

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

def list_products(message):
    with get_cursor() as cursor:
        cursor.execute("SELECT name FROM products")
        products = cursor.fetchall()
    if not products:
        bot.send_message(message.chat.id, "المتجر فارغ.")
        return
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    row = []
    for p in products:
        row.append(types.KeyboardButton(p[0]))
        if len(row) >= 2: markup.add(*row); row = []
    if row: markup.add(*row)
    markup.add("🔙 الرجوع للقائمة الرئيسية")
    bot.send_message(message.chat.id, "👇 اختاري منتجاً من القائمة:", reply_markup=markup)

def contact_sales(message):
    with get_cursor() as cur:
        cur.execute("SELECT name, contact, type FROM staff")
        staff_list = cur.fetchall()
    markup = types.InlineKeyboardMarkup(row_width=1)
    order = temp_orders.get(message.chat.id)
    encoded_text = ""
    if order:
        whatsapp_text = f"مرحباً، أود إتمام طلبي:\n👤 الزبون: {order['customer']}\n📞 الهاتف: {order['phone']}\n📋 المنتجات:\n{order['details']}\n💰 الإجمالي: {order['total']} ج.س"
        encoded_text = urllib.parse.quote(whatsapp_text)
    
    for s in staff_list:
        label = f"{'🟢' if s[2]=='whatsapp' else '🔵'} {s[0]}"
        link = f"https://wa.me/{s[1]}?text={encoded_text}" if s[2]=='whatsapp' else f"https://t.me/{s[1].replace('@','')}"
        markup.add(types.InlineKeyboardButton(label, url=link))
    bot.send_message(message.chat.id, "فريق المبيعات جاهز لخدمتك:", reply_markup=markup)

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

def ask_add(message):
    msg = bot.send_message(message.chat.id, "أرسل البيانات بالترتيب: الاسم | الوصف | السعر | الحالة")
    bot.register_next_step_handler(msg, ask_for_photo)

def ask_for_photo(message):
    try:
        data = [i.strip() for i in message.text.split('|')]
        temp_product_data[message.chat.id] = data
        msg = bot.send_message(message.chat.id, f"✅ أرسل صورة لمنتج '{data[0]}':")
        bot.register_next_step_handler(msg, save_product_final)
    except: bot.send_message(message.chat.id, "خطأ في التنسيق.")

def save_product_final(message):
    if message.content_type == 'photo':
        data = temp_product_data.get(message.chat.id)
        with get_cursor() as cursor:
            cursor.execute("INSERT INTO products (name, description, price, availability, image_url) VALUES (%s,%s,%s,%s,%s)", 
                           (data[0], data[1], int(data[2]), data[3], message.photo[-1].file_id))
        bot.send_message(message.chat.id, "✅ تم الإضافة بنجاح!")

if __name__ == "__main__":
    keep_alive() 
    print("Server is running...")
    while True:
        try: bot.infinity_polling(timeout=20, long_polling_timeout=10)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)
