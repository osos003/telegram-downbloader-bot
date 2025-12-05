import logging
import os
import re
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler

# إعداد التسجيل (Logging)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID"))
CHANNEL_ID = os.environ.get("CHANNEL_ID")


BLOCKED_USERS_FILE = 'blocked_users.txt'

def load_blocked_users():
    """تحميل قائمة المستخدمين المحظورين من الملف النصي."""
    try:
        with open(BLOCKED_USERS_FILE, 'r') as f:
            # قراءة كل سطر وتحويله إلى عدد صحيح (معرف المستخدم)
            return set(int(line.strip()) for line in f if line.strip())
    except FileNotFoundError:
        return set()
    except Exception as e:
        logger.error(f"Error loading blocked users: {e}")
        return set()

def save_blocked_users():
    """حفظ قائمة المستخدمين المحظورين إلى الملف النصي."""
    try:
        with open(BLOCKED_USERS_FILE, 'w') as f:
            # كتابة كل معرف مستخدم في سطر جديد
            for user_id in BLOCKED_USERS:
                f.write(f"{user_id}\n")
    except Exception as e:
        logger.error(f"Error saving blocked users: {e}")

# قائمة المستخدمين المحظورين (سيتم تحميلها عند بدء التشغيل)
BLOCKED_USERS = load_blocked_users()

# قائمة المستخدمين النشطين مؤقتًا لتسهيل لوحة التحكم
ACTIVE_USERS = {} # {user_id: username}

# دقة الفيديو المطلوبة
TARGET_RESOLUTIONS = [720, 480, 360, 240]

# ----------------------------------------------------------------------
# وظائف yt-dlp المساعدة
# ----------------------------------------------------------------------

def get_available_formats(url):
    """يستخرج معلومات التنسيقات المتاحة من الرابط باستخدام yt-dlp."""
    ydl_opts = {
        'quiet': True,
        'skip_download': True,
        'force_generic_extractor': True,
        'simulate': True,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=False)
            
            # إذا كان المحتوى صورة (مثل منشور انستجرام به صورة واحدة)
            if info_dict.get('_type') == 'url' and 'webpage_url' in info_dict:
                # قد يكون رابطًا لصفحة ويب تحتوي على صورة أو فيديو، سنعتبره فيديو مبدئيًا
                pass

            # إذا كان المحتوى عبارة عن قائمة تشغيل أو عدة ملفات (مثل منشور انستجرام متعدد)
            if 'entries' in info_dict:
                # سنركز على أول إدخال فقط لتبسيط العملية
                info_dict = info_dict['entries'][0]
            
            # التحقق مما إذا كان المحتوى فيديو
            if info_dict.get('duration') is not None or info_dict.get('is_live'):
                is_video = True
            else:
                # إذا لم يكن هناك مدة، فقد يكون صورة أو محتوى غير مدعوم
                is_video = False
                
            if not is_video:
                # إذا لم يكن فيديو، سنحاول إرسال الصورة/المحتوى مباشرة
                return None, info_dict # None للتنسيقات، و info_dict للمعلومات
            
            # استخراج التنسيقات المتاحة
            formats = info_dict.get('formats', [])
            
            # تصفية التنسيقات للحصول على أفضل تطابق للدقة المطلوبة
            available_formats = {}
            for res in TARGET_RESOLUTIONS:
                # البحث عن أفضل تنسيق MP4 أو تنسيق فيديو مع دقة قريبة
                best_format = None
                best_diff = float('inf')
                
                for f in formats:
                    if f.get('vcodec') != 'none' and f.get('ext') in ['mp4', 'webm', 'mkv']:
                        height = f.get('height')
                        if height:
                            diff = abs(height - res)
                            if diff < best_diff:
                                best_diff = diff
                                best_format = f
                
                if best_format:
                    # تخزين أفضل تنسيق تم العثور عليه للدقة المطلوبة
                    # نستخدم format_id كقيمة للزر
                    available_formats[f"{res}p"] = best_format['format_id']
                    
            return available_formats, info_dict
            
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp DownloadError: {e}")
        return False, str(e)
    except Exception as e:
        logger.error(f"An unexpected error occurred in yt-dlp: {e}")
        return False, str(e)

def download_media(url, format_id=None):
    """يقوم بتنزيل الوسائط (فيديو أو صورة) باستخدام yt-dlp."""
    output_template = os.path.join(os.getcwd(), 'downloads', '%(title)s.%(ext)s')
    
    ydl_opts = {
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        'format': format_id if format_id else 'best',
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4',
        }] if format_id else [],
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            
            # تحديد المسار الذي تم التنزيل إليه
            # yt-dlp يضيف الامتداد تلقائيًا
            downloaded_file = ydl.prepare_filename(info_dict)
            
            # إذا كان هناك عدة ملفات (مثل منشور انستجرام متعدد)
            if 'entries' in info_dict:
                # سنعيد قائمة بالملفات التي تم تنزيلها
                downloaded_files = []
                for entry in info_dict['entries']:
                    downloaded_files.append(ydl.prepare_filename(entry))
                return downloaded_files, info_dict
            
            return [downloaded_file], info_dict
            
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp DownloadError: {e}")
        return False, str(e)
    except Exception as e:
        logger.error(f"An unexpected error occurred during download: {e}")
        return False, str(e)

# ----------------------------------------------------------------------
# وظيفة فحص الاشتراك الإجباري
# ----------------------------------------------------------------------

async def check_subscription(update: Update, context):
    """يفحص ما إذا كان المستخدم مشتركًا في القناة الإجبارية."""
    user_id = update.effective_user.id
    
    try:
        # استخدام get_chat_member للتحقق من حالة العضوية
        chat_member = await context.bot.get_chat_member(MANDATORY_CHANNEL_ID, user_id)
        
        # حالات العضوية المقبولة: member, administrator, creator
        if chat_member.status in ['member', 'administrator', 'creator']:
            return True
        else:
            # المستخدم ليس مشتركًا
            # يجب أن تكون القناة عامة ليتمكن المستخدم من الانضمام عبر الرابط
            # أو يجب أن يكون البوت مشرفًا في القناة الخاصة
            channel_username = MANDATORY_CHANNEL_ID.lstrip('@')
            if not channel_username.startswith('-100'):
                url = f"https://t.me/{channel_username}"
            else:
                # لا يمكن إنشاء رابط دعوة مباشر للقنوات الخاصة دون صلاحيات
                url = "https://t.me/telegram" # رابط وهمي، يجب على المستخدم الانضمام يدويًا
                
            keyboard = [[InlineKeyboardButton("اشترك في القناة", url=url)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "عذراً، يجب عليك الاشتراك في القناة التالية لاستخدام البوت:",
                reply_markup=reply_markup
            )
            return False
            
    except Exception as e:
        logger.error(f"Error checking subscription: {e}")
        await update.message.reply_text(
            "عذراً، حدث خطأ أثناء التحقق من الاشتراك. يرجى التأكد من أن البوت مشرف في القناة الإجبارية."
        )
        return False

# ----------------------------------------------------------------------
# معالجات رسائل البوت
# ----------------------------------------------------------------------

async def start_command(update: Update, context):
    """يرد على أمر /start."""
    user = update.effective_user
    # تسجيل المستخدم النشط
    if user.username:
        ACTIVE_USERS[user.id] = user.username
    else:
        ACTIVE_USERS[user.id] = f"User_{user.id}"
    user_id = update.effective_user.id
    if user_id in BLOCKED_USERS:
        await update.message.reply_text("عذراً، لقد تم حظرك من استخدام هذا البوت.")
        return
        
    if not await check_subscription(update, context):
        return
        
    await update.message.reply_text(
        "أهلاً بك في بوت تنزيل الوسائط! \n"
        "أرسل لي رابط فيديو أو صورة من أي منصة تواصل اجتماعي وسأقوم بتنزيلها لك. \n"
        "للفيديو، سأعرض لك خيارات الدقة المتاحة."
    )

# ----------------------------------------------------------------------
# أوامر لوحة التحكم (للمدير فقط)
# ----------------------------------------------------------------------

async def admin_command(update: Update, context):
    """يعرض لوحة التحكم للمدير."""
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("عذراً، هذا الأمر مخصص للمدير فقط.")
        return
        
    # عرض قائمة المستخدمين النشطين
    users_list = "قائمة المستخدمين النشطين (آخر من تفاعل مع البوت):\n\n"
    
    # ترتيب المستخدمين حسب آخر تفاعل (افتراضيًا، الترتيب الذي تم به الإضافة)
    for user_id, username in ACTIVE_USERS.items():
        status = "محظور" if user_id in BLOCKED_USERS else "نشط"
        users_list += f"@{username} (ID: {user_id}) - الحالة: {status}\n"
        
    await update.message.reply_text(users_list)
    
    # عرض خيارات الحظر/فك الحظر
    keyboard = []
    for user_id, username in ACTIVE_USERS.items():
        if user_id != ADMIN_USER_ID: # لا يمكن حظر المدير
            if user_id not in BLOCKED_USERS:
                # زر حظر
                keyboard.append([InlineKeyboardButton(f"حظر @{username}", callback_data=f"block_user|{user_id}")])
            else:
                # زر فك الحظر
                keyboard.append([InlineKeyboardButton(f"فك حظر @{username}", callback_data=f"unblock_user|{user_id}")])
                
    if keyboard:
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("اختر مستخدمًا لإدارة حالته:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("لا يوجد مستخدمون آخرون لإدارتهم حاليًا.")

async def block_command(update: Update, context):
    """أمر حظر مستخدم يدويًا."""
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("عذراً، هذا الأمر مخصص للمدير فقط.")
        return
        
    if not context.args:
        await update.message.reply_text("الرجاء تحديد اسم المستخدم (@username) أو معرف المستخدم (ID) للحظر. مثال: /block @username")
        return
        
    target = context.args[0]
    
    # محاولة تحديد المستخدم من القائمة النشطة
    user_to_block_id = None
    
    # البحث بالـ ID
    try:
        user_id_int = int(target)
        if user_id_int in ACTIVE_USERS:
            user_to_block_id = user_id_int
    except ValueError:
        # البحث بالـ Username
        target_username = target.lstrip('@')
        for user_id, username in ACTIVE_USERS.items():
            if username == target_username:
                user_to_block_id = user_id
                break
                
    if user_to_block_id and user_to_block_id != ADMIN_USER_ID:
        BLOCKED_USERS.add(user_to_block_id)
        save_blocked_users() # حفظ التغيير
        username = ACTIVE_USERS.get(user_to_block_id, f"User_{user_to_block_id}")
        await update.message.reply_text(f"تم حظر المستخدم @{username} (ID: {user_to_block_id}) بنجاح.")
        try:
            await context.bot.send_message(user_to_block_id, "لقد تم حظرك من استخدام هذا البوت.")
        except Exception:
            pass
    elif user_to_block_id == ADMIN_USER_ID:
        await update.message.reply_text("لا يمكنك حظر نفسك أيها المدير!")
    else:
        await update.message.reply_text(f"لم يتم العثور على المستخدم {target} في قائمة المستخدمين النشطين.")

async def unblock_command(update: Update, context):
    """أمر فك حظر مستخدم يدويًا."""
    if update.effective_user.id != ADMIN_USER_ID:
        await update.message.reply_text("عذراً، هذا الأمر مخصص للمدير فقط.")
        return
        
    if not context.args:
        await update.message.reply_text("الرجاء تحديد اسم المستخدم (@username) أو معرف المستخدم (ID) لفك الحظر. مثال: /unblock @username")
        return
        
    target = context.args[0]
    
    # محاولة تحديد المستخدم من القائمة النشطة
    user_to_unblock_id = None
    
    # البحث بالـ ID
    try:
        user_id_int = int(target)
        if user_id_int in ACTIVE_USERS:
            user_to_unblock_id = user_id_int
    except ValueError:
        # البحث بالـ Username
        target_username = target.lstrip('@')
        for user_id, username in ACTIVE_USERS.items():
            if username == target_username:
                user_to_unblock_id = user_id
                break
                
    if user_to_unblock_id:
        if user_to_unblock_id in BLOCKED_USERS:
            BLOCKED_USERS.remove(user_to_unblock_id)
            save_blocked_users() # حفظ التغيير
            username = ACTIVE_USERS.get(user_to_unblock_id, f"User_{user_to_unblock_id}")
            await update.message.reply_text(f"تم فك حظر المستخدم @{username} (ID: {user_to_unblock_id}) بنجاح.")
            try:
                await context.bot.send_message(user_to_unblock_id, "تم فك حظرك. يمكنك الآن استخدام البوت مجدداً.")
            except Exception:
                pass
        else:
            await update.message.reply_text(f"المستخدم {target} غير محظور أصلاً.")
    else:
        await update.message.reply_text(f"لم يتم العثور على المستخدم {target} في قائمة المستخدمين النشطين.")

async def handle_link(update: Update, context):
    """يعالج الروابط المرسلة من المستخدمين."""
    user = update.effective_user
    user_id = user.id
    # تسجيل المستخدم النشط
    if user.username:
        ACTIVE_USERS[user_id] = user.username
    else:
        ACTIVE_USERS[user_id] = f"User_{user_id}"
    if user_id in BLOCKED_USERS:
        await update.message.reply_text("عذراً، لقد تم حظرك من استخدام هذا البوت.")
        return
        
    if not await check_subscription(update, context):
        return
    
    url = update.message.text
    
    # تحقق من أن النص المرسل يبدو كرابط
    if not re.match(r'https?://\S+', url):
        await update.message.reply_text("الرجاء إرسال رابط صحيح.")
        return

    await update.message.reply_text("جاري تحليل الرابط... قد يستغرق هذا بضع ثوانٍ.")
    
    formats, info = get_available_formats(url)
    
    if formats is False:
        await update.message.reply_text(f"عذراً، حدث خطأ أثناء تحليل الرابط: {info}")
        return
        
    if formats is None:
        # ليس فيديو، قد يكون صورة أو محتوى آخر يمكن تنزيله مباشرة
        await update.message.reply_text("تم تحديد المحتوى كصورة أو ملف غير فيديو. جاري التنزيل والإرسال مباشرة...")
        
        # سنقوم بتنزيل الملف وإرساله
        downloaded_files, info = download_media(url)
        
        if downloaded_files is False:
            await update.message.reply_text(f"عذراً، حدث خطأ أثناء تنزيل الملف: {info}")
            return
            
        for file_path in downloaded_files:
            try:
                if info.get('ext') in ['jpg', 'jpeg', 'png', 'webp']:
                    await update.message.reply_photo(photo=open(file_path, 'rb'))
                elif info.get('ext') in ['mp4', 'webm', 'mkv']:
                    await update.message.reply_video(video=open(file_path, 'rb'))
                else:
                    await update.message.reply_document(document=open(file_path, 'rb'))
                
                # حذف الملف بعد الإرسال
                os.remove(file_path)
                
            except Exception as e:
                logger.error(f"Error sending file: {e}")
                await update.message.reply_text(f"عذراً، حدث خطأ أثناء إرسال الملف: {e}")
                
        await update.message.reply_text("تم إرسال الملف بنجاح.")
        return

    # إذا كان فيديو، نعرض خيارات الدقة
    keyboard = []
    for res, format_id in formats.items():
        # نستخدم صيغة: DATA_TYPE|URL|FORMAT_ID
        callback_data = f"download|{url}|{format_id}"
        keyboard.append([InlineKeyboardButton(f"تحميل بدقة {res}", callback_data=callback_data)])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"تم تحديد الفيديو: {info.get('title', 'بدون عنوان')}\n"
        "الرجاء اختيار الدقة المطلوبة للتحميل:",
        reply_markup=reply_markup
    )

async def button_callback(update: Update, context):
    """يعالج ضغطات الأزرار المضمنة (Inline Buttons)."""
    query = update.callback_query
    await query.answer() # يجب الرد على الاستعلام لتجنب ظهور "جاري التحميل" للمستخدم
    
    data = query.data.split('|')
    data_type = data[0]
    
    if data_type == "download":
        url = data[1]
        format_id = data[2]
        
        await query.edit_message_text("جاري تنزيل الفيديو بالدقة المطلوبة... قد يستغرق هذا بعض الوقت.")
    
    elif data_type == "block_user":
        # معالجة أمر الحظر من لوحة التحكم
        if query.from_user.id != ADMIN_USER_ID:
            await query.edit_message_text("عذراً، هذا الأمر مخصص للمدير فقط.")
            return
            
        user_to_block_id = int(data[1])
        BLOCKED_USERS.add(user_to_block_id)
        save_blocked_users() # حفظ التغيير
        
        username = ACTIVE_USERS.get(user_to_block_id, f"User_{user_to_block_id}")
        
        await query.edit_message_text(f"تم حظر المستخدم @{username} (ID: {user_to_block_id}) بنجاح.")
        
        # إرسال رسالة للمستخدم المحظور (اختياري)
        try:
            await context.bot.send_message(user_to_block_id, "لقد تم حظرك من استخدام هذا البوت.")
        except Exception:
            pass # قد يكون المستخدم قد حظر البوت بالفعل

    elif data_type == "unblock_user":
        # معالجة أمر فك الحظر من لوحة التحكم
        if query.from_user.id != ADMIN_USER_ID:
            await query.edit_message_text("عذراً، هذا الأمر مخصص للمدير فقط.")
            return
            
        user_to_unblock_id = int(data[1])
        if user_to_unblock_id in BLOCKED_USERS:
            BLOCKED_USERS.remove(user_to_unblock_id)
            save_blocked_users() # حفظ التغيير
            
            username = ACTIVE_USERS.get(user_to_unblock_id, f"User_{user_to_unblock_id}")
            
            await query.edit_message_text(f"تم فك حظر المستخدم @{username} (ID: {user_to_unblock_id}) بنجاح.")
        else:
            await query.edit_message_text("المستخدم غير محظور أصلاً.")
        
        downloaded_files, info = download_media(url, format_id)
        
        if downloaded_files is False:
            await query.edit_message_text(f"عذراً، حدث خطأ أثناء تنزيل الفيديو: {info}")
            return
            
        # إرسال الفيديو
        for file_path in downloaded_files:
            try:
                await context.bot.send_video(
                    chat_id=query.message.chat_id,
                    video=open(file_path, 'rb'),
                    caption=f"تم تنزيل الفيديو: {info.get('title', 'بدون عنوان')}"
                )
                # حذف الملف بعد الإرسال
                os.remove(file_path)
                
            except Exception as e:
                logger.error(f"Error sending video: {e}")
                await query.edit_message_text(f"عذراً، حدث خطأ أثناء إرسال الفيديو: {e}")
                
        await query.edit_message_text("تم إرسال الفيديو بنجاح. يمكنك إرسال رابط آخر.")

# ----------------------------------------------------------------------
# وظيفة التشغيل الرئيسية
# ----------------------------------------------------------------------

def main():
    """يبدأ تشغيل البوت."""
    # التأكد من وجود مجلد التحميلات
    if not os.path.exists('downloads'):
        os.makedirs('downloads')
        
    application = Application.builder().token(BOT_TOKEN).build()

    # معالجات الأوامر والرسائل
    # معالجات الأوامر والرسائل
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("block", block_command))
    application.add_handler(CommandHandler("unblock", unblock_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    application.add_handler(CallbackQueryHandler(button_callback))

    # تشغيل البوت
    logger.info("Bot started polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
