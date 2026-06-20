from datetime import date
from database import (
    get_tasks_for_month, get_bouquet_stats_for_month,
    get_setting, get_all_florists
)
from config import (
    TASK_VITRINA_BOUQUETS, TASK_VITRINA_COMPOSITIONS, TASK_FLOWWOW,
    TASK_NAMES, RATING_BAD, RATING_OK, RATING_EXCELLENT,
    RATING_SCORES, RATING_LABELS
)


async def calc_kpi_for_user(user_id: int, month: str = None):
    if not month:
        month = date.today().strftime("%Y-%m")

    max_skips_vitrina = await get_setting("kpi_vitrina_max_skips")
    max_norm_vitrina = await get_setting("kpi_vitrina_max_norm")
    max_skips_flowwow = await get_setting("kpi_flowwow_max_skips")
    max_norm_flowwow = await get_setting("kpi_flowwow_max_norm")
    max_bad_bouquet = await get_setting("kpi_bouquet_max_bad")

    result = {}

    for task_type in [TASK_VITRINA_BOUQUETS, TASK_VITRINA_COMPOSITIONS, TASK_FLOWWOW]:
        tasks = await get_tasks_for_month(user_id, month, task_type)
        total = len(tasks)
        if total == 0:
            result[task_type] = {
                "total": 0, "excellent": 0, "ok": 0, "bad_skip": 0,
                "points": 0, "max_points": 0, "passed": True,
                "fail_reason": None
            }
            continue

        excellent = sum(1 for t in tasks if t["rating"] == RATING_EXCELLENT)
        ok = sum(1 for t in tasks if t["rating"] == RATING_OK)
        bad_or_skip = sum(1 for t in tasks if t["rating"] == RATING_BAD or t["status"] in ("pending", "overdue", "failed"))
        points = excellent * 2 + ok * 1
        max_points = total * 2

        fail_reason = None
        if task_type in (TASK_VITRINA_BOUQUETS, TASK_VITRINA_COMPOSITIONS):
            if bad_or_skip > max_skips_vitrina:
                fail_reason = f"пропусков {bad_or_skip} — лимит {max_skips_vitrina}"
            elif ok > max_norm_vitrina:
                fail_reason = f"оценок «Норм» {ok} — лимит {max_norm_vitrina}"
        elif task_type == TASK_FLOWWOW:
            if bad_or_skip > max_skips_flowwow:
                fail_reason = f"пропусков {bad_or_skip} — лимит {max_skips_flowwow}"
            elif ok > max_norm_flowwow:
                fail_reason = f"оценок «Норм» {ok} — лимит {max_norm_flowwow}"

        result[task_type] = {
            "total": total,
            "excellent": excellent,
            "ok": ok,
            "bad_skip": bad_or_skip,
            "points": points,
            "max_points": max_points,
            "passed": fail_reason is None,
            "fail_reason": fail_reason,
        }

    # Bouquets quality
    bouquet_stats = await get_bouquet_stats_for_month(user_id, month)
    if bouquet_stats and bouquet_stats["total"]:
        total_b = bouquet_stats["total"]
        avg_rating = bouquet_stats["avg_rating"] or 0
        bad_count = sum(
            1 for b in [] # We'll compute from tasks if needed
        )
        # Approximate: use avg rating
        result["bouquets"] = {
            "total": total_b,
            "avg_rating": round(avg_rating, 1) if avg_rating else 0,
            "passed": True,
            "fail_reason": None,
        }
    else:
        result["bouquets"] = {
            "total": 0, "avg_rating": 0,
            "passed": True, "fail_reason": None,
        }

    all_passed = all(v["passed"] for v in result.values())

    return {
        "month": month,
        "criteria": result,
        "kpi_passed": all_passed,
    }


def format_kpi_for_florist(kpi_data: dict, florist_name: str) -> str:
    today = date.today()
    month_label = today.strftime("%B %Y")
    lines = [f"📊 Мой KPI · {florist_name} · {month_label}\n"]

    icons = {
        TASK_VITRINA_BOUQUETS: "🌸",
        TASK_VITRINA_COMPOSITIONS: "🎋",
        TASK_FLOWWOW: "🛍",
    }

    for task_type, data in kpi_data["criteria"].items():
        if task_type == "bouquets":
            continue
        icon = icons.get(task_type, "•")
        name = TASK_NAMES.get(task_type, task_type)
        lines.append(f"{icon} {name}")
        if data["total"] == 0:
            lines.append("   Задач ещё не было\n")
            continue
        pct = int(data["points"] / data["max_points"] * 100) if data["max_points"] else 0
        bar = _progress_bar(pct)
        lines.append(f"   Всего задач: {data['total']}")
        lines.append(f"   ⭐ Отлично: {data['excellent']}  👌 Норм: {data['ok']}  ❌ Пропуск/Плохо: {data['bad_skip']}")
        lines.append(f"   {bar} {pct}%")
        if data["passed"]:
            lines.append("   ✅ Критерий пройден\n")
        else:
            lines.append(f"   ❌ Не пройден: {data['fail_reason']}\n")

    b = kpi_data["criteria"].get("bouquets", {})
    if b["total"] > 0:
        lines.append(f"🌹 Качество букетов")
        lines.append(f"   Сделано: {b['total']} шт. · Средняя оценка: ⭐ {b['avg_rating']}")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━")
    if kpi_data["kpi_passed"]:
        lines.append("✅ KPI засчитан → премия 5 000 ₽")
    else:
        failed = [
            TASK_NAMES.get(k, k)
            for k, v in kpi_data["criteria"].items()
            if not v["passed"]
        ]
        lines.append("❌ KPI не засчитан")
        lines.append(f"Провал по: {', '.join(failed)}")

    return "\n".join(lines)


def format_kpi_for_director(kpi_data: dict, florist_name: str) -> str:
    lines = [f"📊 KPI · {florist_name}"]
    icons = {
        TASK_VITRINA_BOUQUETS: "🌸",
        TASK_VITRINA_COMPOSITIONS: "🎋",
        TASK_FLOWWOW: "🛍",
    }
    for task_type, data in kpi_data["criteria"].items():
        if task_type == "bouquets":
            continue
        icon = icons.get(task_type, "•")
        name = TASK_NAMES.get(task_type, task_type)
        if data["total"] == 0:
            lines.append(f"{icon} {name}: нет задач")
            continue
        status = "✅" if data["passed"] else "❌"
        pct = int(data["points"] / data["max_points"] * 100) if data["max_points"] else 0
        lines.append(f"{icon} {name}: {status} {pct}% ({data['excellent']}⭐ {data['ok']}👌 {data['bad_skip']}❌)")
        if not data["passed"]:
            lines.append(f"   Причина: {data['fail_reason']}")

    b = kpi_data["criteria"].get("bouquets", {})
    if b["total"] > 0:
        lines.append(f"🌹 Букеты: {b['total']} шт. · оценка ⭐{b['avg_rating']}")

    if kpi_data["kpi_passed"]:
        lines.append("→ ✅ КPI засчитан")
    else:
        lines.append("→ ❌ KPI не засчитан")

    return "\n".join(lines)


def _progress_bar(pct: int, width: int = 10) -> str:
    filled = int(width * pct / 100)
    return "█" * filled + "░" * (width - filled)
