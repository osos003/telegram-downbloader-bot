import os
import logging
import re
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ContextTypes
from yt_dlp import YoutubeDL, DownloadError

# إعداد التسجيل (Logging)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# *****************************************************************
# *********************** إعدادات البوت ***************************
# *****************************************************************

BOT_TOKEN = os.environ.get("BOT_TOKEN")
# حولها إلى int مباشرةً لتجنب الأخطاء لاحقًا
ADMIN_ID = int(os.environ.get("ADMIN_ID")) if os.environ.get("ADMIN_ID") else None 
CHANNEL_ID = os.environ.get("CHANNEL_ID") 

# قائمة المستخدمين المحظورين (تخزين مؤقت في الذاكرة)
# هذه القائمة ستُمسح عند إعادة تشغيل البوت
BANNED_USERS = {} # {user_id: username}

# *****************************************************************
# *********************** وظائف المساعدة ***************************
# *****************************************************************

def is_subscribed(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> bool:
    """التحقق من اشتراك المستخدم في القناة الإجبارية."""
    try:
        # get_chat_member تتطلب أن يكون البوت مشرفًا في القناة
        member = context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        # حالة العضو يجب أن تكون 'member' أو 'administrator' أو 'creator'
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"خطأ في التحقق من الاشتراك: {e}")
        # إذا لم يتمكن البوت من الوصول للقناة، نفترض أنه مشترك لتجنب توقف البوت
        # (يمكنك تغيير هذا السلوك إذا كنت تفضل إيقاف البوت في حالة الخطأ)
        return True

def get_subscription_keyboard() -> InlineKeyboardMarkup:
    """إنشاء لوحة مفاتيح للاشتراك الإجباري."""
    keyboard = [
        [InlineKeyboardButton("اشترك في القناة", url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")],
        [InlineKeyboardButton("تحقّق من الاشتراك", callback_data="check_subscription")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_keyboard() -> InlineKeyboardMarkup:
    """إنشاء لوحة مفاتيح لوحة التحكم الإدارية."""
    keyboard = [
        [InlineKeyboardButton("قائمة المحظورين", callback_data="admin_list_banned")],
        [InlineKeyboardButton("حظر مستخدم", callback_data="admin_ban_user")],
        [InlineKeyboardButton("إلغاء حظر مستخدم", callback_data="admin_unban_user")]
    ]
    return InlineKeyboardMarkup(keyboard)

def is_banned(user_id: int) -> bool:
    """التحقق مما إذا كان المستخدم محظورًا."""
    return user_id in BANNED_USERS

# *****************************************************************
# *********************** معالجات الأوامر ***************************
# *****************************************************************

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة أمر /start."""
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("أنت محظور من استخدام هذا البوت.")
        return

    if not is_subscribed(context, user.id):
        await update.message.reply_text(
            f"مرحباً بك يا {user.first_name}!\n"
            "لاستخدام البوت، يجب عليك الاشتراك في القناة الإجبارية أولاً.",
            reply_markup=get_subscription_keyboard()
        )
        return

    await update.message.reply_text(
        "أهلاً بك في بوت تحميل الفيديوهات والصور!\n"
        "فقط أرسل لي رابط الفيديو أو الصورة وسأقوم بمعالجته."
    )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة أمر /admin (للمشرف فقط)."""
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("أنت لست المشرف.")
        return

    await update.message.reply_text(
        "مرحباً أيها المشرف، هذه لوحة التحكم الخاصة بك:",
        reply_markup=get_admin_keyboard()
    )

# *****************************************************************
# *********************** معالجة الروابط ***************************
# *****************************************************************

async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة الرسائل التي تحتوي على رابط."""
    user = update.effective_user
    if is_banned(user.id):
        await update.message.reply_text("أنت محظور من استخدام هذا البوت.")
        return

    if not is_subscribed(context, user.id):
        await update.message.reply_text(
            "يجب عليك الاشتراك في القناة الإجبارية أولاً.",
            reply_markup=get_subscription_keyboard()
        )
        return

    link = update.message.text
    await update.message.reply_text("جاري معالجة الرابط، يرجى الانتظار...")

    # إعداد yt-dlp
    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'force_generic_extractor': True,
        'format': 'best',
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=False)
            
            # التحقق مما إذا كانت صورة
            # نعتمد على امتداد الملف أو نوع الوسائط
            if info.get('ext') in ['jpg', 'jpeg', 'png', 'webp'] or info.get('mediatype') == 'image':
                # معالجة الصورة
                image_url = info.get('url') or info.get('webpage_url')
                if image_url:
                    await update.message.reply_photo(image_url, caption="تم تحميل الصورة بنجاح.")
                else:
                    await update.message.reply_text("عذراً، لم أتمكن من العثور على رابط مباشر للصورة.")
                return

            # معالجة الفيديو
            formats = info.get('formats', [])
            
            # تصفية واختيار الصيغ المطلوبة
            available_formats = {}
            # الدقات المطلوبة بترتيب تنازلي
            target_resolutions = [720, 480, 360, 240]

            for res in target_resolutions:
                # البحث عن أفضل صيغة مطابقة للدقة المطلوبة
                # نبحث عن صيغة لها دقة (height) أقل من أو تساوي الدقة المطلوبة، ولها كود فيديو وصوت (لتجنب تحميل ملفات فيديو بدون صوت أو العكس)
                best_format = next((f for f in formats if f.get('height') and f['height'] <= res and f.get('vcodec') != 'none' and f.get('acodec') != 'none'), None)
                
                if best_format:
                    # نستخدم دقة الفيديو الفعلية كاسم، ونخزن format_id كقيمة
                    resolution_key = f"{best_format['height']}p"
                    if resolution_key not in available_formats:
                        available_formats[resolution_key] = best_format['format_id']

            if not available_formats:
                await update.message.reply_text("عذراً، لم أتمكن من العثور على صيغ فيديو قابلة للتحميل بالدقة المطلوبة.")
                return

            # إنشاء لوحة مفاتيح لاختيار الجودة
            keyboard_buttons = []
            for res, format_id in available_formats.items():
                # نستخدم JSON لتخزين البيانات في callback_data
                callback_data = json.dumps({
                    "action": "download",
                    "link": link,
                    "format_id": format_id,
                    "res": res
                })
                keyboard_buttons.append(InlineKeyboardButton(f"تحميل {res}", callback_data=callback_data))

            # يتم عرض الأزرار في صف واحد
            reply_markup = InlineKeyboardMarkup([keyboard_buttons])
            
            # إرسال رسالة اختيار الجودة
            await update.message.reply_text(
                f"تم العثور على الفيديو: {info.get('title', 'بدون عنوان')}\n"
                "الرجاء اختيار جودة التحميل:",
                reply_markup=reply_markup
            )

    except DownloadError as e:
        await update.message.reply_text(f"عذراً، حدث خطأ أثناء معالجة الرابط: {e}")
    except Exception as e:
        logger.error(f"خطأ غير متوقع: {e}")
        await update.message.reply_text("عذراً، حدث خطأ غير متوقع. يرجى المحاولة لاحقاً.")
        
# *****************************************************************
# *********************** معالجة الاستدعاءات (Callbacks) ******************
# *****************************************************************

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة استدعاءات لوحة المفاتيح المضمنة."""
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if is_banned(user.id):
        await query.edit_message_text("أنت محظور من استخدام هذا البوت.")
        return

    data = query.data

    # معالجة التحقق من الاشتراك
    if data == "check_subscription":
        if is_subscribed(context, user.id):
            await query.edit_message_text(
                "شكراً لاشتراكك! يمكنك الآن إرسال الروابط.",
                reply_markup=None
            )
        else:
            await query.edit_message_text(
                "ما زلت غير مشترك. يرجى الاشتراك ثم الضغط على 'تحقّق من الاشتراك' مرة أخرى.",
                reply_markup=get_subscription_keyboard()
            )
        return

    # معالجة أوامر المشرف
    if user.id == ADMIN_ID and data.startswith("admin_"):
        await handle_admin_callback(query, context)
        return

    # معالجة تحميل الفيديو
    try:
        callback_data = json.loads(data)
        action = callback_data.get("action")
        
        if action == "download":
            link = callback_data["link"]
            format_id = callback_data["format_id"]
            res = callback_data["res"]
            
            await query.edit_message_text(f"جاري تحميل الفيديو بجودة {res}، يرجى الانتظار...")

            # مسار مؤقت لحفظ الملف
            temp_filename = f"/tmp/video_{user.id}_{res}.mp4"
            
            # إعداد yt-dlp للتحميل الفعلي
            ydl_opts = {
                'format': format_id,
                'outtmpl': temp_filename,
                'quiet': True,
                'noplaylist': True,
            }

            try:
                with YoutubeDL(ydl_opts) as ydl:
                    ydl.download([link])
                
                # إرسال الفيديو
                with open(temp_filename, 'rb') as video_file:
                    await context.bot.send_video(
                        chat_id=user.id,
                        video=video_file,
                        caption=f"تم تحميل الفيديو بجودة {res} بناءً على طلبك."
                    )
                
                await query.edit_message_text(f"تم إرسال الفيديو بجودة {res} بنجاح.")

            except Exception as e:
                logger.error(f"خطأ في تحميل وإرسال الفيديو: {e}")
                await query.edit_message_text("عذراً، حدث خطأ أثناء تحميل أو إرسال الفيديو.")
            finally:
                # حذف الملف المؤقت
                if os.path.exists(temp_filename):
                    os.remove(temp_filename)

    except json.JSONDecodeError:
        logger.error(f"Callback data is not valid JSON: {data}")
        await query.edit_message_text("حدث خطأ في معالجة طلبك.")
    except Exception as e:
        logger.error(f"خطأ غير متوقع في معالجة الاستدعاء: {e}")
        await query.edit_message_text("حدث خطأ غير متوقع.")

# *****************************************************************
# *********************** لوحة تحكم المشرف ***************************
# *****************************************************************

async def handle_admin_callback(query: Update.callback_query, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة استدعاءات لوحة تحكم المشرف."""
    data = query.data
    
    if data == "admin_list_banned":
        if not BANNED_USERS:
            message = "لا يوجد مستخدمون محظورون حالياً."
        else:
            # عرض المستخدمين المحظورين بالصيغة المطلوبة (@username)
            # نستخدم اسم المستخدم المخزن في القائمة
            user_list = "\n".join([f"@{username} (ID: {user_id})" for user_id, username in BANNED_USERS.items()])
            message = f"قائمة المستخدمين المحظورين:\n{user_list}"
        
        await query.edit_message_text(message, reply_markup=get_admin_keyboard())
        return

    # أوامر تتطلب إدخال من المشرف
    if data == "admin_ban_user":
        await query.edit_message_text(
            "للحظر، أرسل لي الأمر /ban متبوعاً بمعرف المستخدم (ID). مثال: /ban 123456789",
            reply_markup=get_admin_keyboard()
        )
        return

    if data == "admin_unban_user":
        await query.edit_message_text(
            "لإلغاء الحظر، أرسل لي الأمر /unban متبوعاً بمعرف المستخدم (ID). مثال: /unban 123456789",
            reply_markup=get_admin_keyboard()
        )
        return

async def ban_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة أمر /ban (للمشرف فقط)."""
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("أنت لست المشرف.")
        return

    if not context.args:
        await update.message.reply_text("الرجاء تحديد معرف المستخدم للحظر. مثال: /ban 123456789")
        return

    target_input = context.args[0]
    
    try:
        # يجب أن يكون الإدخال معرف مستخدم (رقم)
        target_id = int(target_input)
        
        # محاولة الحصول على اسم المستخدم من الرسالة إذا كان متاحاً
        target_username = context.args[1].lstrip('@') if len(context.args) > 1 and context.args[1].startswith('@') else f"User_{target_id}"
        
    except ValueError:
        await update.message.reply_text("الرجاء استخدام معرف المستخدم (ID) للحظر. مثال: /ban 123456789")
        return

    if target_id == ADMIN_ID:
        await update.message.reply_text("لا يمكنك حظر نفسك أيها المشرف.")
        return

    # تخزين الحظر
    BANNED_USERS[target_id] = target_username
    await update.message.reply_text(f"تم حظر المستخدم {target_username} (ID: {target_id}) بنجاح.")
    
    # محاولة إرسال رسالة للمستخدم المحظور
    try:
        await context.bot.send_message(target_id, "لقد تم حظرك من استخدام هذا البوت.")
    except Exception:
        pass # تجاهل إذا لم يتمكن البوت من إرسال رسالة للمستخدم

async def unban_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """معالجة أمر /unban (للمشرف فقط)."""
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("أنت لست المشرف.")
        return

    if not context.args:
        await update.message.reply_text("الرجاء تحديد معرف المستخدم لإلغاء الحظر. مثال: /unban 123456789")
        return

    target_input = context.args[0]
    
    try:
        target_id = int(target_input)
    except ValueError:
        await update.message.reply_text("الرجاء استخدام معرف المستخدم (ID) لإلغاء الحظر.")
        return

    if target_id in BANNED_USERS:
        del BANNED_USERS[target_id]
        await update.message.reply_text(f"تم إلغاء حظر المستخدم صاحب المعرف {target_id} بنجاح.")
    else:
        await update.message.reply_text(f"المستخدم صاحب المعرف {target_id} ليس محظوراً.")

# *****************************************************************
# *********************** الوظيفة الرئيسية ***************************
# *****************************************************************

def main() -> None:
    """تشغيل البوت."""
    # إنشاء التطبيق وتمرير توكن البوت
    application = Application.builder().token(BOT_TOKEN).build()

    # معالجات الأوامر
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("ban", ban_user_command))
    application.add_handler(CommandHandler("unban", unban_user_command))

    # معالج الرسائل (الروابط)
    # نستخدم regex للتحقق من وجود رابط HTTP/HTTPS
    link_filter = filters.TEXT & (~filters.COMMAND) & filters.Regex(r'https?://\S+')
    application.add_handler(MessageHandler(link_filter, handle_link))

    # معالج استدعاءات لوحة المفاتيح المضمنة
    application.add_handler(CallbackQueryHandler(handle_callback))

    # بدء تشغيل البوت (Polling)
    logger.info("البوت يعمل...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
