import anthropic
from datetime import datetime
from config import ANTHROPIC_API_KEY
from database import get_month_tasks, get_month_bouquets, get_month_shifts, get_florists
from kpi import calc_kpi

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """Ты — умный помощник директора цветочной студии REN (Санкт-Петербург).
Ты получаешь данные о работе флористов и помогаешь директору анализировать их работу.

Твой стиль: дружелюбный, конкретный, без воды. Отвечай по делу, используй конкретные цифры из данных.
Давай практичные выводы и рекомендации. Пиши по-русски.

Ты знаешь систему KPI студии:
- Витрина букетов (14:00): не более 4 пропусков и 7 «Норм» в месяц
- Витрина композиций (18:00): те же правила  
- Flowwow (каждые 2 дня): не более 1 пропуска и 4 «Норм»
- Качество букетов: не более 2 «Плохо» и не более половины «Норм»
- KPI засчитан если все 4 критерия пройдены → премия 5 000 ₽
"""


def get_context_data():
    now = datetime.now()
    year_month = now.strftime("%Y-%m")
    florists = get_florists()
    
    context_parts = [f"Текущая дата: {now.strftime('%d.%m.%Y')}"]
    
    for f in florists:
        kpi = calc_kpi(f["id"], year_month)
        tasks = get_month_tasks(year_month, f["id"])
        bouquets = get_month_bouquets(year_month, f["id"])
        shifts = get_month_shifts(f["id"], year_month)
        
        sold = [b for b in bouquets if b["status"] in ("sold_studio", "sold_flowwow")]
        disassembled = [b for b in bouquets if b["status"] == "disassembled"]
        
        context_parts.append(f"""
--- Флорист: {f['name']} ---
Смен в {year_month}: {len(shifts)}

Задачи:
- Витрина букетов: {sum(1 for t in tasks if t['type']=='vitrina_bouquets' and t['rating']==2)} отлично, {sum(1 for t in tasks if t['type']=='vitrina_bouquets' and t['rating']==1)} норм, {sum(1 for t in tasks if t['type']=='vitrina_bouquets' and t['status'] in ('missed','no'))} пропусков
- Витрина композиций: {sum(1 for t in tasks if t['type']=='vitrina_compositions' and t['rating']==2)} отлично, {sum(1 for t in tasks if t['type']=='vitrina_compositions' and t['rating']==1)} норм, {sum(1 for t in tasks if t['type']=='vitrina_compositions' and t['status'] in ('missed','no'))} пропусков
- Flowwow: {sum(1 for t in tasks if t['type']=='flowwow' and t['rating']==2)} отлично, {sum(1 for t in tasks if t['type']=='flowwow' and t['rating']==1)} норм, {sum(1 for t in tasks if t['type']=='flowwow' and t['status'] in ('missed','no'))} пропусков

Букеты:
- Сделано: {len(bouquets)} шт.
- Продано в студии: {sum(1 for b in bouquets if b['sale_channel']=='studio')} шт. на {sum(b['price'] for b in bouquets if b['sale_channel']=='studio')} ₽
- Продано на Flowwow: {sum(1 for b in bouquets if b['sale_channel']=='flowwow')} шт. на {sum(b['price'] for b in bouquets if b['sale_channel']=='flowwow')} ₽
- Разобрано: {len(disassembled)} шт. (потери {sum(b['price'] for b in disassembled)} ₽)
- В витрине сейчас: {sum(1 for b in bouquets if b['status']=='in_vitrina')} шт.
- Оценки качества: {sum(1 for b in bouquets if b['director_rating']==2)} отлично, {sum(1 for b in bouquets if b['director_rating']==1)} норм, {sum(1 for b in bouquets if b['director_rating']==0)} плохо

KPI статус: {'ЗАСЧИТАН ✅' if kpi['kpi_passed'] else 'НЕ ЗАСЧИТАН ❌'}
""")
    
    return "\n".join(context_parts)


def ask_claude(user_question: str) -> str:
    try:
        context = get_context_data()
        
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Данные о работе студии:\n{context}\n\nВопрос директора: {user_question}"
            }]
        )
        return message.content[0].text
    except Exception as e:
        return f"Ошибка при обращении к Claude: {e}"


def generate_monthly_report(year_month: str) -> str:
    try:
        florists = get_florists()
        tasks = []
        bouquets_all = []
        kpi_results = []
        
        for f in florists:
            kpi = calc_kpi(f["id"], year_month)
            kpi_results.append((f["name"], kpi))
            tasks.extend(get_month_tasks(year_month, f["id"]))
            bouquets_all.extend(get_month_bouquets(year_month, f["id"]))
        
        context = get_context_data()
        
        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"""Данные за {year_month}:
{context}

Напиши итоговый анализ месяца для директора:
1. Общую оценку работы каждого флориста
2. Что шло хорошо
3. Что нужно улучшить
4. Конкретные рекомендации
5. Итог по KPI каждого флориста

Будь конкретной, используй цифры из данных."""
            }]
        )
        return f"✦ Анализ {year_month} от Claude\n\n" + message.content[0].text
    except Exception as e:
        return f"Ошибка при формировании отчёта: {e}"
