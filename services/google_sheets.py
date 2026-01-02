import logging
import re
import time
from datetime import datetime
from typing import List, Optional

import pytz
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import Config
from models import (AdminConfig, Campaign, CampaignAssignmentType, CampaignType,
                    Question, UserInfo, UserResult, UserStatus)

logger = logging.getLogger(__name__)


class AdminConfigError(Exception):
    """Ошибка, возникающая при отсутствии или некорректных настройках в листе ⚙️Настройки."""


USERS_SHEET = "Пользователи"
QUESTIONS_SHEET = "Вопросы"
ADMIN_SHEET = "Настройки"
RESULTS_SHEET = "Результаты"
CAMPAIGNS_SHEET = "Кампании"


class GoogleSheetsService:
    def __init__(self):
        credentials = service_account.Credentials.from_service_account_info(
            Config.GOOGLE_CREDENTIALS,
            scopes=['https://www.googleapis.com/auth/spreadsheets']
        )
        self.service = build('sheets', 'v4', credentials=credentials)
        self.sheet_id = Config.SHEET_ID
        self.max_retries = 3
        self.retry_delay = 1

    def _retry_request(self, func, *args, **kwargs):
        last_error = None
        for attempt in range(self.max_retries):
            try:
                request = func(*args, **kwargs)
                if hasattr(request, 'execute'):
                    return request.execute()
                return request
            except HttpError as e:
                last_error = e
                if e.resp.status in [429, 500, 502, 503, 504]:
                    delay = self.retry_delay * (2 ** attempt)
                    logger.warning(
                        f"Ошибка Google Sheets API (попытка {attempt + 1}/{self.max_retries}): {e}. Повтор через {delay}с")
                    time.sleep(delay)
                else:
                    raise
            except Exception as e:
                logger.error(f"Неожиданная ошибка при запросе к Google Sheets: {e}")
                raise
        logger.error(f"Не удалось выполнить запрос после {self.max_retries} попыток")
        raise last_error

    def add_user(self, telegram_id: str, phone_number: str, fio: str, motorcade: str, status: str = "ожидает"):
        try:
            values = [[telegram_id, phone_number, fio, motorcade, status]]
            body = {'values': values}
            self._retry_request(
                self.service.spreadsheets().values().append,
                spreadsheetId=self.sheet_id,
                range=f"'{USERS_SHEET}'!A:E",
                valueInputOption='RAW',
                insertDataOption='INSERT_ROWS',
                body=body
            )
            logger.info(f"Пользователь {telegram_id} добавлен в лист '{USERS_SHEET}' со статусом '{status}'")
        except Exception as e:
            logger.error(f"Ошибка добавления пользователя в лист '{USERS_SHEET}': {e}")
            raise

    def get_user_info(self, telegram_id: str) -> Optional[UserInfo]:
        try:
            range_name = f"'{USERS_SHEET}'!A:E"
            result = self._retry_request(
                self.service.spreadsheets().values().get,
                spreadsheetId=self.sheet_id,
                range=range_name
            )
            values = result.get('values', [])
            if not values:
                return None

            headers = [h.lower() for h in values[0]]
            try:
                id_col = headers.index('telegram_id')
                phone_col = headers.index('телефон')
                fio_col = headers.index('фио')
                motorcade_col = headers.index('автоколонна')
                status_col = headers.index('статус')
            except ValueError as e:
                logger.error(f"В листе '{USERS_SHEET}' отсутствует обязательная колонка: {e}")
                return None

            for row in values[1:]:
                if len(row) > id_col and str(row[id_col]) == telegram_id:
                    try:
                        # Убираем пробелы из статуса перед парсингом
                        status_str = row[status_col].strip()
                        status = UserStatus(status_str)
                        
                        return UserInfo(
                            telegram_id=str(row[id_col]),
                            phone=row[phone_col],
                            fio=row[fio_col],
                            motorcade=row[motorcade_col],
                            status=status
                        )
                    except (ValueError, IndexError):
                        original_status = row[status_col] if status_col < len(row) else "[СТАТУС НЕ НАЙДЕН]"
                        logger.warning(
                            f"Некорректный статус ('{original_status}') или структура для пользователя {telegram_id}"
                        )
                        return None
            return None
        except Exception as e:
            logger.error(f"Ошибка получения информации о пользователе {telegram_id}: {e}")
            return None

    def get_all_campaigns(self) -> List[Campaign]:
        campaigns = []
        try:
            range_name = f"'{CAMPAIGNS_SHEET}'!A:E"
            result = self._retry_request(self.service.spreadsheets().values().get, spreadsheetId=self.sheet_id,
                                          range=range_name)
            values = result.get('values', [])
            if len(values) < 2:
                return []

            headers = [h.lower() for h in values[0]]
            try:
                name_col = headers.index('название_кампании')
                deadline_col = headers.index('дедлайн')
                type_col = headers.index('тип')
                assign_type_col = headers.index('тип_назначения')
                assign_val_col = headers.index('значение_назначения')
            except ValueError as e:
                logger.error(f"В листе '{CAMPAIGNS_SHEET}' отсутствует обязательная колонка: {e}")
                return []

            for row_idx, row in enumerate(values[1:], start=2):
                try:
                    name = row[name_col]
                    if not name: continue

                    deadline = datetime.strptime(row[deadline_col], "%Y-%m-%d")
                    ctype = CampaignType(row[type_col])
                    atype = CampaignAssignmentType(row[assign_type_col].lower())
                    aval = row[assign_val_col] if assign_val_col < len(row) else ""

                    campaigns.append(
                        Campaign(name=name, deadline=deadline, type=ctype, assignment_type=atype, assignment_value=aval))
                except (ValueError, IndexError) as e:
                    logger.warning(f"Ошибка парсинга кампании в строке {row_idx}: {e}")
                    continue
            return campaigns
        except Exception as e:
            logger.error(f"Ошибка чтения кампаний из листа '{CAMPAIGNS_SHEET}': {e}")
            return []

    def get_user_results(self, telegram_id: str) -> List[UserResult]:
        results = []
        try:
            range_name = f"'{RESULTS_SHEET}'!A:H"  # Захватываем все нужные колонки
            result = self._retry_request(self.service.spreadsheets().values().get, spreadsheetId=self.sheet_id,
                                          range=range_name)
            values = result.get('values', [])
            if len(values) < 2:
                return []

            headers = [h.lower() for h in values[0]]
            try:
                id_col = headers.index('telegram_id')
                date_col = headers.index('дата прохождения теста')
                campaign_col = headers.index('название_кампании')
                status_col = headers.index('итоговый_статус')
            except ValueError as e:
                logger.error(f"В листе '{RESULTS_SHEET}' отсутствует обязательная колонка: {e}")
                return []

            for row in values[1:]:
                if len(row) > id_col and str(row[id_col]) == telegram_id:
                    try:
                        date_str = row[date_col]
                        dt = datetime.fromisoformat(date_str)
                        results.append(UserResult(
                            telegram_id=str(row[id_col]),
                            date=dt,
                            campaign_name=row[campaign_col],
                            final_status=row[status_col]
                        ))
                    except (ValueError, IndexError) as e:
                        logger.warning(f"Ошибка парсинга результата для пользователя {telegram_id}: {e}")
                        continue
            return results
        except Exception as e:
            logger.error(f"Ошибка получения результатов пользователя {telegram_id}: {e}")
            return []

    def get_active_campaign_for_user(self, telegram_id: str) -> Optional[Campaign]:
        user_info = self.get_user_info(telegram_id)
        if not user_info:
            logger.warning(f"Для telegram_id {telegram_id} не найдена информация о пользователе.")
            return None

        all_campaigns = self.get_all_campaigns()
        user_results = self.get_user_results(telegram_id)
        
        # Создаем словарь для последнего результата по каждой кампании
        # Сортируем результаты по дате, чтобы гарантировать, что мы берем последний
        user_results.sort(key=lambda r: r.date, reverse=True)
        latest_results = {res.campaign_name: res.final_status for res in reversed(user_results)}

        today = datetime.now()

        for campaign in all_campaigns:
            # 1. Проверка дедлайна
            if campaign.deadline.date() < today.date():
                continue

            # 2. Проверка назначения
            assigned = False
            if campaign.assignment_type == CampaignAssignmentType.ALL:
                assigned = True
            elif campaign.assignment_type == CampaignAssignmentType.MOTORCADE:
                if user_info.motorcade == campaign.assignment_value:
                    assigned = True
            elif campaign.assignment_type == CampaignAssignmentType.TELEGRAM_ID:
                if user_info.telegram_id == campaign.assignment_value:
                    assigned = True
            
            if not assigned:
                continue

            # 3. Проверка статуса прохождения
            last_status = latest_results.get(campaign.name)
            
            # Если статуса нет - кампания доступна
            if last_status is None:
                logger.info(f"Найдена активная кампания '{campaign.name}' для пользователя {telegram_id} (ранее не проходил).")
                return campaign
            
            # Если статус 'разрешена пересдача' - кампания доступна
            if last_status == "разрешена пересдача":
                logger.info(f"Найдена активная кампания '{campaign.name}' для пользователя {telegram_id} (разрешена пересдача).")
                return campaign
            
            # В остальных случаях (пройден, не пройден и т.д.) - кампания недоступна
            # (Логика "не пройден" может быть изменена, но пока считаем любую попытку, кроме пересдачи, завершенной)

        logger.info(f"Для пользователя {telegram_id} не найдено активных кампаний.")
        return None

    def read_admin_config(self) -> AdminConfig:
        try:
            range_name = f"'{ADMIN_SHEET}'!A1:D2"
            result = self._retry_request(
                self.service.spreadsheets().values().get,
                spreadsheetId=self.sheet_id,
                range=range_name
            )
            values = result.get('values', [])

            if len(values) < 2:
                raise AdminConfigError("Лист Настройки должен содержать заголовки и значения")

            headers = values[0]
            data_row = values[1]
            config_dict = {header.lower(): data_row[i] for i, header in enumerate(headers) if i < len(data_row)}

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
                if not raw_value or not str(raw_value).strip():
                    missing_fields.append(header_key)
                    continue
                try:
                    parsed_values[attr_name] = int(str(raw_value).strip())
                except ValueError:
                    raise AdminConfigError(f"Поле '{header_key}' должно быть целым числом")

            if missing_fields:
                raise AdminConfigError("Не заполнены обязательные поля: " + ", ".join(missing_fields))

            return AdminConfig(**parsed_values)
        except AdminConfigError:
            raise
        except Exception as e:
            logger.error(f"Ошибка чтения конфигурации (Настройки): {e}")
            raise

    def read_questions(self) -> List[Question]:
        try:
            range_name = f"'{QUESTIONS_SHEET}'!A:J"  # Расширяем диапазон
            result = self._retry_request(
                self.service.spreadsheets().values().get,
                spreadsheetId=self.sheet_id,
                range=range_name
            )
            values = result.get('values', [])
            if len(values) < 2: return []

            headers = [h.lower().strip() for h in values[0]]
            questions = []

            # Динамически находим индексы
            try:
                h = {
                    'cat': headers.index('категория'), 'q': headers.index('вопрос'),
                    'a1': headers.index('ответ 1'), 'a2': headers.index('ответ 2'),
                    'a3': headers.index('ответ 3'), 'a4': headers.index('ответ 4'),
                    'correct': headers.index('правильный ответ'),
                    'crit': headers.index('критический_вопрос'),
                    'exp': headers.index('пояснение')
                }
            except ValueError as e:
                logger.error(f"В листе '{QUESTIONS_SHEET}' отсутствует обязательная колонка: {e}")
                return []


            for row_idx, row in enumerate(values[1:], start=2):
                try:
                    # Используем get для безопасного доступа
                    get = lambda index: row[index].strip() if index < len(row) and row[index] else ""

                    question_text = get(h['q'])
                    if not get(h['cat']) or not question_text:
                        continue

                    answers = [get(h['a1']), get(h['a2']), get(h['a3']), get(h['a4'])]
                    if len([ans for ans in answers if ans]) < 2:
                        continue

                    correct_answer = int(get(h['correct']))
                    if not (1 <= correct_answer <= 4 and answers[correct_answer - 1]):
                        continue

                    is_critical = get(h['crit']).upper() == 'TRUE'
                    explanation = get(h['exp'])

                    questions.append(Question(
                        category=get(h['cat']), question_text=question_text,
                        answer1=answers[0], answer2=answers[1], answer3=answers[2], answer4=answers[3],
                        correct_answer=correct_answer, is_critical=is_critical,
                        explanation=explanation, row_index=row_idx
                    ))
                except (ValueError, IndexError) as e:
                    logger.warning(f"Ошибка парсинга вопроса в строке {row_idx}: {e}")
                    continue

            return questions
        except Exception as e:
            logger.error(f"Ошибка чтения вопросов ({QUESTIONS_SHEET}): {e}")
            return []

    def get_last_test_time(self, telegram_id: int) -> Optional[float]:
        try:
            range_name = f"'{RESULTS_SHEET}'!A:C"
            result = self._retry_request(
                self.service.spreadsheets().values().get,
                spreadsheetId=self.sheet_id,
                range=range_name
            )
            values = result.get('values', [])
            if len(values) < 2: return None

            telegram_id_str = str(telegram_id)
            for row in reversed(values[1:]):
                if not row: continue
                if str(row[0]) == telegram_id_str and len(row) > 2 and row[2]:
                    try:
                        return datetime.fromisoformat(row[2]).timestamp()
                    except ValueError:
                        logger.warning(f"Не удалось распознать формат даты '{row[2]}'")
                        continue
            return None
        except Exception as e:
            logger.error(f"Ошибка получения времени последнего теста: {e}")
            return None

    def write_result(self, telegram_id: int, display_name: str, test_date: str, fio: str, result: str,
                     correct_count: int, campaign_name: str, final_status: str, notes: Optional[str] = None):
        """Записывает результат теста в лист Результаты."""
        try:
            values = [[
                str(telegram_id), display_name or '', test_date, fio, result,
                str(correct_count), notes or '', final_status, campaign_name
            ]]
            body = {'values': values}

            # Находим правильный диапазон, включая новые колонки
            range_to_append = f"'{RESULTS_SHEET}'!A:I" # A-I, 9 колонок

            append_result = self._retry_request(
                self.service.spreadsheets().values().append,
                spreadsheetId=self.sheet_id, range=range_to_append,
                valueInputOption='RAW', insertDataOption='INSERT_ROWS', body=body
            )

            updated_range = append_result.get('updates', {}).get('updatedRange', '')
            if updated_range:
                match = re.search(r'!?A(\d+):', updated_range)
                if match:
                    row_number = int(match.group(1))
                    try:
                        sheet_id = self._get_sheet_id(RESULTS_SHEET)
                        if sheet_id is not None:
                            clear_format_body = {'requests': [{'repeatCell': {
                                'range': {
                                    'sheetId': sheet_id,
                                    'startRowIndex': row_number - 1, 'endRowIndex': row_number,
                                    'startColumnIndex': 0, 'endColumnIndex': 9
                                },
                                'cell': {'userEnteredFormat': {}},
                                'fields': 'userEnteredFormat'
                            }}]}
                            self._retry_request(
                                self.service.spreadsheets().batchUpdate,
                                spreadsheetId=self.sheet_id, body=clear_format_body
                            )
                    except Exception as e:
                        logger.warning(f"Не удалось очистить форматирование строки {row_number}: {e}")

            logger.info(f"Результат записан ({RESULTS_SHEET}) для telegram_id={telegram_id}")
        except Exception as e:
            logger.error(f"Ошибка записи результата ({RESULTS_SHEET}): {e}")
            raise

    def _get_sheet_id(self, sheet_name: str) -> Optional[int]:
        try:
            spreadsheet = self._retry_request(
                self.service.spreadsheets().get,
                spreadsheetId=self.sheet_id
            )
            for sheet in spreadsheet.get('sheets', []):
                if sheet.get('properties', {}).get('title') == sheet_name:
                    return sheet.get('properties', {}).get('sheetId')
            return None
        except Exception as e:
            logger.warning(f"Не удалось получить ID листа {sheet_name}: {e}")
            return None

