import re
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path


HEADER_WORDS = {
    "тема", "темы", "тема урока", "количество часов", "часы", "удд",
    "компетенции", "содержание", "раздел"
}

PLAN_MARKER = "календарно-тематическое планирование"
STOP_MARKERS = ("основная учебно-методическая литература", "дополнительная учебно-методическая литература")
EQUIPMENT_WORDS = (
    "доска", "монитор", "системный блок", "клавиатура", "мышь", "акустическая",
    "мфу", "экран", "проектор", "рабочее место пользователя",
)


def extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        command = ["pdftotext", "-layout", str(path), "-"]
    elif path.suffix.lower() == ".docx":
        return extract_docx_text(path)
    else:
        command = ["antiword", "-m", "UTF-8.txt", str(path)]
    result = subprocess.run(
        command,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(error or "Не удалось прочитать файл .doc")
    return result.stdout.decode("utf-8", errors="replace")


def extract_docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            xml_data = archive.read("word/document.xml")
        root = ET.fromstring(xml_data)
    except (KeyError, zipfile.BadZipFile, ET.ParseError) as error:
        raise ValueError("Не удалось прочитать структуру файла .docx") from error

    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = []
    for paragraph in root.findall(".//w:p", namespace):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace))
        if text.strip():
            paragraphs.append(text)
    tables = []
    for table in root.findall(".//w:tbl", namespace):
        for row in table.findall("./w:tr", namespace):
            cells = []
            for cell in row.findall("./w:tc", namespace):
                cell_text = " ".join(
                    "".join(node.text or "" for node in paragraph.findall(".//w:t", namespace)).strip()
                    for paragraph in cell.findall("./w:p", namespace)
                )
                cells.append(clean(cell_text))
            if any(cells):
                tables.append("| " + " | ".join(cells) + " |")
    return "\n".join(paragraphs + tables)


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\x00", " ")).strip(" \t|;")


def is_header(line: str) -> bool:
    normalized = clean(line).lower()
    return any(word in normalized for word in HEADER_WORDS)


def split_columns(line: str) -> list[str]:
    parts = [clean(part) for part in re.split(r"\t+|\s{3,}|\s*\|\s*", line)]
    return [part for part in parts if part]


def parse_hours(value: str) -> int | None:
    match = re.search(r"(?<!\d)(\d{1,2})(?!\d)", value)
    return int(match.group(1)) if match else None


def looks_like_topic(value: str) -> bool:
    return len(value) >= 4 and not re.fullmatch(r"[\d\s./-]+", value)


def is_equipment_topic(value: str) -> bool:
    normalized = value.lower()
    return any(word in normalized for word in EQUIPMENT_WORDS)


def parse_pipe_row(line: str) -> tuple[str, int | None, str] | None:
    if "|" not in line:
        return None
    cells = [clean(cell) for cell in line.split("|")]
    if cells and not cells[0]:
        cells = cells[1:]
    if cells and not cells[-1]:
        cells = cells[:-1]
    if len(cells) < 3 or not cells[0].isdigit():
        return None

    numeric_indexes = [index for index, cell in enumerate(cells[1:], start=1) if parse_hours(cell) is not None and cell.isdigit()]
    if not numeric_indexes:
        return None
    hours_index = numeric_indexes[0]
    candidates = [cell for cell in cells[1:hours_index] if looks_like_topic(cell)]
    if not candidates and hours_index == 1 and len(cells) > 2 and looks_like_topic(cells[1]):
        candidates = [cells[1]]
    if not candidates:
        return None
    topic = max(candidates, key=len)
    topic_index = cells.index(topic, 1)
    udd = " ".join(cell for cell in cells[hours_index + 1:] if cell)
    return topic, parse_hours(cells[hours_index]), udd


def parse_document(text: str) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    warnings: list[str] = []
    all_lines = [clean(line) for line in text.splitlines() if clean(line)]
    marker_line = next((index for index, line in enumerate(all_lines) if PLAN_MARKER in line.lower()), None)
    if marker_line is None:
        return [], ["В документе не найден раздел «Календарно-тематическое планирование»."]
    lines = all_lines[marker_line:]
    table_mode = False
    candidate_topics: list[str] = []

    for line_number, line in enumerate(lines, start=1):
        if any(marker in line.lower() for marker in STOP_MARKERS):
            break
        if is_header(line):
            table_mode = True
            continue
        pipe_row = parse_pipe_row(line)
        if table_mode and pipe_row:
            topic, hours, udd = pipe_row
            candidate_topics.append(topic)
            if not is_equipment_topic(topic):
                rows.append({"topic": topic, "hours": hours, "udd": udd})
            continue
        columns = split_columns(line)
        if not table_mode or len(columns) < 2:
            continue

        hours_index = next((i for i, column in enumerate(columns) if parse_hours(column) is not None), None)
        if hours_index is None:
            continue
        topic = next((column for column in columns[:hours_index] if looks_like_topic(column)), "")
        if not topic:
            continue

        hours = parse_hours(columns[hours_index])
        udd_parts = columns[hours_index + 1:]
        if not udd_parts:
            warnings.append(f"Строка {line_number}: для темы «{topic}» не найдены компетенции")
        rows.append({"topic": topic, "hours": hours, "udd": " ".join(udd_parts)})

    if not rows:
        if candidate_topics and all(is_equipment_topic(topic) for topic in candidate_topics):
            warnings.append("После заголовка планирования найдена таблица оборудования, а не таблица уроков. Темы уроков в этом файле отсутствуют.")
        else:
            warnings.append("Не удалось найти строки с темой и количеством часов в таблице уроков. Проверьте структуру документа.")
    return rows, warnings
