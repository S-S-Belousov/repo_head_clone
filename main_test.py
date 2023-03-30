import asyncio
import hashlib
import logging
import os
import shutil
import tempfile
import unittest
from http import HTTPStatus
from unittest import TestCase, mock
from unittest.mock import Mock

import aiohttp

from constants import (END, NUM_OF_BLOCKS, START, TEMP_DIR, TEST_CONTENT,
                       TEST_FILE)
from main import download_and_hash_file, download_chunk, download_repo


class TestDownloadAndHashFile(unittest.TestCase):
    def setUp(self):
        self.test_file = TEST_FILE
        self.test_content = TEST_CONTENT

        # Создаем временный файл для тестирования
        with open(self.test_file, 'wb') as f:
            f.write(self.test_content)

    def tearDown(self):
        # Удаляем временный файл
        os.remove(self.test_file)

    def test_download_and_hash_file(self):
        # Вычисляем ожидаемый хэш
        expected_hash = hashlib.sha256(self.test_content).hexdigest()

        # Вызываем функцию download_and_hash_file и сравниваем результат с ожидаемым хэшем
        loop = asyncio.get_event_loop()
        result_hash = loop.run_until_complete(
            download_and_hash_file(self.test_file, Mock()))

        self.assertEqual(result_hash, expected_hash)


class TestDownloadChunk(unittest.TestCase):

    async def mock_response(self, content):
        response = mock.MagicMock()
        response.status = HTTPStatus.OK
        response.content.iter_chunked.return_value = [content]
        return response

    async def test_download_chunk(self):
        # готовим входные параметры
        temp_dir = tempfile.mkdtemp()
        expected_content = b'a' * (END - START + 1)

        # заменяем реальный объект aiohttp.ClientSession на MagicMock и устанавливаем mock_get вместо метода get
        with Mock.patch('aiohttp.ClientSession.get', new_callable=mock.MagicMock) as mock_get:
            # создаем объект ответа, который будет использоваться вместо реального ответа от сервера
            mock_get.return_value = self.mock_response(expected_content)

            # запускаем тестируемую функцию
            await download_chunk(mock.MagicMock(), START, END, temp_dir, mock.MagicMock())

        # проверяем, что файл с нужным именем был создан и содержит правильное содержимое
        filename = os.path.join(temp_dir, f'temp_{START}_{END}')
        with open(filename, 'rb') as f:
            content = f.read()

        # удаляем временный файл
        os.remove(filename)

        # проверяем, что содержимое файла правильное
        self.assertEqual(content, expected_content)

        # проверяем, что хеш содержимого файла правильный
        expected_hash = hashlib.sha256(expected_content).hexdigest()
        self.assertEqual(expected_hash, await download_and_hash_file(filename, mock.MagicMock()))


class TestDownloadRepo(TestCase):

    def setUp(self):
        self.logger = mock.MagicMock()

    @mock.patch('main.os.makedirs')
    @mock.patch('main.aiohttp.ClientSession.head')
    async def test_successful_download_and_hash(self, mock_head, mock_makedirs):
        # Задаем заглушку для head-запроса
        content_length = 3000
        mock_head.return_value.headers.get.return_value = str(content_length)

        # Создаем временную папку
        mock_makedirs.return_value = None

        # Создаем заглушки для скачивания каждой части репозитория
        async def mock_download_chunk(session, start, end, temp_dir, logger):
            filename = f'temp_{start}_{end}'
            filepath = f'{temp_dir}/{filename}'
            with open(filepath, 'wb') as f:
                f.write(b'0' * (end - start + 1))
            return filename

        # Создаем заглушку для вычисления хэша файла
        async def mock_download_and_hash_file(filepath, logger):
            return 'fake_hash'

        # Вызываем функцию download_repo
        with mock.patch('main.download_chunk', side_effect=mock_download_chunk):
            with mock.patch('main.download_and_hash_file', side_effect=mock_download_and_hash_file):
                await download_repo(self.logger)

        # Проверяем, что все части репозитория были скачаны и хэши вычислены
        for i in range(NUM_OF_BLOCKS):
            self.assertTrue(
                f'temp_{i*1000}_{i*1000+999}' in os.listdir(TEMP_DIR))
            self.logger.info.assert_any_call(
                f'temp_{i*1000}_{i*1000+999}: fake_hash')


class TestAsyncFunctions(unittest.TestCase):

    def setUp(self):
        self.logger = logging.getLogger(__name__)
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    async def test_download_chunk_with_connection_error(self):
        with Mock.patch('aiohttp.ClientSession.get', new_callable=Mock.AsyncMock) as mock_get:
            mock_get.side_effect = aiohttp.client_exceptions.ClientConnectorError()
            await download_chunk(Mock.MagicMock(), START, END, self.temp_dir, self.logger)
        filename = os.path.join(self.temp_dir, f'temp_{START}_{END}')
        self.assertFalse(os.path.exists(filename))

    async def test_download_chunk_with_server_error(self):
        with Mock.patch('aiohttp.ClientSession.get', new_callable=Mock.AsyncMock) as mock_get:
            mock_response = Mock.MagicMock()
            mock_response.status = HTTPStatus.INTERNAL_SERVER_ERROR
            mock_get.return_value = mock_response
            await download_chunk(Mock.MagicMock(), START, END, self.temp_dir, self.logger)
        filename = os.path.join(self.temp_dir, f'temp_{START}_{END}')
        self.assertFalse(os.path.exists(filename))

    async def test_download_and_hash_file_with_missing_file(self):
        with self.assertRaises(Exception) as context:
            await download_and_hash_file(os.path.join(self.temp_dir, 'non_existent_file'), self.logger)
        self.assertTrue('Failed to hash file' in str(context.exception))

    async def test_download_and_hash_file_with_io_error(self):
        filename = os.path.join(self.temp_dir, 'temp_file')
        with open(filename, 'w') as f:
            f.write('test')
        with open(filename, 'r') as f:
            with self.assertRaises(Exception) as context:
                await download_and_hash_file(filename, self.logger)
            self.assertTrue('Failed to hash file' in str(context.exception))

    async def test_download_repo_with_connection_error(self):
        with Mock.patch('aiohttp.ClientSession.head', new_callable=Mock.AsyncMock) as mock_head:
            mock_head.side_effect = aiohttp.client_exceptions.ClientConnectorError()
            await download_repo(self.logger)
        self.assertFalse(os.path.exists(self.temp_dir))

    async def test_download_repo_with_server_error(self):
        with Mock.patch('aiohttp.ClientSession.head', new_callable=Mock.AsyncMock) as mock_head:
            mock_response = Mock.MagicMock()
            mock_response.status = HTTPStatus.INTERNAL_SERVER_ERROR
            mock_head.return_value = mock_response
            await download_repo(self.logger)
        self.assertFalse(os.path.exists(self.temp_dir))
