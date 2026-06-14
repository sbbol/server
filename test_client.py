import httpx
import json
import asyncio

OLLAMA_API = "http://localhost:8000/chat"

async def chat_loop():
    print("Чат с AI-ассистентом СберБизнес (для выхода введите 'выход' или 'exit')")
    history = []  # история диалога

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=5.0)) as client:
        while True:
            try:
                user_input = input("\nВы: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nДо свидания!")
                break

            if not user_input:
                continue

            if user_input.lower() in ("выход", "exit", "quit"):
                print("До свидания!")
                break

            # Отправляем запрос с историей
            payload = {
                "user_id": "console_user",
                "message": user_input,
                "history": history
            }

            print("Бот: ", end="", flush=True)
            full_response = ""

            try:
                async with client.stream("POST", OLLAMA_API, json=payload) as response:
                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[len("data: "):]
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            token = data.get("token", "")
                            if token:
                                print(token, end="", flush=True)
                                full_response += token
                        except json.JSONDecodeError:
                            continue
                print()  # перевод строки после ответа

            except httpx.ConnectError:
                print("\n[Ошибка: сервер недоступен. Проверьте, запущен ли FastAPI на порту 8000]")
                continue
            except httpx.ReadTimeout:
                print("\n[Ошибка: превышено время ожидания ответа. Попробуйте ещё раз.]")
                continue
            except Exception as e:
                print(f"\n[Неожиданная ошибка: {e}]")
                continue

            # Добавляем в историю
            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": full_response})

if __name__ == "__main__":
    asyncio.run(chat_loop())