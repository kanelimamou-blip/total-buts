"use strict";
const MK = { o15: "+1,5 but", o20: "+2 buts", o25: "+2,5 buts" };
const KIND_FILTERS = [["all", "Tous"], ["sur", "Sûrs"], ["ligue", "Par championnat"], ["value", "Value"], ["audace", "Audacieux"], ["jackpot", "Jackpot"]];
const state = { data: null, bt: null, day: null, kind: "all", league: "all", sort: "o15" };
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pct = (p) => (p == null ? "–" : Math.round(p * 100) + " %");
const odds = (o) => (o == null ? "–" : Number(o).toFixed(2).replace(".", ","));
const signed = (x) => (x > 0 ? "+" : "") + x.toFixed(2).replace(".", ",");
const dayLabel = (iso, today) => {
  const d = new Date(iso + "T12:00:00"), t = new Date(today + "T12:00:00");
  const diff = Math.round((d - t) / 864e5);
  if (diff === 0) return "Aujourd'hui";
  if (diff === 1) return "Demain";
  if (diff === -1) return "Hier";
  return d.toLocaleDateString("fr-FR", { weekday: "short", day: "numeric", month: "short" });
};
const store = { get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} } };

async function load() {
  try {
    const [a, b] = await Promise.all([
      fetch("data/app.json", { cache: "no-cache" }).then((r) => r.json()),
      fetch("data/backtest.json", { cache: "no-cache" }).then((r) => r.json()).catch(() => null),
    ]);
    state.data = a; state.bt = b;
  } catch (e) {
    $("#view").innerHTML = `<div class="empty"><h2>Pas de connexion</h2><p>Les données n'ont pas pu être chargées. Réessaie quand tu as du réseau.</p></div>`;
    return;
  }
  const g = new Date(state.data.generated);
  $("#updated").textContent = "Mis à jour " + g.toLocaleString("fr-FR", { weekday: "short", hour: "2-digit", minute: "2-digit" });
  route();
}

function route() {
  const tab = (location.hash || "#coupons").slice(1);
  document.querySelectorAll(".tabs a").forEach((a) => (a.dataset.tab === tab ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  if (!state.data) return;
  const v = { coupons: viewCoupons, matchs: viewMatches, astuces: viewTips, suivi: viewTracking }[tab] || viewCoupons;
  $("#view").innerHTML = v();
  window.scrollTo(0, 0);
}

/* ---------- Coupons ---------- */
function couponDays() {
  const d = state.data;
  const days = [...new Set(d.coupons.filter((c) => c.date >= d.today).map((c) => c.date))].sort();
  return days;
}

function viewCoupons() {
  const d = state.data;
  const days = couponDays();
  if (!days.length) return `<h1>Coupons</h1><div class="empty"><p>Aucun match analysé pour aujourd'hui et les deux prochains jours.</p><p class="small">Les coupons apparaissent dès que le calendrier et les cotes sont publiés, en général la veille.</p></div>${pastBlock()}`;
  if (!state.day || !days.includes(state.day)) state.day = days[0];
  const list = d.coupons.filter((c) => c.date === state.day);
  const shown = list.filter((c) => state.kind === "all" || c.kind === state.kind).sort((a, b) => a.priority - b.priority);
  const count = (k) => list.filter((c) => k === "all" || c.kind === k).length;
  const frozen = list[0]?.frozen;
  return `
  <h1>Coupons</h1>
  <div class="chips">${days.map((x) => `<button class="chip" data-day="${x}" aria-pressed="${x === state.day}">${dayLabel(x, d.today)}</button>`).join("")}</div>
  <div class="chips">${KIND_FILTERS.filter(([k]) => count(k)).map(([k, l]) => `<button class="chip" data-kind="${k}" aria-pressed="${k === state.kind}">${l}<span class="c">${count(k)}</span></button>`).join("")}</div>
  <p class="small muted">${frozen ? "Coupons du jour figés au premier calcul du matin." : "Coupons provisoires : ils peuvent encore changer avec les cotes."} Classés par priorité.</p>
  ${shown.map(couponCard).join("") || `<div class="empty">Aucun coupon de ce type ce jour-là.</div>`}
  ${pastBlock()}`;
}

function couponCard(c) {
  const st = c.status || "pending";
  const settled = st === "won" || st === "lost" || st === "void";
  const meterCls = c.kind === "jackpot" || c.kind === "audace" ? "amber" : "";
  return `<article class="card">
    <div class="coupon-head">
      <div class="t">
        <span class="prio ${c.level}"><i></i>Priorité ${c.priority} · ${c.level}</span>
        <h3>${esc(c.label)}${c.scope && c.scope !== "Toutes ligues" ? " · " + esc(c.scope) : ""}</h3>
        <span class="small muted">${c.legs.length} sélections${settled ? "" : " · " + dayLabel(c.date, state.data.today)}</span>
      </div>
      <div class="big-odds">${odds(c.odds)}<small>cote estimée</small></div>
    </div>
    ${settled ? `<div><span class="status ${st}">${{ won: "Gagné", lost: "Perdu", void: "Annulé" }[st]}</span>${st === "won" ? ` <span class="small muted">retour ${odds(c.return)} × la mise</span>` : ""}</div>` : `
    <div class="kv"><span>Chance de ne pas perdre</span><b>${pct(c.p_not_lose)}</b></div>
    <div class="meter ${meterCls}"><span style="width:${Math.round(c.p_not_lose * 100)}%"></span></div>`}
    <div class="legs">${c.legs.map((l) => legRow(l, settled)).join("")}</div>
    ${settled ? "" : `<div class="stake">Mise conseillée : <b>${String(c.stake_pct).replace(".", ",")} %</b> de ta bankroll${c.ev > 0 ? ` · avantage estimé <b class="pos">+${Math.round(c.ev * 100)} %</b>` : ""}</div>`}
  </article>`;
}

function legRow(l, settled) {
  const res = l.result ? `<span class="res ${l.result}">${esc(l.score || l.goals)}</span>` : "";
  return `<button class="leg" data-match="${esc(l.id)}">
    <span class="teams">${esc(l.home)} – ${esc(l.away)}</span>
    <span class="o">${settled && res ? res : odds(l.odds)}</span>
    <span class="meta"><span class="mk">${MK[l.market]}</span> · ${esc(l.league)}${l.time ? " · " + esc(l.time) : ""} · ${pct(l.p_win)}${l.p_push ? ` (+${pct(l.p_push)} remboursé)` : ""}</span>
    <span class="min">${settled ? odds(l.odds) : "min. " + odds(l.min_odds)}</span>
  </button>`;
}

function pastBlock() {
  const d = state.data;
  const past = d.coupons.filter((c) => c.date < d.today && c.status && c.status !== "pending").sort((a, b) => (a.date < b.date ? 1 : -1) || a.priority - b.priority).slice(0, 6);
  if (!past.length) return "";
  return `<h2 style="margin-top:10px">Derniers résultats</h2>${past.map(couponCard).join("")}<a class="small" href="#suivi">Tout l'historique</a>`;
}

/* ---------- Matchs ---------- */
function viewMatches() {
  const d = state.data;
  if (!d.matches.length) return `<h1>Matchs</h1><div class="empty">Aucun match à venir dans les données pour le moment.</div>`;
  const leagues = [...new Set(d.matches.map((m) => m.div))];
  let ms = d.matches.filter((m) => state.league === "all" || m.div === state.league);
  const byDay = {};
  ms.forEach((m) => (byDay[m.date] ||= []).push(m));
  const sortKey = state.sort;
  return `<h1>Matchs</h1>
  <div class="chips"><button class="chip" data-league="all" aria-pressed="${state.league === "all"}">Toutes ligues</button>${leagues.map((l) => `<button class="chip" data-league="${l}" aria-pressed="${state.league === l}">${esc(d.leagues[l].name)}</button>`).join("")}</div>
  <div class="chips">${["o15", "o20", "o25"].map((k) => `<button class="chip" data-sort="${k}" aria-pressed="${sortKey === k}">Trier par ${MK[k]}</button>`).join("")}<button class="chip" data-sort="time" aria-pressed="${sortKey === "time"}">Par heure</button></div>
  ${Object.keys(byDay).sort().map((day) => {
    const list = byDay[day].slice().sort((a, b) => (sortKey === "time" ? (a.time > b.time ? 1 : -1) : b.p[sortKey] - a.p[sortKey]));
    return `<section class="card"><h2>${dayLabel(day, d.today)}</h2><div>${list.map(matchRow).join("")}</div></section>`;
  }).join("")}`;
}

function matchRow(m) {
  const bar = (k, label) => `<div class="pb"><span class="l">${label}<b>${pct(m.p[k])}</b></span><div class="meter"><span style="width:${Math.round(m.p[k] * 100)}%"></span></div></div>`;
  return `<button class="match" data-match="${esc(m.id)}">
    <span class="teams">${esc(m.home)} – ${esc(m.away)}<br><span class="small muted">${esc(m.league)}</span></span>
    <span class="time">${esc(m.time || "")}</span>
    <span class="probs">${bar("o15", "+1,5")}${bar("o20", "+2")}${bar("o25", "+2,5")}</span>
  </button>`;
}

function findMatch(id) {
  const m = state.data.matches.find((x) => x.id === id);
  if (m) return m;
  const r = state.data.recent.find((x) => x.id === id);
  return r ? { past: true, ...r } : null;
}

function openMatch(id) {
  const m = findMatch(id);
  if (!m) return;
  let html;
  if (m.past) {
    html = `<div class="vs"><span class="team">${esc(m.home)}</span><span class="xg">${esc(m.score)}</span><span class="team">${esc(m.away)}</span></div>
    <p class="muted small" style="text-align:center">${esc(m.league)} · ${dayLabel(m.date, state.data.today)}</p>
    <div class="mk-grid"><div class="mk-box"><span class="s">+1,5 prévu</span><span class="p">${pct(m.o15)}</span><span class="s">${m.goals >= 2 ? "passé" : "raté"}</span></div>
    <div class="mk-box"><span class="s">+2,5 prévu</span><span class="p">${pct(m.o25)}</span><span class="s">${m.goals >= 3 ? "passé" : "raté"}</span></div>
    <div class="mk-box"><span class="s">Buts</span><span class="p">${m.goals}</span><span class="s">au total</span></div></div>`;
  } else {
    const legs = Object.fromEntries(m.legs.map((l) => [l.market, l]));
    const box = (k) => `<div class="mk-box"><span class="s">${MK[k]}</span><span class="p">${pct(m.p[k])}</span><span class="s">cote juste ${odds(legs[k].fair)}</span><span class="s">exige ≥ <b>${odds(legs[k].min_odds)}</b></span></div>`;
    html = `<div class="vs"><span class="team">${esc(m.home)}</span><span class="muted small">buts attendus</span><span class="team">${esc(m.away)}</span>
      <span class="xg">${String(m.xg_home).replace(".", ",")}</span><span class="muted">–</span><span class="xg">${String(m.xg_away).replace(".", ",")}</span></div>
    <p class="muted small" style="text-align:center">${esc(m.league)} · ${dayLabel(m.date, state.data.today)} ${esc(m.time)}</p>
    <div class="mk-grid">${box("o15")}${box("o20")}${box("o25")}</div>
    ${m.p.o20_push ? `<p class="small muted">+2 buts : remboursé si le match finit à 2 buts (${pct(m.p.o20_push)}).</p>` : ""}
    ${m.market_o25 != null ? `<p class="small">Marché sur +2,5 : <b>${pct(m.market_o25)}</b> (cote moyenne ${odds(m.odds_o25)}). Modèle seul : ${pct(m.p_model.o25)}.</p>` : `<p class="small muted">Pas encore de cotes pour ce match : probabilités du modèle seul.</p>`}
    <h3>Nombre de buts</h3>${distChart(m.total_dist)}
    <h3>Scores les plus probables</h3><div class="form">${m.top_scores.map((s) => `<span>${s.s} · ${pct(s.p)}</span>`).join("")}</div>
    ${formBlock(m.home, m.form_home)}${formBlock(m.away, m.form_away)}`;
  }
  $("#sheet-body").innerHTML = html;
  $("#sheet").hidden = false;
}

function formBlock(team, f) {
  if (!f || !f.games.length) return "";
  return `<h3>${esc(team)} · 6 derniers matchs</h3>
  <div class="form">${f.games.map((g) => `<span class="${g.gf + g.ga >= 3 ? "hot" : ""}" title="${esc(g.opp)}">${g.h ? g.gf + "-" + g.ga : g.ga + "-" + g.gf}</span>`).join("")}</div>
  <p class="small muted">${String(f.avg_total).replace(".", ",")} buts par match en moyenne · ${pct(f.o25_rate)} à +2,5</p>`;
}

function distChart(dist) {
  const vals = dist.slice(0, 6).concat([Math.max(0, 1 - dist.slice(0, 6).reduce((a, b) => a + b, 0))]);
  const W = 320, H = 130, pad = 18, bw = (W - pad * 2) / vals.length, max = Math.max(...vals);
  const bars = vals.map((v, i) => {
    const h = (v / max) * (H - 42), x = pad + i * bw + 4, y = H - 20 - h;
    const fill = i >= 3 ? "var(--accent)" : i === 2 ? "var(--amber)" : "var(--muted)";
    return `<rect x="${x}" y="${y}" width="${bw - 8}" height="${h}" rx="3" fill="${fill}" opacity="${i < 2 ? 0.45 : 1}"/>
      <text x="${x + (bw - 8) / 2}" y="${y - 4}" text-anchor="middle">${Math.round(v * 100)}%</text>
      <text x="${x + (bw - 8) / 2}" y="${H - 6}" text-anchor="middle">${i === 6 ? "6+" : i}</text>`;
  }).join("");
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Probabilité de chaque nombre de buts">${bars}</svg>`;
}

/* ---------- Astuces ---------- */
function viewTips() {
  const t = state.data.tips || [];
  const ic = { ligue: "L", prudence: "!", equipe: "↑", value: "€", suivi: "✓", discipline: "%" };
  return `<h1>Astuces</h1><p class="muted small">Générées chaque jour à partir des données et de nos propres résultats.</p>
  ${t.map((x) => `<article class="card tip ${x.type}"${x.match ? ` data-match="${esc(x.match)}" style="cursor:pointer"` : ""}><span class="ic">${ic[x.type] || "i"}</span><div><h3>${esc(x.title)}</h3><p class="small">${esc(x.text)}</p></div></article>`).join("")}`;
}

/* ---------- Suivi ---------- */
function viewTracking() {
  const d = state.data, bt = state.bt;
  const settled = d.coupons.filter((c) => c.status === "won" || c.status === "lost");
  const kinds = Object.entries(d.coupon_kinds);
  const live = d.live || {};
  const tot = Object.values(live).reduce((a, s) => ({ n: a.n + s.n, won: a.won + s.won, units: a.units + s.units }), { n: 0, won: 0, units: 0 });
  let html = `<h1>Suivi</h1>
  <div class="stats">
    <div class="stat"><span class="k">Coupons joués</span><span class="v">${tot.n}</span></div>
    <div class="stat"><span class="k">Gagnés</span><span class="v">${tot.n ? Math.round((tot.won / tot.n) * 100) + " %" : "–"}</span></div>
    <div class="stat"><span class="k">Bilan (mises)</span><span class="v ${tot.units >= 0 ? "pos" : "neg"}">${tot.n ? signed(tot.units) : "–"}</span></div>
    <div class="stat"><span class="k">Matchs suivis</span><span class="v">${d.predictions ? d.predictions.n : 0}</span></div>
  </div>
  <p class="note">Bilan calculé avec une mise de 1 par coupon et la cote estimée. Chaque résultat corrige les probabilités des prochains jours, ligue par ligue.</p>`;
  if (Object.keys(live).length) {
    html += `<section class="card"><h2>Par type de coupon</h2><div class="tbl"><table><thead><tr><th>Type</th><th class="n">Joués</th><th class="n">Gagnés</th><th class="n">Bilan</th></tr></thead><tbody>
    ${kinds.filter(([k]) => live[k]).map(([k, c]) => `<tr><td>${esc(c.label)}</td><td class="n">${live[k].n}</td><td class="n">${Math.round((live[k].won / live[k].n) * 100)} %</td><td class="n ${live[k].units >= 0 ? "pos" : "neg"}">${signed(live[k].units)}</td></tr>`).join("")}
    </tbody></table></div>${curveChart(settled)}</section>`;
  }
  if (d.predictions) {
    const p = d.predictions;
    html += `<section class="card"><h2>Fiabilité réelle</h2>
    <div class="kv"><span>+1,5 annoncé / observé</span><b>${pct(p.o15_pred)} / ${pct(p.o15_obs)}</b></div>
    <div class="kv"><span>+2,5 annoncé / observé</span><b>${pct(p.o25_pred)} / ${pct(p.o25_obs)}</b></div>
    <p class="small muted">Plus les deux chiffres sont proches, mieux le modèle est calibré.</p></section>`;
  }
  const rel = d.feedback?.reliability || {};
  if (Object.keys(rel).length) {
    html += `<section class="card"><h2>Confiance par championnat</h2><p class="small muted">Les ligues au-dessus de 1 sont mises en avant dans les coupons.</p>
    ${Object.entries(rel).sort((a, b) => b[1] - a[1]).map(([div, r]) => `<div class="kv"><span>${esc(d.leagues[div]?.name || div)}</span><b>${String(r.toFixed(2)).replace(".", ",")}</b></div><div class="meter ${r < 1 ? "amber" : ""}"><span style="width:${Math.round(((r - 0.7) / 0.5) * 100)}%"></span></div>`).join("")}</section>`;
  }
  if (d.recent?.length) {
    html += `<section class="card"><h2>Derniers matchs analysés</h2>${d.recent.slice(0, 25).map((r) => `<button class="match" data-match="${esc(r.id)}"><span class="teams">${esc(r.home)} – ${esc(r.away)}<br><span class="small muted">${esc(r.league)} · ${dayLabel(r.date, d.today)}</span></span><span class="res ${r.goals >= 3 ? "won" : r.goals === 2 ? "push" : "lost"}">${esc(r.score)}</span></button>`).join("")}</section>`;
  }
  const hist = d.coupons.filter((c) => c.date < d.today).sort((a, b) => (a.date < b.date ? 1 : -1));
  if (hist.length) html += `<h2>Historique des coupons</h2>${hist.slice(0, 40).map(couponCard).join("")}`;
  if (bt) html += backtestBlock(bt);
  return html;
}

function curveChart(settled) {
  const s = settled.slice().sort((a, b) => (a.date > b.date ? 1 : -1));
  if (s.length < 2) return "";
  let acc = 0;
  const pts = s.map((c) => (acc += c.return - 1));
  return lineChart(pts, "Bilan cumulé (mises)");
}

function lineChart(pts, label) {
  const W = 320, H = 120, p = 22, min = Math.min(0, ...pts), max = Math.max(0, ...pts), span = max - min || 1;
  const x = (i) => p + (i / (pts.length - 1)) * (W - p * 2), y = (v) => H - p - ((v - min) / span) * (H - p * 2);
  const path = pts.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const last = pts[pts.length - 1];
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="${label}">
    <line x1="${p}" x2="${W - p}" y1="${y(0)}" y2="${y(0)}" stroke="var(--line)"/>
    <path d="${path}L${x(pts.length - 1)},${y(0)}L${x(0)},${y(0)}Z" fill="var(--accent)" opacity=".12"/>
    <path d="${path}" fill="none" stroke="${last >= 0 ? "var(--won)" : "var(--lost)"}" stroke-width="2"/>
    <circle cx="${x(pts.length - 1)}" cy="${y(last)}" r="3.5" fill="${last >= 0 ? "var(--won)" : "var(--lost)"}"/>
    <text x="${p}" y="12">${label}</text><text x="${W - p}" y="12" text-anchor="end">${signed(last)}</text>
    <text x="4" y="${y(0) + 3}">0</text></svg>`;
}

function calibChart(cal) {
  const W = 300, H = 200, p = 28, s = (v) => p + v * (W - p * 2), t = (v) => H - p - v * (H - p * 2);
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Calibration : probabilité annoncée contre fréquence observée">
    <line x1="${s(0)}" y1="${t(0)}" x2="${s(1)}" y2="${t(1)}" stroke="var(--line)" stroke-dasharray="4 4"/>
    <line x1="${s(0)}" y1="${t(0)}" x2="${s(1)}" y2="${t(0)}" stroke="var(--line)"/><line x1="${s(0)}" y1="${t(0)}" x2="${s(0)}" y2="${t(1)}" stroke="var(--line)"/>
    ${[0, 0.5, 1].map((v) => `<text x="${s(v)}" y="${H - 10}" text-anchor="middle">${v * 100}%</text><text x="${p - 4}" y="${t(v) + 3}" text-anchor="end">${v * 100}%</text>`).join("")}
    <path d="${cal.map((c, i) => `${i ? "L" : "M"}${s(c.pred).toFixed(1)},${t(c.obs).toFixed(1)}`).join("")}" fill="none" stroke="var(--accent)" stroke-width="2"/>
    ${cal.map((c) => `<circle cx="${s(c.pred)}" cy="${t(c.obs)}" r="3.5" fill="var(--accent)"/>`).join("")}
    <text x="${s(0.02)}" y="${t(0.97)}">observé</text><text x="${s(0.98)}" y="${t(0.04)}" text-anchor="end">annoncé</text></svg>`;
}

function backtestBlock(bt) {
  const m25 = bt.markets.o25, m15 = bt.markets.o15;
  const gain = (m) => Math.round((1 - m.brier_final / m.brier_base) * 100);
  const coupons = Object.entries(bt.coupons || {});
  return `<section class="card"><h2>Test sur le passé</h2>
  <p class="small muted">${bt.n_matches.toLocaleString("fr-FR")} matchs rejoués du ${new Date(bt.period[0]).toLocaleDateString("fr-FR")} au ${new Date(bt.period[1]).toLocaleDateString("fr-FR")}, le modèle ne voyant que le passé. Recalculé chaque semaine.</p>
  <div class="stats"><div class="stat"><span class="k">Gain de précision +1,5</span><span class="v">${gain(m15)} %</span></div><div class="stat"><span class="k">Gain de précision +2,5</span><span class="v">${gain(m25)} %</span></div>
  <div class="stat"><span class="k">Part modèle / marché</span><span class="v">${Math.round(bt.blend * 100)} / ${Math.round((1 - bt.blend) * 100)}</span></div><div class="stat"><span class="k">Matchs à +2,5</span><span class="v">${pct(m25.rate)}</span></div></div>
  <h3>Calibration +2,5</h3>${calibChart(m25.calibration)}
  ${coupons.length ? `<h3>Coupons rejoués</h3><div class="tbl"><table><thead><tr><th>Type</th><th class="n">Nombre</th><th class="n">Prévu</th><th class="n">Réel</th><th class="n">Rentab.</th></tr></thead><tbody>
  ${coupons.map(([k, c]) => `<tr><td>${esc(c.label)}</td><td class="n">${c.n}</td><td class="n">${pct(c.pred_hit)}</td><td class="n">${pct(c.hit)}</td><td class="n ${c.roi >= 0 ? "pos" : "neg"}">${(c.roi * 100).toFixed(1).replace(".", ",")} %</td></tr>`).join("")}</tbody></table></div>` : ""}
  ${bt.value?.o25?.length ? `<h3>Paris simples +2,5 avec avantage</h3><div class="tbl"><table><thead><tr><th>Avantage mini</th><th class="n">Paris</th><th class="n">Réussite</th><th class="n">Rentab.</th></tr></thead><tbody>
  ${bt.value.o25.map((v) => `<tr><td>${Math.round(v.threshold * 100)} %</td><td class="n">${v.bets}</td><td class="n">${pct(v.hit)}</td><td class="n ${v.roi >= 0 ? "pos" : "neg"}">${(v.roi * 100).toFixed(1).replace(".", ",")} %</td></tr>`).join("")}</tbody></table></div>` : ""}
  <h3>Par championnat</h3><div class="tbl"><table><thead><tr><th>Ligue</th><th class="n">Buts/match</th><th class="n">+1,5</th><th class="n">+2,5</th></tr></thead><tbody>
  ${bt.leagues.slice().sort((a, b) => b.avg_goals - a.avg_goals).map((l) => `<tr><td>${esc(l.name)}</td><td class="n">${String(l.avg_goals).replace(".", ",")}</td><td class="n">${pct(l.o15_rate)}</td><td class="n">${pct(l.o25_rate)}</td></tr>`).join("")}</tbody></table></div>
  ${bt.europe ? `<h3>Coupes d'Europe</h3><p class="small muted">${bt.europe.n} matchs européens rejoués. Pas de cotes gratuites pour ces matchs : probabilités du modèle seul, à prendre avec plus de prudence.</p>
  <div class="kv"><span>+1,5 annoncé / observé</span><b>${pct(bt.europe.o15.pred)} / ${pct(bt.europe.o15.rate)}</b></div>
  <div class="kv"><span>+2,5 annoncé / observé</span><b>${pct(bt.europe.o25.pred)} / ${pct(bt.europe.o25.rate)}</b></div>
  <div class="kv"><span>Gain de précision +2,5</span><b>${Math.round((1 - bt.europe.o25.brier / bt.europe.o25.brier_base) * 100)} %</b></div>` : ""}
  <p class="note">${esc(bt.note)}</p></section>`;
}

/* ---------- Événements ---------- */
document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-day],[data-kind],[data-league],[data-sort],[data-match],[data-close]");
  if (!t) return;
  if (t.dataset.close !== undefined) { $("#sheet").hidden = true; return; }
  if (t.dataset.match) { openMatch(t.dataset.match); return; }
  if (t.dataset.day) state.day = t.dataset.day;
  if (t.dataset.kind) { state.kind = t.dataset.kind; store.set("kind", state.kind); }
  if (t.dataset.league) state.league = t.dataset.league;
  if (t.dataset.sort) { state.sort = t.dataset.sort; store.set("sort", state.sort); }
  const y = window.scrollY; route(); window.scrollTo(0, y);
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("#sheet").hidden = true; });
window.addEventListener("hashchange", () => { $("#sheet").hidden = true; route(); });
state.kind = store.get("kind", "all"); state.sort = store.get("sort", "o15");

let deferred;
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); deferred = e; $("#install").hidden = false; });
$("#install").addEventListener("click", async () => { if (!deferred) return; deferred.prompt(); await deferred.userChoice; deferred = null; $("#install").hidden = true; });
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") load(); });
load();
