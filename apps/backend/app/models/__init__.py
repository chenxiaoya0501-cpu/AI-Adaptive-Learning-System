from app.models.knowledge import KnowledgePoint, KnowledgeRelation, TypicalQuestion
from app.models.system import SystemConfig, UploadedFile, ExtractionTask
from app.models.question import (
    ExamPaper, Question, KpLinkTask, KpLinkSuggestion,
    AnswerRewriteTask, AnswerRewriteSuggestion,
    AbilityLabelTask, AbilityLabelSuggestion,
    ExamScoreScheme, ExamStructureTemplate, ExamKpScoreStat,
)
from app.models.resource import KpExplanation, KpVideoResource
from app.models.chapter import TextbookChapter
from app.models.user import User
from app.models.student.goal import LearningGoal, GoalLearnedChapter, GoalResultRecord
from app.models.student.test_paper import (
    TestPaper, TestQuestion, TestAnswer, WrongQuestionAiExercise,
)
from app.models.student.learning_path import LearningPath, LearningPathNode, LearningTask
from app.models.student.mastery_sync import CourseMasterySync
