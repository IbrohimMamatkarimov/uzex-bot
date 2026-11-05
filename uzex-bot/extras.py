"""Chart (PNG), Excel (XLSX) and source text built from the SQL queries the agent used."""
import io, re, datetime, decimal
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
import agent

TIME_COLS = {"year", "month", "quarter", "deal_date", "date", "yil", "год", "oy"}

def _num(v):
    return isinstance(v, (int, float, decimal.Decimal)) and not isinstance(v, bool)

def _human(v, lang):
    sfx = ("трлн", "млрд", "млн") if lang == "ru" else ("trln", "mlrd", "mln")
    a = abs(v)
    if a >= 1e12: return f"{v/1e12:.2f} {sfx[0]}"
    if a >= 1e9:  return f"{v/1e9:.2f} {sfx[1]}"
    if a >= 1e6:  return f"{v/1e6:.2f} {sfx[2]}"
    if a >= 1000: return f"{v:,.0f}".replace(",", " ")
    return f"{v:.2f}".rstrip("0").rstrip(".")

def pick_chartable(sqls):
    """Latest query that returns 2..40 rows and at least one numeric column."""
    for q in reversed(sqls):
        try:
            cols, rows = agent.exec_rows(q, 60)
        except Exception:
            continue
        if not (2 <= len(rows) <= 40):
            continue
        num_idx = [i for i in range(len(cols)) if all(_num(r[i]) or r[i] is None for r in rows)
                   and any(r[i] is not None for r in rows)]
        if not num_idx:
            continue
        label_idx = next((i for i in range(len(cols)) if i not in num_idx), 0)
        if label_idx in num_idx and len(num_idx) < 2:
            continue
        val_idx = next((i for i in num_idx if i != label_idx), None)
        if val_idx is None:
            continue
        return cols, rows, label_idx, val_idx
    return None

def can_chart(sqls) -> bool:
    return pick_chartable(sqls) is not None

def build_chart(sqls, title, lang="uz"):
    pk = pick_chartable(sqls)
    if not pk:
        return None
    cols, rows, li, vi = pk
    rows = [r for r in rows if r[vi] is not None][:12]
    labels = [str(r[li])[:34] for r in rows]
    vals = [float(r[vi]) for r in rows]
    is_time = cols[li].lower() in TIME_COLS
    fig, ax = plt.subplots(figsize=(8, max(3.6, 0.55 * len(rows) + 1.6)) if not is_time else (8, 4.4), dpi=130)
    color = "#2563eb"
    if is_time:
        bars = ax.bar(labels, vals, color=color)
        ax.set_ylim(0, max(vals) * 1.15)
        for b, v in zip(bars, vals):
            ax.annotate(_human(v, lang), (b.get_x() + b.get_width() / 2, v), ha="center", va="bottom", fontsize=7)
    else:
        y = range(len(vals))
        bars = ax.barh(list(y), vals, color=color)
        ax.set_yticks(list(y)); ax.set_yticklabels(labels, fontsize=8); ax.invert_yaxis()
        ax.set_xlim(0, max(vals) * 1.2)
        for b, v in zip(bars, vals):
            ax.annotate(_human(v, lang), (v, b.get_y() + b.get_height() / 2), xytext=(4, 0),
                        textcoords="offset points", va="center", fontsize=7)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: _human(v, lang))) if not is_time else \
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: _human(v, lang)))
    ax.set_title(title[:70], fontsize=10)
    ax.set_xlabel(cols[vi] if not is_time else "", fontsize=8)
    ax.tick_params(axis="x", labelsize=7)
    for sp in ("top", "right"): ax.spines[sp].set_visible(False)
    fig.text(0.99, 0.01, "UZEX reyestri · SQL bo‘yicha hisob", ha="right", fontsize=6, color="#888")
    fig.tight_layout()
    buf = io.BytesIO(); fig.savefig(buf, format="png"); plt.close(fig)
    buf.seek(0)
    return buf

def build_excel(sqls):
    wb = Workbook(); wb.remove(wb.active)
    n = 0
    for q in sqls[:6]:
        try:
            cols, rows = agent.exec_rows(q, 5000)
        except Exception:
            continue
        n += 1
        ws = wb.create_sheet(f"Natija {n}")
        ws.append(cols)
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="2563EB")
        for r in rows:
            ws.append([float(v) if isinstance(v, decimal.Decimal) else v for v in r])
        for i, c in enumerate(cols, 1):
            width = max([len(str(c))] + [len(str(r[i - 1])) for r in rows[:200]]) + 2
            ws.column_dimensions[get_column_letter(i)].width = min(width, 50)
        ws.freeze_panes = "A2"
    ws = wb.create_sheet("SQL")
    ws.column_dimensions["A"].width = 120
    for q in sqls:
        ws.append([q])
    buf = io.BytesIO(); wb.save(buf); buf.seek(0)
    return buf if n else None

def source_text(sqls, lang="uz"):
    head = "Ответ основан на этих SQL-запросах к реестру:" if lang == "ru" else "Javob quyidagi SQL so‘rovlarga asoslangan:"
    body = "\n\n".join(f"{i}) {q}" for i, q in enumerate(sqls[:5], 1))
    return f"{head}\n\n{body}"[:3900]
