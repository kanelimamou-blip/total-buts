"use strict";
const MK = { o15: "+1,5 but", o20: "+2 buts", o25: "+2,5 buts" };
const KIND_FILTERS = [["all", "Tous"], ["sur", "Sûrs"], ["favoris", "Favoris"], ["periode", "Sur une période"], ["ligue", "Par championnat"], ["tendance", "Tendances"], ["value", "Value"], ["audace", "Audacieux"], ["jackpot", "Jackpot"], ["mille", "Cote 1000"]];
const kindOf = (c) => (c.kind.startsWith("periode") ? "periode" : c.kind);
const mkLabel = (l) => (l.market === "1" || l.market === "2" ? `Victoire ${l.team || (l.market === "1" ? l.home : l.away)}` : MK[l.market]);
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
  liveTick();
}

function route() {
  const tab = (location.hash || "#coupons").slice(1);
  document.querySelectorAll(".tabs a").forEach((a) => (a.dataset.tab === tab ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  if (!state.data) return;
  const v = { coupons: viewCoupons, matchs: viewMatches, astuces: viewTips, suivi: viewTracking }[tab] || viewCoupons;
  $("#view").innerHTML = v();
  renderBasketBar();
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
  if (!days.length) return `<h1>Coupons</h1><div class="empty"><p>Pas encore de coupon pour les 7 prochains jours.</p><p class="small">Les coupons sont recalculés toutes les heures.</p></div>${pastBlock()}`;
  if (!state.day || !days.includes(state.day)) state.day = days[0];
  const list = d.coupons.filter((c) => c.date === state.day);
  const shown = list.filter((c) => state.kind === "all" || kindOf(c) === state.kind).sort((a, b) => a.priority - b.priority);
  const count = (k) => list.filter((c) => k === "all" || kindOf(c) === k).length;
  const frozen = list[0]?.frozen;
  return `
  <h1>Coupons</h1>
  <div class="chips">${days.map((x) => `<button class="chip" data-day="${x}" aria-pressed="${x === state.day}">${dayLabel(x, d.today)}</button>`).join("")}</div>
  <div class="chips">${KIND_FILTERS.filter(([k]) => count(k)).map(([k, l]) => `<button class="chip" data-kind="${k}" aria-pressed="${k === state.kind}">${l}<span class="c">${count(k)}</span></button>`).join("")}</div>
  ${liveBlock()}
  <p class="small muted">${frozen ? "Coupons du jour figés au premier calcul du matin." : "Coupons provisoires : ils seront affinés quand les cotes du marché seront publiées, puis figés le jour du match."} Classés par priorité.</p>
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
        <span class="small muted">${c.legs.length} sélections${c.kind.startsWith("periode") ? " · ticket du " + dayLabel(c.date, state.data.today).toLowerCase() : settled ? "" : " · " + dayLabel(c.date, state.data.today)}</span>
      </div>
      <div class="big-odds">${odds(c.odds)}<small>cote estimée</small><small class="net">${odds(netOdds(c.odds))} après taxe</small></div>
    </div>
    ${settled ? `<div><span class="status ${st}">${{ won: "Gagné", lost: "Perdu", void: "Annulé" }[st]}</span>${st === "won" ? ` <span class="small muted">retour ${odds(c.return)} × la mise</span>` : ""}${st !== "void" ? ` <span class="small muted">· prévu ${pct(c.p_win)} de chances</span>` : ""}</div>` : `
    <div class="kv"><span>Chance de ne pas perdre</span><b>${c.p_not_lose < 0.01 ? "1 sur " + Math.round(1 / Math.max(c.p_not_lose, 1e-6)).toLocaleString("fr-FR") : pct(c.p_not_lose)}</b></div>
    <div class="meter ${meterCls}"><span style="width:${Math.round(c.p_not_lose * 100)}%"></span></div>`}
    <div class="legs">${c.legs.map((l) => legRow(l, settled)).join("")}</div>
    ${settled ? "" : `<button class="btn-main" data-play='${esc(JSON.stringify({ label: c.label + (c.scope && c.scope !== "Toutes ligues" ? " · " + c.scope : ""), odds: c.odds, legs: c.legs.map((l) => ({ id: l.id, market: l.market, team: l.team, home: l.home, away: l.away, league: l.league, odds: l.odds, p_win: l.p_win, p_push: l.p_push })) }))}'>Je l'ai joué</button>`}
    ${settled ? "" : `<button class="btn-copy" data-quick='${esc(JSON.stringify(c.legs.map((l) => [l.home, l.away, mkLabel(l), l.min_odds, l.time || ""])))}'>Saisie rapide 1xBet</button>`}
    ${settled ? "" : `<button class="btn-copy" data-copy="${esc(c.id || "")}" data-coupon='${esc(JSON.stringify(c.legs.map((l) => [l.home, l.away, mkLabel(l), l.min_odds])))}'>Copier le coupon pour 1xBet</button>`}
    ${settled ? "" : `<div class="stake">Mise conseillée : <b>${String(c.stake_pct).replace(".", ",")} %</b> de ta bankroll${c.ev > 0 ? ` · avantage estimé <b class="pos">+${Math.round(c.ev * 100)} %</b>` : ""}</div>`}
  </article>`;
}

function legRow(l, settled) {
  const res = l.result ? `<span class="res ${l.result}">${esc(l.score || l.goals)}</span>` : "";
  const lv = !settled && liveOf(state.data.matches.find((m) => m.id === l.id));
  if (lv && lv.state !== "pre") {
    const t = lv.hg + lv.ag, done = l.market === "o15" ? t >= 2 : l.market === "o25" || l.market === "o20" ? t >= 3 : l.market === "1" ? lv.hg > lv.ag : l.market === "2" ? lv.ag > lv.hg : false;
    l = { ...l, _live: `<span class="live ${lv.state}${done ? " ok" : ""}">${lv.state === "in" ? esc(lv.clock) : "Fin"} ${lv.hg}-${lv.ag}${done ? " ✓" : ""}</span>` };
  }
  return `<button class="leg" data-match="${esc(l.id)}">
    <span class="teams">${esc(l.home)} – ${esc(l.away)} ${l._live || ""}</span>
    <span class="o">${res || odds(l.odds)}</span>
    <span class="meta"><span class="mk">${esc(mkLabel(l))}</span> · ${esc(l.league)}${l.id ? " · " + dayLabel(l.id.slice(0, 4) + "-" + l.id.slice(4, 6) + "-" + l.id.slice(6, 8), state.data.today) : ""}${l.time ? " " + esc(l.time) : ""} · ${pct(l.p_win)}${l.p_push ? ` (+${pct(l.p_push)} remboursé)` : ""}</span>
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
  const mdays = [...new Set(ms.map((m) => m.date))].sort();
  if (!state.mday || !mdays.includes(state.mday)) state.mday = mdays[0];
  const byDay = {};
  ms.filter((m) => m.date === state.mday).forEach((m) => (byDay[m.date] ||= []).push(m));
  const sortKey = state.sort;
  return `<h1>Matchs</h1>
  <div class="chips"><button class="chip" data-league="all" aria-pressed="${state.league === "all"}">Toutes ligues</button>${leagues.map((l) => `<button class="chip" data-league="${l}" aria-pressed="${state.league === l}">${esc(d.leagues[l].name)}</button>`).join("")}</div>
  <div class="chips">${mdays.map((x) => `<button class="chip" data-mday="${x}" aria-pressed="${x === state.mday}">${dayLabel(x, d.today)}<span class="c">${ms.filter((m) => m.date === x).length}</span></button>`).join("")}</div>
  <div class="chips"><button class="chip" data-favview="1" aria-pressed="${!!state.favView}">Favoris ≤ 1,40</button>${["o15", "o20", "o25"].map((k) => `<button class="chip" data-sort="${k}" aria-pressed="${sortKey === k}">Trier par ${MK[k]}</button>`).join("")}<button class="chip" data-sort="time" aria-pressed="${sortKey === "time"}">Par heure</button></div>
  ${state.favView ? favList(ms.filter((m) => m.date === state.mday)) : Object.keys(byDay).sort().map((day) => {
    const list = byDay[day].slice().sort((a, b) => (sortKey === "time" ? (a.time > b.time ? 1 : -1) : b.p[sortKey] - a.p[sortKey]));
    return `<section class="card"><h2>${dayLabel(day, d.today)}</h2><div>${list.map(matchRow).join("")}</div></section>`;
  }).join("")}`;
}

function favList(ms) {
  const all = ms.filter((m) => m.fav && !m.provisional).sort((a, b) => b.fav.p_win - a.fav.p_win);
  const favs = all.filter((m) => m.fav.odds <= 1.4).slice(0, 50);
  const more = all.filter((m) => m.fav.odds > 1.4 && m.fav.odds <= 1.6).slice(0, Math.max(0, 50 - favs.length));
  if (!favs.length && !more.length) return `<div class="empty">Aucun favori net ce jour-là.</div>`;
  // suggestions : tickets de 3 favoris consécutifs (les plus sûrs ensemble), cote visée autour de 2
  const tickets = [];
  const pool = favs.concat(more);
  for (let i = 0; i + 2 < pool.length && tickets.length < 6; ) {
    const t = [pool[i], pool[i + 1], pool[i + 2]];
    let o = t.reduce((a, m) => a * m.fav.odds, 1);
    if (o < 2 && pool[i + 3]) { t.push(pool[i + 3]); o *= pool[i + 3].fav.odds; }
    tickets.push(t); i += t.length;
  }
  const leg = (m) => ({ id: m.id, market: m.fav.market, team: m.fav.team, home: m.home, away: m.away, league: m.league, time: m.time, odds: m.fav.odds, p_win: m.fav.p_win, p_push: 0, min_odds: m.fav.min_odds });
  return `<section class="card"><h2>Suggestions</h2><p class="small muted">Les favoris les plus sûrs, regroupés par 3 ou 4.</p>
    ${tickets.map((t, k) => { const legs = t.map(leg), o = legs.reduce((a, l) => a * l.odds, 1), p = legs.reduce((a, l) => a * l.p_win, 1);
      return `<div class="kv"><span>Ticket ${k + 1} : ${t.map((m) => esc(m.fav.team)).join(", ")}</span><b>${odds(o)} (net ${odds(netOdds(o))}) · ${pct(p)}</b></div>
      <button class="btn-copy" data-play='${esc(JSON.stringify({ label: "Favoris ≤ 1,40", odds: +o.toFixed(2), legs }))}'>Je l'ai joué</button>`; }).join("")}
  </section>
  ${[[favs, `${favs.length} favori${favs.length > 1 ? "s" : ""} à 1,40 max`], [more, "Un peu plus risqués (1,41 à 1,60)"]].filter(([l]) => l.length).map(([l, title]) => `<section class="card"><h2>${title}</h2>
    ${l.map((m) => `<button class="match" data-match="${esc(m.id)}"><span class="teams">${esc(m.fav.team)} <span class="small muted">gagne</span><br><span class="small muted">${esc(m.home)} – ${esc(m.away)} · ${esc(m.league)} ${esc(m.time || "")}</span></span>
      <span class="time">${odds(m.fav.odds)}<br><span class="small">${pct(m.fav.p_win)}</span></span></button>`).join("")}
  </section>`).join("")}
  <p class="note">Les cotes sans marché publié sont estimées. Sur 1xBet, ne garde un favori que si sa cote est au moins la cote juste de la fiche du match.</p>`;
}

function matchRow(m) {
  const bar = (k, label) => `<div class="pb"><span class="l">${label}<b>${pct(m.p[k])}</b></span><div class="meter"><span style="width:${Math.round(m.p[k] * 100)}%"></span></div></div>`;
  return `<button class="match" data-match="${esc(m.id)}">
    <span class="teams">${esc(m.home)} – ${esc(m.away)}<br><span class="small muted">${esc(m.league)}${m.provisional ? " · en rodage" : ""}${m.has_odds === false ? " · sans cotes" : ""}</span></span>
    <span class="time">${liveBadge(m) || esc(m.time || "")}</span>
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
    const box = (k) => `<div class="mk-box"><span class="s">${MK[k]}</span><span class="p">${pct(m.p[k])}</span><span class="s">cote juste ${odds(legs[k].fair)}</span><span class="s">exige ≥ <b>${odds(legs[k].min_odds)}</b></span>${addBtn(m, k)}</div>`;
    html = `<div class="vs"><span class="team">${esc(m.home)}</span><span class="muted small">buts attendus</span><span class="team">${esc(m.away)}</span>
      <span class="xg">${String(m.xg_home).replace(".", ",")}</span><span class="muted">–</span><span class="xg">${String(m.xg_away).replace(".", ",")}</span></div>
    <p class="muted small" style="text-align:center">${esc(m.league)} · ${dayLabel(m.date, state.data.today)} ${esc(m.time)}</p>
    <div class="mk-grid">${box("o15")}${box("o20")}${box("o25")}</div>
    ${m.res ? `<div class="mk-grid"><div class="mk-box"><span class="s">Victoire ${esc(m.home)}</span><span class="p">${pct(m.res["1"])}</span>${addBtn(m, "1")}</div><div class="mk-box"><span class="s">Nul</span><span class="p">${pct(m.res.X)}</span></div><div class="mk-box"><span class="s">Victoire ${esc(m.away)}</span><span class="p">${pct(m.res["2"])}</span>${addBtn(m, "2")}</div></div>` : ""}
    ${m.p.o20_push ? `<p class="small muted">+2 buts : remboursé si le match finit à 2 buts (${pct(m.p.o20_push)}).</p>` : ""}
    ${m.provisional ? `<p class="note">Coupe d'Europe en rodage : l'historique des matchs européens se charge encore. Ce match n'entre pas dans les coupons pour l'instant.</p>` : ""}
    ${m.market_o25 != null ? `<p class="small">Marché sur +2,5 : <b>${pct(m.market_o25)}</b> (cote moyenne ${odds(m.odds_o25)}). Modèle seul : ${pct(m.p_model.o25)}.</p>` : `<p class="small muted">Cotes du marché pas encore publiées dans nos sources : probabilités du modèle seul, affinées à l'approche du match.</p>`}
    ${m.context?.length ? `<div class="form">${m.context.map((c) => `<span>${esc(c)}</span>`).join("")}</div>` : ""}
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
  ${surprisesBlock()}
  ${t.map((x) => `<article class="card tip ${x.type}"${x.match ? ` data-match="${esc(x.match)}" style="cursor:pointer"` : ""}><span class="ic">${ic[x.type] || "i"}</span><div><h3>${esc(x.title)}</h3><p class="small">${esc(x.text)}</p></div></article>`).join("")}`;
}

function surprisesBlock() {
  const s = state.data.surprises;
  if (!s) return "";
  const list = (rows, fmt) => rows.map((r) => `<div class="kv"><span>${esc(r.team)} <span class="small">· ${esc(r.league)}</span></span><b>${fmt(r)}</b></div>`).join("");
  const sign = (x) => (x > 0 ? "+" : "") + String(x).replace(".", ",");
  return `<section class="card"><h2>Surprises de la saison</h2>
  <p class="small muted">Comparées à ce que prévoyaient les cotes des bookmakers avant chaque match, depuis le début de la saison.</p>
  <h3>Au-dessus des attentes</h3>${list(s.over, (r) => `${r.pts} pts au lieu de ${String(r.xpts).replace(".", ",")}`)}
  <h3>En dessous des attentes</h3>${list(s.under, (r) => `${r.pts} pts au lieu de ${String(r.xpts).replace(".", ",")}`)}
  <h3>Plus de buts que prévu</h3>${list(s.goals, (r) => `${r.o25} matchs à +2,5 sur ${r.n25} (prévu ${String(r.xo25).replace(".", ",")})`)}
  <h3>Moins de buts que prévu</h3>${list(s.closed, (r) => `${r.o25} sur ${r.n25} (prévu ${String(r.xo25).replace(".", ",")})`)}
  </section>`;
}

/* ---------- Suivi ---------- */
// Marge d'erreur due au hasard (95 %) : un écart plus petit que la marge ne prouve rien
function calibVerdict(p) {
  const marg = (q) => 1.96 * Math.sqrt((q * (1 - q)) / p.n);
  const m15 = marg(p.o15_pred), m25 = marg(p.o25_pred);
  const out = (pred, obs, m) => Math.abs(obs - pred) > m;
  const pts = (x) => Math.round(x * 100);
  const verdict = p.n < 300 ? `Encore ${300 - p.n} matchs avant une première lecture (300), et 500 à 1 000 pour être sûr.`
    : out(p.o15_pred, p.o15_obs, m15) || out(p.o25_pred, p.o25_obs, m25) ? "Un écart dépasse la marge : défaut réel, les corrections s'appliquent." : "Écarts dans la marge : le modèle tient en conditions réelles.";
  return `<p class="small muted">${p.n} matchs suivis. Marge due au hasard : ± ${pts(m15)} pts (+1,5), ± ${pts(m25)} pts (+2,5). Un écart plus petit que la marge ne veut rien dire.</p><p class="small"><b>${verdict}</b></p>`;
}
function favOk(r) {
  const [h, a] = String(r.score).split("-").map(Number);
  return r.fav_side === "1" ? h > a : a > h;
}

// Pronostics de l'appli face aux résultats : sélections de tous les coupons proposés, joués ou non
function propVsReal(d) {
  const seen = new Set(), legs = [];
  for (const c of d.coupons) for (const l of c.legs) {
    const k = l.id + "|" + l.market;
    if (!l.result || seen.has(k)) continue;
    seen.add(k); legs.push(l);
  }
  const cps = d.coupons.filter((c) => c.status === "won" || c.status === "lost");
  if (!legs.length) return `<section class="card"><h2>Pronostics contre résultats</h2><p class="small muted">Les premiers matchs proposés seront comparés ici dès leur fin : ce que l'appli annonçait, et ce qui s'est passé.</p></section>`;
  const bands = [[0.5, 0.6], [0.6, 0.7], [0.7, 0.8], [0.8, 0.9], [0.9, 1.01]].map(([lo, hi]) => {
    const g = legs.filter((l) => l.p_win >= lo && l.p_win < hi);
    return { lo, hi, n: g.length, p: g.reduce((a, l) => a + l.p_win, 0) / (g.length || 1), w: g.filter((l) => l.result === "won").length, push: g.filter((l) => l.result === "push").length };
  }).filter((b) => b.n);
  const n = legs.length, won = legs.filter((l) => l.result === "won").length, pAvg = legs.reduce((a, l) => a + l.p_win, 0) / n;
  const gap = won / n - pAvg;
  const verdict = n < 100 ? `Encore ${100 - n} sélections avant un premier avis fiable.` : Math.abs(gap) <= 0.03 ? "Le réel colle au prévu : les probabilités sont fiables." : gap > 0 ? "L'appli est trop prudente : le réel dépasse le prévu." : "L'appli est trop optimiste : le réel est sous le prévu, les corrections s'appliquent.";
  const mk = {};
  for (const l of legs) { const m = (mk[l.market === "1" || l.market === "2" ? "Victoire du favori" : mkLabel(l)] ||= { n: 0, w: 0, p: 0 }); m.n++; m.p += l.p_win; m.w += l.result === "won"; }
  return `<section class="card"><h2>Pronostics contre résultats</h2>
  <p class="small muted">Chaque sélection proposée, jouée ou non, est comparée au score final. Le pronostic d'avant-match reste figé.</p>
  <div class="kv"><span>Sélections réglées</span><b>${n}</b></div>
  <div class="kv"><span>Passées : prévu / réel</span><b>${pct(pAvg)} / ${pct(won / n)}</b></div>
  ${cps.length ? `<div class="kv"><span>Coupons complets : prévu / réel</span><b>${pct(cps.reduce((a, c) => a + c.p_win, 0) / cps.length)} / ${pct(cps.filter((c) => c.status === "won").length / cps.length)} (${cps.length})</b></div>` : ""}
  <p class="small"><b>${verdict}</b></p>
  <h3>Selon la confiance annoncée</h3>
  <div class="tbl"><table><thead><tr><th>Annoncé</th><th class="n">Sélections</th><th class="n">Prévu</th><th class="n">Réel</th></tr></thead><tbody>
  ${bands.map((b) => `<tr><td>${Math.round(b.lo * 100)}–${Math.min(100, Math.round(b.hi * 100))} %</td><td class="n">${b.n}</td><td class="n">${pct(b.p)}</td><td class="n ${b.w / b.n >= b.p - 0.03 ? "pos" : "neg"}">${pct(b.w / b.n)}${b.push ? ` <span class="small muted">+${b.push} remb.</span>` : ""}</td></tr>`).join("")}
  </tbody></table></div>
  <h3>Par marché</h3>
  ${Object.entries(mk).map(([k, m]) => `<div class="kv"><span>${esc(k)} · ${m.n} sélections</span><b>${pct(m.p / m.n)} / ${pct(m.w / m.n)}</b></div>`).join("")}
  </section>`;
}

function viewTracking() {
  const d = state.data, bt = state.bt;
  const settled = d.coupons.filter((c) => c.status === "won" || c.status === "lost");
  const kinds = Object.entries(d.coupon_kinds);
  const live = d.live || {};
  const tot = Object.values(live).reduce((a, s) => ({ n: a.n + s.n, won: a.won + s.won, units: a.units + s.units }), { n: 0, won: 0, units: 0 });
  let html = `<h1>Suivi</h1>${myBetsBlock()}<h2>Propositions de l'appli</h2>
  <div class="stats">
    <div class="stat"><span class="k">Coupons réglés</span><span class="v">${tot.n}</span></div>
    <div class="stat"><span class="k">Gagnés</span><span class="v">${tot.n ? Math.round((tot.won / tot.n) * 100) + " %" : "–"}</span></div>
    <div class="stat"><span class="k">Bilan (mises)</span><span class="v ${tot.units >= 0 ? "pos" : "neg"}">${tot.n ? signed(tot.units) : "–"}</span></div>
    <div class="stat"><span class="k">Matchs suivis</span><span class="v">${d.predictions ? d.predictions.n : 0}</span></div>
  </div>
  <p class="note">Tous les coupons proposés sont suivis, que tu les joues ou non. Bilan calculé avec une mise fictive de 1 par coupon et la cote estimée. Chaque résultat corrige les probabilités des prochains jours, ligue par ligue.</p>`;
  if (Object.keys(live).length) {
    html += `<section class="card"><h2>Par type de coupon</h2><div class="tbl"><table><thead><tr><th>Type</th><th class="n">Réglés</th><th class="n">Gagnés</th><th class="n">Bilan</th></tr></thead><tbody>
    ${kinds.filter(([k]) => live[k]).map(([k, c]) => `<tr><td>${esc(c.label)}</td><td class="n">${live[k].n}</td><td class="n">${Math.round((live[k].won / live[k].n) * 100)} %</td><td class="n ${live[k].units >= 0 ? "pos" : "neg"}">${signed(live[k].units)}</td></tr>`).join("")}
    </tbody></table></div>${curveChart(settled)}</section>`;
  }
  html += propVsReal(d);
  if (d.predictions) {
    const p = d.predictions;
    html += `<section class="card"><h2>Fiabilité réelle</h2>
    <div class="kv"><span>+1,5 annoncé / observé</span><b>${pct(p.o15_pred)} / ${pct(p.o15_obs)}</b></div>
    <div class="kv"><span>+2,5 annoncé / observé</span><b>${pct(p.o25_pred)} / ${pct(p.o25_obs)}</b></div>
    ${calibVerdict(p)}</section>`;
  }
  if (d.learning?.length) {
    html += `<section class="card"><h2>Apprentissage</h2><p class="small muted">Chaque semaine, ce que l'appli annonçait comparé à ce qui s'est passé. Les écarts corrigent automatiquement les prochaines prédictions, ligue par ligue et pour les favoris.</p>
    <div class="tbl"><table><thead><tr><th>Semaine du</th><th class="n">Matchs</th><th class="n">+1,5 prévu/réel</th><th class="n">+2,5 prévu/réel</th><th class="n">Favoris prévu/réel</th></tr></thead><tbody>
    ${d.learning.slice().reverse().map((w) => `<tr><td>${new Date(w.week).toLocaleDateString("fr-FR", { day: "numeric", month: "short" })}</td><td class="n">${w.n}</td><td class="n">${pct(w.p15)} / ${pct(w.o15)}</td><td class="n">${pct(w.p25)} / ${pct(w.o25)}</td><td class="n">${w.pf != null ? pct(w.pf) + " / " + pct(w.of) : "–"}</td></tr>`).join("")}
    </tbody></table></div>
    ${Object.keys(d.feedback?.kinds || {}).length ? `<h3>Par type de coupon</h3>${Object.entries(d.feedback.kinds).map(([k, v]) => `<div class="kv"><span>${esc(d.coupon_kinds[k]?.label || k)} · ${v.won} gagnés sur ${v.n} (prévu ${String(v.pred).replace(".", ",")})</span><b class="${v.factor >= 1 ? "pos" : "neg"}">${v.factor >= 1 ? "mis en avant" : "relégué"}</b></div>`).join("")}` : ""}
    </section>`;
  }
  const rel = d.feedback?.reliability || {};
  if (Object.keys(rel).length) {
    html += `<section class="card"><h2>Confiance par championnat</h2><p class="small muted">Les ligues au-dessus de 1 sont mises en avant dans les coupons.</p>
    ${Object.entries(rel).sort((a, b) => b[1] - a[1]).map(([div, r]) => `<div class="kv"><span>${esc(d.leagues[div]?.name || div)}</span><b>${String(r.toFixed(2)).replace(".", ",")}</b></div><div class="meter ${r < 1 ? "amber" : ""}"><span style="width:${Math.round(((r - 0.7) / 0.5) * 100)}%"></span></div>`).join("")}</section>`;
  }
  if (d.recent?.length) {
    html += `<section class="card"><h2>Derniers matchs analysés</h2>${d.recent.slice(0, 25).map((r) => `<button class="match" data-match="${esc(r.id)}"><span class="teams">${esc(r.home)} – ${esc(r.away)}<br><span class="small muted">${esc(r.league)} · ${dayLabel(r.date, d.today)}</span></span><span class="res ${r.goals >= 3 ? "won" : r.goals === 2 ? "push" : "lost"}">${esc(r.score)}</span><span class="meta">Prévu : +1,5 ${pct(r.o15)} ${r.goals >= 2 ? "✓" : "✗"} · +2,5 ${pct(r.o25)} ${r.goals >= 3 ? "✓" : "✗"}${r.fav_p != null ? ` · ${r.fav_side === "1" ? esc(r.home) : esc(r.away)} gagne ${pct(r.fav_p)} ${favOk(r) ? "✓" : "✗"}` : ""}</span></button>`).join("")}</section>`;
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
  ${bt.context?.factors?.length ? `<h3>Facteurs de contexte</h3><p class="small muted">Écart entre les buts prévus par les cotes et ce qui s'est vraiment passé, selon la situation.${["o15", "o25"].some((k) => bt.context.markets[k]?.use) ? " Les facteurs qui améliorent la précision sur une période de test sont appliqués aux probabilités." : " Aucun n'améliore assez la précision pour être appliqué pour l'instant."}</p>
  <div class="tbl"><table><thead><tr><th>Situation</th><th class="n">Matchs</th><th class="n">+2,5 prévu</th><th class="n">+2,5 réel</th></tr></thead><tbody>
  ${bt.context.factors.map((f) => `<tr><td style="white-space:normal">${esc(f.label)}</td><td class="n">${f.n}</td><td class="n">${pct(f.pred_o25)}</td><td class="n ${f.obs_o25 > f.pred_o25 ? "pos" : "neg"}">${pct(f.obs_o25)}</td></tr>`).join("")}</tbody></table></div>` : ""}
  ${metaBlock(bt)}${diagBlock(bt)}
  <p class="note">${esc(bt.note)}</p></section>`;
}

// Méta-modèle : ce que les tirs cadrés apportent, testé sur une année jamais vue
function metaBlock(bt) {
  const m = bt.meta;
  if (!m) return "";
  const row = (lab, e) => e ? `<tr><td>${lab}</td><td class="n ${e.gain_pct > 0 ? "pos" : "neg"}">${e.gain_pct > 0 ? "+" : ""}${String(e.gain_pct).replace(".", ",")} %</td><td class="n">${e.use ? "oui" : "non"}</td></tr>` : "";
  return `<h3>Tirs cadrés et méta-modèle</h3><p class="small muted">Un second modèle combine le marché, le modèle de buts, les tirs et tirs cadrés de chaque équipe et l'écart de niveau. Il sert surtout aux matchs lointains, encore sans cotes. Il n'est appliqué que s'il prédit mieux sur une année de matchs qu'il n'a jamais vus.</p>
  <div class="tbl"><table><thead><tr><th>Cas</th><th class="n">Gain</th><th class="n">Utilisé</th></tr></thead><tbody>
  ${row("+1,5 avec cotes", m.market?.o15)}${row("+2,5 avec cotes", m.market?.o25)}${row("+1,5 sans cotes", m.no_market?.o15)}${row("+2,5 sans cotes", m.no_market?.o25)}
  </tbody></table></div>`;
}

// Diagnostic des réglages : réussite réelle des sélections selon la ligue, le marché, la confiance et la cote
function diagBlock(bt) {
  const g = bt.diagnostic;
  if (!g) return "";
  const cell = (x) => `<td class="n">${pct(x.pred)}</td><td class="n ${x.obs >= x.pred - 0.02 ? "pos" : "neg"}">${pct(x.obs)}</td>`;
  const worst = g.segments.slice().sort((a, b) => a.z - b.z);
  return `<h3>Diagnostic des réglages</h3><p class="small muted">Chaque sélection proposable rejouée sur le passé : prévu contre réel. Une case nettement sous le prévu est retirée automatiquement des coupons.${g.blocked.length ? "" : " Aucune ne l'est pour l'instant."}</p>
  <div class="tbl"><table><thead><tr><th>Confiance</th><th class="n">Sélections</th><th class="n">Prévu</th><th class="n">Réel</th></tr></thead><tbody>
  ${g.bands.map((b) => `<tr><td>${esc(b.market)} ${esc(b.band)}</td><td class="n">${b.n}</td>${cell(b)}</tr>`).join("")}</tbody></table></div>
  <div class="tbl"><table><thead><tr><th>Cote</th><th class="n">Sélections</th><th class="n">Prévu</th><th class="n">Réel</th><th class="n">Rentab.</th></tr></thead><tbody>
  ${g.odds.map((b) => `<tr><td>${esc(b.range)}</td><td class="n">${b.n}</td>${cell(b)}<td class="n ${b.roi >= 0 ? "pos" : "neg"}">${(b.roi * 100).toFixed(1).replace(".", ",")} %</td></tr>`).join("")}</tbody></table></div>
  <div class="tbl"><table><thead><tr><th>Ligue · marché</th><th class="n">Sélections</th><th class="n">Prévu</th><th class="n">Réel</th></tr></thead><tbody>
  ${worst.map((x) => `<tr><td>${esc(x.name)} ${esc(x.market)}${x.blocked ? " ⛔" : ""}</td><td class="n">${x.n}</td>${cell(x)}</tr>`).join("")}</tbody></table></div>`;
}

/* ---------- Direct (scores ESPN, interrogés depuis le téléphone) ---------- */
state.live = {};
function poissonAtLeast(lam, k) {
  if (k <= 0) return 1;
  let term = Math.exp(-lam), cdf = term;
  for (let i = 1; i < k; i++) { term *= lam / i; cdf += term; }
  return Math.max(0, 1 - cdf);
}
function liveOf(m) { return m && m.espn ? state.live[m.espn[1]] : null; }
function liveProbs(m, lv) {
  const minute = lv.state === "post" ? 95 : Math.min(lv.minute || 0, 94);
  const lam = (m.xg_home + m.xg_away) * Math.max(0, 94 - minute) / 94;
  const g = lv.hg + lv.ag;
  return { o15: poissonAtLeast(lam, 2 - g), o25: poissonAtLeast(lam, 3 - g), o20: poissonAtLeast(lam, 3 - g), goals: g };
}
async function liveTick() {
  if (!state.data || document.visibilityState !== "visible") return;
  const now = Date.now();
  const wanted = state.data.matches.filter((m) => {
    if (!m.espn || !m.time) return false;
    const t = Date.parse(`${m.date}T${m.time}:00Z`);
    return now > t - 10 * 60e3 && now < t + 3 * 3600e3;
  });
  const groups = {};
  wanted.forEach((m) => (groups[`${m.espn[0]}|${m.date.replace(/-/g, "")}`] = 1));
  let changed = false;
  await Promise.all(Object.keys(groups).map(async (k) => {
    const [slug, d] = k.split("|");
    try {
      const r = await fetch(`https://site.api.espn.com/apis/site/v2/sports/soccer/${slug}/scoreboard?dates=${d}`);
      const j = await r.json();
      (j.events || []).forEach((e) => {
        const c = e.competitions[0], st = c.status || e.status, tm = Object.fromEntries(c.competitors.map((x) => [x.homeAway, x]));
        state.live[e.id] = { state: st.type.state, clock: st.displayClock, minute: parseInt(st.displayClock, 10) || 0, detail: st.type.shortDetail,
          hg: parseInt(tm.home.score, 10) || 0, ag: parseInt(tm.away.score, 10) || 0 };
        changed = true;
      });
    } catch { /* pas de réseau ou source indisponible : on réessaiera */ }
  }));
  if (changed && $("#sheet").hidden) { const y = window.scrollY; route(); window.scrollTo(0, y); }
}
function liveBadge(m) {
  const lv = liveOf(m);
  if (!lv || lv.state === "pre") return "";
  return `<span class="live ${lv.state}">${lv.state === "in" ? "● " + esc(lv.clock) : "Terminé"} · ${lv.hg}-${lv.ag}</span>`;
}
function liveBlock() {
  const d = state.data;
  const ids = new Set(d.coupons.filter((c) => c.date >= d.today || !c.status).flatMap((c) => c.legs.map((l) => l.id)));
  const lives = d.matches.filter((m) => { const lv = liveOf(m); return lv && lv.state === "in"; });
  if (!lives.length) return "";
  lives.sort((a, b) => ids.has(b.id) - ids.has(a.id));
  return `<section class="card"><h2>En direct</h2><p class="small muted">Probabilités recalculées avec le score et le temps restant. Mise à jour chaque minute.</p>
  ${lives.map((m) => { const lp = liveProbs(m, liveOf(m)); return `<button class="match" data-match="${esc(m.id)}"><span class="teams">${esc(m.home)} – ${esc(m.away)}${ids.has(m.id) ? ' <span class="tag">dans un coupon</span>' : ""}<br><span class="small muted">${esc(m.league)}</span></span>${liveBadge(m)}
    <span class="probs">${["o15", "o20", "o25"].map((k) => `<div class="pb"><span class="l">${{ o15: "+1,5", o20: "+2", o25: "+2,5" }[k]}<b>${lp[k] >= 0.999 ? "✓" : pct(lp[k])}</b></span><div class="meter"><span style="width:${Math.round(lp[k] * 100)}%"></span></div></div>`).join("")}</span></button>`; }).join("")}</section>`;
}
setInterval(liveTick, 60e3);

/* ---------- Saisie rapide dans 1xBet ---------- */
// libellés des marchés tels qu'ils apparaissent dans 1xBet
function xbetLabel(mk, h, a) {
  return mk.startsWith("+1,5") ? "Total Plus de 1.5" : mk.startsWith("+2,5") ? "Total Plus de 2.5" : mk.startsWith("+2 ") ? "Total Plus de 2 (asiatique)"
    : mk === `Victoire ${h}` ? "V1 (victoire domicile)" : mk === `Victoire ${a}` ? "V2 (victoire extérieur)" : mk;
}
function openQuick(legs) {
  $("#sheet-body").innerHTML = `<h2>Saisie rapide 1xBet</h2>
  <p class="small muted">Pour chaque match : touche le nom pour le copier, colle-le dans « Recherche d'événement » de 1xBet, choisis le marché indiqué, puis coche.</p>
  <div class="legs">${legs.map(([h, a, mk, mo, t], i) => `<div class="leg quick" id="q${i}">
    <span class="teams"><button class="btn-team" data-copy-text="${esc(h)}">${esc(h)}</button> – ${esc(a)}${t ? ` <span class="small muted">${esc(t)}</span>` : ""}</span>
    <span class="o"><input type="checkbox" id="qc${i}" aria-label="Fait"></span>
    <span class="meta"><b>${esc(xbetLabel(mk, h, a))}</b> · cote min ${odds(mo)}</span></div>`).join("")}</div>`;
  $("#sheet").hidden = false;
}

/* ---------- Mon coupon et Mes paris (gardés sur ce téléphone) ---------- */
const basket = () => store.get("basket", []);
const bets = () => store.get("bets", []);

function legFor(m, mk) {
  if (mk === "1" || mk === "2") {
    const p = m.res[mk], real = m.fav && m.fav.market === mk && m.fav.odds_source === "marché" ? m.fav.odds : null;
    return { market: mk, team: mk === "1" ? m.home : m.away, p_win: p, p_push: 0, odds: real || +(1 / p / 1.06).toFixed(2), min_odds: +((1 / p) * 1.03).toFixed(2) };
  }
  const l = m.legs.find((x) => x.market === mk);
  return { market: mk, p_win: l.p_win, p_push: l.p_push, odds: l.odds, min_odds: l.min_odds };
}

function addBtn(m, mk) {
  const inB = basket().some((b) => b.id === m.id && b.market === mk);
  return `<button class="btn-add" data-add="${esc(m.id)}" data-mk="${mk}">${inB ? "Retirer" : "+ Mon coupon"}</button>`;
}

function comboStats(legs) {
  const pOk = legs.reduce((a, l) => a * (l.p_win + l.p_push), 1);
  const pWin = legs.reduce((a, l) => a * l.p_win, 1);
  const o = legs.reduce((a, l) => a * l.odds, 1);
  return { pOk, pWin, odds: o };
}

function renderBasketBar() {
  const b = basket();
  let bar = $("#basket-bar");
  if (!bar) { bar = document.createElement("button"); bar.id = "basket-bar"; bar.className = "basket-bar"; bar.dataset.openBasket = "1"; document.body.appendChild(bar); }
  bar.hidden = !b.length;
  if (b.length) { const st = comboStats(b); bar.innerHTML = `<span>Mon coupon · ${b.length} sélection${b.length > 1 ? "s" : ""}</span><b>${odds(st.odds)} (net ${odds(netOdds(st.odds))}) · ${pct(st.pOk)}</b>`; }
}

function openBasket() {
  const b = basket(), st = comboStats(b);
  $("#sheet-body").innerHTML = `<h2>Mon coupon</h2>
  ${b.length ? `<div class="stats"><div class="stat"><span class="k">Cote estimée (nette)</span><span class="v">${odds(st.odds)} <span class="small">(${odds(netOdds(st.odds))})</span></span></div><div class="stat"><span class="k">Ne pas perdre</span><span class="v">${pct(st.pOk)}</span></div></div>
  <div class="legs">${b.map((l, i) => `<div class="leg"><span class="teams">${esc(l.home)} – ${esc(l.away)}</span><span class="o">${odds(l.odds)}</span>
    <span class="meta"><span class="mk">${esc(mkLabel(l))}</span> · ${esc(l.league)} · ${pct(l.p_win)}</span><button class="btn-x" data-remove="${i}">Retirer</button></div>`).join("")}</div>
  ${st.pOk < 0.3 ? `<p class="note">Moins de 30 % de chances de ne pas perdre : c'est un coupon risqué.</p>` : ""}
  <button class="btn-copy" data-coupon='${esc(JSON.stringify(b.map((l) => [l.home, l.away, mkLabel(l), l.min_odds])))}'>Copier le coupon pour 1xBet</button>
  <button class="btn-main" data-played-basket="1">Je l'ai joué</button>
  <button class="btn-x" data-clear-basket="1">Vider le coupon</button>` : `<p class="muted">Ajoute des sélections depuis la fiche d'un match (onglet Matchs).</p>`}`;
  $("#sheet").hidden = false;
}

function openPlayForm(legs, label, est) {
  state.pending = { legs, label };
  $("#sheet-body").innerHTML = `<h2>J'ai joué ce coupon</h2><p class="small muted">${esc(label)} · ${legs.length} sélections</p>
  <form id="play-form" class="form-col">
    <label for="stake">Mise (FCFA)</label><input id="stake" type="number" inputmode="decimal" min="1" required value="${store.get("lastStake", 1000)}">
    <label for="real-odds">Cote obtenue sur 1xBet</label><input id="real-odds" type="number" inputmode="decimal" step="0.01" min="1.01" required value="${est.toFixed(2)}">
    <button class="btn-main" type="submit">Enregistrer</button>
  </form>`;
  $("#sheet").hidden = false;
}

function legResult(l) {
  const r = state.data.recent.find((x) => x.id === l.id);
  let sc = r ? r.score : null;
  if (!sc) for (const c of state.data.coupons) { const x = c.legs.find((y) => y.id === l.id && y.score); if (x) { sc = x.score; break; } }
  if (!sc) return null;
  const [h, a] = sc.split("-").map(Number), t = h + a;
  const res = l.market === "1" ? (h > a ? "won" : "lost") : l.market === "2" ? (a > h ? "won" : "lost") : l.market === "o15" ? (t >= 2 ? "won" : "lost") : l.market === "o25" ? (t >= 3 ? "won" : "lost") : t >= 3 ? "won" : t === 2 ? "push" : "lost";
  return { res, score: sc };
}

function betStatus(bet) {
  const rs = bet.legs.map(legResult);
  if (rs.some((r) => r && r.res === "lost")) return { status: "lost", ret: 0, rs };
  if (rs.some((r) => !r)) return { status: "pending", ret: null, rs };
  // remboursements : la cote du coupon est réduite de la cote estimée des sélections remboursées
  let o = bet.odds;
  bet.legs.forEach((l, i) => { if (rs[i].res === "push") o /= l.odds; });
  return { status: "won", ret: bet.stake * Math.max(netOdds(o), 1), rs };  // gain net après taxe
}

function myBetsBlock() {
  const list = bets();
  const start = store.get("bankroll", null);
  let staked = 0, ret = 0, pending = 0;
  const rows = list.slice().reverse().map((b, ri) => {
    const st = betStatus(b), idx = list.length - 1 - ri;
    if (st.status === "pending") pending += b.stake; else { staked += b.stake; ret += st.ret; }
    return `<div class="leg"><span class="teams">${esc(b.label)}<br><span class="small muted">${new Date(b.created).toLocaleDateString("fr-FR")} · ${b.legs.length} sélections · cote ${odds(b.odds)}</span></span>
      <span class="o"><span class="status ${st.status}">${{ won: "Gagné", lost: "Perdu", pending: "En cours" }[st.status]}</span></span>
      <span class="meta">Mise ${fmt(b.stake)}${st.status === "won" ? ` · gain ${fmt(st.ret)}` : ""} · ${b.legs.map((l, i) => `${esc(l.home)}${st.rs[i] ? " " + esc(st.rs[i].score) : ""}`).join(", ")}</span>
      <button class="btn-x" data-del-bet="${idx}">Supprimer</button></div>`;
  }).join("");
  const profit = ret - staked;
  return `<section class="card"><h2>Mes paris</h2>
    <div class="form-row"><label for="bankroll">Bankroll de départ (FCFA)</label><input id="bankroll" type="number" inputmode="decimal" value="${start ?? ""}" placeholder="ex. 50000"></div>
    <div class="form-row"><label for="tax">Taxe sur les gains (%)</label><input id="tax" type="number" inputmode="decimal" min="0" max="50" value="${store.get("tax", 20)}"></div>
    <div class="stats"><div class="stat"><span class="k">Bilan</span><span class="v ${profit >= 0 ? "pos" : "neg"}">${profit >= 0 ? "+" : ""}${fmt(profit)}</span></div>
    <div class="stat"><span class="k">Bankroll</span><span class="v">${start != null ? fmt(start + profit - pending) : "–"}</span></div>
    <div class="stat"><span class="k">En jeu</span><span class="v">${fmt(pending)}</span></div>
    <div class="stat"><span class="k">Paris</span><span class="v">${list.length}</span></div></div>
    ${list.length ? `<div class="legs">${rows}</div>` : `<p class="small muted">Touche « Je l'ai joué » sur un coupon pour suivre tes vrais paris. Ils sont réglés automatiquement avec les scores. Ces données restent sur ce téléphone.</p>`}
  </section>`;
}
const taxRate = () => store.get("tax", 20) / 100;
const netOdds = (o) => 1 + (o - 1) * (1 - taxRate());
const fmt = (x) => Math.round(x).toLocaleString("fr-FR");

/* ---------- Événements ---------- */
document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-favview],[data-day],[data-mday],[data-kind],[data-league],[data-sort],[data-match],[data-close]");
  if (!t) return;
  if (t.dataset.close !== undefined) { $("#sheet").hidden = true; return; }
  if (t.dataset.match) { openMatch(t.dataset.match); return; }
  if (t.dataset.day) state.day = t.dataset.day;
  if (t.dataset.mday) state.mday = t.dataset.mday;
  if (t.dataset.favview) state.favView = !state.favView;
  if (t.dataset.kind) { state.kind = t.dataset.kind; store.set("kind", state.kind); }
  if (t.dataset.league) state.league = t.dataset.league;
  if (t.dataset.sort) { state.sort = t.dataset.sort; store.set("sort", state.sort); }
  const y = window.scrollY; route(); window.scrollTo(0, y);
});
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-coupon]");
  if (!b) return;
  e.stopPropagation();
  const legs = JSON.parse(b.dataset.coupon);
  const xbet = xbetLabel;
  const text = legs.map(([h, a, mk, mo], i) => `${i + 1}. ${h} - ${a} : ${xbet(mk, h, a)}, cote min ${odds(mo)}`).join("\n");
  try { await navigator.clipboard.writeText(text); b.textContent = "Copié ✓"; }
  catch { const t = document.createElement("textarea"); t.value = text; document.body.appendChild(t); t.select(); document.execCommand("copy"); t.remove(); b.textContent = "Copié ✓"; }
  setTimeout(() => (b.textContent = "Copier le coupon pour 1xBet"), 2000);
}, true);
document.addEventListener("click", (e) => {
  const q = e.target.closest("[data-quick],[data-copy-text]");
  if (q) {
    e.stopPropagation();
    if (q.dataset.quick) return openQuick(JSON.parse(q.dataset.quick));
    const txt = q.dataset.copyText, done = () => { q.textContent = "Copié ✓"; setTimeout(() => (q.textContent = txt), 1500); };
    navigator.clipboard.writeText(txt).then(done).catch(() => { const t = document.createElement("textarea"); t.value = txt; document.body.appendChild(t); t.select(); document.execCommand("copy"); t.remove(); done(); });
    return;
  }
  const t = e.target.closest("[data-add],[data-open-basket],[data-remove],[data-clear-basket],[data-played-basket],[data-play],[data-del-bet]");
  if (!t) return;
  e.stopPropagation();
  if (t.dataset.add) {
    const m = state.data.matches.find((x) => x.id === t.dataset.add);
    let b = basket();
    const i = b.findIndex((x) => x.id === m.id && x.market === t.dataset.mk);
    if (i >= 0) b.splice(i, 1);
    else { b = b.filter((x) => x.id !== m.id); b.push({ id: m.id, home: m.home, away: m.away, league: m.league, date: m.date, time: m.time, ...legFor(m, t.dataset.mk) }); }
    store.set("basket", b); renderBasketBar(); openMatch(m.id); return;
  }
  if (t.dataset.openBasket) return openBasket();
  if (t.dataset.remove) { const b = basket(); b.splice(+t.dataset.remove, 1); store.set("basket", b); renderBasketBar(); return openBasket(); }
  if (t.dataset.clearBasket) { store.set("basket", []); renderBasketBar(); $("#sheet").hidden = true; return; }
  if (t.dataset.playedBasket) { const b = basket(); return openPlayForm(b, "Mon coupon", comboStats(b).odds); }
  if (t.dataset.play) { const c = JSON.parse(t.dataset.play); return openPlayForm(c.legs, c.label, c.odds); }
  if (t.dataset.delBet) {
    if (t.dataset.confirm !== "1") { t.dataset.confirm = "1"; t.textContent = "Confirmer la suppression"; return; }
    const l = bets(); l.splice(+t.dataset.delBet, 1); store.set("bets", l); route(); return;
  }
}, true);
document.addEventListener("submit", (e) => {
  if (e.target.id !== "play-form") return;
  e.preventDefault();
  const stake = parseFloat($("#stake").value), o = parseFloat($("#real-odds").value);
  if (!(stake > 0) || !(o > 1)) return;
  const l = bets(); l.push({ created: new Date().toISOString(), label: state.pending.label, legs: state.pending.legs, stake, odds: o });
  store.set("bets", l); store.set("lastStake", stake);
  if (state.pending.label === "Mon coupon") store.set("basket", []);
  renderBasketBar();
  $("#sheet-body").innerHTML = `<h2>Pari enregistré</h2><p>Il sera réglé automatiquement avec les scores. Retrouve-le dans l'onglet Suivi.</p>`;
});
document.addEventListener("change", (e) => {
  if (e.target.id === "bankroll") { const v = parseFloat(e.target.value); store.set("bankroll", isNaN(v) ? null : v); route(); }
  if (e.target.id === "tax") { const v = parseFloat(e.target.value); store.set("tax", isNaN(v) ? 20 : Math.min(Math.max(v, 0), 50)); route(); }
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
