import json
import os
import re

import httpx


MODEL = os.getenv("AI_MODEL", "gemini-3.8-flash")
BASE_URL = os.getenv("AI_BASE_URL", "https://ru.cheapvibecode.ru/v1").rstrip("/")


def _extract_json(content: str) -> dict:
    content = content.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", content, re.DOTALL | re.IGNORECASE)
    candidate = fenced.group(1) if fenced else content
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as error:
        raise ValueError("Модель вернула ответ не в формате JSON") from error
    if not isinstance(value, dict) or not isinstance(value.get("rows"), list):
        raise ValueError("Модель вернула JSON без обязательного массива rows")
    return value


def _normalize_result(result: dict) -> dict:
    rows = []
    for row in result.get("rows", []):
        if not isinstance(row, dict):
            continue
        topic = str(row.get("topic") or "").strip()
        udd = str(row.get("udd") or "").strip()
        hours = row.get("hours")
        if isinstance(hours, str) and hours.strip().isdigit():
            hours = int(hours.strip())
        if not isinstance(hours, int) or hours <= 0:
            hours = None
        if topic:
            rows.append({"topic": topic, "hours": hours, "udd": udd})

    result["rows"] = rows
    result["warnings"] = [str(item) for item in result.get("warnings", []) if str(item).strip()]
    diagnostics = result.get("diagnostics")
    result["diagnostics"] = diagnostics if isinstance(diagnostics, dict) else {}
    result["diagnostics"]["total_hours"] = sum(row["hours"] or 0 for row in rows)
    return result


def _target_hours(text: str) -> int | None:
    match = re.search(r"(?:рассчитана|рассчитано|составляет|всего)\s+на\s+(\d{2,3})\s+час", text.lower())
    return int(match.group(1)) if match else None


def _reconcile_hours(result: dict, target: int) -> dict:
    rows = result["rows"]
    if not rows:
        raise ValueError("Невозможно скорректировать часы: модель не вернула строки плана")
    difference = target - result["diagnostics"]["total_hours"]
    if difference == 0:
        return result

    adjustable = [
        (index, row) for index, row in enumerate(rows)
        if row["hours"] is not None and "контрольная" not in row["topic"].lower()
    ] or list(enumerate(rows))
    index, row = max(adjustable, key=lambda item: item[1]["hours"] or 0)
    updated_hours = (row["hours"] or 0) + difference
    if updated_hours <= 0:
        raise ValueError(f"Невозможно скорректировать часы до {target}: отрицательное значение для строки {index + 1}")
    row["hours"] = updated_hours
    result["diagnostics"]["total_hours"] = sum(item["hours"] or 0 for item in rows)
    result["warnings"].append(
        f"Модель выдала {target - difference} часов вместо {target}. Разница {abs(difference)} ч. скорректирована автоматически в теме «{row['topic']}»."
    )
    return result


def _request(api_key: str, body: dict) -> str:
    try:
        response = httpx.post(
            f"{BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
            timeout=180,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as error:
        detail = error.response.text[:1000]
        raise ValueError(f"AI API вернул HTTP {error.response.status_code}: {detail}") from error
    except (httpx.HTTPError, KeyError, IndexError, TypeError) as error:
        raise ValueError(f"Не удалось получить ответ AI API: {error}") from error


def parse_with_ai(text: str) -> dict:
    api_key = os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("Не задан AI_API_KEY. Передайте ключ API через переменную окружения.")

    prompt = """Ты восстанавливаешь структурированный учебно-календарный план школы из файла Word.
Верни ТОЛЬКО валидный JSON без Markdown и пояснений строго такого вида:
{
  "rows": [
    {"topic": "Тема урока", "hours": 1, "udd": "Компетенции, которые должен получить ученик"}
  ],
  "warnings": ["..."],
  "diagnostics": {"message": "...", "mode": "extracted или reconstructed"}
}

Правила:
1. Сначала найди настоящую таблицу уроков. Не принимай за нее оборудование, литературу, график контрольных работ или пояснительную записку.
2. Если настоящая таблица заполнена, точно извлеки из нее тему, часы и планируемые результаты. Укажи diagnostics.mode = "extracted".
3. Если заголовок таблицы уроков есть, но ее строки отсутствуют, повреждены или заменены посторонней таблицей, НЕ возвращай пустой rows. Восстанови календарно-тематический план по всем доступным сведениям документа: предмету, классу, учебнику, авторской программе, общему числу часов, часам в неделю, требованиям к результатам и темам контрольных работ. Укажи diagnostics.mode = "reconstructed".
4. При восстановлении используй стандартную последовательность тем именно для указанного в документе класса и учебника. Не добавляй темы из другого класса.
5. topic — конкретная тема урока или группы однородных уроков. Не используй оборудование и служебные разделы.
6. hours — положительное целое число. При восстановлении сумма hours ОБЯЗАНА точно совпасть с общим объемом программы, указанным в документе. Если указан объем 68 часов, сумма всех строк должна быть ровно 68.
7. udd — конкретные компетенции ученика после темы: что он будет знать, уметь распознавать, доказывать, строить, вычислять или применять. Для каждой строки udd должен быть заполнен содержательным текстом.
8. Сохраняй логический порядок изучения курса. Контрольные работы включай отдельными строками, если они указаны в документе.
9. В warnings честно сообщи, что исходная таблица отсутствовала и план восстановлен моделью, если использован режим reconstructed.
10. Возвращай rows пустым только тогда, когда из документа невозможно определить даже предмет, класс и объем программы.

Текст документа:
"""
    body = {
        "model": MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "Ты методист школы и специалист по восстановлению поврежденных календарно-тематических планов. Строго соблюдай предмет, класс и общий объем часов из документа."},
            {"role": "user", "content": prompt + text[:250000]},
        ],
    }
    result = _normalize_result(_extract_json(_request(api_key, body)))
    target_hours = _target_hours(text)
    actual_hours = result["diagnostics"]["total_hours"]
    if target_hours and actual_hours != target_hours:
        repair_body = {
            "model": MODEL,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "Ты проверяешь и исправляешь JSON учебного плана. Верни только JSON."},
                {"role": "user", "content": (
                    f"Исправь поле hours в JSON. Общий объем программы должен быть ровно {target_hours} часов, "
                    f"сейчас сумма равна {actual_hours}. Не меняй topic и udd, не удаляй строки, сохрани порядок. "
                    "Верни объект с rows, warnings и diagnostics.\n" + json.dumps(result, ensure_ascii=False)
                )},
            ],
        }
        result = _normalize_result(_extract_json(_request(api_key, repair_body)))
        result = _reconcile_hours(result, target_hours)
        result["diagnostics"]["hours_validated"] = result["diagnostics"]["total_hours"] == target_hours
        result["warnings"].append(f"Распределение часов проверено: итоговая сумма {target_hours} часов.")
    elif target_hours:
        result = _reconcile_hours(result, target_hours)
        result["diagnostics"]["hours_validated"] = result["diagnostics"]["total_hours"] == target_hours
    if target_hours:
        result["diagnostics"]["target_hours"] = target_hours
    result.setdefault("warnings", [])
    result.setdefault("diagnostics", {})
    return result
