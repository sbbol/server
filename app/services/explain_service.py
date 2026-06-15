"""Сервис «Перевод с банковского на человеческий» (Language Adapter)."""

import httpx

from app.config import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT
from app.prompts.dale import EXPLAIN_PROMPT


class ExplainService:
    async def explain(self, text: str) -> str:
        prompt = EXPLAIN_PROMPT.format(text=text.strip())

        try:
            async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
                resp = await client.post(
                    f"{OLLAMA_BASE_URL}/api/generate",
                    json={
                        "model": OLLAMA_MODEL,
                        "prompt": prompt,
                        "stream": False,
                        "options": {"temperature": 0.3, "num_predict": 200},
                    },
                )
                data = resp.json()
                return data.get("response", "").strip() or "Не удалось получить объяснение."
        except httpx.ConnectError:
            return self._fallback_explain(text)

    def _fallback_explain(self, text: str) -> str:
        """Простые объяснения без LLM для MVP."""
        glossary = {
            "инкассовое поручение": "Документ, по которому банк списывает деньги с вашего счёта по требованию другой организации (например, налоговой).",
            "дебет": "Списание денег со счёта.",
            "кредит": "Поступление денег на счёт.",
            "эцп": "Электронная цифровая подпись — ваш «электронный паспорт» для подписания документов в интернет-банке.",
            "банковский день": "Период, в который банк обрабатывает платежи. Может отличаться от календарных суток.",
            "мгновенный платеж": "Перевод, который зачисляется получателю в течение нескольких минут.",
            "платёжное поручение": "Стандартный документ для перевода денег другому контрагенту через банк.",
        }
        lower = text.lower()
        for term, explanation in glossary.items():
            if term in lower:
                return explanation
        return "Это банковский термин. Выделите конкретное слово или обратитесь к Дейлу в чате за подробным объяснением."
