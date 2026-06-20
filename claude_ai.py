import anthropic
from datetime import date
from config import ANTHROPIC_API_KEY
from database import (
    get_all_florists, get_all_tasks_for_month,
    get_bouquet_stats_for_month, get_active_bouquets,
    get_setting
)
from kpi import calc_kpi_for_user, format_kpi_for_director

client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """Ты — умный ассистент директора цветочной студии REN (Санкт-Петербург).
Ты знаешь всё о работе флористов: их KPI, задачи по витрине, готовые букеты, продажи.
Отвечай на русском языке. Будь конкретной, используй данные из контекста.
Давай практичные советы. Не придумывай данные — только то что есть в контексте.
Отвечай коротко и по делу."""


async def get_context_for_month(month: str = None) -> str:
    if not month:
        month = date.today().strftime("%Y-%m")

    florists = await get_all_florists()
    all_tasks = await get_all_tasks_for_month(month)
    active_bouquets = await get_active_bouquets()

    lines = [f"=== ДАННЫЕ ЗА {month} ===\n"]

    for florist in florists:
        uid = florist["id"]
        name = florist["name"]
        lines.append(f"--- Флорист: {name} ---")

        kpi = await calc_kpi_for_user(uid, month)
        lines.append(format_kpi_for_director(kpi, name))

        b_stats = await get_bouquet_stats_for_month(uid, month)
        if b_stats and b_stats["total"]:
            lines.append(f"Букеты за месяц: {b_stats['total']} шт.")
            lines.append(f"  Продано в студии: {b_stats['sold_studio']} шт. → {b_stats['revenue_studio'] or 0:,} ₽")
            lines.append(f"  Продано на Flowwow: {b_stats['sold_flowwow']} шт. → {b_stats['revenue_flowwow'] or 0:,} ₽")
            lines.append(f"  Итого продаж: {b_stats['sold_total']} шт. → {b_stats['revenue'] or 0:,} ₽")
            lines.append(f"  Разобрано: {b_stats['disassembled']} шт. (потери {b_stats['losses'] or 0:,} ₽)")
            lines.append(f"  В витрине сейчас: {b_stats['in_vitrina']} шт.")

        lines.append("")

    if active_bouquets:
        lines.append(f"=== АКТИВНЫЕ БУКЕТЫ СЕЙЧАС ({len(active_bouquets)} шт.) ===")
        for b in active_bouquets:
            from datetime import datetime
            created = datetime.fromisoformat(b["created_at"])
            days_ago = (datetime.now() - created).days
            lines.append(f"  #{b['id']} · {b['florist_name']} · {b['price']:,} ₽ · {days_ago} дн.")

    return "\n".join(lines)


async def ask_claude(question: str, month: str = None) -> str:
    context = await get_context_for_month(month)
    today = date.today().strftime("%d.%m.%Y")

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Сегодня {today}.\n\n{context}\n\nВопрос директора: {question}"
            }]
        )
        return response.content[0].text
    except Exception as e:
        return f"Не удалось получить ответ: {str(e)}"


async def generate_monthly_report(month: str = None) -> str:
    if not month:
        month = date.today().strftime("%Y-%m")
    context = await get_context_for_month(month)

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"{context}\n\nСоставь итоговый аналитический отчёт за месяц {month}. "
                          f"Оцени работу каждого флориста, выдели сильные стороны и проблемы. "
                          f"Дай конкретные рекомендации. Начни с общего итога, потом по каждому флористу."
            }]
        )
        return response.content[0].text
    except Exception as e:
        return f"Ошибка генерации отчёта: {str(e)}"


async def generate_weekly_alert(month: str = None) -> str | None:
    if not month:
        month = date.today().strftime("%Y-%m")
    context = await get_context_for_month(month)

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"{context}\n\nПосмотри на текущие показатели флористов. "
                          f"Есть ли кто-то кто рискует не получить KPI? "
                          f"Если да — напиши предупреждение для директора. "
                          f"Если всё в порядке — ответь одним словом: НОРМА"
            }]
        )
        text = response.content[0].text.strip()
        if text.upper() == "НОРМА":
            return None
        return text
    except Exception:
        return None
