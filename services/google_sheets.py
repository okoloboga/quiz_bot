import logging
import re
import time
from typing import List, Optional
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from models import Question, AdminConfig
from config import Config

logger = logging.getLogger(__name__)


class AdminConfigError(Exception):
    """Ошибка, возникающая при отсутствии или некорректных настройках в листе ⚙️Настройки."""


QUESTIONS_SHEET = "❓Вопросы"
ADMIN_SHEET = "⚙️Настройки"
RESULTS_SHEET = "📊Результаты"


class GoogleSheetsService:
    def __init__(self):
        credentials = service_account.Credentials.from_service_account_info(
            Config.GOOGLE_CREDENTIALS,
            scopes=['https://www.googleapis.com/auth/spreadsheets']
        )
        self.service = build('sheets', 'v4', credentials=credentials)
        self.sheet_id = Config.SHEET_ID
        self.max_retries = 3
        self.retry_delay = 1  # начальная задержка в секундах

    def _retry_request(self, func, *args, **kwargs):
        """Выполняет запрос с повторными попытками при ошибках."""
        last_error = None
        for attempt in range(self.max_retries):
            try:
                request = func(*args, **kwargs)
                # Google API возвращает объект запроса, нужно вызвать execute()
                if hasattr(request, 'execute'):
                    return request.execute()
                return request
            except HttpError as e:
                last_error = e
                if e.resp.status in [429, 500, 502, 503, 504]:  # Rate limit или временные ошибки
                    delay = self.retry_delay * (2 ** attempt)  # экспоненциальная задержка
                    logger.warning(f"Ошибка Google Sheets API (попытка {attempt + 1}/{self.max_retries}): {e}. Повтор через {delay}с")
                    time.sleep(delay)
                else:
                    raise
            except Exception as e:
                logger.error(f"Неожиданная ошибка при запросе к Google Sheets: {e}")
                raise
        
        # Если все попытки исчерпаны
        logger.error(f"Не удалось выполнить запрос после {self.max_retries} попыток")
        raise last_error

    def read_admin_config(self) -> AdminConfig:
        """Читает конфигурацию из листа ⚙️Настройки."""
        try:
            range_name = f'{ADMIN_SHEET}!A1:D2'  # Заголовки в A1-D1, значения в A2-D2
            result = self._retry_request(
                self.service.spreadsheets().values().get,
                spreadsheetId=self.sheet_id,
                range=range_name
            )
            values = result.get('values', [])
            
            if len(values) < 2:
                raise AdminConfigError("Лист ⚙️Настройки должен содержать заголовки и значения")
            
            # Ищем значения по заголовкам
            headers = values[0] if len(values) > 0 else []
            data_row = values[1] if len(values) > 1 else []
            
            config_dict = {}
            for i, header in enumerate(headers):
                if i < len(data_row):
                    config_dict[header.lower()] = data_row[i]
            
            required_fields = {
                'количество вопросов': 'num_questions',
                'количество допустимых ошибок': 'max_errors',
                'как часто можно проходить тест (часов)': 'retry_hours',
                'количество секунд на одно задание': 'seconds_per_question',
            }

            parsed_values = {}
            missing_fields = []
            for header_key, attr_name in required_fields.items():
                raw_value = config_dict.get(header_key)
                if raw_value is None or str(raw_value).strip() == '':
                    missing_fields.append(header_key)
                    continue
                try:
                    parsed_values[attr_name] = int(str(raw_value).strip())
                except ValueError:
                    raise AdminConfigError(f"Поле '{header_key}' должно быть целым числом")

            if missing_fields:
                raise AdminConfigError(
                    "Не заполнены обязательные поля: " + ", ".join(missing_fields)
                )
            
            return AdminConfig(
                num_questions=parsed_values['num_questions'],
                max_errors=parsed_values['max_errors'],
                retry_hours=parsed_values['retry_hours'],
                seconds_per_question=parsed_values['seconds_per_question']
            )
        except AdminConfigError:
            raise
        except Exception as e:
            logger.error(f"Ошибка чтения конфигурации (⚙️Настройки): {e}")
            raise

    def read_questions(self) -> List[Question]:
        """Читает все вопросы из листа ❓Вопросы."""
        try:
            range_name = f'{QUESTIONS_SHEET}!A:H'  # Категория, Вопрос, Ответ 1-4, Правильный ответ, ID
            result = self._retry_request(
                self.service.spreadsheets().values().get,
                spreadsheetId=self.sheet_id,
                range=range_name
            )
            values = result.get('values', [])
            
            if len(values) < 2:
                return []
            
            headers = values[0]
            questions = []
            
            # Находим индексы колонок
            header_map = {}
            for i, header in enumerate(headers):
                header_lower = header.lower().strip()
                if 'категория' in header_lower:
                    header_map['category'] = i
                elif 'вопрос' in header_lower:
                    header_map['question'] = i
                elif 'ответ 1' in header_lower or 'ответ1' in header_lower:
                    header_map['answer1'] = i
                elif 'ответ 2' in header_lower or 'ответ2' in header_lower:
                    header_map['answer2'] = i
                elif 'ответ 3' in header_lower or 'ответ3' in header_lower:
                    header_map['answer3'] = i
                elif 'ответ 4' in header_lower or 'ответ4' in header_lower:
                    header_map['answer4'] = i
                elif 'правильный ответ' in header_lower:
                    header_map['correct'] = i
            
            # Читаем строки данных
            for row_idx, row in enumerate(values[1:], start=2):
                if len(row) < max(header_map.values()) + 1:
                    continue
                
                try:
                    def get_value(key, default_index):
                        idx = header_map.get(key)
                        if idx is None:
                            idx = default_index
                        if idx is None or idx >= len(row):
                            return ''
                        return row[idx].strip()

                    category = get_value('category', 0)
                    question_text = get_value('question', 1)
                    if not category or not question_text:
                        logger.warning(f"Строка {row_idx}: категория или текст вопроса пустые")
                        continue
                    def get_answer(key, default_index):
                        idx = header_map.get(key)
                        if idx is None:
                            idx = default_index
                        if idx is None or idx >= len(row):
                            return ''
                        return row[idx].strip()
                    
                    answer1 = get_answer('answer1', 2)
                    answer2 = get_answer('answer2', 3)
                    answer3 = get_answer('answer3', 4)
                    answer4 = get_answer('answer4', 5)
                    answer_list = [answer1, answer2, answer3, answer4]
                    non_empty_answers = [ans for ans in answer_list if ans]
                    if len(non_empty_answers) < 2:
                        logger.warning(f"Строка {row_idx}: недостаточно вариантов ответов (минимум 2)")
                        continue
                    
                    correct_str = row[header_map.get('correct', 6)] if header_map.get('correct') is not None else ''
                    try:
                        correct_answer = int(correct_str)
                        if correct_answer not in [1, 2, 3, 4]:
                            logger.warning(f"Строка {row_idx}: Правильный ответ должен быть 1-4, получено {correct_answer}")
                            continue
                    except (ValueError, TypeError):
                        logger.warning(f"Строка {row_idx}: Неверный формат правильного ответа: {correct_str}")
                        continue
                    
                    if correct_answer > len(answer_list) or correct_answer < 1:
                        logger.warning(f"Строка {row_idx}: индекс правильного ответа вне диапазона: {correct_answer}")
                        continue
                    if not answer_list[correct_answer - 1]:
                        logger.warning(f"Строка {row_idx}: правильный ответ указывает на пустой вариант")
                        continue
                    
                    question = Question(
                        category=category.strip(),
                        question_text=question_text.strip(),
                        answer1=answer1.strip(),
                        answer2=answer2.strip(),
                        answer3=answer3.strip(),
                        answer4=answer4.strip(),
                        correct_answer=correct_answer,
                        row_index=row_idx
                    )
                    questions.append(question)
                except Exception as e:
                    logger.warning(f"Ошибка парсинга строки {row_idx}: {e}")
                    continue
            
            return questions
        except Exception as e:
            logger.error(f"Ошибка чтения вопросов (❓Вопросы): {e}")
            return []

    def get_last_test_time(self, telegram_id: int) -> Optional[float]:
        """Возвращает timestamp последнего прохождения теста для пользователя."""
        try:
            range_name = f'{RESULTS_SHEET}!A:A'  # Колонка telegram_id
            result = self._retry_request(
                self.service.spreadsheets().values().get,
                spreadsheetId=self.sheet_id,
                range=range_name
            )
            values = result.get('values', [])
            
            if len(values) < 2:  # Только заголовок
                return None
            
            # Ищем последнюю запись для этого telegram_id
            telegram_id_str = str(telegram_id)
            last_row = None
            
            for i in range(len(values) - 1, 0, -1):  # Идем с конца
                if i < len(values) and len(values[i]) > 0:
                    if str(values[i][0]) == telegram_id_str:
                        last_row = i + 1  # +1 потому что строки в Sheets начинаются с 1
                        break
            
            if last_row is None:
                return None
            
            # Читаем дату из колонки "Дата прохождения теста" (колонка C, индекс 2)
            date_range = f'{RESULTS_SHEET}!C{last_row}'
            date_result = self._retry_request(
                self.service.spreadsheets().values().get,
                spreadsheetId=self.sheet_id,
                range=date_range
            )
            date_values = date_result.get('values', [])
            
            if not date_values or not date_values[0]:
                return None
            
            # Парсим дату
            from datetime import datetime
            try:
                date_str = date_values[0][0]
                # Пробуем парсить как ISO 8601
                try:
                    dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    return dt.timestamp()
                except ValueError:
                    # Пробуем парсить старый формат
                    dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
                    # Предполагаем, что старые даты были в том же часовом поясе
                    import pytz
                    tz = pytz.timezone("Europe/Moscow")
                    dt = tz.localize(dt)
                    return dt.timestamp()
            except Exception as e:
                logger.warning(f"Ошибка парсинга даты '{date_values[0][0]}': {e}")
                return None
        except Exception as e:
            logger.error(f"Ошибка получения времени последнего теста: {e}")
            return None

    def write_result(
        self,
        telegram_id: int,
        display_name: str,
        test_date: str,
        fio: str,
        result: str,
        correct_count: int,
        notes: Optional[str] = None
    ):
        """Записывает результат теста в лист 📊Результаты."""
        try:
            values = [[
                str(telegram_id),
                display_name or '',
                test_date,
                fio,
                result,
                str(correct_count),
                notes or ''
            ]]
            
            body = {
                'values': values
            }
            
            # Добавляем строку
            append_result = self._retry_request(
                self.service.spreadsheets().values().append,
                spreadsheetId=self.sheet_id,
                range=f'{RESULTS_SHEET}!A:G',
                valueInputOption='RAW',
                insertDataOption='INSERT_ROWS',
                body=body
            )
            
            # Получаем номер добавленной строки из ответа
            updated_range = append_result.get('updates', {}).get('updatedRange', '')
            if updated_range:
                # Парсим номер строки из формата "📊Результаты!A5:G5" или "A5:G5"
                match = re.search(r'!?A(\d+):', updated_range)
                if match:
                    row_number = int(match.group(1))
                    
                    # Очищаем форматирование добавленной строки
                    clear_format_body = {
                        'requests': [{
                            'repeatCell': {
                                'range': {
                                    'sheetId': self._get_sheet_id(RESULTS_SHEET),
                                    'startRowIndex': row_number - 1,  # 0-based
                                    'endRowIndex': row_number,
                                    'startColumnIndex': 0,
                                    'endColumnIndex': 7  # A-G (7 колонок)
                                },
                                'cell': {
                                    'userEnteredFormat': {}
                                },
                                'fields': 'userEnteredFormat'
                            }
                        }]
                    }
                    
                    try:
                        self._retry_request(
                            self.service.spreadsheets().batchUpdate,
                            spreadsheetId=self.sheet_id,
                            body=clear_format_body
                        )
                    except Exception as e:
                        logger.warning(f"Не удалось очистить форматирование строки {row_number}: {e}")
            
            logger.info(f"Результат записан (📊Результаты) для telegram_id={telegram_id}")
        except Exception as e:
            logger.error(f"Ошибка записи результата (📊Результаты): {e}")
            raise
    
    def _get_sheet_id(self, sheet_name: str) -> Optional[int]:
        """Получает ID листа по его названию."""
        try:
            spreadsheet = self._retry_request(
                self.service.spreadsheets().get,
                spreadsheetId=self.sheet_id
            )
            sheets = spreadsheet.get('sheets', [])
            for sheet in sheets:
                if sheet.get('properties', {}).get('title') == sheet_name:
                    return sheet.get('properties', {}).get('sheetId')
            return None
        except Exception as e:
            logger.warning(f"Не удалось получить ID листа {sheet_name}: {e}")
            return None

