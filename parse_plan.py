import docx
import json
import re

doc = docx.Document('W:/teacher_ai/programma_g-7.docx')
t = doc.tables[2]

current_quarter = ""
current_chapter = ""

curriculum = []

for r_idx in range(3, len(t.rows)):
    row = t.rows[r_idx]
    cells = [c.text.strip().replace('\r', '').replace('\n', ' ') for c in row.cells]
    
    lesson_num = re.sub(r'\s+', ' ', cells[0]).strip()
    point = re.sub(r'\s+', ' ', cells[1]).strip()
    topic = re.sub(r'\s+', ' ', cells[2]).strip()
    hours_str = re.sub(r'\s+', ' ', cells[3]).strip()
    date_plan = re.sub(r'\s+', ' ', cells[4]).strip()
    date_fact = re.sub(r'\s+', ' ', cells[5]).strip()
    subject_competencies = re.sub(r'\s+', ' ', cells[6]).strip()
    meta_competencies = re.sub(r'\s+', ' ', cells[7]).strip()
    activities = re.sub(r'\s+', ' ', cells[8]).strip()

    if not lesson_num:
        if 'четверть' in topic.lower():
            current_quarter = topic
            continue
        if point.startswith('Гл') or '«' in topic:
            current_chapter = f"{point} {topic}".strip() if point else topic
            continue
        if not hours_str:
            continue

    try:
        hours = int(hours_str) if hours_str.isdigit() else float(hours_str)
    except ValueError:
        hours = hours_str

    competencies = {}
    if subject_competencies:
        competencies["предметные"] = subject_competencies
    if meta_competencies:
        competencies["метапредметные_и_личностные"] = meta_competencies

    item = {
        "номер_урока": lesson_num,
        "пункт": point if point else None,
        "тема_урока": topic,
        "количество_часов": hours,
        "четверть": current_quarter if current_quarter else None,
        "раздел": current_chapter if current_chapter else None,
        "дата_план": date_plan if date_plan else None,
        "дата_факт": date_fact if date_fact else None,
        "компетенции": competencies if competencies else None,
        "виды_деятельности": activities if activities else None
    }
    curriculum.append(item)

with open('W:/teacher_ai/programma_g-7.json', 'w', encoding='utf-8') as f:
    json.dump(curriculum, f, ensure_ascii=True, indent=2)

print(f"Parsed {len(curriculum)} items successfully.")
