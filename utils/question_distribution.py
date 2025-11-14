import random
from typing import List, Dict
from models import Question


def distribute_questions_by_category(
    questions: List[Question],
    num_questions: int
) -> List[Question]:
    """
    Распределяет N вопросов пропорционально по категориям.
    
    Алгоритм:
    1. Группируем вопросы по категориям
    2. Вычисляем квоту для каждой категории пропорционально
    3. Распределяем остатки от округления
    4. Обрабатываем случаи, когда в категории меньше вопросов, чем квота
    5. Случайно выбираем вопросы из каждой категории
    """
    if not questions:
        return []
    
    if len(questions) < num_questions:
        # Если вопросов меньше, чем нужно - используем все доступные
        return random.sample(questions, len(questions))
    
    # Группируем по категориям
    categories: Dict[str, List[Question]] = {}
    for q in questions:
        if q.category not in categories:
            categories[q.category] = []
        categories[q.category].append(q)
    
    total_questions = len(questions)
    num_categories = len(categories)
    
    # Вычисляем начальные квоты
    quotas: Dict[str, int] = {}
    fractional_parts: Dict[str, float] = {}
    
    for category, cat_questions in categories.items():
        count_c = len(cat_questions)
        raw = num_questions * (count_c / total_questions)
        quota_c = int(raw)
        quotas[category] = quota_c
        fractional_parts[category] = raw - quota_c
    
    # Распределяем остатки от округления
    total_quota = sum(quotas.values())
    remaining = num_questions - total_quota
    
    if remaining > 0:
        # Сортируем категории по дробной части (убывание)
        sorted_categories = sorted(
            fractional_parts.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        for i in range(remaining):
            category = sorted_categories[i % len(sorted_categories)][0]
            quotas[category] += 1
    
    # Проверяем, не превышает ли квота количество вопросов в категории
    for category in list(quotas.keys()):
        max_available = len(categories[category])
        if quotas[category] > max_available:
            excess = quotas[category] - max_available
            quotas[category] = max_available
            
            # Перераспределяем избыток
            if excess > 0:
                other_categories = [
                    c for c in quotas.keys()
                    if c != category and quotas[c] < len(categories[c])
                ]
                if other_categories:
                    per_category = excess // len(other_categories)
                    remainder = excess % len(other_categories)
                    
                    for i, other_cat in enumerate(other_categories):
                        add = per_category + (1 if i < remainder else 0)
                        quotas[other_cat] = min(
                            quotas[other_cat] + add,
                            len(categories[other_cat])
                        )
    
    # Случайно выбираем вопросы из каждой категории
    selected_questions: List[Question] = []
    for category, quota in quotas.items():
        if quota > 0:
            category_questions = categories[category]
            selected = random.sample(category_questions, min(quota, len(category_questions)))
            selected_questions.extend(selected)
    
    # Перемешиваем итоговый список
    random.shuffle(selected_questions)
    
    return selected_questions[:num_questions]

