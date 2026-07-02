from database import get_month_tasks, get_month_shifts, get_month_bouquets, get_setting, get_month_lates, get_month_custom_tasks

RATING_LABELS = {0: "👎 Плохо", 1: "👌 Норм", 2: "⭐ Отлично", None: "—"}

MIN_VITRINA = 6  # минимум букетов на витрине


def calc_kpi(florist_id, year_month):
    tasks    = get_month_tasks(year_month, florist_id)
    shifts   = get_month_shifts(florist_id, year_month)
    bouquets = get_month_bouquets(year_month, florist_id)
    lates    = get_month_lates(florist_id, year_month)

    max_light  = int(get_setting("kpi_late_light_max",  "4"))
    max_medium = int(get_setting("kpi_late_medium_max", "3"))
    max_heavy  = int(get_setting("kpi_late_heavy_max",  "2"))

    results = {}

    # ── Витрина букетов / Витрина композиций / Flowwow ──────────
    for ttype in ["vitrina_bouquets", "vitrina_compositions", "flowwow"]:
        tt         = [t for t in tasks if t["type"] == ttype]
        total      = len(tt)
        skips      = sum(1 for t in tt if t["status"] in ("missed", "no"))
        excellent  = sum(1 for t in tt if t["rating"] == 2)
        norm       = sum(1 for t in tt if t["rating"] == 1)
        bad        = sum(1 for t in tt if t["rating"] == 0)
        rated      = excellent + norm + bad

        # Пропуски: ≤3 допустимо, 4+ = не пройден
        skip_fail  = skips >= 4

        # Уровень по оценкам (только если есть оценки)
        if rated > 0:
            pct_bad  = bad / rated * 100
            pct_exc  = excellent / rated * 100
            if pct_bad >= 30:
                quality = "bad"     # KPI не пройден
            elif pct_exc >= 80:
                quality = "excellent"
            else:
                quality = "norm"
        else:
            quality = "norm"

        failed = skip_fail or quality == "bad"
        results[ttype] = dict(
            total=total, skips=skips, excellent=excellent, norm=norm, bad=bad,
            rated=rated, skip_fail=skip_fail, quality=quality, failed=failed
        )

    # ── Качество букетов ─────────────────────────────────────────
    rated_b    = [b for b in bouquets if b["director_rating"] is not None]
    total_b    = len(rated_b)
    bad_b      = sum(1 for b in rated_b if b["director_rating"] == 0)
    norm_b     = sum(1 for b in rated_b if b["director_rating"] == 1)
    good_b     = sum(1 for b in rated_b if b["director_rating"] == 2)

    if total_b > 0:
        pct_bad_b = bad_b / total_b * 100
        pct_exc_b = good_b / total_b * 100
        if pct_bad_b >= 30:
            b_quality = "bad"
        elif pct_exc_b >= 80:
            b_quality = "excellent"
        else:
            b_quality = "norm"
    else:
        b_quality = "norm"

    b_failed = b_quality == "bad"
    results["bouquet_quality"] = dict(
        total=total_b, bad=bad_b, norm=norm_b, excellent=good_b,
        quality=b_quality, failed=b_failed
    )

    # ── Опоздания ────────────────────────────────────────────────
    late_fine     = 0
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
        light=lates.get("light", 0), medium=lates.get("medium", 0),
        heavy=lates.get("heavy", 0), no_show=lates.get("no_show", 0),
        failed=late_kpi_fail, fine=late_fine,
        max_light=max_light, max_medium=max_medium, max_heavy=max_heavy,
    )

    # ── Обязательные задачи (день в день) ──────────────────────────
    custom_tasks = get_month_custom_tasks(year_month, florist_id)
    missed_mandatory = sum(1 for t in custom_tasks if t.get("status") == "missed_mandatory")
    results["mandatory_tasks"] = dict(
        missed=missed_mandatory, failed=missed_mandatory > 0
    )

    num_shifts = len(shifts)
    kpi_passed = not any(v["failed"] for v in results.values())

    return dict(
        criteria=results, kpi_passed=kpi_passed,
        num_shifts=num_shifts, year_month=year_month,
        late_fine=late_fine
    )


def _quality_emoji(q):
    return {"excellent": "⭐", "norm": "👌", "bad": "👎"}.get(q, "—")


def format_kpi_for_florist(florist_name, kpi_data):
    c     = kpi_data["criteria"]
    lines = [
        f"📊 Мой KPI · {florist_name} · {kpi_data['year_month']}",
        f"Смен отработано: {kpi_data['num_shifts']}",
        ""
    ]

    for ttype, label in [
        ("vitrina_bouquets",    "🌸 Витрина букетов"),
        ("vitrina_compositions","🎋 Витрина композиций"),
        ("flowwow",             "🛍 Flowwow"),
    ]:
        r   = c[ttype]
        st  = "❌ Не пройден" if r["failed"] else "✅ Пройден"
        qe  = _quality_emoji(r["quality"])
        pct = f"{r['excellent']/r['rated']*100:.0f}%" if r["rated"] else "—"
        lines += [
            label,
            f"  Отчётов: {r['total']} · Пропусков: {r['skips']}/3",
            f"  Оценки: {r['excellent']} отл / {r['norm']} норм / {r['bad']} плохо {qe}",
            f"  {st}",
            ""
        ]

    b  = c["bouquet_quality"]
    bs = "❌ Не пройден" if b["failed"] else "✅ Пройден"
    qe = _quality_emoji(b["quality"])
    lines += [
        "🌹 Качество букетов",
        f"  Оценено: {b['total']} — {b['excellent']} отл / {b['norm']} норм / {b['bad']} плохо {qe}",
        f"  {bs}",
        ""
    ]

    l  = c["lates"]
    ls = "❌ Не пройден" if l["failed"] else "✅ Пройден"
    lines += [
        "⏰ Опоздания",
        f"  Лёгкие (до 10:15): {l['light']}/{l['max_light']-1} допустимых",
        f"  Средние (до 10:30): {l['medium']}/{l['max_medium']-1} допустимых",
        f"  Серьёзные (до 11:00): {l['heavy']}/{l['max_heavy']-1} допустимых",
        f"  {ls}" + (f" · Штраф: —{l['fine']} ₽" if l["fine"] else ""),
        ""
    ]

    overall = "✅ KPI ЗАСЧИТАН" if kpi_data["kpi_passed"] else "❌ KPI НЕ ЗАСЧИТАН"
    m = c.get("mandatory_tasks")
    if m and m["missed"]:
        lines.append(f"🔴 Обязательные задачи: просрочено {m['missed']} — минус в KPI")
    if kpi_data.get("late_fine"):
        overall += f"\n❗ Штраф за опоздания: —{kpi_data['late_fine']} ₽"
    lines.append(f"{'—'*16}\n{overall}")
    return "\n".join(lines)


def format_kpi_for_director(florist_name, kpi_data):
    return format_kpi_for_florist(florist_name, kpi_data)


def format_sales_report(bouquets, florist_name=None, overhead_pct=25):
    header   = f"💰 Продажи · {florist_name or 'Все'}"
    sold     = [b for b in bouquets if b["status"] in ("sold_studio","sold_flowwow","sold_discount")]
    dis      = [b for b in bouquets if b["status"] == "disassembled"]
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
             f"Разобрано:  {len(dis)} шт.", "",
             f"Выручка:       {total_revenue:,} ₽".replace(",", " "),
             f"Себестоимость: {total_cost:,} ₽".replace(",", " "),
             f"Накладные {overhead_pct}%: {overhead:,} ₽".replace(",", " "),
             f"Прибыль:       {profit:,} ₽".replace(",", " ")]
    return "\n".join(lines)
