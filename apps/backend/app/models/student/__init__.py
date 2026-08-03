from app.models.student.goal import LearningGoal, GoalLearnedChapter, GoalResultRecord
from app.models.student.test_paper import (
    TestPaper, TestQuestion, TestAnswer, WrongQuestionAiExercise,
)
from app.models.student.learning_path import LearningPath, LearningPathNode, LearningTask

__all__ = [
    "LearningGoal",
    "GoalLearnedChapter",
    "GoalResultRecord",
    "TestPaper",
    "TestQuestion",
    "TestAnswer",
    "WrongQuestionAiExercise",
    "LearningPath",
    "LearningPathNode",
    "LearningTask",
]
