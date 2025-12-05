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

# تأكد من تعيين هذه المتغيرات كمتغيرات بيئة
BOT_TOKEN = os.environ.get("BOT_TOKEN")
# حولها إلى int مباشرةً لتجنب الأخطاء لاحقًا
ADMIN_ID = int(os.environ.get("ADMIN_ID")) if os.environ.get("ADMIN_ID") else None 
CHANNEL_ID = os.environ.get("CHANNEL_ID") 

# **اسم ملف الكوكيز (يجب أن يكون موجوداً في نفس مجلد البوت)**
COOKIE_FILE = 'youtube_cookies.txt' 

BLOCKED_USERS_FILE = 'blocked_users.txt'

# ----------------------------------------------------------------------
# وظائف التحميل والحفظ
# ----------------------------------------------------------------------

def load_blocked_users():
    """تحميل قائمة المستخدمين المحظورين من الملف النصي."""
    try:
        with open(BLOCKED_USERS_FILE, 'r') as f:
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
            for user_id in BLOCKED_USERS:
                f.write(f"{user_id}\n")
    except Exception as e:
        logger.error(f"Error saving blocked users: {e}")

# قائمة المستخدمين المحظورين
BLOCKED_USERS = load_blocked_users()

# قائمة المستخدمين النشطين مؤقتًا
ACTIVE_USERS = {} 

# دقة الفيديو المطلوبة
TARGET_RESOLUTIONS = [720, 480, 360, 240]

# ----------------------------------------------------------------------
# وظائف yt-dlp المساعدة (تم تعديلها)
# ----------------------------------------------------------------------

def get_base_ydl_opts():
    """إرجاع قاموس الخيارات الأساسية لـ yt-dlp."""
    opts = {
        'quiet': True,
        'skip_download': True,
        'force_generic_extractor': True,
        'simulate': True,
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
    }
    # إضافة ملف الكوكيز إذا كان موجوداً - الحل لمشكلة يوتيوب
    if os.path.exists(COOKIE_FILE):
        opts['cookiefile'] = COOKIE_FILE
    return opts

def get_available_formats(url):
    """يستخرج معلومات التنسيقات المتاحة من الرابط باستخدام yt-dlp."""
    ydl_opts = get_base_ydl_opts()
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=False)
            
            # معالجة قوائم التشغيل / المنشورات المتعددة
            if 'entries' in info_dict:
                info_dict = info_dict['entries'][0]
            
            # تحديد ما إذا كان المحتوى فيديو
            is_video = info_dict.get('duration') is not None or info_dict.get('is_live')
                
            if not is_video:
                return None, info_dict
            
            formats = info_dict.get('formats', [])
            
            # تصفية التنسيقات وعرض الدقة الفعلية
            available_formats = {}
            for res in TARGET_RESOLUTIONS:
                best_format = None
                best_diff = float('inf')
                
                for f in formats:
                    # نركز على تنسيقات الفيديو الصريحة التي تحتوي على دقة
                    if f.get('vcodec') != 'none' and f.get('height'): 
                        height = f.get('height')
                        diff = abs(height - res)
                        if diff < best_diff:
                            best_diff = diff
                            best_format = f
                
                if best_format:
                    actual_height = best_format.get('height')
                    available_formats[f"{actual_height}p"] = best_format['format_id']
                    
            return available_formats, info_dict
            
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp DownloadError: {e}")
        return False, str(e)
    except Exception as e:
        logger.error(f"An unexpected error occurred in yt-dlp: {e}")
        return False, str(e)

def download_media(url, format_id=None):
    """يقوم بتنزيل الوسائط (فيديو أو صورة) باستخدام yt-dlp. (تم تعديلها لدمج الصوت والفيديو)"""
    output_template = os.path.join(os.getcwd(), 'downloads', '%(title)s.%(ext)s')
    
    ydl_opts = {
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        # **الإصلاح:** دمج الصوت مع الفيديو عند اختيار format_id
        'format': f"{format_id}+bestaudio/best" if format_id else 'best', 
        'postprocessors': [{
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4',
        }] if format_id else [],
    }
    
    # إضافة ملف الكوكيز إذا كان موجوداً - الحل لمشكلة يوتيوب
    if os.path.exists(COOKIE_FILE):
        ydl_opts['cookiefile'] = COOKIE_FILE
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            
            # تحديد المسار الذي تم التنزيل إليه
            downloaded_files = []
            
            if 'entries' in info_dict:
                for entry in info_dict['entries']:
                    downloaded_files.append(ydl.prepare_filename(entry))
            else:
                downloaded_files.append(ydl.prepare_filename(info_dict))
            
            return downloaded_files, info_dict
            
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
    
    if not CHANNEL_ID:
        logger.warning("CHANNEL_ID is not set in environment variables.")
        return True 
    
    try:
        chat_member = await context.bot.get_chat_member(CHANNEL_ID, user_id)
        
        if chat_member.status in ['member', 'administrator', 'creator']:
            return True
        else:
            invite_link = None
            try:
                chat = await context.bot.get_chat(CHANNEL_ID)
                invite_link = chat.invite_link or f"https://t.me/{CHANNEL_ID.lstrip('@')}"
            except Exception:
                invite_link = "https://t.me/telegram" 
            
            keyboard = [[InlineKeyboardButton("اشترك في القناة", url=invite_link)]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                "عذراً، يجب عليك الاشتراك في القناة التالية لاستخدام البوت:",
                reply_markup=reply_markup
            )
            return False
            
    except Exception as e:
        error_message = str(e)
        logger.error(f"Error checking subscription: {error_message}")
        
        if update.effective_user.id == ADMIN_ID:
            await update.message.reply_text(f"خطأ إجباري: {error_message}")
        else:
             await update.message.reply_text("عذراً، حدث خطأ أثناء التحقق من الاشتراك. يرجى إبلاغ المدير.")
            
        return False

# ----------------------------------------------------------------------
# معالجات رسائل البوت
# ----------------------------------------------------------------------

async def start_command(update: Update, context):
    """يرد على أمر /start."""
    user = update.effective_user
    username = user.username or f"User_{user.id}"
    ACTIVE_USERS[user.id] = username
    
    user_id = user.id
    if user_id in BLOCKED_USERS:
        await update.message.reply_text("عذراً، لقد تم حظرك من استخدام هذا البوت.")
        return
        
    if not await check_subscription(update, context):
        return
    
    await update.message.reply_text(
        "أهلاً بك في بوت تنزيل الوسائط! \n"
        "أرسل لي **رابط** فيديو أو صورة من أي منصة تواصل اجتماعي وسأقوم بتنزيلها لك. \n"
        "للفيديو، سأعرض لك خيارات الدقة المتاحة."
    )

async def admin_command(update: Update, context):
    """يعرض لوحة التحكم للمدير."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("عذراً، هذا الأمر مخصص للمدير فقط.")
        return
        
    users_list = "قائمة المستخدمين النشطين (آخر من تفاعل مع البوت):\n\n"
    
    for user_id, username in ACTIVE_USERS.items():
        status = "محظور" if user_id in BLOCKED_USERS else "نشط"
        users_list += f"@{username} (ID: {user_id}) - الحالة: {status}\n"
        
    await update.message.reply_text(users_list)
    
    keyboard = []
    for user_id, username in ACTIVE_USERS.items():
        if user_id != ADMIN_ID:
            action = "unblock" if user_id in BLOCKED_USERS else "block"
            text = f"فك حظر @{username}" if user_id in BLOCKED_USERS else f"حظر @{username}"
            keyboard.append([InlineKeyboardButton(text, callback_data=f"{action}_user|{user_id}")])
                
    if keyboard:
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("اختر مستخدمًا لإدارة حالته:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("لا يوجد مستخدمون آخرون لإدارتهم حاليًا.")

async def block_command(update: Update, context):
    """أمر حظر مستخدم يدويًا."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("عذراً، هذا الأمر مخصص للمدير فقط.")
        return
        
    if not context.args:
        await update.message.reply_text("الرجاء تحديد اسم المستخدم (@username) أو معرف المستخدم (ID) للحظر. مثال: /block @username")
        return
        
    target = context.args[0]
    user_to_block_id = None
    
    try:
        user_id_int = int(target)
        if user_id_int in ACTIVE_USERS:
            user_to_block_id = user_id_int
    except ValueError:
        target_username = target.lstrip('@')
        for user_id, username in ACTIVE_USERS.items():
            if username == target_username:
                user_to_block_id = user_id
                break
                
    if user_to_block_id and user_to_block_id != ADMIN_ID:
        BLOCKED_USERS.add(user_to_block_id)
        save_blocked_users()
        username = ACTIVE_USERS.get(user_to_block_id, f"User_{user_to_block_id}")
        await update.message.reply_text(f"تم حظر المستخدم @{username} (ID: {user_to_block_id}) بنجاح.")
        try:
            await context.bot.send_message(user_to_block_id, "لقد تم حظرك من استخدام هذا البوت.")
        except Exception:
            pass
    elif user_to_block_id == ADMIN_ID:
        await update.message.reply_text("لا يمكنك حظر نفسك أيها المدير!")
    else:
        await update.message.reply_text(f"لم يتم العثور على المستخدم {target} في قائمة المستخدمين النشطين.")

async def unblock_command(update: Update, context):
    """أمر فك حظر مستخدم يدويًا."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("عذراً، هذا الأمر مخصص للمدير فقط.")
        return
        
    if not context.args:
        await update.message.reply_text("الرجاء تحديد اسم المستخدم (@username) أو معرف المستخدم (ID) لفك الحظر. مثال: /unblock @username")
        return
        
    target = context.args[0]
    user_to_unblock_id = None
    
    try:
        user_id_int = int(target)
        if user_id_int in ACTIVE_USERS:
            user_to_unblock_id = user_id_int
    except ValueError:
        target_username = target.lstrip('@')
        for user_id, username in ACTIVE_USERS.items():
            if username == target_username:
                user_to_unblock_id = user_id
                break
                
    if user_to_unblock_id:
        if user_to_unblock_id in BLOCKED_USERS:
            BLOCKED_USERS.remove(user_to_unblock_id)
            save_blocked_users()
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
    """يعالج الروابط المرسلة من المستخدمين. (تم تعديلها لمعالجة خطأ 'No video found' و 'Sign In')"""
    user = update.effective_user
    user_id = user.id
    username = user.username or f"User_{user.id}"
    ACTIVE_USERS[user_id] = username
    
    if user_id in BLOCKED_USERS:
        await update.message.reply_text("عذراً، لقد تم حظرك من استخدام هذا البوت.")
        return
        
    if not await check_subscription(update, context):
        return
    
    url = update.message.text
    
    if not re.match(r'https?://\S+', url):
        await update.message.reply_text("الرجاء إرسال رابط صحيح.")
        return

    wait_message = await update.message.reply_text("جاري تحليل الرابط... قد يستغرق هذا بضع ثوانٍ.")
    
    formats, info = get_available_formats(url)
    
    if formats is False:
        # **معالجة أخطاء yt-dlp الخارجية**
        error_info = str(info)
        
        if "No video could be found in this tweet" in error_info or "No video formats found" in error_info:
             await wait_message.edit_text("عذراً، لم يتم العثور على فيديو في الرابط المرسل (قد تكون صورة أو ملف غير مدعوم).")
             return
             
        elif "Sign in to confirm you're not a bot" in error_info or "Private video" in error_info or "Video unavailable" in error_info:
             msg = (
                 "عذراً، يتطلب هذا الفيديو تسجيل الدخول أو أنه خاص. "
                 "يرجى التأكد من أنك قمت بإضافة ملف `youtube_cookies.txt` صالح بجوار ملف البوت."
             )
             await wait_message.edit_text(msg)
             return
        
        await wait_message.edit_text(f"عذراً، حدث خطأ أثناء تحليل الرابط: {error_info}")
        return
        
    # المنطق عندما لا يكون المحتوى فيديو (مثل صورة أو ملف آخر)
    if formats is None:
        await wait_message.edit_text("تم تحديد المحتوى كصورة أو ملف غير فيديو. جاري التنزيل والإرسال مباشرة...")
        
        downloaded_files, info = download_media(url)
        
        if downloaded_files is False:
            await wait_message.edit_text(f"عذراً، حدث خطأ أثناء تنزيل الملف: {info}")
            return
            
        file_paths_to_delete = downloaded_files
        
        try:
            for file_path in downloaded_files:
                # **التحسين:** استخدام with open لضمان إغلاق الملف
                with open(file_path, 'rb') as f:
                    # محاولة استنتاج الامتداد من info_dict أو file_path
                    ext = info.get('ext', os.path.splitext(file_path)[1].lstrip('.').lower())
                    
                    if ext in ['jpg', 'jpeg', 'png', 'webp']:
                        await update.message.reply_photo(photo=f)
                    elif ext in ['mp4', 'webm', 'mkv', 'mov']:
                        await update.message.reply_video(video=f)
                    else:
                        await update.message.reply_document(document=f)
                
            await wait_message.edit_text("تم إرسال الملف بنجاح.")
                
        except Exception as e:
            logger.error(f"Error sending file: {e}")
            await wait_message.edit_text(f"عذراً، حدث خطأ أثناء إرسال الملف: {e}")
            
        finally:
            # **التحسين:** ضمان حذف الملفات
            for file_path in file_paths_to_delete:
                if os.path.exists(file_path):
                    os.remove(file_path)
            
        return

    # إذا كان فيديو، نعرض خيارات الدقة
    keyboard = []
    for res, format_id in formats.items():
        callback_data = f"download|{url}|{format_id}"
        keyboard.append([InlineKeyboardButton(f"تحميل بدقة {res}", callback_data=callback_data)])
        
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await wait_message.edit_text(
        f"تم تحديد الفيديو: {info.get('title', 'بدون عنوان')}\n"
        "الرجاء اختيار الدقة المطلوبة للتحميل:",
        reply_markup=reply_markup
    )

async def button_callback(update: Update, context):
    """يعالج ضغطات الأزرار المضمنة (Inline Buttons)."""
    query = update.callback_query
    await query.answer() 
    
    data = query.data.split('|')
    data_type = data[0]
    
    # معالجة أوامر المدير
    if data_type in ["block_user", "unblock_user"]:
        if query.from_user.id != ADMIN_ID:
            await query.edit_message_text("عذراً، هذا الأمر مخصص للمدير فقط.")
            return
            
        user_id_to_manage = int(data[1])
        username = ACTIVE_USERS.get(user_id_to_manage, f"User_{user_id_to_manage}")
        
        if data_type == "block_user":
            BLOCKED_USERS.add(user_id_to_manage)
            save_blocked_users()
            await query.edit_message_text(f"تم حظر المستخدم @{username} (ID: {user_id_to_manage}) بنجاح.")
            try:
                await context.bot.send_message(user_id_to_manage, "لقد تم حظرك من استخدام هذا البوت.")
            except Exception:
                pass 
                
        elif data_type == "unblock_user":
            if user_id_to_manage in BLOCKED_USERS:
                BLOCKED_USERS.remove(user_id_to_manage)
                save_blocked_users()
                await query.edit_message_text(f"تم فك حظر المستخدم @{username} (ID: {user_id_to_manage}) بنجاح.")
                try:
                    await context.bot.send_message(user_id_to_manage, "تم فك حظرك. يمكنك الآن استخدام البوت مجدداً.")
                except Exception:
                    pass
            else:
                await query.edit_message_text("المستخدم غير محظور أصلاً.")
        
        return 

    # معالجة أمر التنزيل
    elif data_type == "download":
        url = data[1]
        format_id = data[2]
        
        await query.edit_message_text("جاري تنزيل الفيديو بالدقة المطلوبة... قد يستغرق هذا بعض الوقت.")
        
        downloaded_files, info = download_media(url, format_id)
        
        if downloaded_files is False:
            await query.edit_message_text(f"عذراً، حدث خطأ أثناء تنزيل الفيديو: {info}")
            return
            
        file_paths_to_delete = downloaded_files
        
        try:
            # إرسال الفيديو
            for file_path in downloaded_files:
                # **التحسين:** استخدام with open لضمان إغلاق الملف
                with open(file_path, 'rb') as f:
                    await context.bot.send_video(
                        chat_id=query.message.chat_id,
                        video=f,
                        caption=f"تم تنزيل الفيديو: {info.get('title', 'بدون عنوان')}"
                    )
                
            await query.edit_message_text("تم إرسال الفيديو بنجاح. يمكنك إرسال رابط آخر.")
            
        except Exception as e:
            logger.error(f"Error sending video: {e}")
            await query.edit_message_text(f"عذراً، حدث خطأ أثناء إرسال الفيديو: {e}")
            
        finally:
            # **التحسين:** ضمان حذف الملفات
            for file_path in file_paths_to_delete:
                if os.path.exists(file_path):
                    os.remove(file_path)

# ----------------------------------------------------------------------
# وظيفة التشغيل الرئيسية
# ----------------------------------------------------------------------

def main():
    """يبدأ تشغيل البوت."""
    
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is not set. Please set the environment variable.")
        return
    if ADMIN_ID is None:
        logger.error("ADMIN_ID is not set. Please set the environment variable.")
        return
    
    # رسالة تنبيه بشأن ملف الكوكيز
    if not os.path.exists(COOKIE_FILE):
        logger.warning(
            f"⚠️ {COOKIE_FILE} not found. YouTube download errors may occur due to sign-in requirements. "
            f"Please place a valid cookies file in the bot directory."
        )
        
    # التأكد من وجود مجلد التحميلات
    if not os.path.exists('downloads'):
        os.makedirs('downloads')
        
    application = Application.builder().token(BOT_TOKEN).build()

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
