import telebot
from telebot import types
import yt_dlp
import os
import logging
import subprocess
import re
import glob

# Настройки логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Автоочистка папки downloads перед запуском
script_dir = os.path.dirname(os.path.abspath(__file__))
output_dir = os.path.join(script_dir, "downloads")
logger.info("Autodeletings files into 'downloads' folder")

if os.path.exists(output_dir):
    for file in glob.glob(os.path.join(output_dir, "*")):
        try:
            os.remove(file)
            logger.info(f"Removed old file: {file}")
        except Exception as e:
            logger.warning(f"Failed to remove file during cleanup: {e}")
else:
    os.makedirs(output_dir, exist_ok=True)
    logger.info("Created downloads directory")

# Проверка наличия FFmpeg
try:
    # Явно указываем полный путь к FFmpeg
    ffmpeg_path = r'C:\\abc\\ffmpeg-2025-05-15-git-12b853530a-essentials_build\\bin\\ffmpeg'
    result = subprocess.run([ffmpeg_path, '-version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if result.returncode == 0:
        logger.info("FFmpeg: Установлен и готов к использованию")
    else:
        raise FileNotFoundError("FFmpeg не найден по указанному пути")

except FileNotFoundError as e:
    logger.error(f"FFmpeg не установлен или не добавлен в PATH: {e}")
    print("[Ошибка] FFmpeg не установлен или не добавлен в переменные среды (PATH).")
    print("👉 Скачай с https://www.gyan.dev/ffmpeg/builds/ ")
    print("👉 Распакуй архив и добавь путь к ffmpeg\\bin в системные переменные среды")
    exit(1)

# Добавляем путь к FFmpeg в окружение для yt-dlp
os.environ["PATH"] += os.pathsep + os.path.dirname(ffmpeg_path)
logger.info(f"Added FFmpeg path to environment: {ffmpeg_path}")

# === Настройки бота ===
TOKEN = '7999725213:AAE8DApPm0NapLJtXjj5eEJhUdUWYk5Olvo'  # заменить на свой токен
bot = telebot.TeleBot(TOKEN)

# === Состояния пользователей ===
user_state = {}  # {chat_id: {"platform": "youtube", "awaiting_url": True}}

# === Клавиатура для выбора платформы ===
markup_platforms = types.ReplyKeyboardMarkup(resize_keyboard=True)
markup_platforms.add(types.KeyboardButton("Instagram"))
logging.info('All consts has are initialized')

# === Команда /start ===
@bot.message_handler(commands=['start'])
def start(message):
    chat_id = message.chat.id
    user_state[chat_id] = {"platform": None, "awaiting_url": True}
    bot.send_message(chat_id, "Привет! Выбери платформу, с которой хочешь скачать видео:", reply_markup=markup_platforms)
    logger.info(f"User {chat_id} started")

# === Выбор платформы ===
@bot.message_handler(func=lambda m: m.text in ["Instagram"])
def handle_platform_choice(message):
    chat_id = message.chat.id
    platform = message.text.lower()
    user_state[chat_id]["platform"] = platform
    user_state[chat_id]["awaiting_url"] = True
    bot.send_message(chat_id, f"Хорошо! Пришли ссылку на видео с {platform.capitalize()}.")
    logger.info(f"User {chat_id} selected platform: {platform}")

# === Обработка URL от пользователя ===
@bot.message_handler(func=lambda m: user_state.get(m.chat.id, {}).get("awaiting_url"))
def handle_video_url(message):
    chat_id = message.chat.id
    url = message.text.strip()
    bot.send_message(chat_id, "Скачиваю видео... Подожди немного.")

    try:
        downloaded_file_path = None

        def hook(d):
            nonlocal downloaded_file_path
            if d['status'] == 'finished':
                downloaded_file_path = d['filename']

        ydl_opts = {
            'format': 'best[ext=mp4]',  # Берём уже готовое .mp4 (без разделения на video/audio)
            'outtmpl': os.path.join(output_dir, '%(title)s.%(ext)s'),
            'retries': 5,
            'socket_timeout': 60,
            'ffmpeg_location': os.path.dirname(ffmpeg_path),
        }

        platform = user_state[chat_id].get("platform")
        if platform == "instagram":
            ydl_opts.update({
                'extractor_args': {'instagram': ['--username', 'public', '--password', 'none']},
            })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        # Поиск скачанного файла
        title = info.get('title', 'video')
        safe_title = re.sub(r'[<>:"/\\|?*]', '_', title)

        video_path = None
        for ext in ['.mp4', '.webm', '.mkv', '.avi']:
            test_path = os.path.join(output_dir, f"{safe_title}{ext}")
            if os.path.isfile(test_path):
                video_path = test_path
                break

        # Если не нашли по названию, ищем любой .mp4 файл
        if not video_path:
            video_files = glob.glob(os.path.join(output_dir, "*.mp4"))
            if video_files:
                video_path = video_files[0]
                logger.warning(f"Used fallback file detection: {video_path}")
            else:
                bot.send_message(chat_id, "Не удалось найти скачанное видео.")
                logger.error(f"No valid video file found for user {chat_id}")
                return

        # Переименовываем в безопасное имя
        final_path = os.path.join(output_dir, f"{chat_id}_video.mp4")
        os.rename(video_path, final_path)
        video_path = final_path

        # Проверяем длительность
        duration = info.get('duration')
        if duration and duration > 60:
            bot.send_message(chat_id, f"Видео слишком длинное: {duration:.1f} секунд. Максимум 60 секунд.")
            logger.warning(f"Video too long ({duration:.1f}s) for user {chat_id}")
            os.remove(video_path)
            return

        # Проверяем размер
        file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
        if file_size_mb > 49:
            bot.send_message(chat_id, f"Видео слишком большое ({file_size_mb:.2f} МБ).")
            logger.warning(f"Video too large ({file_size_mb:.2f} MB), skipped sending.")
            os.remove(video_path)
            return

        # Отправляем видео
        with open(video_path, 'rb') as video_file:
            bot.send_video(chat_id, video_file)
        bot.send_message(chat_id, "Видео успешно отправлено!")
        logger.info(f"Sent {platform} video to user {chat_id}")

        # Удаляем файл после отправки
        os.remove(video_path)

    except Exception as e:
        logger.error(f'Error downloading video for user {chat_id}: {e}', exc_info=True)
        bot.send_message(chat_id, f"Ошибка при скачивании или отправке видео: {str(e)}")

    finally:
        if chat_id in user_state:
            del user_state[chat_id]

# === Запуск бота ===
if __name__ == '__main__':
    logger.info("Starting Telegram bot...")
    bot.polling(none_stop=True)