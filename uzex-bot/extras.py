"""Excel (XLSX), chart (PNG) and source text, all built from the SQL queries the agent used.

Excel file layout (clear for the user):
  sheet 1  "Hisobot" / "Сводка"   -> the question, answer, source, and result-sheet summary
  sheet 2+ "Natija 1", ...        -> the data table of each SQL query (nice headers, number formats, filter)
  last     "SQL"                  -> the exact SQL queries, so everything can be re-checked
"""
import io, re, math, textwrap, datetime, decimal
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
import agent

EXCEL_ROW_LIMIT = 5000
MAX_SHEETS = 6
TIME_COLS = {"year", "month", "quarter", "deal_date", "date", "yil", "год", "oy", "month_num", "period"}
NO_FORMAT_HINTS = ("inn", "id", "code", "hs", "year", "yil", "month", "quarter", "phone", "rank")

# column name -> (Uzbek header, Russian header). Unknown names are kept as they are.
LABELS = {
    "commodity": ("Tovar", "Товар"), "commodity_uz": ("Tovar (o‘zbekcha)", "Товар (узб.)"),
    "category": ("Kategoriya", "Категория"), "product_group": ("Mahsulot guruhi", "Группа товаров"),
    "industry": ("Tarmoq", "Отрасль"), "region": ("Hudud", "Регион"), "region_ru": ("Hudud (ruscha)", "Регион (рус.)"),
    "year": ("Yil", "Год"), "month": ("Oy", "Месяц"), "quarter": ("Chorak", "Квартал"),
    "deal_date": ("Bitim sanasi", "Дата сделки"), "status": ("Holat", "Статус"), "unit": ("O‘lchov birligi", "Ед. изм."),
    "deals": ("Bitimlar soni", "Количество сделок"), "deal_count": ("Bitimlar soni", "Количество сделок"),
    "n_deals": ("Bitimlar soni", "Количество сделок"), "num_deals": ("Bitimlar soni", "Количество сделок"),
    "count": ("Soni", "Количество"), "cnt": ("Soni", "Количество"),
    "amount_uzs": ("Summa (so‘m)", "Сумма (сум)"), "total_uzs": ("Summa (so‘m)", "Сумма (сум)"),
    "turnover": ("Aylanma (so‘m)", "Оборот (сум)"), "turnover_uzs": ("Aylanma (so‘m)", "Оборот (сум)"),
    "amount_usd": ("Summa (USD)", "Сумма (USD)"), "total_usd": ("Summa (USD)", "Сумма (USD)"),
    "volume_tonnes": ("Hajm (tonna)", "Объём (тонн)"), "volume_units": ("Hajm (birlik)", "Объём (ед.)"),
    "unit_price_uzs": ("Narx (so‘m / birlik)", "Цена (сум / ед.)"), "avg_price": ("O‘rtacha narx", "Средняя цена"),
    "avg_price_uzs": ("O‘rtacha narx (so‘m)", "Средняя цена (сум)"),
    "seller_name": ("Sotuvchi", "Продавец"), "buyer_name": ("Xaridor", "Покупатель"),
    "seller_inn": ("Sotuvchi STIR", "ИНН продавца"), "buyer_inn": ("Xaridor STIR", "ИНН покупателя"),
    "seller_broker_name": ("Sotuvchi brokeri", "Брокер продавца"), "buyer_broker_name": ("Xaridor brokeri", "Брокер покупателя"),
    "broker_name": ("Broker", "Брокер"), "pct": ("Ulush, %", "Доля, %"), "share_pct": ("Ulush, %", "Доля, %"),
    "contract_type": ("Shartnoma turi", "Тип контракта"), "contract_form": ("Shartnoma shakli", "Форма контракта"),
    "auction_type": ("Auksion turi", "Тип аукциона"),
}

def _label(col, lang):
    hit = LABELS.get(str(col).lower())
    return (hit[1] if lang == "ru" else hit[0]) if hit else str(col)

def _num(v):
    return isinstance(v, (int, float, decimal.Decimal)) and not isinstance(v, bool)

def _human(v, lang):
    sfx = ("трлн", "млрд", "млн") if lang == "ru" else ("trln", "mlrd", "mln")
    a = abs(v)
    if a >= 1e12: return f"{v/1e12:.2f} {sfx[0]}"
    if a >= 1e9:  return f"{v/1e9:.2f} {sfx[1]}"
    if a >= 1e6:  return f"{v/1e6:.2f} {sfx[2]}"
    if a >= 1000: return f"{v:,.0f}".replace(",", " ")
    return f"{v:.2f}".rstrip("0").rstrip(".") or "0"

def _clean(v):
    """Turn any database value into something Excel can always store (never raises)."""
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, decimal.Decimal):
        v = float(v)
    if isinstance(v, float):
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(v, int):
        return v if abs(v) < 10**15 else str(v)
    if isinstance(v, datetime.datetime):
        return v.replace(tzinfo=None)
    if isinstance(v, (datetime.date, datetime.time, datetime.timedelta)):
        return v
    return ILLEGAL_CHARACTERS_RE.sub("", str(v))[:32000]

# ------------------------------------------------------------------ chart
def pick_chartable(sqls):
    """Latest query that returns 2..40 rows, one label column and at least one numeric column."""
    for q in reversed(sqls):
        cached = agent.cached_rows(q)
        if cached is None:
            continue
        cols, rows = cached
        if not (2 <= len(rows) <= 40):
            continue
        num_idx = [i for i in range(len(cols)) if all(_num(r[i]) or r[i] is None for r in rows)
                   and any(r[i] is not None for r in rows)]
        if not num_idx:
            continue
        label_idx = next((i for i in range(len(cols)) if i not in num_idx), 0)
        val_idx = next((i for i in num_idx if i != label_idx), None)
        if val_idx is None:
            continue
        return cols, rows, label_idx, val_idx
    return None

def can_chart(sqls) -> bool:
    return pick_chartable(sqls) is not None

def build_chart(sqls, title, lang="uz"):
    """Returns a PNG BytesIO, or None when the data is not suitable for a chart."""
    pk = pick_chartable(sqls)
    if not pk:
        return None
    cols, rows, li, vi = pk
    rows = [r for r in rows if r[vi] is not None]
    if len(rows) < 2:
        return None
    is_time = str(cols[li]).lower() in TIME_COLS
    if is_time:
        try:
            rows.sort(key=lambda r: r[li])
        except TypeError:
            pass
    else:
        rows = rows[:12]
    labels = [(r[li].strftime("%d.%m.%Y") if isinstance(r[li], datetime.date) else str(r[li]))[:34] for r in rows]
    vals = [float(r[vi]) for r in rows]
    lo, hi = min(0.0, min(vals)), max(0.0, max(vals))
    pad = (hi - lo) * 0.18 or 1.0
    lims = (lo - (pad if lo < 0 else 0), hi + (pad if hi > 0 else 0))
    color = "#2563eb"
    if is_time:
        fig, ax = plt.subplots(figsize=(max(8, 0.35 * len(rows) + 4), 4.6), dpi=130)
        bars = ax.bar(labels, vals, color=color)
        ax.set_ylim(*lims)
        for b, v in zip(bars, vals):
            ax.annotate(_human(v, lang), (b.get_x() + b.get_width() / 2, v), ha="center",
                        va="bottom" if v >= 0 else "top", fontsize=7)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _human(v, lang)))
        if len(rows) > 8:
            plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
        ax.set_ylabel(_label(cols[vi], lang), fontsize=8)
    else:
        fig, ax = plt.subplots(figsize=(8, max(3.6, 0.55 * len(rows) + 1.8)), dpi=130)
        y = list(range(len(vals)))
        bars = ax.barh(y, vals, color=color)
        ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=8); ax.invert_yaxis()
        ax.set_xlim(*lims)
        for b, v in zip(bars, vals):
            ax.annotate(_human(v, lang), (v, b.get_y() + b.get_height() / 2), xytext=(4 if v >= 0 else -4, 0),
                        textcoords="offset points", va="center", ha="left" if v >= 0 else "right", fontsize=7)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: _human(v, lang)))
        ax.set_xlabel(_label(cols[vi], lang), fontsize=8)
    ax.set_title("\n".join(textwrap.wrap(title, 70)[:2]), fontsize=10)
    ax.tick_params(axis="x", labelsize=7)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    fig.text(0.99, 0.01, "Реестр UZEX · расчёт по SQL" if lang == "ru" else "UZEX reyestri · SQL bo‘yicha hisob",
             ha="right", fontsize=6, color="#888")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf

# ------------------------------------------------------------------ excel
_HEAD_FONT = Font(bold=True, color="FFFFFF")
_HEAD_FILL = PatternFill("solid", fgColor="2563EB")
_ALT_FILL = PatternFill("solid", fgColor="F3F7FC")
_THIN = Side(style="thin", color="D1D5DB")

def _write_sheet(ws, cols, rows, lang):
    for j, c in enumerate(cols, 1):
        cell = ws.cell(row=1, column=j, value=_label(c, lang))
        cell.font, cell.fill = _HEAD_FONT, _HEAD_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 32
    for i, r in enumerate(rows, 2):
        for j, v in enumerate(r, 1):
            v = _clean(v)
            cell = ws.cell(row=i, column=j, value=v)
            if i % 2 == 0:
                cell.fill = _ALT_FILL
            cell.border = Border(bottom=_THIN)
            cell.alignment = Alignment(vertical="top", wrap_text=isinstance(v, str) and len(v) > 36)
            if isinstance(v, str) and v[:1] in ("=", "+", "@"):
                cell.data_type = "s"              # never let text turn into an Excel formula
    for j, c in enumerate(cols, 1):
        col_vals = [_clean(r[j - 1]) for r in rows[:200]]
        sample = [v for v in col_vals if v is not None]
        name = str(c).lower()
        fmt = None
        if sample and all(isinstance(v, datetime.datetime) for v in sample):
            fmt = "DD.MM.YYYY HH:MM"
        elif sample and all(isinstance(v, datetime.date) and not isinstance(v, datetime.datetime) for v in sample):
            fmt = "DD.MM.YYYY"
        elif sample and any(h in name for h in NO_FORMAT_HINTS):
            fmt = None
        elif sample and any(isinstance(v, float) for v in sample) and all(_num(v) for v in sample):
            fmt = "# ##0.00"
        elif sample and all(isinstance(v, int) and not isinstance(v, bool) for v in sample) and max(abs(v) for v in sample) >= 10000:
            fmt = "# ##0"
        if fmt:
            for i in range(2, len(rows) + 2):
                ws.cell(row=i, column=j).number_format = fmt
        width = max([len(_label(c, lang))] + [len(str(v)) for v in sample[:200]] + [8]) + 3
        ws.column_dimensions[get_column_letter(j)].width = min(width, 45)
    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{len(rows) + 1}"

def build_excel(sqls, question="", answer="", lang="uz"):
    """Returns an XLSX BytesIO, or None if none of the queries can be run."""
    ru = lang == "ru"
    wb = Workbook()
    info = wb.active
    info.title = "Сводка" if ru else "Hisobot"
    wb.properties.title = "UZEX deal registry report"
    wb.properties.subject = question[:250]
    wb.properties.creator = "UZEX AI Assistant"
    results = []                                   # (sheet name, n rows, truncated)
    seen = set()
    n = 0
    for q in sqls:
        if q in seen:
            continue
        seen.add(q)
        if n >= MAX_SHEETS:
            break
        try:
            cols, rows = agent.exec_rows(q, EXCEL_ROW_LIMIT + 1)
        except Exception:
            continue
        truncated = len(rows) > EXCEL_ROW_LIMIT
        rows = rows[:EXCEL_ROW_LIMIT]
        n += 1
        name = f"{'Результат' if ru else 'Natija'} {n}"
        _write_sheet(wb.create_sheet(name), cols, rows, lang)
        results.append((name, len(rows), truncated))
    if not n:
        return None

    # --- readable overview sheet
    info.sheet_view.showGridLines = False
    info.merge_cells("A1:B1")
    title = info["A1"]
    title.value = "UZEX — ОТЧЁТ ПО СДЕЛКАМ" if ru else "UZEX — BITIMLAR HISOBOTI"
    title.font = Font(bold=True, size=18, color="FFFFFF")
    title.fill = PatternFill("solid", fgColor="17365D")
    title.alignment = Alignment(vertical="center")
    info.row_dimensions[1].height = 38
    info.merge_cells("A2:B2")
    subtitle = info["A2"]
    subtitle.value = ("Данные из реестра UZEX. Ниже — сводка, результаты и SQL-запросы." if ru else
                      "UZEX reyestridan olingan ma’lumotlar. Quyida qisqacha xulosa, natijalar va SQL so‘rovlari berilgan.")
    subtitle.font = Font(italic=True, color="475569", size=10)
    subtitle.alignment = Alignment(wrap_text=True, vertical="center")
    info.row_dimensions[2].height = 32
    lines = [
        ("Вопрос" if ru else "Savol", question),
        ("Ответ бота" if ru else "Bot javobi", answer),
        ("Создано" if ru else "Yaratilgan vaqt", datetime.datetime.now().strftime("%d.%m.%Y %H:%M")),
        ("Источник" if ru else "Manba", "Реестр сделок UZEX, 500 000 сделок (2022–2026)" if ru
         else "UZEX bitimlar reyestri, 500 000 bitim (2022–2026)"),
    ]
    for name, cnt, trunc in results:
        txt = f"{cnt} " + ("строк" if ru else "qator")
        if trunc:
            txt += (f" (показаны первые {EXCEL_ROW_LIMIT})" if ru else f" (dastlabki {EXCEL_ROW_LIMIT} tasi ko‘rsatilgan)")
        lines.append((name, txt))
    lines.append(("SQL", "Лист «SQL» — точные запросы" if ru else "«SQL» varag‘i — aniq so‘rovlar"))
    info.column_dimensions["A"].width = 25
    info.column_dimensions["B"].width = 92
    info.row_dimensions[3].height = 8
    for i, (k, v) in enumerate(lines, 4):
        a = info.cell(row=i, column=1, value=k)
        a.font = Font(bold=True, color="17365D"); a.fill = PatternFill("solid", fgColor="DBEAFE")
        a.alignment = Alignment(vertical="top")
        b = info.cell(row=i, column=2, value=_clean(v) or "")
        b.alignment = Alignment(wrap_text=True, vertical="top")
        a.border = Border(bottom=_THIN)
        b.border = Border(bottom=_THIN)
        estimated_lines = max(str(v).count("\n") + 1, (len(str(v)) + 89) // 90)
        info.row_dimensions[i].height = min(360, max(24, 18 * estimated_lines))
        if isinstance(b.value, str) and b.value[:1] in ("=", "+", "@"):
            b.data_type = "s"
    info.freeze_panes = "A4"
    info.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    info.page_setup.fitToWidth = 1
    info.page_setup.fitToHeight = 0
    info.page_setup.orientation = "landscape"

    # --- SQL sheet
    ws = wb.create_sheet("SQL")
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 120
    for j, value in enumerate(("№", "SQL-запрос" if ru else "SQL so‘rovi"), 1):
        cell = ws.cell(row=1, column=j, value=value)
        cell.font, cell.fill = _HEAD_FONT, _HEAD_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 26
    for i, q in enumerate(sqls, 2):
        ws.cell(row=i, column=1, value=i - 1).font = Font(bold=True, color="17365D")
        c = ws.cell(row=i, column=2, value=_clean(q))
        c.alignment = Alignment(wrap_text=True, vertical="top")
        c.border = Border(bottom=_THIN)
        if i % 2 == 0:
            c.fill = _ALT_FILL
        ws.row_dimensions[i].height = min(90, max(30, 15 * (str(q).count("\n") + 1)))
        c.data_type = "s"
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf

# ------------------------------------------------------------------ source text
def source_text(sqls, lang="uz"):
    head = "Ответ основан на этих SQL-запросах к реестру:" if lang == "ru" else "Javob quyidagi SQL so‘rovlarga asoslangan:"
    body = "\n\n".join(f"{i}) {q}" for i, q in enumerate(sqls[:5], 1))
    return f"{head}\n\n{body}"[:3900]

