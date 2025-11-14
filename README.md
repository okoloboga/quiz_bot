# Telegram Quiz Bot

Telegram bot for conducting tests with questions stored in Google Sheets.

## Requirements

- Docker and Docker Compose
- Google Service Account with access to Google Sheets
- Telegram Bot Token

## Setup

1. Create a `.env` file in the project root and add the following variables:

```env
TELEGRAM_TOKEN=your_telegram_bot_token_here
GOOGLE_CREDENTIALS=config/quizbot.json
SHEET_ID=your_google_sheet_id_here
REDIS_URL=redis://redis:6379/0
LOG_LEVEL=INFO
SESSION_TTL_PADDING=300
```

   Note: The timezone is hardcoded in the code as `Europe/Moscow` (UTC+3).

2. Configure Google Sheets:
   - Create a document with three sheets: `❓Вопросы`, `⚙️Настройки`, `📊Результаты`
   - Grant access to the service account
   - Fill in the sheets according to the specification in `SPEC.md`

## Running

```bash
docker-compose up -d
```

## Google Sheets Structure

### Sheet ❓Вопросы
Columns:
- Category
- Question
- Answer 1
- Answer 2
- Answer 3
- Answer 4
- Correct Answer (1-4)
- The number of valid questions in this sheet must be at least equal to the "Number of questions" value from the ⚙️Настройки sheet. Otherwise, the bot will respond: "В боте недостаточно вопросов. обратитесь к администратору" (Not enough questions in the bot. Contact the administrator).

### Sheet ⚙️Настройки
Columns (headers in the first row, values in the second):
- Number of questions
- Number of allowed errors
- How often the test can be taken (hours)
- Number of seconds per question
- All four fields are required. If at least one of them is empty, the bot will respond: "У бота отсутствуют необходимые настройки. обратитесь к администратору" (The bot is missing necessary settings. Contact the administrator).

### Sheet 📊Результаты
Columns (filled automatically):
- telegram_id
- username (if available). If username is missing, `first_name + last_name` is recorded (or just `first_name` if last name is not specified).
- Test completion date
- Full name (FIO)
- Result
- Number of correct answers
- Notes

## Logs

Logs are output to stdout and contain information about:
- Session start/completion
- Questions and answers
- Test results
- API errors

## Stopping

```bash
docker-compose down
```

## License

MIT License - see [LICENSE](LICENSE) file for details.
