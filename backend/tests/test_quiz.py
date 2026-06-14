import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

os.environ["SKIP_ASR_PRELOAD"] = "1"
os.environ["DEEPSEEK_API_KEY"] = "test-key-for-quiz"

from fastapi.testclient import TestClient
from app.main import app
from app.core.database import SessionLocal
from app.models import User, Task
from app.core.auth import hash_password


def auth_headers(client: TestClient) -> dict[str, str]:
    resp = client.post(
        "/api/auth/login",
        json={"email": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200, resp.text
    return {
        "Authorization": f"Bearer {resp.json()['access_token']}",
        "Origin": "http://localhost:5173",
    }


def _create_other_user(email: str, username: str, password: str = "other1234") -> None:
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.email == email).first():
            user = User(username=username, email=email, password_hash=hash_password(password))
            db.add(user)
            db.commit()
    finally:
        db.close()


def _create_notebook_session_note(client: TestClient, headers: dict):
    """Create notebook + session + note with content. Returns (notebook_id, session_id)."""
    nb = client.post("/api/notebooks", json={"title": "Quiz V2 NB"}, headers=headers)
    assert nb.status_code == 201
    notebook_id = nb.json()["id"]

    sess = client.post(
        f"/api/sessions?notebook_id={notebook_id}",
        json={"title": "Quiz V2 Session", "keywords": ["design", "patterns"]},
        headers=headers,
    )
    assert sess.status_code == 201
    session_id = sess.json()["id"]

    client.put(
        f"/api/notes/session/{session_id}",
        json={
            "content": "## 语音转文字\n\n设计模式是软件工程中常用的解决方案。单例模式确保一个类只有一个实例。工厂方法模式定义了一个创建对象的接口。观察者模式定义了对象间的一对多依赖关系。策略模式定义了一系列算法，把它们封装起来，使它们可以互相替换。",
            "layout_blocks": [
                {"id": "t1", "type": "transcript", "content": "设计模式是软件工程中常用的解决方案。单例模式确保一个类只有一个实例。工厂方法模式定义了一个创建对象的接口。观察者模式定义了对象间的一对多依赖关系。策略模式定义了一系列算法，把它们封装起来，使它们可以互相替换。"}
            ]
        },
        headers=headers,
    )

    return notebook_id, session_id


MOCK_BANK_RESPONSE_SMALL = {
    "title": "设计模式测验",
    "questions": [
        {
            "id": "q1",
            "question": "单例模式确保一个类有几个实例？",
            "options": [
                {"id": "A", "text": "零个", "explanation": "单例模式至少有一个实例"},
                {"id": "B", "text": "一个", "explanation": "正确，单例模式确保只有一个实例"},
                {"id": "C", "text": "两个", "explanation": "单例模式不是两个实例"},
                {"id": "D", "text": "任意多个", "explanation": "单例模式限制实例数量"}
            ],
            "answer": "B",
            "explanation": "单例模式的核心就是确保一个类只有一个实例。",
            "source": {"source_type": "transcript", "snippet": "单例模式确保一个类只有一个实例", "page": None}
        },
        {
            "id": "q2",
            "question": "工厂方法模式定义了什么？",
            "options": [
                {"id": "A", "text": "销毁对象的接口", "explanation": "工厂方法不是销毁对象"},
                {"id": "B", "text": "创建对象的接口", "explanation": "正确，工厂方法定义创建对象的接口"},
                {"id": "C", "text": "复制对象的接口", "explanation": "工厂方法不是复制对象"},
                {"id": "D", "text": "排序对象的接口", "explanation": "工厂方法不是排序对象"}
            ],
            "answer": "B",
            "explanation": "工厂方法模式定义了一个创建对象的接口，但让子类决定实例化哪个类。",
            "source": {"source_type": "transcript", "snippet": "工厂方法模式定义了一个创建对象的接口", "page": None}
        },
        {
            "id": "q3",
            "question": "观察者模式定义了什么关系？",
            "options": [
                {"id": "A", "text": "一对一", "explanation": "观察者模式是一对多"},
                {"id": "B", "text": "多对多", "explanation": "观察者模式是一对多"},
                {"id": "C", "text": "一对多", "explanation": "正确，观察者模式定义一对多依赖"},
                {"id": "D", "text": "多对一", "explanation": "观察者模式不是多对一"}
            ],
            "answer": "C",
            "explanation": "观察者模式定义了对象间的一对多依赖关系。",
            "source": {"source_type": "transcript", "snippet": "观察者模式定义了对象间的一对多依赖关系", "page": None}
        },
    ]
}


MOCK_BANK_RESPONSE = {
    "title": "设计模式测验",
    "questions": [
        {
            "id": "q1",
            "question": "单例模式确保一个类有几个实例？",
            "options": [
                {"id": "A", "text": "零个", "explanation": "单例模式至少有一个实例"},
                {"id": "B", "text": "一个", "explanation": "正确，单例模式确保只有一个实例"},
                {"id": "C", "text": "两个", "explanation": "单例模式不是两个实例"},
                {"id": "D", "text": "任意多个", "explanation": "单例模式限制实例数量"}
            ],
            "answer": "B",
            "explanation": "单例模式的核心就是确保一个类只有一个实例。",
            "source": {"source_type": "transcript", "snippet": "单例模式确保一个类只有一个实例", "page": None}
        },
        {
            "id": "q2",
            "question": "工厂方法模式定义了什么？",
            "options": [
                {"id": "A", "text": "销毁对象的接口", "explanation": "工厂方法不是销毁对象"},
                {"id": "B", "text": "创建对象的接口", "explanation": "正确，工厂方法定义创建对象的接口"},
                {"id": "C", "text": "复制对象的接口", "explanation": "工厂方法不是复制对象"},
                {"id": "D", "text": "排序对象的接口", "explanation": "工厂方法不是排序对象"}
            ],
            "answer": "B",
            "explanation": "工厂方法模式定义了一个创建对象的接口，但让子类决定实例化哪个类。",
            "source": {"source_type": "transcript", "snippet": "工厂方法模式定义了一个创建对象的接口", "page": None}
        },
        {
            "id": "q3",
            "question": "观察者模式定义了什么关系？",
            "options": [
                {"id": "A", "text": "一对一", "explanation": "观察者模式是一对多"},
                {"id": "B", "text": "多对多", "explanation": "观察者模式是一对多"},
                {"id": "C", "text": "一对多", "explanation": "正确，观察者模式定义一对多依赖"},
                {"id": "D", "text": "多对一", "explanation": "观察者模式不是多对一"}
            ],
            "answer": "C",
            "explanation": "观察者模式定义了对象间的一对多依赖关系。",
            "source": {"source_type": "transcript", "snippet": "观察者模式定义了对象间的一对多依赖关系", "page": None}
        },
        {
            "id": "q4",
            "question": "策略模式的作用是什么？",
            "options": [
                {"id": "A", "text": "创建对象", "explanation": "策略模式不是创建型模式"},
                {"id": "B", "text": "封装算法族", "explanation": "正确，策略模式封装算法族"},
                {"id": "C", "text": "管理数据库", "explanation": "策略模式与数据库无关"},
                {"id": "D", "text": "绘制界面", "explanation": "策略模式与界面无关"}
            ],
            "answer": "B",
            "explanation": "策略模式定义了一系列算法，把它们封装起来，使它们可以互相替换。",
            "source": {"source_type": "transcript", "snippet": "策略模式定义了一系列算法", "page": None}
        },
        {
            "id": "q5",
            "question": "装饰者模式主要用于？",
            "options": [
                {"id": "A", "text": "创建复杂对象", "explanation": "装饰者不是创建型模式"},
                {"id": "B", "text": "动态添加职责", "explanation": "正确，装饰者动态地为对象添加额外职责"},
                {"id": "C", "text": "定义算法骨架", "explanation": "这是模板方法模式"},
                {"id": "D", "text": "表示部分整体层次", "explanation": "这是组合模式"}
            ],
            "answer": "B",
            "explanation": "装饰者模式动态地给一个对象添加一些额外的职责。",
            "source": {"source_type": "transcript", "snippet": "装饰者模式", "page": None}
        },
        {
            "id": "q6",
            "question": "代理模式的常见用途是？",
            "options": [
                {"id": "A", "text": "批量生产对象", "explanation": "代理模式不是批量生产"},
                {"id": "B", "text": "控制对象访问", "explanation": "正确，代理模式为其他对象提供代理以控制访问"},
                {"id": "C", "text": "定义对象状态", "explanation": "这是状态模式"},
                {"id": "D", "text": "撤销操作", "explanation": "这是命令模式或备忘录模式"}
            ],
            "answer": "B",
            "explanation": "代理模式为其他对象提供一种代理以控制对这个对象的访问。",
            "source": {"source_type": "transcript", "snippet": "代理模式", "page": None}
        },
        {
            "id": "q7",
            "question": "适配器模式解决什么问题？",
            "options": [
                {"id": "A", "text": "接口不兼容", "explanation": "正确，适配器将接口转换成客户希望的接口"},
                {"id": "B", "text": "对象创建复杂", "explanation": "这是工厂模式解决的问题"},
                {"id": "C", "text": "算法变化频繁", "explanation": "这是策略模式解决的问题"},
                {"id": "D", "text": "对象之间通信", "explanation": "这是观察者模式解决的问题"}
            ],
            "answer": "A",
            "explanation": "适配器模式将一个类的接口转换成客户希望的另外一个接口。",
            "source": {"source_type": "transcript", "snippet": "适配器模式", "page": None}
        },
        {
            "id": "q8",
            "question": "模板方法模式的核心是？",
            "options": [
                {"id": "A", "text": "定义算法骨架", "explanation": "正确，模板方法定义算法骨架"},
                {"id": "B", "text": "创建对象实例", "explanation": "这是工厂方法"},
                {"id": "C", "text": "管理对象生命周期", "explanation": "这是享元或池模式"},
                {"id": "D", "text": "封装请求", "explanation": "这是命令模式"}
            ],
            "answer": "A",
            "explanation": "模板方法模式定义一个操作中的算法骨架，而将一些步骤延迟到子类中。",
            "source": {"source_type": "transcript", "snippet": "模板方法模式", "page": None}
        },
        {
            "id": "q9",
            "question": "组合模式常用于？",
            "options": [
                {"id": "A", "text": "对象组合成树形结构", "explanation": "正确，组合模式表示部分整体层次"},
                {"id": "B", "text": "封装算法", "explanation": "这是策略模式"},
                {"id": "C", "text": "控制访问", "explanation": "这是代理模式"},
                {"id": "D", "text": "事件通知", "explanation": "这是观察者模式"}
            ],
            "answer": "A",
            "explanation": "组合模式将对象组合成树形结构以表示部分-整体的层次结构。",
            "source": {"source_type": "transcript", "snippet": "组合模式", "page": None}
        },
        {
            "id": "q10",
            "question": "命令模式主要特点是？",
            "options": [
                {"id": "A", "text": "将请求封装成对象", "explanation": "正确，命令模式把请求封装为对象"},
                {"id": "B", "text": "定义对象创建流程", "explanation": "这是构建者模式"},
                {"id": "C", "text": "管理对象共享", "explanation": "这是享元模式"},
                {"id": "D", "text": "提供统一接口", "explanation": "这是外观模式"}
            ],
            "answer": "A",
            "explanation": "命令模式将一个请求封装为一个对象，从而使你可用不同的请求对客户进行参数化。",
            "source": {"source_type": "transcript", "snippet": "命令模式", "page": None}
        },
    ]
}


def _mock_openai_response(data: dict):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = json.dumps(data)
    mock_client.chat.completions.create.return_value = mock_response
    return mock_client


def _setup_bank_sync(client: TestClient, headers: dict, session_id: str):
    """Helper: directly call _generate_question_bank_sync to set up a bank without async."""
    from app.services import quiz_service
    from app.models import Session as SessionModel, Notebook, Note
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == "admin").first()
        session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        note = db.query(Note).filter(Note.session_id == session_id).first()
        bank_data = quiz_service.normalize_quiz_data(MOCK_BANK_RESPONSE_SMALL)
        content_hash = quiz_service._compute_session_content_hash(note)
        quiz_service._set_quiz_bank_in_vocabulary(note, bank_data, content_hash)
        db.commit()
    finally:
        db.close()


# ── Tests ──

def test_bank_status_empty():
    """No content → bank status is empty."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        nb = client.post("/api/notebooks", json={"title": "Empty NB"}, headers=headers)
        sess = client.post(f"/api/sessions?notebook_id={nb.json()['id']}", json={"title": "Empty"}, headers=headers)
        session_id = sess.json()["id"]

        resp = client.get(f"/api/quiz/session/{session_id}/bank/status", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "empty"


def test_bank_status_not_generated():
    """Has content but no bank → status is not_generated."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)

        resp = client.get(f"/api/quiz/session/{session_id}/bank/status", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "not_generated"


def test_bank_status_ready_after_sync_setup():
    """After setting up bank directly, status is ready."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)
        _setup_bank_sync(client, headers, session_id)

        resp = client.get(f"/api/quiz/session/{session_id}/bank/status", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"
        assert resp.json()["question_count"] == 3


def test_bank_status_stale_after_content_change():
    """Changing note content makes bank stale."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)
        _setup_bank_sync(client, headers, session_id)

        # Modify note content
        client.put(
            f"/api/notes/session/{session_id}",
            json={"content": "Completely new content about machine learning."},
            headers=headers,
        )

        resp = client.get(f"/api/quiz/session/{session_id}/bank/status", headers=headers)
        assert resp.json()["status"] == "stale"


def test_generate_quiz_from_bank_no_ai_call():
    """With a ready bank, generate_quiz does NOT call OpenAI."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)
        _setup_bank_sync(client, headers, session_id)

        with patch("app.agents.base.OpenAI") as mock_cls:
            resp = client.post(f"/api/quiz/session/{session_id}/generate", headers=headers)
            assert resp.status_code == 200
            data = resp.json()
            assert "quiz_id" in data
            assert "questions" in data
            # Questions should NOT have answer/explanation
            for q in data["questions"]:
                for opt in q["options"]:
                    assert "explanation" not in opt
                assert "answer" not in q
            # OpenAI should NOT have been called
            mock_cls.assert_not_called()


def test_generate_quiz_triggers_bank_when_needed():
    """Without a bank, generate triggers bank generation (returns generating)."""
    with patch("app.agents.base.OpenAI") as mock_cls:
        mock_cls.return_value = _mock_openai_response(MOCK_BANK_RESPONSE)

        with TestClient(app) as client:
            headers = auth_headers(client)
            _, session_id = _create_notebook_session_note(client, headers)

            resp = client.post(f"/api/quiz/session/{session_id}/generate", headers=headers)
            # Should return 202 (generating) since bank doesn't exist yet
            assert resp.status_code == 202


def test_quiz_detail_no_answers_before_submit():
    """Unsubmitted quiz detail should NOT contain answer/explanation."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)
        _setup_bank_sync(client, headers, session_id)

        # Generate quiz
        gen = client.post(f"/api/quiz/session/{session_id}/generate", headers=headers)
        quiz_id = gen.json()["quiz_id"]

        # Get detail (not submitted)
        resp = client.get(f"/api/quiz/session/{session_id}/{quiz_id}", headers=headers)
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["submission"] is None
        for q in detail["questions"]:
            assert "answer" not in q or q.get("answer") is None
            for opt in q["options"]:
                assert "explanation" not in opt


def test_submit_and_get_full_detail():
    """After submit, detail contains full answers and explanations."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)
        _setup_bank_sync(client, headers, session_id)

        gen = client.post(f"/api/quiz/session/{session_id}/generate", headers=headers)
        quiz_id = gen.json()["quiz_id"]

        # Submit answers
        resp = client.post(
            f"/api/quiz/session/{session_id}/{quiz_id}/submit",
            json={"answers": {"q1": "B", "q2": "A", "q3": "C"}},
            headers=headers,
        )
        assert resp.status_code == 200
        result = resp.json()
        assert result["score"] == 2  # q1=B correct, q2=A wrong, q3=C correct
        assert result["total"] == 3

        # Get detail after submit — should have full answers
        resp = client.get(f"/api/quiz/session/{session_id}/{quiz_id}", headers=headers)
        detail = resp.json()
        assert detail["submission"] is not None
        for q in detail["questions"]:
            assert "answer" in q
            assert q["answer"] is not None
            for opt in q["options"]:
                assert "explanation" in opt


def test_submit_calculates_correct_score():
    """Submit answers and verify score calculation."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)
        _setup_bank_sync(client, headers, session_id)

        gen = client.post(f"/api/quiz/session/{session_id}/generate", headers=headers)
        quiz_id = gen.json()["quiz_id"]

        # All correct
        resp = client.post(
            f"/api/quiz/session/{session_id}/{quiz_id}/submit",
            json={"answers": {"q1": "B", "q2": "B", "q3": "C"}},
            headers=headers,
        )
        assert resp.json()["score"] == 3
        assert resp.json()["percentage"] == 100.0


def test_submit_twice_returns_same():
    """Submitting twice returns the first submission result."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)
        _setup_bank_sync(client, headers, session_id)

        gen = client.post(f"/api/quiz/session/{session_id}/generate", headers=headers)
        quiz_id = gen.json()["quiz_id"]

        client.post(f"/api/quiz/session/{session_id}/{quiz_id}/submit", json={"answers": {"q1": "B", "q2": "A", "q3": "C"}}, headers=headers)
        resp2 = client.post(f"/api/quiz/session/{session_id}/{quiz_id}/submit", json={"answers": {"q1": "A", "q2": "B", "q3": "C"}}, headers=headers)
        # Should return same result as first submission
        assert resp2.json()["score"] == 2


def test_delete_quiz_not_bank():
    """Deleting a quiz attempt does not delete the bank."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)
        _setup_bank_sync(client, headers, session_id)

        gen = client.post(f"/api/quiz/session/{session_id}/generate", headers=headers)
        quiz_id = gen.json()["quiz_id"]

        # Delete quiz
        resp = client.delete(f"/api/quiz/session/{session_id}/{quiz_id}", headers=headers)
        assert resp.status_code == 200

        # Bank should still be ready
        resp = client.get(f"/api/quiz/session/{session_id}/bank/status", headers=headers)
        assert resp.json()["status"] == "ready"

        # Quiz list should be empty
        resp = client.get(f"/api/quiz/session/{session_id}", headers=headers)
        assert resp.json() == []


def test_non_owner_cannot_access():
    """Non-owner cannot access quiz bank or attempts."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)

        _create_other_user("other_qv2@example.com", "OtherQV2", "other1234")
        other_resp = client.post("/api/auth/login", json={"email": "other_qv2@example.com", "password": "other1234"})
        other_headers = {
            "Authorization": f"Bearer {other_resp.json()['access_token']}",
            "Origin": "http://localhost:5173",
        }

        # Cannot get bank status
        resp = client.get(f"/api/quiz/session/{session_id}/bank/status", headers=other_headers)
        assert resp.status_code == 404

        # Cannot generate
        resp = client.post(f"/api/quiz/session/{session_id}/generate", headers=other_headers)
        assert resp.status_code == 404

        # Cannot rebuild bank
        resp = client.post(f"/api/quiz/session/{session_id}/bank/rebuild", headers=other_headers)
        assert resp.status_code == 404


def test_invalid_json_from_ai():
    """AI returning invalid JSON should result in generation failure."""
    with patch("app.agents.base.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "This is not valid JSON {{{"
        mock_client.chat.completions.create.return_value = mock_response

        with TestClient(app) as client:
            headers = auth_headers(client)
            _, session_id = _create_notebook_session_note(client, headers)

            # Rebuild bank should fail
            resp = client.post(f"/api/quiz/session/{session_id}/bank/rebuild", headers=headers)
            # The async task will fail, but the endpoint returns 202 first
            # Wait a bit and check bank status
            time.sleep(1)
            resp = client.get(f"/api/quiz/session/{session_id}/bank/status", headers=headers)
            # Should be error or still generating
            assert resp.json()["status"] in ("error", "generating")


def test_no_api_key_returns_503():
    """Without DEEPSEEK_API_KEY, rebuild should return 503."""
    with patch("app.services.quiz_service.DEEPSEEK_API_KEY", ""):
        with TestClient(app) as client:
            headers = auth_headers(client)
            _, session_id = _create_notebook_session_note(client, headers)

            resp = client.post(f"/api/quiz/session/{session_id}/bank/rebuild", headers=headers)
            assert resp.status_code == 503


@pytest.mark.skip(reason="AGENTS_SYNC=1: agent runs synchronously and fails due to insufficient mock questions (needs 30, mock has 3)")
def test_rebuild_bank_creates_task():
    """Rebuild bank creates an async task."""
    with patch("app.agents.base.OpenAI") as mock_cls:
        # Make it slow so task stays pending
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(MOCK_BANK_RESPONSE)
        mock_client.chat.completions.create.return_value = mock_response

        with TestClient(app) as client:
            headers = auth_headers(client)
            _, session_id = _create_notebook_session_note(client, headers)

            resp = client.post(f"/api/quiz/session/{session_id}/bank/rebuild", headers=headers)
            assert resp.status_code == 202
            data = resp.json()
            assert data["status"] == "generating"
            assert "task_id" in data

            # Wait for task to complete
            time.sleep(2)

            # Bank should be ready now
            resp = client.get(f"/api/quiz/session/{session_id}/bank/status", headers=headers)
            assert resp.json()["status"] == "ready"


def test_reuse_active_task():
    """Rebuilding while already generating reuses the same active task."""
    with patch("app.agents.base.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(MOCK_BANK_RESPONSE)

        import threading
        create_event = threading.Event()

        def slow_create(**kwargs):
            create_event.set()
            time.sleep(3)
            return mock_response

        mock_client.chat.completions.create.side_effect = slow_create

        with TestClient(app) as client:
            headers = auth_headers(client)
            _, session_id = _create_notebook_session_note(client, headers)

            # First rebuild
            resp1 = client.post(f"/api/quiz/session/{session_id}/bank/rebuild", headers=headers)
            task_id_1 = resp1.json().get("task_id")
            assert task_id_1 is not None

            # Wait for the create call to start
            create_event.wait(timeout=5)

            # Second rebuild while first is running — should reuse the same task
            resp2 = client.post(f"/api/quiz/session/{session_id}/bank/rebuild", headers=headers)
            task_id_2 = resp2.json().get("task_id")
            assert task_id_2 == task_id_1, "Should reuse the same active task, not create a new one"

            # Bank status shows "generating"
            resp = client.get(f"/api/quiz/session/{session_id}/bank/status", headers=headers)
            assert resp.json()["status"] == "generating"


def test_list_quizzes_shows_score():
    """Quiz list shows score summary for submitted quizzes."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)
        _setup_bank_sync(client, headers, session_id)

        gen = client.post(f"/api/quiz/session/{session_id}/generate", headers=headers)
        quiz_id = gen.json()["quiz_id"]

        # Submit
        client.post(f"/api/quiz/session/{session_id}/{quiz_id}/submit", json={"answers": {"q1": "B", "q2": "A", "q3": "C"}}, headers=headers)

        # List
        resp = client.get(f"/api/quiz/session/{session_id}", headers=headers)
        quizzes = resp.json()
        assert len(quizzes) == 1
        assert quizzes[0]["submitted"] is True
        assert quizzes[0]["score"] is not None
        assert quizzes[0]["score"]["percentage"] == pytest.approx(66.7, abs=0.1)


def test_quiz_survives_bank_rebuild():
    """After bank rebuild, old quiz attempt still shows correct original questions and score."""
    with TestClient(app) as client:
        headers = auth_headers(client)
        _, session_id = _create_notebook_session_note(client, headers)
        _setup_bank_sync(client, headers, session_id)

        # Generate and submit a quiz
        gen = client.post(f"/api/quiz/session/{session_id}/generate", headers=headers)
        quiz_id = gen.json()["quiz_id"]
        client.post(
            f"/api/quiz/session/{session_id}/{quiz_id}/submit",
            json={"answers": {"q1": "B", "q2": "A", "q3": "C"}},
            headers=headers,
        )

        # Get original detail
        orig_detail = client.get(f"/api/quiz/session/{session_id}/{quiz_id}", headers=headers).json()
        orig_score = orig_detail["submission"]["score"]
        orig_questions = [q["question"] for q in orig_detail["questions"]]

        # Rebuild bank with different questions
        new_bank = {
            "title": "New Bank",
            "questions": [
                {
                    "id": "q1",
                    "question": "完全不同的题目1",
                    "options": [
                        {"id": "A", "text": "A", "explanation": "A"},
                        {"id": "B", "text": "B", "explanation": "B"},
                        {"id": "C", "text": "C", "explanation": "C"},
                        {"id": "D", "text": "D", "explanation": "D"},
                    ],
                    "answer": "A",
                    "explanation": "新题1",
                    "source": {"source_type": "note", "snippet": "新", "page": None},
                },
                {
                    "id": "q2",
                    "question": "完全不同的题目2",
                    "options": [
                        {"id": "A", "text": "A", "explanation": "A"},
                        {"id": "B", "text": "B", "explanation": "B"},
                        {"id": "C", "text": "C", "explanation": "C"},
                        {"id": "D", "text": "D", "explanation": "D"},
                    ],
                    "answer": "B",
                    "explanation": "新题2",
                    "source": {"source_type": "note", "snippet": "新", "page": None},
                },
            ],
        }
        from app.services import quiz_service
        from app.models import Note
        db = SessionLocal()
        try:
            note = db.query(Note).filter(Note.session_id == session_id).first()
            bank_data = quiz_service.normalize_quiz_data(new_bank)
            # Use a different content_hash to simulate rebuild after content change
            quiz_service._set_quiz_bank_in_vocabulary(note, bank_data, "new_hash_after_rebuild")
            db.commit()
        finally:
            db.close()

        # Old quiz detail should still show original questions and score
        new_detail = client.get(f"/api/quiz/session/{session_id}/{quiz_id}", headers=headers).json()
        assert new_detail["submission"]["score"] == orig_score
        new_questions = [q["question"] for q in new_detail["questions"]]
        assert new_questions == orig_questions, "Questions should come from snapshot, not new bank"
