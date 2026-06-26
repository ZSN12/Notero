from sqlalchemy import Column, DateTime, String, Text, Integer, JSON, ForeignKey, Float, Boolean, LargeBinary, UniqueConstraint, Index
from sqlalchemy.orm import relationship, DeclarativeBase
from sqlalchemy.sql import func
import uuid

try:
    from pgvector.sqlalchemy import Vector
    _PGVECTOR_AVAILABLE = True
except ImportError:
    _PGVECTOR_AVAILABLE = False


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String(50), nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    security_question = Column(Text, nullable=True)
    security_answer_hash = Column(String(255), nullable=True)
    avatar_url = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    notebooks = relationship("Notebook", back_populates="user", cascade="all, delete-orphan")
    vector_chunks = relationship("VectorChunk", back_populates="user", cascade="all, delete-orphan")


class Notebook(Base):
    __tablename__ = "notebooks"
    __table_args__ = (
        Index("ix_notebooks_user_id_created", "user_id", "created_at"),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(100), nullable=False)
    description = Column(Text)
    icon = Column(String(50))
    color = Column(String(50))
    session_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    user = relationship("User", back_populates="notebooks")
    sessions = relationship("Session", back_populates="notebook", cascade="all, delete-orphan")
    vocabulary = relationship("Vocabulary", back_populates="notebook", cascade="all, delete-orphan")
    course_terms = relationship("CourseTerm", back_populates="notebook", cascade="all, delete-orphan")
    vector_chunks = relationship("VectorChunk", back_populates="notebook", cascade="all, delete-orphan")
    rag_messages = relationship("RAGMessage", back_populates="notebook", cascade="all, delete-orphan")

class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("ix_sessions_notebook_id_created", "notebook_id", "created_at"),
        Index("ix_sessions_share_token", "share_token"),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    notebook_id = Column(String(36), ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(200), nullable=False)
    summary = Column(Text, nullable=True)
    keywords = Column(JSON, default=[])
    duration = Column(String(20))
    status = Column(String(20), default="pending")
    share_enabled = Column(Boolean, default=False)
    share_token = Column(String(64), nullable=True)
    share_expires_at = Column(DateTime(timezone=True), nullable=True)
    share_max_views = Column(Integer, nullable=True)
    share_view_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    notebook = relationship("Notebook", back_populates="sessions")
    notes = relationship("Note", back_populates="session", cascade="all, delete-orphan")
    files = relationship("File", back_populates="session", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="session", cascade="all, delete-orphan")
    vector_chunks = relationship("VectorChunk", back_populates="session", cascade="all, delete-orphan")
    processing_states = relationship("SessionProcessingState", back_populates="session", cascade="all, delete-orphan")
    rag_messages = relationship("RAGMessage", back_populates="session", cascade="all, delete-orphan")

class Note(Base):
    __tablename__ = "notes"
    __table_args__ = (
        Index("ix_notes_session_id", "session_id"),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text)
    transcript = Column(JSON)
    ppt_images = Column(JSON)
    vocabulary = Column(JSON)
    annotations = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    session = relationship("Session", back_populates="notes")

    @property
    def layout_blocks(self):
        if not isinstance(self.vocabulary, list):
            return None
        for item in self.vocabulary:
            if isinstance(item, dict) and item.get("kind") == "layout_blocks":
                blocks = item.get("blocks")
                return blocks if isinstance(blocks, list) else None
        return None

    @layout_blocks.setter
    def layout_blocks(self, blocks):
        existing = self.vocabulary if isinstance(self.vocabulary, list) else []
        next_items = [
            item for item in existing
            if not (isinstance(item, dict) and item.get("kind") == "layout_blocks")
        ]
        if blocks is not None:
            next_items.append({"kind": "layout_blocks", "blocks": blocks})
        self.vocabulary = next_items

class File(Base):
    __tablename__ = "files"
    __table_args__ = (
        Index("ix_files_session_id", "session_id"),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    file_type = Column(String(20), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_path = Column(Text, nullable=False)
    file_size = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    session = relationship("Session", back_populates="files")

class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_session_id_status", "session_id", "status"),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    task_type = Column(String(50), nullable=False)
    status = Column(String(20), default="pending")
    progress = Column(Float, default=0.0)
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)
    session = relationship("Session", back_populates="tasks")

class Vocabulary(Base):
    __tablename__ = "vocabulary"
    __table_args__ = (
        Index("ix_vocabulary_notebook_id", "notebook_id"),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    notebook_id = Column(String(36), ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False)
    term = Column(String(200), nullable=False)
    translation = Column(String(200))
    definition = Column(Text)
    source = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    notebook = relationship("Notebook", back_populates="vocabulary")


class CourseTerm(Base):
    __tablename__ = "course_terms"
    __table_args__ = (
        UniqueConstraint("notebook_id", "term", name="uix_course_terms_notebook_term"),
        Index("ix_course_terms_notebook_weight", "notebook_id", "weight"),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    notebook_id = Column(String(36), ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False)
    term = Column(String(100), nullable=False)
    source = Column(String(50), nullable=True)
    weight = Column(Float, default=1.0, nullable=False)
    first_seen_session_id = Column(String(36), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    notebook = relationship("Notebook", back_populates="course_terms")


class VectorChunk(Base):
    __tablename__ = "vector_chunks"
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    notebook_id = Column(String(36), ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type = Column(String(20), nullable=False)  # transcript | note | ppt | layout
    source_id = Column(String(36), nullable=True)
    chunk_index = Column(Integer, default=0)
    text = Column(Text, nullable=False)
    chunk_meta = Column(JSON, default={})
    embedding = Column(LargeBinary, nullable=True)  # packed float32 vector (legacy TF-IDF)
    embedding_v2 = Column(LargeBinary, nullable=True)  # packed float32 vector (neural embedding)
    if _PGVECTOR_AVAILABLE:
        embedding_vector = Column(Vector(1536), nullable=True)  # pgvector column for DB-level search
    content_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    user = relationship("User", back_populates="vector_chunks")
    notebook = relationship("Notebook", back_populates="vector_chunks")
    session = relationship("Session", back_populates="vector_chunks")

class SessionProcessingState(Base):
    __tablename__ = "session_processing_states"
    __table_args__ = (
        UniqueConstraint("session_id", "stage", name="uix_session_stage"),
        Index("ix_sps_session_id", "session_id"),
        Index("ix_sps_status_updated", "status", "updated_at"),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    stage = Column(String(50), nullable=False)
    status = Column(String(20), default="idle", nullable=False)
    progress = Column(Float, default=0.0)
    message = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    content_hash = Column(String(64), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    session = relationship("Session", back_populates="processing_states")


class AgentWorkflow(Base):
    __tablename__ = "agent_workflows"
    __table_args__ = (
        Index("ix_agent_workflows_session_id", "session_id"),
        Index("ix_agent_workflows_status", "status"),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    roles = Column(JSON, default=list, nullable=False)
    dependencies = Column(JSON, default=dict, nullable=False)
    role_states = Column(JSON, default=dict, nullable=False)
    status = Column(String(20), default="pending", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)
    last_heartbeat_at = Column(DateTime(timezone=True), nullable=True)


class RAGMessage(Base):
    __tablename__ = "rag_messages"
    __table_args__ = (
        Index("ix_rag_messages_session_id_created", "session_id", "created_at"),
    )
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    notebook_id = Column(String(36), ForeignKey("notebooks.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    sources = Column(JSON, nullable=True)
    is_summary = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    session = relationship("Session", back_populates="rag_messages")
    notebook = relationship("Notebook", back_populates="rag_messages")


__all__ = ["Base", "User", "Notebook", "Session", "Note", "File", "Task", "Vocabulary", "CourseTerm", "VectorChunk", "SessionProcessingState", "AgentWorkflow", "RAGMessage"]
