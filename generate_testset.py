import os
import json
from pathlib import Path
from ragas.testset.generator import TestsetGenerator
from ragas.testset.evolutions import simple, reasoning, multi_context
from langchain_ollama import ChatOllama, OllamaEmbeddings
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper

# 1. Настройка локальных моделей через Ollama
# Используем ту же модель эмбеддингов, что и в основной системе
embed_model = OllamaEmbeddings(model="ai-forever/ru-en-RoSBERTa")  # или та, которую вы используете
# Для генерации вопросов нужна более мощная LLM
generator_llm = ChatOllama(model="qwen2.5:7b", temperature=0.3)

# Оборачиваем в RAGAS-совместимые классы
ragas_llm = LangchainLLMWrapper(generator_llm)
ragas_embeddings = LangchainEmbeddingsWrapper(embed_model)

# 2. Загрузка документов
documents = []
data_dir = Path("data")
for txt_file in data_dir.glob("*.txt"):
    with open(txt_file, "r", encoding="utf-8") as f:
        text = f.read()
        documents.append({"page_content": text, "metadata": {"source": txt_file.name}})

# 3. Создание генератора тестсета
generator = TestsetGenerator(
    llm=ragas_llm,
    embedding_model=ragas_embeddings
)

# 4. Генерация тестов (параметры можно менять)
testset = generator.generate_with_langchain_docs(
    documents,
    test_size=10,              # сколько вопросов сгенерировать (начните с малого)
    distributions={simple: 0.5, reasoning: 0.3, multi_context: 0.2},  # типы вопросов
)

# 5. Сохранение результатов
output = []
for test_row in testset:
    output.append({
        "question": test_row.question,
        "ground_truth": test_row.ground_truth,
        "contexts": test_row.contexts,  # ожидаемые релевантные чанки
    })

with open("testset.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"Сгенерировано {len(output)} тестовых вопросов. Сохранено в testset.json")