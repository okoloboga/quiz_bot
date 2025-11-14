from dataclasses import dataclass, asdict
from typing import List, Optional
from datetime import datetime


@dataclass
class Question:
    category: str
    question_text: str
    answer1: str
    answer2: str
    answer3: str
    answer4: str
    correct_answer: int  # 1-4
    row_index: int  # индекс строки в таблице


@dataclass
class AdminConfig:
    num_questions: int  # N
    max_errors: int  # M
    retry_hours: int  # H
    seconds_per_question: int  # S


@dataclass
class Session:
    fio: str
    question_ids: List[int]
    current_index: int
    remaining_score: int
    correct_count: int
    started_at: float
    last_action_at: float
    per_question_deadline: Optional[float]
    admin_config_snapshot: dict

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict):
        return cls(**data)

