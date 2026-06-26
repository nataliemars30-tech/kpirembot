from database import get_month_tasks, get_month_shifts, get_month_bouquets, get_setting, get_month_lates

RATING_LABELS = {0: "👎 Плохо", 1: "👌 Норм", 2: "⭐ Отлично", None: "—"}


def calc_kpi(florist_id, year_month):
    tasks    = get_month_tasks(year_month, florist_id)
    shifts   = get_month_shifts(florist_id, year_month)
    bouquets = get_month_bouquets(year_month, florist_id)
    lates    = get_month_lates(florist_id, year_month)

    max_skips_v  = int(get_setting("kpi_vitrina_max_skips", "4"))
    max_norm_v   = int(get_setting("kpi_vitrina_max_norm", "7"))
    max_skips_f  = int(get_setting("kpi_flowwow_max_skips", "1"))
    max_norm_f   = int(get_setting("kpi_flowwow_max_norm", "4"))
    max_bad_b    = int(get_setting("kpi_bouquet_max_bad", "2"))
    max_light    = int(get_setting("kpi_late_light_max", "5"))
    max_medium   = int(get_setting("kpi_late_medium_max", "3"))
    max_heavy    = int(get_setting("kpi_late_heavy_max", "2"))

    results = {}

    for ttype in ["vitrina_bouquets", "vitrina_compositions", "flowwow"]:
        tt = [t for t in tasks if t["type"] == ttype]
        total     = len(tt)
        skips     = sum(1 for t in tt if t["status"] in ("missed","no") or t["rating"] == 0)
        norms     = sum(1 for t in tt if t["rating"] == 1)
        excellents= sum(1 for t in tt if t["rating"] == 2)
        if ttype in ("vitrina_bouquets","vitrina_compositions"):
            failed = skips >= max_skips_v + 1 or norms >= max_norm_v + 1
            max_s, max_n = max_skips_v, max_norm_v
        else:
            failed = skips >= max_skips_f + 1 or norms >= max_norm_f + 1
            max_s, max_n = max_skips_f, max_norm_f
        points = excellents * 2 + norms
        results[ttype] = dict(total=total, skips=skips, norms=norms, excellents=excellents,
                              points=points, max_points=total*2, failed=failed,
                              max_allowed_skips=max_s, max_allowed_norm=max_n)

    rated   = [b for b in bouquets if b["director_rating"] is not None]
    bad_b   = sum(1 for b in rated if b["director_rating"] == 0)
    norm_b  = sum(1 for b in rated if b["director_rating"] == 1)
    good_b  = sum(1 for b in rated if b["director_rating"] == 2)
    total_b = len(rated)
    b_fail  = bad_b >= max_bad_b + 1 or (total_b > 0 and norm_b > total_b // 2)
    results["bouquet_quality"] = dict(total=total_b, bad=bad_b, norms=norm_b,
                                       excellents=good_b, points=good_b*2+norm_b,
                                       max_points=total_b*2, failed=b_fail, max_bad=max_bad_b)

    # KPI опозданий
    late_fine = 0
    late_kpi_fail = False
    # Штраф срабатывает при достижении порога (>= max)
    # Лёгкое: штраф на 4-й раз (max=4), Среднее: на 3-й (max=3), Серьёзное: на 2-й (max=2)
    if lates.get("no_show", 0) >= 1:
        late_kpi_fail = True
        late_fine = 2000
    elif lates.get("heavy", 0) >= max_heavy:
        late_kpi_fail = True
        late_fine = 2000
    elif lates.get("medium", 0) >= max_medium:
        late_kpi_fail = True
        late_fine = 2000
    elif lates.get("light", 0) >= max_light:
        late_kpi_fail = True
        late_fine = 2000

    results["lates"] = dict(
        light=lates.get("light",0), medium=lates.get("medium",0),
        heavy=lates.get("heavy",0), no_show=lates.get("no_show",0),
        failed=late_kpi_fail, fine=late_fine,
        max_light=max_light, max_medium=max_medium, max_heavy=max_heavy,
    )

    num_shifts = len(shifts)
    min_shifts = 10
    kpi_passed = (num_shifts >= min_shifts and
                  not any(v["failed"] for v in results.values()))

    return dict(criteria=results, kpi_passed=kpi_passed,
                num_shifts=num_shifts, year_month=year_month,
                late_fine=late_fine)


def format_kpi_for_florist(florist_name, kpi_data):
    c = kpi_data["criteria"]
    lines = [f"KPI · {florist_name} · {kpi_data['year_month']}",
             f"Смен: {kpi_data['num_shifts']}", ""]

    for ttype, label in [
        ("vitrina_bouquets",    "🌸 Витрина букетов"),
        ("vitrina_compositions","🎋 Витрина композиций"),
        ("flowwow",             "🛍 Flowwow"),
    ]:
        r = c[ttype]
        s = "❌ Не пройден" if r["failed"] else "✅ Пройден"
        pct = f"{r['points']/r['max_points']*100:.0f}%" if r["max_points"] else "—"
        lines += [label,
                  f"  Задач: {r['total']} · Пропусков: {r['skips']}/{r['max_allowed_skips']} · «Норм»: {r['norms']}/{r['max_allowed_norm']}",
                  f"  Баллов: {r['points']}/{r['max_points']} ({pct}) · {s}", ""]

    b = c["bouquet_quality"]
    bs = "❌ Не пройден" if b["failed"] else "✅ Пройден"
    lines += ["🌹 Качество букетов",
              f"  Оценено: {b['total']} · Плохо: {b['bad']}/{b['max_bad']} · Норм: {b['norms']} · Отлично: {b['excellents']}",
              f"  {bs}", ""]

    l = c["lates"]
    ls = "❌ Не пройден" if l["failed"] else "✅ Пройден"
    lines += ["⏰ Опоздания",
              f"  Лёгкие (до 10:15): {l['light']}/{l['max_light']}",
              f"  Средние (до 10:30): {l['medium']}/{l['max_medium']}",
              f"  Серьёзные (до 11:00): {l['heavy']}/{l['max_heavy']}",
              f"  {ls}" + (f" · Штраф: —{l['fine']} ₽" if l["fine"] else ""), ""]

    overall = "✅ KPI ЗАСЧИТАН — ПРЕМИЯ 5 000 ₽" if kpi_data["kpi_passed"] else "❌ KPI НЕ ЗАСЧИТАН"
    if kpi_data.get("late_fine"):
        overall += f"\n❗ Штраф за опоздания: —{kpi_data['late_fine']} ₽"
    if kpi_data["num_shifts"] < 10:
        overall = f"⏳ Ещё не достаточно смен (нужно 10, сейчас {kpi_data['num_shifts']})"
    lines.append(f"{'—'*16}\n{overall}")
    return "\n".join(lines)


def format_kpi_for_director(florist_name, kpi_data):
    return format_kpi_for_florist(florist_name, kpi_data)


def format_sales_report(bouquets, florist_name=None, overhead_pct=25):
    header = f"💰 Продажи · {florist_name or 'Все'}"
    sold   = [b for b in bouquets if b["status"] in ("sold_studio","sold_flowwow","sold_discount")]
    dis    = [b for b in bouquets if b["status"] == "disassembled"]

    studio   = [b for b in sold if b.get("sale_channel") == "studio"]
    flowwow  = [b for b in sold if b.get("sale_channel") == "flowwow"]
    discount = [b for b in sold if b.get("sale_channel") == "discount"]

    def sp(b): return b.get("sold_price") or b.get("price") or 0
    def sc(b): return b.get("cost") or 0

    total_revenue = sum(sp(b) for b in sold)
    total_cost    = sum(sc(b) for b in sold)
    overhead      = int(total_cost * overhead_pct / 100)
    profit        = total_revenue - total_cost - overhead

    lines = [header, "",
             f"В студии:   {len(studio)} шт. → {sum(sp(b) for b in studio):,} ₽".replace(",", " "),
             f"Со скидкой: {len(discount)} шт. → {sum(sp(b) for b in discount):,} ₽".replace(",", " "),
             f"Flowwow:    {len(flowwow)} шт. → {sum(sp(b) for b in flowwow):,} ₽".replace(",", " "),
             f"Разобрано:  {len(dis)} шт.",
             "",
             f"Выручка:      {total_revenue:,} ₽".replace(",", " "),
             f"Себестоимость:{total_cost:,} ₽".replace(",", " "),
             f"Накладные {overhead_pct}%: {overhead:,} ₽".replace(",", " "),
             f"Прибыль:      {profit:,} ₽".replace(",", " "),
             ]
    return "\n".join(lines)
from database import get_month_tasks, get_month_shifts, get_month_bouquets, get_setting, get_month_lates

RATING_LABELS = {0: "👎 Плохо", 1: "👌 Норм", 2: "⭐ Отлично", None: "—"}


def calc_kpi(florist_id, year_month):
    tasks    = get_month_tasks(year_month, florist_id)
    shifts   = get_month_shifts(florist_id, year_month)
    bouquets = get_month_bouquets(year_month, florist_id)
    lates    = get_month_lates(florist_id, year_month)

    max_skips_v  = int(get_setting("kpi_vitrina_max_skips", "4"))
    max_norm_v   = int(get_setting("kpi_vitrina_max_norm", "7"))
    max_skips_f  = int(get_setting("kpi_flowwow_max_skips", "1"))
    max_norm_f   = int(get_setting("kpi_flowwow_max_norm", "4"))
    max_bad_b    = int(get_setting("kpi_bouquet_max_bad", "2"))
    max_light    = int(get_setting("kpi_late_light_max", "5"))
    max_medium   = int(get_setting("kpi_late_medium_max", "3"))
    max_heavy    = int(get_setting("kpi_late_heavy_max", "2"))

    results = {}

    for ttype in ["vitrina_bouquets", "vitrina_compositions", "flowwow"]:
        tt = [t for t in tasks if t["type"] == ttype]
        total     = len(tt)
        skips     = sum(1 for t in tt if t["status"] in ("missed","no") or t["rating"] == 0)
        norms     = sum(1 for t in tt if t["rating"] == 1)
        excellents= sum(1 for t in tt if t["rating"] == 2)
        if ttype in ("vitrina_bouquets","vitrina_compositions"):
            failed = skips >= max_skips_v + 1 or norms >= max_norm_v + 1
            max_s, max_n = max_skips_v, max_norm_v
        else:
            failed = skips >= max_skips_f + 1 or norms >= max_norm_f + 1
            max_s, max_n = max_skips_f, max_norm_f
        points = excellents * 2 + norms
        results[ttype] = dict(total=total, skips=skips, norms=norms, excellents=excellents,
                              points=points, max_points=total*2, failed=failed,
                              max_allowed_skips=max_s, max_allowed_norm=max_n)

    rated   = [b for b in bouquets if b["director_rating"] is not None]
    bad_b   = sum(1 for b in rated if b["director_rating"] == 0)
    norm_b  = sum(1 for b in rated if b["director_rating"] == 1)
    good_b  = sum(1 for b in rated if b["director_rating"] == 2)
    total_b = len(rated)
    b_fail  = bad_b >= max_bad_b + 1 or (total_b > 0 and norm_b > total_b // 2)
    results["bouquet_quality"] = dict(total=total_b, bad=bad_b, norms=norm_b,
                                       excellents=good_b, points=good_b*2+norm_b,
                                       max_points=total_b*2, failed=b_fail, max_bad=max_bad_b)

    # KPI опозданий
    late_fine = 0
    late_kpi_fail = False
    if lates.get("no_show", 0) >= 1:
        late_kpi_fail = True
        late_fine = 2000
    elif lates.get("heavy", 0) >= max_heavy:
        late_kpi_fail = True
        late_fine = 2000
    elif lates.get("medium", 0) >= max_medium:
        late_kpi_fail = True
        late_fine = 2000
    elif lates.get("light", 0) >= max_light:
        late_kpi_fail = True
        late_fine = 2000

    results["lates"] = dict(
        light=lates.get("light",0), medium=lates.get("medium",0),
        heavy=lates.get("heavy",0), no_show=lates.get("no_show",0),
        failed=late_kpi_fail, fine=late_fine,
        max_light=max_light, max_medium=max_medium, max_heavy=max_heavy,
    )

    num_shifts = len(shifts)
    min_shifts = 10
    kpi_passed = (num_shifts >= min_shifts and
                  not any(v["failed"] for v in results.values()))

    return dict(criteria=results, kpi_passed=kpi_passed,
                num_shifts=num_shifts, year_month=year_month,
                late_fine=late_fine)


def format_kpi_for_florist(florist_name, kpi_data):
    c = kpi_data["criteria"]
    lines = [f"KPI · {florist_name} · {kpi_data['year_month']}",
             f"Смен: {kpi_data['num_shifts']}", ""]

    for ttype, label in [
        ("vitrina_bouquets",    "🌸 Витрина букетов"),
        ("vitrina_compositions","🎋 Витрина композиций"),
        ("flowwow",             "🛍 Flowwow"),
    ]:
        r = c[ttype]
        s = "❌ Не пройден" if r["failed"] else "✅ Пройден"
        pct = f"{r['points']/r['max_points']*100:.0f}%" if r["max_points"] else "—"
        lines += [label,
                  f"  Задач: {r['total']} · Пропусков: {r['skips']}/{r['max_allowed_skips']} · «Норм»: {r['norms']}/{r['max_allowed_norm']}",
                  f"  Баллов: {r['points']}/{r['max_points']} ({pct}) · {s}", ""]

    b = c["bouquet_quality"]
    bs = "❌ Не пройден" if b["failed"] else "✅ Пройден"
    lines += ["🌹 Качество букетов",
              f"  Оценено: {b['total']} · Плохо: {b['bad']}/{b['max_bad']} · Норм: {b['norms']} · Отлично: {b['excellents']}",
              f"  {bs}", ""]

    l = c["lates"]
    ls = "❌ Не пройден" if l["failed"] else "✅ Пройден"
    lines += ["⏰ Опоздания",
              f"  Лёгкие (до 10:15): {l['light']}/{l['max_light']}",
              f"  Средние (до 10:30): {l['medium']}/{l['max_medium']}",
              f"  Серьёзные (до 11:00): {l['heavy']}/{l['max_heavy']}",
              f"  {ls}" + (f" · Штраф: —{l['fine']} ₽" if l["fine"] else ""), ""]

    overall = "✅ KPI ЗАСЧИТАН — ПРЕМИЯ 5 000 ₽" if kpi_data["kpi_passed"] else "❌ KPI НЕ ЗАСЧИТАН"
    if kpi_data.get("late_fine"):
        overall += f"\n❗ Штраф за опоздания: —{kpi_data['late_fine']} ₽"
    if kpi_data["num_shifts"] < 10:
        overall = f"⏳ Ещё не достаточно смен (нужно 10, сейчас {kpi_data['num_shifts']})"
    lines.append(f"{'—'*16}\n{overall}")
    return "\n".join(lines)


def format_kpi_for_director(florist_name, kpi_data):
    return format_kpi_for_florist(florist_name, kpi_data)


def format_sales_report(bouquets, florist_name=None, overhead_pct=25):
    header = f"💰 Продажи · {florist_name or 'Все'}"
    sold   = [b for b in bouquets if b["status"] in ("sold_studio","sold_flowwow","sold_discount")]
    dis    = [b for b in bouquets if b["status"] == "disassembled"]

    studio   = [b for b in sold if b.get("sale_channel") == "studio"]
    flowwow  = [b for b in sold if b.get("sale_channel") == "flowwow"]
    discount = [b for b in sold if b.get("sale_channel") == "discount"]

    def sp(b): return b.get("sold_price") or b.get("price") or 0
    def sc(b): return b.get("cost") or 0

    total_revenue = sum(sp(b) for b in sold)
    total_cost    = sum(sc(b) for b in sold)
    overhead      = int(total_cost * overhead_pct / 100)
    profit        = total_revenue - total_cost - overhead

    lines = [header, "",
             f"В студии:   {len(studio)} шт. → {sum(sp(b) for b in studio):,} ₽".replace(",", " "),
             f"Со скидкой: {len(discount)} шт. → {sum(sp(b) for b in discount):,} ₽".replace(",", " "),
             f"Flowwow:    {len(flowwow)} шт. → {sum(sp(b) for b in flowwow):,} ₽".replace(",", " "),
             f"Разобрано:  {len(dis)} шт.",
             "",
             f"Выручка:      {total_revenue:,} ₽".replace(",", " "),
             f"Себестоимость:{total_cost:,} ₽".replace(",", " "),
             f"Накладные {overhead_pct}%: {overhead:,} ₽".replace(",", " "),
             f"Прибыль:      {profit:,} ₽".replace(",", " "),
             ]
    return "\n".join(lines)
from database import get_month_tasks, get_month_shifts, get_month_bouquets, get_setting


RATING_LABELS = {0: "👎 Плохо", 1: "👌 Норм", 2: "⭐ Отлично", None: "—"}
TASK_TYPE_LABELS = {
    "vitrina_bouquets": "Витрина букетов",
    "vitrina_compositions": "Витрина композиций",
    "flowwow": "Flowwow",
}


def calc_kpi(florist_id, year_month):
    tasks = get_month_tasks(year_month, florist_id)
    shifts = get_month_shifts(florist_id, year_month)
    bouquets = get_month_bouquets(year_month, florist_id)

    max_skips_v = int(get_setting("kpi_vitrina_max_skips", "4"))
    max_norm_v = int(get_setting("kpi_vitrina_max_norm", "7"))
    max_skips_f = int(get_setting("kpi_flowwow_max_skips", "1"))
    max_norm_f = int(get_setting("kpi_flowwow_max_norm", "4"))
    max_bad_b = int(get_setting("kpi_bouquet_max_bad", "2"))

    results = {}

    for ttype in ["vitrina_bouquets", "vitrina_compositions", "flowwow"]:
        type_tasks = [t for t in tasks if t["type"] == ttype]
        total = len(type_tasks)
        skips = sum(1 for t in type_tasks if t["status"] in ("missed", "no") or t["rating"] == 0)
        norms = sum(1 for t in type_tasks if t["rating"] == 1)
        excellents = sum(1 for t in type_tasks if t["rating"] == 2)

        if ttype in ("vitrina_bouquets", "vitrina_compositions"):
            failed = skips >= max_skips_v + 1 or norms >= max_norm_v + 1
            max_allowed_skips = max_skips_v
            max_allowed_norm = max_norm_v
        else:
            failed = skips >= max_skips_f + 1 or norms >= max_norm_f + 1
            max_allowed_skips = max_skips_f
            max_allowed_norm = max_norm_f

        points = excellents * 2 + norms * 1
        max_points = total * 2

        results[ttype] = {
            "total": total,
            "skips": skips,
            "norms": norms,
            "excellents": excellents,
            "points": points,
            "max_points": max_points,
            "failed": failed,
            "max_allowed_skips": max_allowed_skips,
            "max_allowed_norm": max_allowed_norm,
        }

    # Bouquet quality
    rated = [b for b in bouquets if b["director_rating"] is not None]
    bad_b = sum(1 for b in rated if b["director_rating"] == 0)
    norm_b = sum(1 for b in rated if b["director_rating"] == 1)
    good_b = sum(1 for b in rated if b["director_rating"] == 2)
    total_b = len(rated)
    bouquet_failed = bad_b >= max_bad_b + 1 or (total_b > 0 and norm_b > total_b // 2)
    b_points = good_b * 2 + norm_b * 1
    b_max = total_b * 2

    results["bouquet_quality"] = {
        "total": total_b,
        "bad": bad_b,
        "norms": norm_b,
        "excellents": good_b,
        "points": b_points,
        "max_points": b_max,
        "failed": bouquet_failed,
        "max_bad": max_bad_b,
    }

    kpi_passed = not any(v["failed"] for v in results.values())
    num_shifts = len(shifts)

    return {
        "criteria": results,
        "kpi_passed": kpi_passed,
        "num_shifts": num_shifts,
        "year_month": year_month,
    }


def format_kpi_for_florist(florist_name, kpi_data):
    c = kpi_data["criteria"]
    lines = [f"📊 Мій KPI · {florist_name} · {kpi_data['year_month']}",
             f"Смен отработано: {kpi_data['num_shifts']}", ""]

    for ttype, label in [
        ("vitrina_bouquets", "🌸 Витрина букетов (14:00)"),
        ("vitrina_compositions", "🎋 Витрина композиций (18:00)"),
        ("flowwow", "🛍 Flowwow"),
    ]:
        r = c[ttype]
        status = "❌ Критерий не пройден" if r["failed"] else "✅ Критерий пройден"
        pct = f"{r['points']/r['max_points']*100:.0f}%" if r["max_points"] else "—"
        lines += [
            label,
            f"  Задач: {r['total']} · Пропусков: {r['skips']}/{r['max_allowed_skips']} · «Норм»: {r['norms']}/{r['max_allowed_norm']}",
            f"  Баллов: {r['points']}/{r['max_points']} ({pct})",
            f"  {status}", "",
        ]

    b = c["bouquet_quality"]
    b_status = "❌ Критерий не пройден" if b["failed"] else "✅ Критерий пройден"
    lines += [
        "🌹 Качество букетов",
        f"  Оценено: {b['total']} · «Плохо»: {b['bad']}/{b['max_bad']} · «Норм»: {b['norms']} · «Отлично»: {b['excellents']}",
        f"  {b_status}", "",
    ]

    overall = "✅ KPI ЗАСЧИТАН — ПРЕМИЯ 5 000 ₽" if kpi_data["kpi_passed"] else "❌ KPI НЕ ЗАСЧИТАН — премии нет"
    lines.append(f"━━━━━━━━\n{overall}")
    return "\n".join(lines)


def format_kpi_for_director(florist_name, kpi_data):
    return format_kpi_for_florist(florist_name, kpi_data)


def format_sales_report(bouquets, florist_name=None):
    header = f"💰 Продажи букетов · {florist_name or 'Все флористы'}"
    
    studio = [b for b in bouquets if b["sale_channel"] == "studio"]
    flowwow = [b for b in bouquets if b["sale_channel"] == "flowwow"]
    disassembled = [b for b in bouquets if b["status"] == "disassembled"]
    
    s_sum = sum(b["price"] for b in studio)
    f_sum = sum(b["price"] for b in flowwow)
    d_sum = sum(b["price"] for b in disassembled)
    total_sum = s_sum + f_sum

    lines = [
        header, "",
        f"✅ В студии: {len(studio)} шт. → {s_sum:,} ₽".replace(",", " "),
        f"🛍 Flowwow: {len(flowwow)} шт. → {f_sum:,} ₽".replace(",", " "),
        f"💵 Итого продано: {len(studio)+len(flowwow)} шт. → {total_sum:,} ₽".replace(",", " "),
        f"🗑 Разобрано: {len(disassembled)} шт. → потери {d_sum:,} ₽".replace(",", " "),
    ]
    return "\n".join(lines)
