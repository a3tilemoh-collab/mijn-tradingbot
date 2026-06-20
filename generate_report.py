# ============================================================
#  UniversalBot - generate_report.py
#  Genereert een interactief HTML rapport na een backtest
# ============================================================
#
#  Gebruik:
#    python generate_report.py --symbol EURUSD --days 365
#    python generate_report.py --all --days 365
#
# ============================================================

import argparse
import json
import os
import sys
from datetime import datetime

# Backtest engine importeren
from backtest import (
    load_data_mt5, load_data_csv,
    run_backtest, calc_statistics,
)
from config import SYMBOLS, BACKTEST


# ─────────────────────────────────────────────────────────────────────────────
#  HTML GENEREREN
# ─────────────────────────────────────────────────────────────────────────────

def generate_html(stats: dict, result) -> str:
    """Bouwt het volledige HTML rapport op als string."""

    # Equity curve data voor chart
    eq_df      = result.df_equity
    eq_labels  = [str(r["time"])[:16] for _, r in eq_df.iterrows()] if not eq_df.empty else []
    eq_values  = [round(r["equity"], 2) for _, r in eq_df.iterrows()] if not eq_df.empty else []

    # Downscale voor performance (max 500 punten)
    if len(eq_labels) > 500:
        step      = len(eq_labels) // 500
        eq_labels = eq_labels[::step]
        eq_values = eq_values[::step]

    # Trades per maand (bar chart)
    trades_df = result.df_trades
    monthly_pnl = {}
    if not trades_df.empty:
        trades_df["month"] = trades_df["exit_time"].astype(str).str[:7]
        grouped = trades_df.groupby("month")["pnl"].sum().round(2)
        monthly_pnl = grouped.to_dict()

    monthly_labels = json.dumps(list(monthly_pnl.keys()))
    monthly_values = json.dumps(list(monthly_pnl.values()))

    # Kleurcodering per metric
    def pf_color(v):
        return "#22c55e" if v >= 2.0 else ("#f59e0b" if v >= 1.5 else "#ef4444")

    def wr_color(v):
        return "#22c55e" if v >= 55 else ("#f59e0b" if v >= 45 else "#ef4444")

    def dd_color(v):
        return "#22c55e" if v > -10 else ("#f59e0b" if v > -20 else "#ef4444")

    def sh_color(v):
        return "#22c55e" if v >= 1.5 else ("#f59e0b" if v >= 1.0 else "#ef4444")

    pnl_color  = "#22c55e" if stats.get("total_pnl_usd", 0) >= 0 else "#ef4444"
    ret_color  = "#22c55e" if stats.get("total_return_pct", 0) >= 0 else "#ef4444"

    # Beoordeling
    pf = stats.get("profit_factor", 0)
    wr = stats.get("win_rate_pct", 0)
    dd = stats.get("max_drawdown_pct", 0)
    sh = stats.get("sharpe_ratio", 0)

    if pf >= 2.0 and wr >= 50 and dd > -20 and sh > 1:
        verdict_icon  = "🟢"
        verdict_text  = "GOED"
        verdict_desc  = "Klaar voor verdere validatie op out-of-sample data."
        verdict_color = "#22c55e"
    elif pf >= 1.5 and wr >= 45 and dd > -30:
        verdict_icon  = "🟡"
        verdict_text  = "GEMIDDELD"
        verdict_desc  = "Strategie heeft potentie — optimaliseer parameters."
        verdict_color = "#f59e0b"
    else:
        verdict_icon  = "🔴"
        verdict_text  = "ZWAK"
        verdict_desc  = "Overweeg andere parameters of strategie."
        verdict_color = "#ef4444"

    eq_json     = json.dumps(eq_values)
    eq_lbl_json = json.dumps(eq_labels)

    symbol  = stats.get("symbol", "?")
    period  = stats.get("period", "?")
    gen_ts  = datetime.now().strftime("%d-%m-%Y %H:%M")

    html = f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>UniversalBot — Backtest {symbol}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=Inter:wght@300;400;500;600&display=swap');

  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  :root {{
    --bg:        #0a0d12;
    --surface:   #111620;
    --border:    #1e2535;
    --text:      #c9d1e0;
    --muted:     #4a5568;
    --accent:    #3b82f6;
    --accent2:   #06b6d4;
    --green:     #22c55e;
    --red:       #ef4444;
    --yellow:    #f59e0b;
    --font-mono: 'IBM Plex Mono', monospace;
    --font-body: 'Inter', sans-serif;
  }}

  html {{ scroll-behavior: smooth; }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--font-body);
    font-size: 14px;
    line-height: 1.6;
    min-height: 100vh;
  }}

  /* ── Header ── */
  header {{
    border-bottom: 1px solid var(--border);
    padding: 20px 32px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: var(--surface);
    position: sticky;
    top: 0;
    z-index: 100;
  }}
  .logo {{
    font-family: var(--font-mono);
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.1em;
    color: var(--accent);
    text-transform: uppercase;
  }}
  .logo span {{ color: var(--text); opacity: 0.5; }}
  .header-meta {{
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--muted);
    text-align: right;
  }}
  .header-meta strong {{ color: var(--text); }}

  /* ── Layout ── */
  main {{
    max-width: 1200px;
    margin: 0 auto;
    padding: 32px 24px 64px;
  }}

  /* ── Hero ── */
  .hero {{
    display: grid;
    grid-template-columns: 1fr auto;
    align-items: end;
    gap: 24px;
    margin-bottom: 40px;
    padding-bottom: 32px;
    border-bottom: 1px solid var(--border);
  }}
  .hero-symbol {{
    font-family: var(--font-mono);
    font-size: 52px;
    font-weight: 600;
    line-height: 1;
    letter-spacing: -0.02em;
    color: #fff;
  }}
  .hero-symbol span {{
    font-size: 16px;
    font-weight: 400;
    color: var(--muted);
    display: block;
    margin-bottom: 6px;
    letter-spacing: 0.15em;
    text-transform: uppercase;
  }}
  .hero-period {{
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--muted);
    margin-top: 8px;
  }}
  .verdict-badge {{
    padding: 10px 20px;
    border-radius: 6px;
    font-family: var(--font-mono);
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.08em;
    border: 1px solid;
    white-space: nowrap;
  }}

  /* ── KPI Grid ── */
  .kpi-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 12px;
    margin-bottom: 32px;
  }}
  .kpi {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px 18px;
    position: relative;
    overflow: hidden;
  }}
  .kpi::before {{
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: var(--kpi-accent, var(--border));
  }}
  .kpi-label {{
    font-size: 10px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--muted);
    font-family: var(--font-mono);
    margin-bottom: 6px;
  }}
  .kpi-value {{
    font-family: var(--font-mono);
    font-size: 22px;
    font-weight: 600;
    line-height: 1.1;
    color: var(--kpi-color, #fff);
  }}
  .kpi-sub {{
    font-size: 11px;
    color: var(--muted);
    margin-top: 3px;
    font-family: var(--font-mono);
  }}

  /* ── Charts ── */
  .chart-section {{
    margin-bottom: 28px;
  }}
  .section-title {{
    font-family: var(--font-mono);
    font-size: 11px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 14px;
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .section-title::after {{
    content: '';
    flex: 1;
    height: 1px;
    background: var(--border);
  }}
  .chart-wrap {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px 20px 16px;
  }}
  .chart-row {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin-bottom: 28px;
  }}

  /* ── Stats table ── */
  .stats-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin-bottom: 28px;
  }}
  .stats-block {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 20px;
  }}
  .stats-block h3 {{
    font-family: var(--font-mono);
    font-size: 10px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 16px;
  }}
  .stat-row {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 7px 0;
    border-bottom: 1px solid var(--border);
  }}
  .stat-row:last-child {{ border-bottom: none; }}
  .stat-name {{
    font-size: 12px;
    color: var(--muted);
  }}
  .stat-val {{
    font-family: var(--font-mono);
    font-size: 13px;
    font-weight: 600;
    color: #fff;
  }}

  /* ── Footer ── */
  footer {{
    text-align: center;
    padding: 24px;
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--muted);
    border-top: 1px solid var(--border);
  }}

  /* ── Responsive ── */
  @media (max-width: 700px) {{
    .chart-row, .stats-grid {{ grid-template-columns: 1fr; }}
    .hero {{ grid-template-columns: 1fr; }}
    .hero-symbol {{ font-size: 36px; }}
  }}
</style>
</head>
<body>

<header>
  <div class="logo">Universal<span>Bot</span> · Backtest Rapport</div>
  <div class="header-meta">
    Gegenereerd op <strong>{gen_ts}</strong><br>
    UniversalBot v1 · EMA/RSI strategie
  </div>
</header>

<main>

  <!-- Hero -->
  <section class="hero">
    <div>
      <div class="hero-symbol">
        <span>Backtest resultaten</span>
        {symbol}
      </div>
      <div class="hero-period">📅 Periode: {period}</div>
    </div>
    <div class="verdict-badge" style="color:{verdict_color}; border-color:{verdict_color}; background:{verdict_color}18;">
      {verdict_icon} &nbsp;{verdict_text}<br>
      <span style="font-size:10px; font-weight:400; opacity:0.8;">{verdict_desc}</span>
    </div>
  </section>

  <!-- KPI Cards -->
  <div class="kpi-grid" style="margin-bottom:32px;">

    <div class="kpi" style="--kpi-accent:{pf_color(pf)}; --kpi-color:{pf_color(pf)};">
      <div class="kpi-label">Profit Factor</div>
      <div class="kpi-value">{stats.get('profit_factor','—')}</div>
      <div class="kpi-sub">≥ 2.0 = uitstekend</div>
    </div>

    <div class="kpi" style="--kpi-accent:{wr_color(wr)}; --kpi-color:{wr_color(wr)};">
      <div class="kpi-label">Win Rate</div>
      <div class="kpi-value">{stats.get('win_rate_pct','—')}%</div>
      <div class="kpi-sub">{stats.get('tp_trades','?')} TP · {stats.get('sl_trades','?')} SL</div>
    </div>

    <div class="kpi" style="--kpi-accent:{pnl_color}; --kpi-color:{pnl_color};">
      <div class="kpi-label">Totale P&amp;L</div>
      <div class="kpi-value">${stats.get('total_pnl_usd','—'):,}</div>
      <div class="kpi-sub" style="color:{ret_color};">{stats.get('total_return_pct','—')}% rendement</div>
    </div>

    <div class="kpi" style="--kpi-accent:{dd_color(dd)}; --kpi-color:{dd_color(dd)};">
      <div class="kpi-label">Max Drawdown</div>
      <div class="kpi-value">{stats.get('max_drawdown_pct','—')}%</div>
      <div class="kpi-sub">≤ 20% = acceptabel</div>
    </div>

    <div class="kpi" style="--kpi-accent:{sh_color(sh)}; --kpi-color:{sh_color(sh)};">
      <div class="kpi-label">Sharpe Ratio</div>
      <div class="kpi-value">{stats.get('sharpe_ratio','—')}</div>
      <div class="kpi-sub">≥ 1.0 = goed</div>
    </div>

    <div class="kpi" style="--kpi-accent:#6366f1; --kpi-color:#a5b4fc;">
      <div class="kpi-label">Calmar Ratio</div>
      <div class="kpi-value">{stats.get('calmar_ratio','—')}</div>
      <div class="kpi-sub">rendement / drawdown</div>
    </div>

    <div class="kpi" style="--kpi-accent:#06b6d4; --kpi-color:#67e8f9;">
      <div class="kpi-label">Totaal Trades</div>
      <div class="kpi-value">{stats.get('total_trades','—')}</div>
      <div class="kpi-sub">gem. {stats.get('avg_bars_in_trade','?')} bars per trade</div>
    </div>

    <div class="kpi" style="--kpi-accent:#8b5cf6; --kpi-color:#c4b5fd;">
      <div class="kpi-label">Expectancy</div>
      <div class="kpi-value">${stats.get('expectancy_usd','—')}</div>
      <div class="kpi-sub">per trade gemiddeld</div>
    </div>

  </div>

  <!-- Equity Curve -->
  <div class="chart-section">
    <div class="section-title">Equity Curve</div>
    <div class="chart-wrap" style="height:320px;">
      <canvas id="equityChart"></canvas>
    </div>
  </div>

  <!-- Monthly P&L + Win/Loss Distribution -->
  <div class="chart-row">
    <div class="chart-section">
      <div class="section-title">Maandelijkse P&amp;L</div>
      <div class="chart-wrap" style="height:240px;">
        <canvas id="monthlyChart"></canvas>
      </div>
    </div>
    <div class="chart-section">
      <div class="section-title">Uitkomsten</div>
      <div class="chart-wrap" style="height:240px; display:flex; align-items:center; justify-content:center;">
        <canvas id="donutChart" style="max-height:200px;"></canvas>
      </div>
    </div>
  </div>

  <!-- Detail Stats -->
  <div class="stats-grid">
    <div class="stats-block">
      <h3>Performance</h3>
      <div class="stat-row">
        <span class="stat-name">Startkapitaal</span>
        <span class="stat-val">${stats.get('initial_balance',0):,.2f}</span>
      </div>
      <div class="stat-row">
        <span class="stat-name">Eindkapitaal</span>
        <span class="stat-val">${stats.get('final_balance',0):,.2f}</span>
      </div>
      <div class="stat-row">
        <span class="stat-name">Gem. winst per trade</span>
        <span class="stat-val" style="color:var(--green);">${stats.get('avg_win_usd',0):,.2f}</span>
      </div>
      <div class="stat-row">
        <span class="stat-name">Gem. verlies per trade</span>
        <span class="stat-val" style="color:var(--red);">${stats.get('avg_loss_usd',0):,.2f}</span>
      </div>
      <div class="stat-row">
        <span class="stat-name">Risk:Reward ratio</span>
        <span class="stat-val">1 : 2.0</span>
      </div>
    </div>
    <div class="stats-block">
      <h3>Reeksen &amp; Risico</h3>
      <div class="stat-row">
        <span class="stat-name">Max opeenvolgende wins</span>
        <span class="stat-val" style="color:var(--green);">{stats.get('max_consec_wins','—')}</span>
      </div>
      <div class="stat-row">
        <span class="stat-name">Max opeenvolgende verliezen</span>
        <span class="stat-val" style="color:var(--red);">{stats.get('max_consec_losses','—')}</span>
      </div>
      <div class="stat-row">
        <span class="stat-name">TP trades</span>
        <span class="stat-val">{stats.get('tp_trades','—')}</span>
      </div>
      <div class="stat-row">
        <span class="stat-name">SL trades</span>
        <span class="stat-val">{stats.get('sl_trades','—')}</span>
      </div>
      <div class="stat-row">
        <span class="stat-name">Gem. bars in trade</span>
        <span class="stat-val">{stats.get('avg_bars_in_trade','—')}</span>
      </div>
    </div>
  </div>

</main>

<footer>
  UniversalBot v1 · EMA 20/50/200 + RSI + ATR · Gegenereerd op {gen_ts} · Alleen voor demo-gebruik
</footer>

<script>
const EQUITY_LABELS = {eq_lbl_json};
const EQUITY_VALUES = {eq_json};
const MONTHLY_LABELS = {monthly_labels};
const MONTHLY_VALUES = {monthly_values};
const TP_TRADES = {stats.get('tp_trades', 0)};
const SL_TRADES = {stats.get('sl_trades', 0)};
const INITIAL_BALANCE = {stats.get('initial_balance', 10000)};

Chart.defaults.color = '#4a5568';
Chart.defaults.borderColor = '#1e2535';
Chart.defaults.font.family = "'IBM Plex Mono', monospace";
Chart.defaults.font.size = 11;

// ── Equity curve ──────────────────────────────────────────
const eqCtx = document.getElementById('equityChart').getContext('2d');
const gradient = eqCtx.createLinearGradient(0, 0, 0, 300);
gradient.addColorStop(0, 'rgba(59,130,246,0.3)');
gradient.addColorStop(1, 'rgba(59,130,246,0)');

new Chart(eqCtx, {{
  type: 'line',
  data: {{
    labels: EQUITY_LABELS,
    datasets: [{{
      label: 'Equity ($)',
      data: EQUITY_VALUES,
      borderColor: '#3b82f6',
      backgroundColor: gradient,
      borderWidth: 1.5,
      pointRadius: 0,
      fill: true,
      tension: 0.2,
    }},
    {{
      label: 'Startkapitaal',
      data: EQUITY_LABELS.map(() => INITIAL_BALANCE),
      borderColor: '#1e2535',
      borderWidth: 1,
      borderDash: [4, 4],
      pointRadius: 0,
      fill: false,
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    interaction: {{ mode: 'index', intersect: false }},
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{
        backgroundColor: '#111620',
        borderColor: '#1e2535',
        borderWidth: 1,
        callbacks: {{
          label: ctx => ` ${{ctx.dataset.label}}: $${{ctx.raw.toLocaleString('nl-NL', {{minimumFractionDigits: 2}})}}`
        }}
      }}
    }},
    scales: {{
      x: {{
        ticks: {{ maxTicksLimit: 8, maxRotation: 0 }},
        grid: {{ color: '#1e2535' }}
      }},
      y: {{
        ticks: {{
          callback: v => '$' + v.toLocaleString('nl-NL')
        }},
        grid: {{ color: '#1e2535' }}
      }}
    }}
  }}
}});

// ── Maandelijkse P&L ──────────────────────────────────────
new Chart(document.getElementById('monthlyChart'), {{
  type: 'bar',
  data: {{
    labels: MONTHLY_LABELS,
    datasets: [{{
      label: 'P&L ($)',
      data: MONTHLY_VALUES,
      backgroundColor: MONTHLY_VALUES.map(v => v >= 0 ? 'rgba(34,197,94,0.7)' : 'rgba(239,68,68,0.7)'),
      borderColor:     MONTHLY_VALUES.map(v => v >= 0 ? '#22c55e' : '#ef4444'),
      borderWidth: 1,
      borderRadius: 3,
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{
        backgroundColor: '#111620',
        borderColor: '#1e2535',
        borderWidth: 1,
        callbacks: {{
          label: ctx => ` P&L: $${{ctx.raw.toLocaleString('nl-NL', {{minimumFractionDigits: 2}})}}`
        }}
      }}
    }},
    scales: {{
      x: {{ grid: {{ display: false }} }},
      y: {{
        ticks: {{ callback: v => '$' + v.toLocaleString('nl-NL') }},
        grid: {{ color: '#1e2535' }}
      }}
    }}
  }}
}});

// ── Donut: TP vs SL ───────────────────────────────────────
new Chart(document.getElementById('donutChart'), {{
  type: 'doughnut',
  data: {{
    labels: ['Take Profit', 'Stop Loss'],
    datasets: [{{
      data: [TP_TRADES, SL_TRADES],
      backgroundColor: ['rgba(34,197,94,0.8)', 'rgba(239,68,68,0.8)'],
      borderColor: ['#22c55e', '#ef4444'],
      borderWidth: 2,
      hoverOffset: 8,
    }}]
  }},
  options: {{
    responsive: true,
    maintainAspectRatio: false,
    cutout: '68%',
    plugins: {{
      legend: {{
        position: 'bottom',
        labels: {{ padding: 16, boxWidth: 12 }}
      }},
      tooltip: {{
        backgroundColor: '#111620',
        borderColor: '#1e2535',
        borderWidth: 1,
      }}
    }}
  }}
}});
</script>
</body>
</html>"""

    return html


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────

def run_and_report(symbol: str, days: int, initial_balance: float = None, csv_path: str = None):
    print(f"  ⏳  Backtest + rapport genereren voor {symbol}...")

    if csv_path:
        df = load_data_csv(csv_path)
    else:
        df = load_data_mt5(symbol, days)

    result = run_backtest(symbol, df, initial_balance)
    stats  = calc_statistics(result)

    if "error" in stats:
        print(f"  ❌  {stats['error']}")
        return

    html = generate_html(stats, result)

    os.makedirs("backtest_results", exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"backtest_results/rapport_{symbol}_{ts}.html"

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  ✅  Rapport opgeslagen: {filename}")
    print(f"  🌐  Open het bestand in je browser om het te bekijken.\n")
    return filename


def main():
    parser = argparse.ArgumentParser(description="UniversalBot — HTML Rapport Generator")
    parser.add_argument("--symbol",  type=str, help="Symbol (bijv. EURUSD)")
    parser.add_argument("--all",     action="store_true", help="Alle symbolen")
    parser.add_argument("--days",    type=int,   default=365)
    parser.add_argument("--balance", type=float, default=None)
    parser.add_argument("--csv",     type=str,   default=None)
    args = parser.parse_args()

    if not args.symbol and not args.all:
        parser.print_help()
        sys.exit(1)

    print("\n" + "═"*55)
    print("  📊  UniversalBot — HTML Rapport Generator")
    print("═"*55 + "\n")

    if args.all:
        all_symbols = SYMBOLS["forex"] + SYMBOLS["crypto"] + SYMBOLS["metals"]
        for sym in all_symbols:
            try:
                run_and_report(sym, args.days, args.balance)
            except Exception as e:
                print(f"  ❌  {sym} overgeslagen: {e}\n")
    else:
        try:
            run_and_report(args.symbol.upper(), args.days, args.balance, args.csv)
        except Exception as e:
            print(f"\n  ❌  Fout: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
