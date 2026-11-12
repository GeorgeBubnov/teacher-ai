import json
import os
import re
import subprocess
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware


STORAGE = Path(os.getenv("STORAGE_DIR", "/data"))
BOOKS = STORAGE / "books"
RESULTS = STORAGE / "results"
BOOKS.mkdir(parents=True, exist_ok=True)
RESULTS.mkdir(parents=True, exist_ok=True)
BASE_URL = os.getenv("AI_BASE_URL", "https://ru.cheapvibecode.ru/v1").rstrip("/")
MODEL = os.getenv("AI_MODEL", "gemini-3.8-flash")

app = FastAPI(title="Материал для урока за 15 минут")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def extract_pdf(path: Path) -> str:
    result = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, check=False)
    if result.returncode:
        raise ValueError(result.stderr.decode("utf-8", errors="replace") or "Не удалось прочитать PDF")
    return result.stdout.decode("utf-8", errors="replace")


def parse_page_range(value: str, page_count: int) -> list[int]:
    indexes = set()
    for part in re.split(r"[,;]\s*", value.strip()):
        match = re.fullmatch(r"(\d+)(?:\s*[-–—]\s*(\d+))?", part)
        if not match:
            continue
        start = int(match.group(1))
        end = int(match.group(2) or start)
        for page in range(max(1, start), min(page_count, end) + 1):
            indexes.add(page - 1)
    return sorted(indexes)


def select_source(text: str, topic: str, pages: str) -> str:
    pdf_pages = text.split("\f")
    requested = parse_page_range(pages, len(pdf_pages))
    if requested:
        return "\n\n".join(f"[Страница {index + 1}]\n{pdf_pages[index]}" for index in requested)

    topic_words = [
        word.lower().replace("ё", "е")
        for word in re.findall(r"[а-яёa-z]{4,}", topic, flags=re.IGNORECASE)
        if word.lower() not in {"урока", "тема", "класс", "геометрия"}
    ]
    # Учебник и тема используют разные падежи: "отрезок", "отрезка", "отрезки".
    # Поиск по началу слова устойчивее точного совпадения словоформы.
    terms = {word[:max(4, min(7, len(word) - 1))] for word in topic_words}
    if not terms:
        return text[:300000]

    scored = []
    ordered_stems = [word[:max(4, min(7, len(word) - 1))] for word in topic_words]
    phrase_pattern = r"\b" + r"[а-яa-z]*\W+(?:[а-яa-z]+\W+){0,2}".join(
        re.escape(stem) for stem in ordered_stems
    ) + r"[а-яa-z]*"
    for index, page in enumerate(pdf_pages):
        normalized = page.lower().replace("ё", "е")
        score = sum(len(re.findall(rf"\b{re.escape(term)}[а-яa-z]*", normalized)) for term in terms)
        if len(topic_words) > 1 and all(re.search(rf"\b{re.escape(word[:4])}[а-яa-z]*", normalized) for word in topic_words):
            score += 8
        if re.search(phrase_pattern, normalized):
            score += 1000
        if score:
            scored.append((score, index))
    selected = set()
    ranked = sorted(scored, reverse=True)
    if ranked and ranked[0][0] >= 1000:
        section_start = ranked[0][1]
        selected.update(range(max(0, section_start - 1), min(len(pdf_pages), section_start + 6)))
    else:
        for _, index in ranked[:8]:
            selected.update(range(max(0, index - 1), min(len(pdf_pages), index + 2)))
    if not selected:
        return text[:300000]
    return "\n\n".join(f"[Страница {index + 1}]\n{pdf_pages[index]}" for index in sorted(selected))[:300000]


def get_text(response: httpx.Response) -> str:
    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise ValueError("AI API вернул ответ без текста") from error
    content = re.sub(r"^```(?:text|markdown)?\s*|\s*```$", "", content.strip(), flags=re.I)
    return content.strip()


def generate_material(text: str, topic: str, pages: str) -> str:
    key = os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not key:
        raise ValueError("Не задан AI_API_KEY")
    scope = f"Тема урока: {topic.strip() or 'определи подходящую тему по запросу'}\n"
    if pages.strip():
        scope += f"Предпочтительные страницы или диапазон: {pages.strip()}\n"
    source = select_source(text, topic, pages)
    prompt = f"""Ты готовишь материал для школьного урока по учебнику.
{scope}
Выбери из текста учебника только материал, который можно разобрать примерно за 15 минут.
Верни только один цельный связный текст на русском языке без заголовков Markdown, списков, JSON, таблиц, ссылок на процесс подготовки и фраз про искусственный интеллект.
Текст должен объяснить тему ученику соответствующего класса, включать определения, ключевые свойства или правила, один понятный пример и короткий вывод.
Ориентировочный объем готового текста — 1500–2000 слов. Не растягивай текст повторами ради объема.
Не добавляй сведения, которых нет в учебнике. Если в книге не найден материал по теме, честно напиши об этом одной фразой.

Релевантный фрагмент PDF учебника:
{source}"""
    body = {
        "model": MODEL,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": "Ты опытный школьный учитель. Пиши ясным, деловым и естественным языком."},
            {"role": "user", "content": prompt},
        ],
    }
    try:
        response = httpx.post(
            f"{BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=body,
            timeout=240,
        )
        response.raise_for_status()
        return get_text(response)
    except httpx.HTTPStatusError as error:
        raise ValueError(f"AI API вернул HTTP {error.response.status_code}: {error.response.text[:500]}") from error
    except httpx.HTTPError as error:
        raise ValueError(f"Не удалось обратиться к AI API: {error}") from error


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/material")
async def material(file: UploadFile = File(...), topic: str = Form(""), pages: str = Form("")):
    if not file.filename or Path(file.filename).suffix.lower() != ".pdf":
        raise HTTPException(400, "Этот проект принимает только PDF-книги")
    document_id = uuid.uuid4().hex
    path = BOOKS / f"{document_id}.pdf"
    path.write_bytes(await file.read())
    try:
        source = extract_pdf(path)
        output = generate_material(source, topic, pages)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    result = {"id": document_id, "filename": file.filename, "topic": topic, "pages": pages, "text": output}
    (RESULTS / f"{document_id}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
