import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from config import Config
from handlers import common, fio, test
from services.redis_service import RedisService

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger(__name__)

redis_service = RedisService()


async def main():
    """Главная функция запуска бота."""
    # Валидация конфигурации
    try:
        Config.validate()
    except ValueError as e:
        logger.error(f"Ошибка конфигурации: {e}")
        sys.exit(1)
    
    # Подключение к Redis
    await redis_service.connect()
    
    # Инициализация бота и диспетчера
    bot = Bot(token=Config.TELEGRAM_TOKEN)
    
    # Используем Redis storage для FSM
    storage = None
    if redis_service.redis_client:
        try:
            storage = RedisStorage.from_url(Config.REDIS_URL)
        except Exception as e:
            logger.warning(f"Не удалось создать RedisStorage, используем память: {e}")
            from aiogram.fsm.storage.memory import MemoryStorage
            storage = MemoryStorage()
    else:
        from aiogram.fsm.storage.memory import MemoryStorage
        storage = MemoryStorage()
        logger.warning("Используется MemoryStorage вместо Redis")
    
    dp = Dispatcher(storage=storage)
    
    # Регистрация роутеров
    dp.include_router(common.router)
    dp.include_router(fio.router)
    dp.include_router(test.router)
    
    logger.info("Бот запущен")
    
    try:
        # Запуск polling
        await dp.start_polling(bot, skip_updates=True)
    finally:
        await bot.session.close()
        await redis_service.disconnect()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановка по запросу пользователя")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)

