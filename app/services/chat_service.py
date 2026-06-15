"""Сервис чата с Дейлом."""

import json
from typing import AsyncGenerator

import httpx

from app.config import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_NUM_PREDICT, OLLAMA_TIMEOUT
from app.intent.escalation import should_escalate_to_operator
from app.permissions import get_permissions
from app.prompts.dale import DALE_SYSTEM_PROMPT, LOADING_PHRASES
from app.search.hybrid import format_context, hybrid_search
from app.services.orchestrator import ChatOrchestrator
from app.services.output_sanitizer import sanitize_llm_output
from app.storage.database import Database

FAQ_PROMPT = """{system}

{extra}

Диалог:
{history}

Пользователь: {query}
Дейл:"""


def _format_history(history: list[dict]) -> str:
    lines = []
    for msg in history[-10:]:
        if msg["role"] == "user":
            lines.append(f"Пользователь: {msg['content']}")
        elif msg["role"] == "operator":
            lines.append(f"Оператор банка: {msg['content']}")
        else:
            lines.append(f"Дейл: {msg['content']}")
    return "\n".join(lines) if lines else "(начало диалога)"


class ChatService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.orchestrator = ChatOrchestrator(db)

    async def stream_chat(
        self,
        user_id: str,
        message: str,
        conversation_id: str | None = None,
    ) -> AsyncGenerator[str, None]:
        conv_id = self.db.get_or_create_conversation(user_id, conversation_id)
        history = self.db.get_messages(conv_id)

        yield self._sse({"type": "meta", "conversation_id": conv_id})
        yield self._sse({"type": "status", "text": LOADING_PHRASES[0]})

        self.db.add_message(conv_id, "user", message)

        escalation_reason = should_escalate_to_operator(message)
        if escalation_reason:
            yield self._sse({"type": "status", "text": LOADING_PHRASES[2]})
            self.db.escalate_conversation(conv_id)
            from app.services.conversation_slots import ConversationSlots

            self.orchestrator.slots_manager.save(conv_id, ConversationSlots())
            response = (
                "Передал ваш диалог сотруднику банка — он скоро подключится. "
                "Можете продолжать писать сюда, ответы оператора появятся в чате."
            )
            self.db.add_message(conv_id, "assistant", response, {"escalated": True})
            yield self._sse({"type": "action", "action": {"type": "escalate", "reason": escalation_reason}})
            async for chunk in self._stream_text(response):
                yield chunk
            yield "data: [DONE]\n\n"
            return

        if self.db.is_escalated(conv_id):
            response = "Сообщение отправлено оператору. Ожидайте ответа — он появится в этом чате."
            self.db.add_message(conv_id, "assistant", response, {"system": True})
            async for chunk in self._stream_text(response):
                yield chunk
            yield "data: [DONE]\n\n"
            return

        yield self._sse({"type": "status", "text": LOADING_PHRASES[1]})

        rag_chunks = hybrid_search(message)
        if not rag_chunks:
            yield self._sse({"type": "status", "text": "База знаний недоступна — отвечаю без документов."})
        rag_context = format_context(rag_chunks)
        slots = self.orchestrator.slots_manager.load(conv_id)
        plan, slots = self.orchestrator.plan(
            message, user_id, rag_context, history,
            conversation_id=conv_id,
            slots=slots,
        )
        self.orchestrator.slots_manager.save(conv_id, slots)

        for action in plan.actions:
            yield self._sse({"type": "action", "action": action})

        if not plan.use_llm:
            yield self._sse({"type": "status", "text": LOADING_PHRASES[2]})
            async for chunk in self._stream_text(plan.text):
                yield chunk
            self.db.add_message(conv_id, "assistant", plan.text, {"actions": plan.actions})
            yield "data: [DONE]\n\n"
            return

        yield self._sse({"type": "status", "text": LOADING_PHRASES[2]})

        permissions = get_permissions(user_id)
        perm_text = "\n".join(f"- {k}: {'да' if v else 'нет'}" for k, v in permissions.items())
        system = DALE_SYSTEM_PROMPT.format(
            context=plan.llm_context,
            permissions=perm_text,
            query=message,
        )

        extra = "Отвечай ТОЛЬКО на русском языке. Кратко, 2-4 предложения."
        if plan.actions:
            extra += " Кнопки навигации уже показаны — не создавай ссылки и markdown."

        prompt = FAQ_PROMPT.format(
            system=system,
            extra=extra,
            history=_format_history(history),
            query=message,
        )

        has_nav = any(a.get("type") == "navigate" for a in plan.actions)
        raw_response = ""

        try:
            async for token in self._ollama_generate_stream(prompt):
                raw_response += token
                yield self._sse({"type": "token", "text": token})
        except (httpx.ConnectError, httpx.ReadTimeout) as exc:
            fallback = (
                "Не удалось связаться с языковой моделью."
                if isinstance(exc, httpx.ConnectError)
                else "Модель не успела ответить. Попробуйте короче сформулировать вопрос."
            )
            async for chunk in self._stream_text(fallback):
                yield chunk
            self.db.add_message(conv_id, "assistant", fallback)
            yield "data: [DONE]\n\n"
            return

        full_response = sanitize_llm_output(raw_response, has_nav_button=has_nav)
        yield self._sse({"type": "replace", "text": full_response})
        self.db.add_message(conv_id, "assistant", full_response, {"actions": plan.actions})
        yield "data: [DONE]\n\n"

    async def get_draft_suggestions(self, user_id: str) -> list[dict]:
        return self.db.get_drafts(user_id)

    async def _ollama_generate_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        timeout = httpx.Timeout(OLLAMA_TIMEOUT, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            payload = {
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": True,
                "options": {"temperature": 0.2, "num_predict": OLLAMA_NUM_PREDICT},
            }
            async with client.stream("POST", f"{OLLAMA_BASE_URL}/api/generate", json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    token = data.get("response", "")
                    if token:
                        yield token
                    if data.get("done"):
                        break

    async def _stream_text(self, text: str) -> AsyncGenerator[str, None]:
        for char in text:
            yield self._sse({"type": "token", "text": char})

    @staticmethod
    def _sse(data: dict) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
