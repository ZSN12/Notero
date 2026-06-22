"""Factory Boy factories for notero models.

These factories are registered with pytest-factoryboy so they can be used as
fixtures (e.g. `user_factory`, `notebook_factory`).  When used with the shared
`db` fixture they participate in the same transaction and are rolled back at the
end of each test.
"""

import uuid

import factory
from factory.fuzzy import FuzzyText

from app.core.auth import hash_password
from app.models import Notebook, Note, RAGMessage, Session, Task, User, Vocabulary


class UserFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = User
        sqlalchemy_session_persistence = "flush"

    id = factory.LazyFunction(lambda: str(uuid.uuid4()))
    username = factory.Sequence(lambda n: f"testuser{n}")
    email = factory.Sequence(lambda n: f"testuser{n}@example.com")
    password_hash = factory.LazyFunction(lambda: hash_password("password123"))


class NotebookFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = Notebook
        sqlalchemy_session_persistence = "flush"

    id = factory.LazyFunction(lambda: str(uuid.uuid4()))
    title = factory.Sequence(lambda n: f"Test Notebook {n}")
    description = factory.Faker("sentence")
    user = factory.SubFactory(UserFactory)


class SessionFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = Session
        sqlalchemy_session_persistence = "flush"

    id = factory.LazyFunction(lambda: str(uuid.uuid4()))
    title = factory.Sequence(lambda n: f"Test Session {n}")
    keywords = factory.LazyFunction(list)
    notebook = factory.SubFactory(NotebookFactory)


class NoteFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = Note
        sqlalchemy_session_persistence = "flush"

    id = factory.LazyFunction(lambda: str(uuid.uuid4()))
    content = factory.Faker("paragraph")
    session = factory.SubFactory(SessionFactory)


class TaskFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = Task
        sqlalchemy_session_persistence = "flush"

    id = factory.LazyFunction(lambda: str(uuid.uuid4()))
    task_type = "review"
    status = "pending"
    session = factory.SubFactory(SessionFactory)


class RAGMessageFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = RAGMessage
        sqlalchemy_session_persistence = "flush"

    id = factory.LazyFunction(lambda: str(uuid.uuid4()))
    role = "user"
    content = factory.Faker("sentence")
    sources = factory.LazyFunction(list)
    is_summary = False
    session = factory.SubFactory(SessionFactory)
    notebook = factory.LazyAttribute(lambda obj: obj.session.notebook)


class VocabularyFactory(factory.alchemy.SQLAlchemyModelFactory):
    class Meta:
        model = Vocabulary
        sqlalchemy_session_persistence = "flush"

    id = factory.LazyFunction(lambda: str(uuid.uuid4()))
    term = factory.Sequence(lambda n: f"term{n}")
    translation = factory.Faker("word")
    definition = factory.Faker("sentence")
    notebook = factory.SubFactory(NotebookFactory)
