"""Загружаем библиотеки."""
import asyncio
import hashlib
import logging
import os

import aiohttp

from constants import BLOCK_SIZE, NUM_OF_BLOCKS, REPO_URL, TEMP_DIR


async def get_content_length(logger, session):
    """Функция получения размера репозитория из заголовка Content-Length."""
    try:
        async with session.head(REPO_URL) as response:
            content_length = int(response.headers.get('Content-Length', 0))
        return content_length
    except aiohttp.client_exceptions.ClientConnectorError as error:
        logger.error("Failed to connect to server: {}".format(error))


async def create_temp_dir(logger):
    """Функция создания временной папки"""
    if not os.path.exists(TEMP_DIR):
        try:
            os.makedirs(TEMP_DIR)
        except OSError as error:
            logger.error("Failed to create directory: {}".format(error))
            return False
    return True


async def download_chunks(logger, session, content_length):
    """Функция загрузки разных частей репозитория"""
    chunk_size = content_length // NUM_OF_BLOCKS
    tasks = []

    for i in range(NUM_OF_BLOCKS):
        start = i * chunk_size
        end = start + chunk_size - 1
        if i == 2:
            end = content_length
        task = asyncio.create_task(download_chunk(session, start, end, TEMP_DIR, logger))
        tasks.append(task)

    try:
        await asyncio.gather(*tasks)
        return True
    except Exception as error:
        logger.error("Failed to download repository: {}".format(error))
        return False


async def compute_file_hashes(logger):
    """Функция вычисления SHA256 хэша каждого файла во временной папке"""
    for filename in os.listdir(TEMP_DIR):
        filepath = os.path.join(TEMP_DIR, filename)
        try:
            hash_digest = await download_and_hash_file(filepath, logger)
            logger.info("{filename}: {hash_digest}".format(
                filename, hash_digest)
                )
        except Exception as error:
            logger.error("Failed to hash file: {}".format(error))
            return False
    return True


async def download_repo(logger):
    """Функция загрузки HEAD репозитория"""
    async with aiohttp.ClientSession() as session:
        content_length = await get_content_length(logger, session)
        if content_length is None:
            return

        if not await create_temp_dir(logger):
            return

        if not await download_chunks(logger, session, content_length):
            return

        if not await compute_file_hashes(logger):
            return


async def download_chunk(session, start, end, temp_dir, logger):
    # задаем заголовок Range, чтобы загрузить только нужную часть репозитория
    headers = {"Range": "bytes={}-{}".format(start, end)}
    try:
        async with session.get(REPO_URL, headers=headers) as response:
            # создаем временный файл и записываем в него содержимое
            with open(
                os.path.join(temp_dir, "temp_{}_{}".format(start, end)), "wb"
                      ) as file:
                async for chunk in response.content.iter_chunked(BLOCK_SIZE):
                    file.write(chunk)
    except Exception as error:
        logger.error("Failed to download chunk: {}".format(error))
        return


async def download_and_hash_file(filepath, logger):
    # читаем содержимое файла, вычисляем для него SHA256 хэш
    with open(filepath, "rb") as file:
        content = file.read()
        hash_object = hashlib.sha256(content)
        return hash_object.hexdigest()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(download_repo(logger))
