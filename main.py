# main.py (النسخة المصححة لمشكلة البث)

import logging
import os
import asyncio
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler, ConversationHandler
from telegram.constants import ChatMemberStatus

# --- إعدادات أساسية (تُقرأ من متغيرات البيئة) ---
try:
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    ADMIN_ID = int(os.environ.get("ADMIN_ID"))
    CHANNEL_ID = os.environ.get("CHANNEL_ID")
except (TypeError, ValueError):
    print("خطأ: لم يتم العثور على متغيرات البيئة. سيتم استخدام القيم المحلية للتجربة.")

# أسماء الملفات لتخزين البيانات
USERS_FILE = "users.txt"
LINKS_FILE = "links.txt"

# إعداد تسجيل الأخطاء
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# حالات المحادثة لميزة البث
BROADCAST_MESSAGE = range(1)

# --- دوال الأدمن وحفظ البيانات (كما هي) ---
def get_all_user_ids():
    if not os.path.exists(USERS_FILE): return []
    try:
        with open(USERS_FILE, "r") as f: return [int(user_id) for user_id in f.read().splitlines()]
    except Exception as e:
        logger.error(f"خطأ في قراءة ملف المستخدمين: {e}")
        return []

def add_user_to_file(user_id: int):
    try:
        if user_id not in get_all_user_ids():
            with open(USERS_FILE, "a") as f: f.write(str(user_id) + "\n")
    except Exception as e: logger.error(f"خطأ في إضافة مستخدم: {e}")

def get_users_count() -> int: return len(get_all_user_ids())
def add_link_to_file(user_id: int, link: str):
    try:
        with open(LINKS_FILE, "a", encoding='utf-8') as f: f.write(f"User_ID: {user_id}, Link: {link}\n")
    except Exception as e: logger.error(f"خطأ في إضافة رابط: {e}")

def get_last_links(count: int = 10) -> str:
    # ... (الكود هنا لم يتغير)
    try:
        if not os.path.exists(LINKS_FILE): return "لم يتم إرسال أي روابط بعد."
        with open(LINKS_FILE, "r", encoding='utf-8') as f:
            lines = f.readlines()
            return "".join(lines[-count:]) if lines else "لا توجد روابط حالياً."
    except Exception as e:
        logger.error(f"خطأ في قراءة الروابط: {e}")
        return "حدث خطأ أثناء قراءة الروابط."

# --- دوال البوت الأساسية ---
async def is_user_subscribed(user_id: int, context: CallbackContext) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except Exception as e:
        logger.error(f"خطأ في التحقق من الاشتراك: {e}")
        return False

async def start_command(update: Update, context: CallbackContext):
    user = update.message.from_user
    add_user_to_file(user.id)
    welcome_message = f"أهلاً بك يا {user.first_name}!\n\n"
    if await is_user_subscribed(user.id, context):
        welcome_message += "أرسل لي أي رابط فيديو وسأقوم بتجهيزه لك."
        await update.message.reply_text(welcome_message)
    else:
        welcome_message += "لاستخدام البوت، يرجى الاشتراك في قناتنا أولاً ثم الضغط على /start مجدداً."
        keyboard = [[InlineKeyboardButton("✅ اضغط هنا للاشتراك", url=f"https://t.me/{CHANNEL_ID.replace('@', '')}")]]
        await update.message.reply_text(welcome_message, reply_markup=InlineKeyboardMarkup(keyboard))

# --- معالجة الروابط والتحميل (كما هي) ---
async def handle_link(update: Update, context: CallbackContext):
    # ... (الكود هنا لم يتغير)
    user_id = update.message.from_user.id
    if not await is_user_subscribed(user_id, context):
        await update.message.reply_text("عذراً، يجب عليك الاشتراك في القناة أولاً. اضغط /start للمحاولة مجدداً.")
        return
    link = update.message.text
    add_link_to_file(user_id, link)
    processing_message = await update.message.reply_text("⏳ جاري استخراج معلومات الفيديو، يرجى الانتظار...")
    try:
        ydl_opts = {'quiet': True, 'dump_json': True, 'skip_download': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(link, download=False)
        context.user_data['video_info'] = info_dict
        formats = [f for f in info_dict.get('formats', []) if f.get('vcodec') != 'none' and f.get('acodec') != 'none' and f.get('height') is not None]
        available_resolutions = sorted(list(set([f['height'] for f in formats if f['height'] in [240, 360, 480, 720]])))
        if not available_resolutions:
            await processing_message.edit_text("لم يتم العثور على جودات فيديو مدعومة (240, 360, 480, 720p).")
            return
        keyboard = []
        for res in available_resolutions:
            best_format = max([f for f in formats if f['height'] == res], key=lambda f: f.get('filesize', 0) or f.get('filesize_approx', 0))
            format_id = best_format['format_id']
            filesize_mb = (best_format.get('filesize') or best_format.get('filesize_approx', 0)) / (1024 * 1024)
            label = f"{res}p"
            if filesize_mb > 0: label += f" ({filesize_mb:.1f} MB)"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"download_{format_id}")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await processing_message.edit_text(f"✅ تم العثور على الفيديو:\n\n*{info_dict.get('title', 'بلا عنوان')}*\n\nاختر جودة الفيديو المطلوبة:", reply_markup=reply_markup, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"خطأ في معالجة الرابط {link}: {e}")
        await processing_message.edit_text("❌ عذراً، لم أتمكن من معالجة هذا الرابط.")

async def button_handler(update: Update, context: CallbackContext):
    # ... (الكود هنا لم يتغير)
    query = update.callback_query
    await query.answer()
    action = query.data
    info = context.user_data.get('video_info')
    if not info:
        await query.edit_message_text("انتهت صلاحية هذه الجلسة. يرجى إرسال الرابط مرة أخرى.")
        return
    if action.startswith('download_'):
        format_id = action.split('_')[-1]
        await query.edit_message_text("⏳ جاري تجهيز الفيديو...")
        await download_and_send(query, context, format_id=format_id)

async def download_and_send(query, context, format_id):
    # ... (الكود هنا لم يتغير)
    info = context.user_data.get('video_info')
    chat_id = query.message.chat_id
    progress_hooks = [lambda d: progress_hook(d, query, context)]
    try:
        ydl_opts = {'format': format_id, 'outtmpl': f'{chat_id}_%(id)s.%(ext)s', 'progress_hooks': progress_hooks, 'noplaylist': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            file_info = ydl.extract_info(info['webpage_url'], download=False)
            filename = ydl.prepare_filename(file_info)
            ydl.download([info['webpage_url']])
        await query.edit_message_text("⬆ جاري رفع الملف إليك...")
        with open(filename, 'rb') as file_to_send:
            await context.bot.send_video(chat_id=chat_id, video=file_to_send, caption=info.get('title', ''), supports_streaming=True)
        await query.delete_message()
    except Exception as e:
        logger.error(f"خطأ في التحميل/الإرسال: {e}")
        await query.edit_message_text(f"❌ حدث خطأ فادح أثناء التحميل.")
    finally:
        if 'filename' in locals() and os.path.exists(filename):
            os.remove(filename)

async def progress_hook(d, query, context):
    # ... (الكود هنا لم يتغير)
    if d['status'] == 'downloading':
        if 'last_update' in context.user_data and (d['_eta_str'] == context.user_data.get('last_update')): return
        percent, speed, eta = d['_percent_str'].strip(), d['_speed_str'].strip(), d['_eta_str'].strip()
        try:
            await query.edit_message_text(f"Downloading...\n\n📊 *التقدم:* {percent}\n⚙ *السرعة:* {speed}\n⏱ *الوقت المتبقي:* {eta}", parse_mode='Markdown')
            context.user_data['last_update'] = eta
        except Exception: pass

# --- أوامر الأدمن (تم تحديثها) ---
async def admin_command(update: Update, context: CallbackContext):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("هذا الأمر مخصص للمالك فقط.")
        return
    keyboard = [
        [InlineKeyboardButton("📊 عرض عدد المستخدمين", callback_data='admin_stats')],
        [InlineKeyboardButton("🔗 عرض آخر 10 روابط", callback_data='admin_links')],
        [InlineKeyboardButton("📢 إرسال رسالة للجميع", callback_data='admin_broadcast')]
    ]
    await update.message.reply_text("أهلاً بك يا مالك البوت! هذه لوحة التحكم:", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("ليس لديك صلاحية.")
        return
    
    if query.data == 'admin_stats':
        await query.edit_message_text(f"إجمالي المستخدمين: {get_users_count()}")
    elif query.data == 'admin_links':
        await query.edit_message_text(f"آخر 10 روابط:\n\n{get_last_links(10)}")
    elif query.data == 'admin_broadcast':
        await query.edit_message_text("حسناً، أرسل الآن الرسالة التي تود إرسالها لجميع المستخدمين. للإلغاء أرسل /cancel.")
        return BROADCAST_MESSAGE

# --- دوال ميزة البث (تم تصحيحها) ---
async def broadcast_message_handler(update: Update, context: CallbackContext):
    message_to_broadcast = update.message
    user_ids = get_all_user_ids()
    await update.message.reply_text(f"تم استلام الرسالة. سأبدأ الآن بإرسالها إلى {len(user_ids)} مستخدم...")
    
    success_count = 0
    fail_count = 0
    
    # هنا نستخدم context.application.bot بدلاً من context.bot
    bot = context.application.bot 
    
    for user_id in user_ids:
        try:
            await bot.copy_message(chat_id=user_id, from_chat_id=update.message.chat_id, message_id=message_to_broadcast.message_id)
            success_count += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"فشل إرسال البث إلى {user_id}: {e}")
            fail_count += 1
            
    await update.message.reply_text(f"✅ اكتمل البث!\n\n- نجح: {success_count}\n- فشل: {fail_count}")
    return ConversationHandler.END

async def cancel_broadcast(update: Update, context: CallbackContext):
    await update.message.reply_text("تم إلغاء عملية البث.")
    return ConversationHandler.END

async def post_init(application: Application):
    """دالة للتهيئة بعد تشغيل البوت"""
    await application.bot.set_my_commands([
        ('start', 'بدء استخدام البوت'),
        ('admin', 'لوحة تحكم المالك')
    ])

async def main():
    """الدالة الرئيسية لتشغيل البوت"""
    # تم إضافة post_init هنا
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    broadcast_conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_button_handler, pattern='^admin_broadcast$')],
        states={
            BROADCAST_MESSAGE: [MessageHandler(filters.ALL & ~filters.COMMAND, broadcast_message_handler)],
        },
        fallbacks=[CommandHandler('cancel', cancel_broadcast)],
        conversation_timeout=300 # مهلة 5 دقائق
    )

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    
    application.add_handler(broadcast_conv_handler)
    application.add_handler(CallbackQueryHandler(button_handler, pattern='^download_'))
    application.add_handler(CallbackQueryHandler(admin_button_handler, pattern='^admin_'))

    print("البوت قيد التشغيل...")
    # تم تغيير run_polling إلى الطريقة الجديدة
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    # حلقة لا نهائية لإبقاء البوت يعمل
    while True:
        await asyncio.sleep(3600)

if __name__ == '__main__':
    # تشغيل الدالة الرئيسية غير المتزامنة
    asyncio.run(main())
