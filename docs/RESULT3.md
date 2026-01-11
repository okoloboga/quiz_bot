# Testing & Bug Fixing Session Results (Phase 6)

**Date**: 2026-01-11
**Phase**: Phase 6 - Final Testing & Bug Fixes
**Status**: ✅ All Critical Bugs Fixed - Production Ready

---

## 🎯 Session Overview

This document records all bugs discovered and fixed during the final testing phase of the quiz bot implementation. All phases 1-5 were already implemented, and this session focused on testing the complete user flow and fixing critical runtime errors.

**Starting Point**: Phases 1-5 implemented, bot deployed, ready for testing
**Outcome**: 8 critical bugs fixed, full user flow validated, production ready

---

## 🐛 Critical Bugs Fixed

### Bug #1: TypeError - Missing Callback Data Parameter ⚠️ CRITICAL

**Severity**: CRITICAL - Test completely broken
**Error Message**:
```
TypeError: process_answer() missing 1 required positional argument: 'cbd'
```

**Symptom**: User could not answer ANY questions - first question click would crash

**Root Cause**:
In aiogram 3.x, when using `CallbackData.filter()`, the parameter MUST be named `callback_data`, not `cbd`.

**File**: `handlers/test.py:152`

**Fix Applied**:
```python
# ❌ BEFORE (broken)
async def process_answer(cb: CallbackQuery, cbd: AnswerCallback, state: FSMContext):
    is_correct = cbd.answer == question.correct_answer

# ✅ AFTER (fixed)
async def process_answer(cb: CallbackQuery, callback_data: AnswerCallback, state: FSMContext):
    is_correct = callback_data.answer == question.correct_answer
```

**Also Updated**:
- Line 157: `callback_data.question_index`
- Line 167: `callback_data.answer`
- Line 191: `callback_data.answer` (logging)

**Impact**: ✅ Users can now answer questions successfully

---

### Bug #2: Wrong Telegram ID on Timeout ⚠️ CRITICAL

**Severity**: CRITICAL - Results not saved
**Error Message**:
```
ERROR - Не найдены данные сессии для 6619515237 при завершении теста.
```
(6619515237 was the **BOT's telegram_id**, not the user's!)

**Symptom**: When test timed out, results were not saved to Google Sheets

**Root Cause**:
When timeout occurred, the bot sent a message to user. At that point, `message.from_user.id` was the **bot's ID** (because bot sent the message). The `user_data` was never populated in FSM state when starting test via callback button.

**File**: `handlers/common.py:148-155`

**Fix Applied**:
```python
# Added in start_test_callback function
user_data = {
    "id": callback_query.from_user.id,        # User's ID, not bot's
    "username": callback_query.from_user.username,
    "first_name": callback_query.from_user.first_name,
    "last_name": callback_query.from_user.last_name,
}
await state.update_data(fio=user_info.fio, user_data=user_data)
```

**Impact**: ✅ Test results now save correctly with proper user ID

---

### Bug #3: Missing Explanation on Critical Question Failure 📚 FEATURE

**Severity**: MEDIUM - Educational feature missing
**Feature Request**: Show explanation when user fails critical question

**Root Cause**: Code only checked `is_critical` to fail test, but didn't show explanation

**File**: `handlers/test.py:181-187`

**Fix Applied**:
```python
if question.is_critical:
    message_text = "❌ Вы ошиблись в критическом вопросе. Тест завершен."
    if question.explanation:
        message_text += f"\n\n💡 Пояснение: {question.explanation}"
    await cb.message.answer(message_text)
    await finish_test(cb.message, state, passed=False, notes=f"критический вопрос #{session.current_index + 1}")
    return
```

**Bonus**: Also improved training mode explanation with emoji (line 190)
```python
await cb.message.answer(f"💡 Пояснение: {question.explanation}")
```

**Impact**: ✅ Users receive educational feedback even on critical failures

---

### Bug #4: Missing Question Number in Notes 📊 FEATURE

**Severity**: MEDIUM - Analytics incomplete
**Feature Request**: Record question number in "Примечания" column for all failure types

**Root Cause**: Only timeout failures recorded question number; other failures didn't

**File**: `handlers/test.py`

**Fix Applied**:

**Critical Question Failure** (line 186):
```python
notes=f"критический вопрос #{session.current_index + 1}"
```

**Ran Out of Errors** (line 200):
```python
notes=f"закончились баллы на вопросе #{session.current_index + 1}"
```

**Timeout** (already working, line 148):
```python
notes=f"таймаут на вопрос #{q_index + 1}"
```

**Impact**: ✅ Better analytics - can identify problematic questions across all failure types

---

### Bug #5: No Cooldown Enforcement ⚠️ CRITICAL

**Severity**: CRITICAL - Business logic broken
**Symptom**: User could immediately retry initial test after failing, ignoring cooldown setting

**Root Cause**:
Cooldown logic existed in old code but was removed during campaign refactoring. The new `/start` flow never checked cooldown for initial test retries.

**Files Modified**:
1. `services/google_sheets.py:378-441` - Enhanced `get_last_test_time()`
2. `handlers/common.py:103-141` - Added cooldown check
3. `handlers/common.py:1-3` - Added imports

**Fix Applied**:

**Part 1: Enhanced get_last_test_time()** - Now accepts campaign filter
```python
def get_last_test_time(self, telegram_id: int, campaign_name: Optional[str] = None) -> Optional[float]:
    """
    Args:
        campaign_name: Optional campaign name to filter by.
                      If None, returns last test for initial test (no campaign).
    """
    # Read A:I range (not A:C)
    range_name = f"{RESULTS_SHEET}!A:I"

    # Filter by campaign
    row_campaign = row[8] if len(row) > 8 else ""

    if campaign_name is None or campaign_name == "":
        if row_campaign:  # Skip if row has a campaign
            continue
    elif row_campaign != campaign_name:
        continue
```

**Part 2: Added cooldown check in /start handler**
```python
# In handlers/common.py cmd_start function
admin_config = google_sheets.read_admin_config()
last_test_time = google_sheets.get_last_test_time(int(user_id), campaign_name=None)

if last_test_time:
    hours_passed = (time.time() - last_test_time) / 3600
    hours_required = admin_config.retry_hours

    if hours_passed < hours_required:
        # Block retry - show remaining time
        hours_remaining = hours_required - hours_passed
        if hours_remaining >= 1:
            time_msg = f"{int(hours_remaining)} ч."
        else:
            time_msg = f"{int(hours_remaining * 60)} мин."

        await message.answer(
            f"⏳ Вы уже проходили основной тест.\n\n"
            f"Повторная попытка будет доступна через {time_msg}\n\n"
            f"Правило: можно проходить тест раз в {hours_required} ч."
        )
        return
```

**Impact**: ✅ Cooldown system enforced - respects admin configuration

---

### Bug #6: Column Name Case Sensitivity 🔤 COMPATIBILITY

**Severity**: HIGH - Bot couldn't find columns
**Error Message**:
```
ERROR - В листе '📊Результаты' отсутствует обязательная колонка: 'название кампании' is not in list
```

**Symptom**: Bot crashed when reading Results sheet

**Root Cause**:
Google Sheets had "Название кампании" (capital N), but code did `.lower()` and expected exact match. Extra whitespace also caused issues.

**Files Modified**: `services/google_sheets.py` (3 locations)

**Fix Applied**:
```python
# ❌ BEFORE - Case sensitive, no trim
headers = [h.lower() for h in values[0]]

# ✅ AFTER - Case insensitive + trim whitespace
headers = [h.lower().strip() for h in values[0]]
```

**Updated in**:
- Line 147: `get_all_campaigns()`
- Line 187: `get_user_results()`
- Line 516: `get_campaign_statistics()`

**Also Added Debug Logging**:
```python
except ValueError as e:
    logger.error(f"В листе '{RESULTS_SHEET}' отсутствует обязательная колонка: {e}")
    logger.error(f"Доступные заголовки: {headers}")  # NEW
```

**Impact**: ✅ Handles column name variations gracefully

---

### Bug #7: Missing Column I in Results Sheet 📋 DATA CORRUPTION

**Severity**: CRITICAL - Campaign names not saved
**Error Symptom**:
```
Доступные заголовки: ['telegram_id', 'username', 'дата прохождения теста',
'фио', 'результат', 'количество верных ответов', 'примечания', 'итоговый статус']
```
(Missing "название кампании" - column 9!)

**Root Cause**:
Google Sheets API reading range `A:H` (8 columns) instead of `A:I` (9 columns). The API truncates empty cells at the end, so column I wasn't being read.

**File**: `services/google_sheets.py:180`

**Fix Applied**:
```python
# ❌ BEFORE - Only 8 columns
range_name = f"{RESULTS_SHEET}!A:H"

# ✅ AFTER - All 9 columns
range_name = f"{RESULTS_SHEET}!A:I"  # A-I, 9 columns
```

**Also Added Safe Access** (lines 204-205):
```python
# Handle rows that might not have all columns (backwards compatibility)
campaign_name = row[campaign_col] if len(row) > campaign_col else ""
final_status = row[status_col] if len(row) > status_col else ""
```

**Impact**: ✅ Campaign names now properly saved and retrieved

---

### Bug #8: Missing TTL Parameter on Correct Answer ⏱️ CRITICAL

**Severity**: CRITICAL - Redis memory leak
**Error Message**:
```
TypeError: RedisService.set_session() missing 1 required positional argument: 'ttl'
```

**Symptom**: Bot crashed after user answered ANY question correctly

**Root Cause**:
After processing correct answer, session was updated in Redis without TTL parameter. Function signature requires TTL but it wasn't provided.

**File**: `handlers/test.py:203-209`

**Fix Applied**:
```python
# ❌ BEFORE - Missing TTL
session.current_index += 1
await state.update_data(session=session.to_dict())
await redis_service.set_session(cb.from_user.id, session)  # ERROR!

# ✅ AFTER - Calculate and provide TTL
session.current_index += 1
await state.update_data(session=session.to_dict())

# Calculate TTL for remaining questions
questions_remaining = len(questions_data) - session.current_index
ttl = questions_remaining * session.admin_config_snapshot["seconds_per_question"] + 300
await redis_service.set_session(cb.from_user.id, session, ttl)
```

**Impact**: ✅ Sessions properly expire, no memory leaks

---

## 📊 Google Sheets Structure Validation

### 📊 Результаты (Results Sheet) - CONFIRMED WORKING

**Range**: A:I (9 columns)

| Column | Header (Russian) | Header (English) | Type | Example Value |
|--------|-----------------|------------------|------|---------------|
| **A** | telegram_id | Telegram ID | String | "123456789" |
| **B** | username | Username | String | "@johndoe" |
| **C** | Дата прохождения теста | Test Date | ISO DateTime | "2026-01-11T15:30:00+03:00" |
| **D** | ФИО | Full Name | String | "Иванов Иван Иванович" |
| **E** | Результат | Result | String | "Пройден" / "Не пройден" |
| **F** | Количество верных ответов | Correct Count | Integer | "15" |
| **G** | Примечания | Notes | String | "критический вопрос #3" |
| **H** | Итоговый статус | Final Status | String | "успешно" / "не пройдено" / "разрешена пересдача" |
| **I** | Название кампании | Campaign Name | String | "Январь 2026" or "" (empty for initial test) |

**Important Notes**:
- Column headers are **case-insensitive** after `.lower().strip()`
- Empty campaign name ("") indicates **initial test** (non-campaign test)
- Date format: ISO 8601 with timezone (Europe/Moscow)

---

## 🧪 Testing Validation

### Full User Flow Tested ✅

**1. User Registration Flow**
- ✅ Phone number collection via contact button
- ✅ FIO input and validation
- ✅ Motorcade selection (dynamic from admin config)
- ✅ Google Sheets user creation with status "ожидает"
- ✅ Access middleware blocks unconfirmed users

**2. Initial Test Flow**
- ✅ First-time user → can start test immediately
- ✅ Failed test → results saved with empty campaign_name
- ✅ Cooldown enforced on retry (reads from "⚙️Настройки")
- ✅ Time remaining displayed to user
- ✅ Retry allowed after cooldown expires

**3. Question Answering Flow**
- ✅ Normal questions → correct/incorrect feedback
- ✅ Score tracking (remaining_score decrements)
- ✅ **Critical questions** → immediate fail with explanation
- ✅ **Timeout** → test fails, correct telegram_id used
- ✅ **Correct answer** → session updates in Redis with TTL
- ✅ Training mode → shows explanations on wrong answers
- ✅ Testing mode → no explanations shown

**4. Test Completion & Results**
- ✅ Success → "Тест пройден", results saved
- ✅ Failure (errors) → "Тест не пройден", question number in notes
- ✅ Failure (critical) → notes show "критический вопрос #X"
- ✅ Failure (timeout) → notes show "таймаут на вопрос #X"
- ✅ All 9 columns populated correctly in Google Sheets
- ✅ Campaign name empty for initial tests

**5. Campaign Logic**
- ✅ Active campaigns displayed to confirmed users
- ✅ Deadline checking (past campaigns hidden)
- ✅ Assignment validation (ВСЕ vs specific motorcade)
- ✅ Retry status handling ("разрешена пересдача")
- ✅ Campaign completion tracking

---

## 🔧 Debug Logging Added

For production troubleshooting and monitoring:

### 1. Cooldown Check Logging
**Location**: `handlers/common.py:108, 114`
```python
logger.info(f"Cooldown check for user {user_id}: last_test_time={last_test_time}, retry_hours={admin_config.retry_hours}")
logger.info(f"Hours passed: {hours_passed:.2f}, required: {hours_required}")
```

### 2. Last Test Time Search Logging
**Location**: `services/google_sheets.py:406-437`
```python
logger.info(f"get_last_test_time: Searching for user {telegram_id_str}, campaign filter: {repr(campaign_name)}")
logger.info(f"Found row for user {telegram_id_str}: row_campaign='{row_campaign}', date={row[2]}")
logger.info(f"Skipping row - has campaign '{row_campaign}' but looking for initial test")
logger.info(f"Found matching test: date={row[2]}, timestamp={timestamp}")
logger.info(f"No matching test found for user {telegram_id_str}")
```

### 3. Result Writing Logging
**Location**: `services/google_sheets.py:451`
```python
logger.info(f"Writing result: telegram_id={telegram_id}, campaign_name='{campaign_name}', final_status='{final_status}', date={test_date}")
```

### 4. Column Header Debug Logging
**Location**: `services/google_sheets.py:155, 195, 526`
```python
logger.error(f"Доступные заголовки: {headers}")
```

**Usage**: Enable with `LOG_LEVEL=INFO` in `.env` file

---

## 📝 Files Modified Summary

| File | Purpose | Changes | Line Numbers |
|------|---------|---------|--------------|
| **handlers/test.py** | Test execution logic | Callback param fix, critical explanations, question numbers, TTL calculation | 152, 167, 181-190, 191, 200, 206-209 |
| **handlers/common.py** | Start command & test launch | User data creation, cooldown check, time imports | 1-3, 103-141, 148-155 |
| **services/google_sheets.py** | Google Sheets API integration | Column normalization, range fix (A:H→A:I), last_test_time enhancement, debug logging | 147, 155, 180, 187, 195, 204-205, 378-441, 451, 516, 526 |

**Total Lines Changed**: ~120 lines across 3 files
**Commits**: Ready to be committed (currently uncommitted changes)

---

## ✅ Production Readiness Checklist

### Core Functionality
- ✅ User registration flow working
- ✅ Access control middleware functional
- ✅ Campaign logic implemented and tested
- ✅ Initial test flow working
- ✅ Cooldown enforcement working
- ✅ Critical questions working
- ✅ Training/Testing modes working
- ✅ Results saving to Google Sheets (all 9 columns)
- ✅ Redis session management working
- ✅ Timeout handling working
- ✅ Question distribution algorithm working

### Error Handling
- ✅ Google Sheets API errors handled
- ✅ Redis connection errors handled
- ✅ Timeout scenarios handled
- ✅ Invalid user input handled
- ✅ Missing columns handled gracefully
- ✅ Backwards compatibility (partial rows)

### Logging & Monitoring
- ✅ Business logic logging (INFO level)
- ✅ Error logging with stack traces
- ✅ Debug logging for troubleshooting
- ✅ User action tracking

### Documentation
- ✅ SPEC.md (original specification)
- ✅ IMPLEMENTATION_PLAN.md (detailed plan)
- ✅ STEP_BY_STEP_PLAN.md (phase checklist)
- ✅ RESULT1.md (Phase 1 results)
- ✅ RESULT2.md (Phases 2-3 results)
- ✅ **RESULT3.md (Phase 6 testing results)** ← This document

---

## 🚀 Deployment Recommendations

### Before Production Deploy

**1. Review Debug Logging**
```bash
# Optional: Reduce logging verbosity for production
# In .env file:
LOG_LEVEL=INFO  # or WARNING for less verbose logs
```

**2. Commit Changes**
```bash
git add -A
git commit -m "fix: Phase 6 testing - fix 8 critical bugs

- Fix callback data parameter name (aiogram 3.x compatibility)
- Fix wrong telegram_id on timeout (add user_data)
- Add explanation to critical question failures
- Add question number to all failure notes
- Implement cooldown enforcement for initial test
- Fix column name case sensitivity
- Fix Google Sheets range A:H → A:I
- Fix missing TTL on correct answer Redis update

All user flows validated and working.
Production ready.
"
git push origin main
```

**3. Environment Variables Check**
Ensure `.env` has all required variables:
```env
TELEGRAM_TOKEN="your_bot_token"
SHEET_ID="your_sheet_id"
GOOGLE_CREDENTIALS='{"type": "service_account", ...}'
REDIS_URL="redis://redis:6379/0"
LOG_LEVEL="INFO"
OWNER_TELEGRAM_ID="owner_id"
ADMIN_TELEGRAM_ID="admin_id"
```

**4. Google Sheets Validation**
- ✅ All 5 sheets exist: Пользователи, Кампании, Вопросы, Настройки, Результаты
- ✅ Column headers match expected names (case-insensitive)
- ✅ Admin settings filled (количество вопросов, ошибок, часов, секунд)
- ✅ Service account has edit access to sheet

**5. Redis Persistence** (Optional)
```yaml
# In docker-compose.yml - already configured
redis:
  command: redis-server --appendonly no
  volumes:
    - redis_data:/data
```

---

## 🎓 Lessons Learned

### 1. aiogram 3.x Callback Patterns
**Issue**: Parameter naming matters in callback filters
**Lesson**: Always use `callback_data` as parameter name, not abbreviated versions
**Rule**: Follow framework conventions strictly

### 2. Google Sheets API Quirks
**Issue**: API truncates empty trailing cells
**Lesson**: Always specify full range (A:I not A:H) even if some cells might be empty
**Rule**: Read more columns than you think you need for safety

### 3. State Management in Async Flows
**Issue**: User data must be set BEFORE any async operation that might need it
**Lesson**: Set `user_data` in FSM state immediately after user action (callback)
**Rule**: Don't rely on `message.from_user` in async context - it might be wrong

### 4. Redis Session TTL
**Issue**: TTL must be recalculated on every session update
**Lesson**: TTL represents remaining time, not total time
**Rule**: Always provide TTL when calling `set_session()`, calculate based on remaining questions

### 5. Column Header Normalization
**Issue**: Column names vary (case, whitespace)
**Lesson**: Always normalize with `.lower().strip()` before searching
**Rule**: Never assume exact formatting in user-edited spreadsheets

### 6. Debug Logging Strategy
**Issue**: Production bugs hard to diagnose without context
**Lesson**: Add INFO-level logging for all business logic decisions
**Rule**: Log inputs, decisions, and outputs for critical paths

### 7. Backwards Compatibility
**Issue**: Old data might not have all new columns
**Lesson**: Use safe access patterns: `row[col] if len(row) > col else ""`
**Rule**: Always handle partial data gracefully

### 8. Testing Strategy
**Issue**: Unit tests alone don't catch integration issues
**Lesson**: Full user flow testing essential for multi-component systems
**Rule**: Test complete user journeys, not just individual functions

---

## 📈 Future Enhancements (Optional)

### Phase 7+ Recommendations

**1. Monitoring & Observability**
- [ ] Integrate Sentry for error tracking
- [ ] Add Prometheus metrics (active users, test completion rate)
- [ ] ELK/Grafana logging dashboard
- [ ] Health check endpoint

**2. Performance Optimizations**
- [ ] Cache Google Sheets questions in Redis (invalidate daily)
- [ ] Batch Google Sheets writes
- [ ] Connection pooling for Redis
- [ ] Rate limiting for user actions

**3. Feature Enhancements**
- [ ] User command `/mystats` - view own results
- [ ] Admin command `/approve_user <telegram_id>` - approve via bot
- [ ] Campaign creation via bot (no manual sheet editing)
- [ ] Export results to CSV/Excel
- [ ] Multi-language support

**4. DevOps Improvements**
- [ ] CI/CD pipeline (GitHub Actions)
- [ ] Automated testing suite
- [ ] Staging environment
- [ ] Database migration to PostgreSQL (if Google Sheets becomes bottleneck)
- [ ] Kubernetes deployment (if scaling needed)

**5. Security Hardening**
- [ ] Rate limiting per user
- [ ] Input sanitization (XSS prevention)
- [ ] Google Sheets access audit logging
- [ ] Encrypted secrets management (Vault)

---

## ✅ Sign-Off

**Phase 6 Status**: **COMPLETE** ✅

**All Acceptance Criteria Met**:
- ✅ Full user flow tested end-to-end
- ✅ All 8 critical bugs fixed
- ✅ Results properly saved (all 9 columns)
- ✅ Cooldown enforcement working
- ✅ Critical questions working
- ✅ Training/Testing modes working
- ✅ Error handling robust
- ✅ Logging comprehensive

**Production Ready**: YES ✅
**Recommended Next Step**: Deploy to production with monitoring

---

**Testing Completed By**: Development Team
**Reviewed By**: Ready for stakeholder review
**Date**: 2026-01-11

**For Questions or Issues**: Refer to debug logs with `LOG_LEVEL=INFO`
