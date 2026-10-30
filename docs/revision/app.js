"use strict";
// Révision BAC et BFEM : quiz, examen blanc, erreurs à revoir, progrès, accès premium par code
const $view = document.getElementById("view");
const LETTERS = "ABCD";
const QUIZ_LEN = 10, EXAM_LEN = 20, EXAM_MIN = 20;
let DATA = null, CFG = null, timer = null;

const store = {
  load() { try { return JSON.parse(localStorage.getItem("rev") || "{}"); } catch { return {}; } },
  save() { try { localStorage.setItem("rev", JSON.stringify(S)); } catch {} },
};
const S = Object.assign({ level: null, premium: false, stats: {}, sessions: [], days: [] }, store.load());

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const today = () => new Date().toISOString().slice(0, 10);
const shuffle = (a) => { a = a.slice(); for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
const fcfa = (n) => n.toLocaleString("fr-FR") + " FCFA";
const subjectsOf = (level) => DATA.subjects.filter((s) => s.levels.includes(level));
const inLevel = (q) => subjectsOf(S.level).some((s) => s.id === q.s);
const examOf = () => CFG.exams[S.level] || null;
const blancName = () => (examOf() ? "Examen blanc" : "Devoir blanc");
const open = (q) => S.premium || q.free;
const qsOf = (sid) => DATA.questions.filter((q) => q.s === sid);
const subjName = (sid) => (DATA.subjects.find((s) => s.id === sid) || {}).name || "";

function mastery(sid) {
  const qs = qsOf(sid), done = qs.filter((q) => S.stats[q.id] && S.stats[q.id].last).length;
  return Math.round((100 * done) / qs.length);
}
function record(q, ok) {
  const st = S.stats[q.id] || { ok: 0, ko: 0 };
  st[ok ? "ok" : "ko"]++; st.last = ok; S.stats[q.id] = st;
  if (!S.days.includes(today())) S.days.push(today());
  store.save();
}
function streak() {
  let n = 0; const d = new Date();
  if (!S.days.includes(today())) d.setDate(d.getDate() - 1);
  while (S.days.includes(d.toISOString().slice(0, 10))) { n++; d.setDate(d.getDate() - 1); }
  return n;
}

// ---------- Choix de la classe
function viewLevel() {
  $view.innerHTML = `<h1>Tu es en quelle classe ?</h1>
    <p class="muted">Tu pourras changer plus tard en touchant ta classe en haut de l'écran.</p>
    <div class="grid">${DATA.levels.map((l) => `<button class="subj lvl" data-l="${esc(l)}"${l === S.level ? ' aria-pressed="true"' : ""}>
      <b>${esc(l)}</b><span class="small muted">${CFG.exams[l] ? "Année du " + CFG.exams[l][0] : subjectsOf(l).length + " matières"}</span></button>`).join("")}</div>`;
  $view.querySelectorAll("[data-l]").forEach((b) => b.onclick = () => { S.level = b.dataset.l; store.save(); go("accueil"); render(); });
}

// ---------- Accueil
function viewHome() {
  const ex = examOf();
  const days = ex ? Math.max(0, Math.ceil((new Date(ex[1]) - new Date(today())) / 864e5)) : 0;
  const answered = Object.values(S.stats).reduce((n, s) => n + s.ok + s.ko, 0);
  const free = DATA.questions.filter((q) => q.free && inLevel(q));
  const daily = free[Math.floor(new Date(today()).getTime() / 864e5) % free.length];
  const subs = subjectsOf(S.level).map((s) => `
    <a class="subj" href="#quiz/${s.id}" style="text-decoration:none;color:inherit">
      <b>${esc(s.name)}</b>
      <span class="small muted">${S.premium ? s.count : s.free} questions${S.premium ? "" : ` · <span class="lock">🔒 ${s.count - s.free} premium</span>`}</span>
      <span class="bar"><i style="width:${mastery(s.id)}%"></i></span>
    </a>`).join("");
  $view.innerHTML = `
    <div class="card">
      <div class="row">${ex ? `<div><p class="small muted">${ex[0]} ${ex[1].slice(0, 4)}, date indicative</p><p class="count">J−${days}</p></div>`
        : `<div><p class="small muted">Réponses données</p><p class="count">${answered}</p></div>`}
      <div style="text-align:right"><p class="small muted">Série en cours</p><p class="count">${streak()} 🔥</p></div></div>
    </div>
    <div class="card" id="daily">
      <h2><span class="hi">Question du jour</span></h2>
      <p class="small muted">${esc(subjName(daily.s))}</p>
      ${questionBlock(daily)}
    </div>
    <h2>Choisis une matière</h2>
    <div class="grid">${subs}</div>
    <div class="btns">
      <a class="btn hi-btn" href="#examen">${blancName()} : ${EXAM_LEN} questions en ${EXAM_MIN} min${S.premium ? "" : " 🔒"}</a>
      <button class="btn alt" id="share">Partager l'appli à un camarade</button>
    </div>`;
  bindQuestion($view.querySelector("#daily"), daily, () => {});
  $view.querySelector("#share").onclick = share;
}

function questionBlock(q) {
  return `<p class="q">${esc(q.q)}</p><div class="choices">${q.c.map((c, i) =>
    `<button class="choice" data-i="${i}"><span class="l">${LETTERS[i]}</span><span>${esc(c)}</span></button>`).join("")}</div>
    <div class="expl" hidden></div>`;
}
function bindQuestion(root, q, done, showExpl = true) {
  root.querySelectorAll(".choice").forEach((b) => b.onclick = () => {
    const i = +b.dataset.i, ok = i === q.a;
    root.querySelectorAll(".choice").forEach((x) => { x.disabled = true; if (+x.dataset.i === q.a && showExpl) x.classList.add("ok"); });
    if (showExpl) {
      if (!ok) b.classList.add("ko");
      const ex = root.querySelector(".expl");
      ex.innerHTML = `<b class="${ok ? "msg-ok" : "msg-ko"}">${ok ? "Bonne réponse !" : "Pas tout à fait."}</b> ${esc(q.e)}`;
      ex.hidden = false;
    } else b.classList.add("ok");
    record(q, ok); done(ok, i);
  });
}

// ---------- Quiz par matière, erreurs, examen blanc
function runQuiz(title, qs, back, { exam = false } = {}) {
  clearInterval(timer);
  if (!qs.length) { $view.innerHTML = `<div class="card"><h2>${esc(title)}</h2><p class="muted">Aucune question ici pour l'instant.</p><a class="btn" href="${back}">Retour</a></div>`; return; }
  let k = 0, score = 0; const answers = [];
  const end = Date.now() + EXAM_MIN * 60e3;
  if (exam) timer = setInterval(() => {
    const left = Math.max(0, end - Date.now()), el = document.getElementById("timer");
    if (el) el.textContent = `${Math.floor(left / 60e3)}:${String(Math.floor(left / 1e3) % 60).padStart(2, "0")}`;
    if (!left) finish();
  }, 500);
  function step() {
    const q = qs[k];
    $view.innerHTML = `<div class="progress"><span>${esc(title)}</span><span>${exam ? `<span class="timer" id="timer"></span> · ` : ""}${k + 1} / ${qs.length}</span></div>
      <div class="bar"><i style="width:${(100 * k) / qs.length}%"></i></div>
      <div class="card" id="qc">${exam ? `<p class="small muted">${esc(subjName(q.s))}</p>` : ""}${questionBlock(q)}</div>
      <button class="btn" id="next" hidden>${k + 1 < qs.length ? "Question suivante" : "Voir mon score"}</button>`;
    const next = document.getElementById("next");
    bindQuestion(document.getElementById("qc"), q, (ok, i) => {
      score += ok; answers.push({ q, i, ok });
      if (exam) { k + 1 < qs.length ? (k++, step()) : finish(); } else next.hidden = false;
    }, !exam);
    next.onclick = () => (k + 1 < qs.length ? (k++, step()) : finish());
    window.scrollTo(0, 0);
  }
  function finish() {
    clearInterval(timer);
    const total = exam ? qs.length : answers.length, note = Math.round((20 * score) / total * 10) / 10;
    S.sessions.push({ t: title, score, total, d: today() }); store.save();
    const mot = note >= 16 ? "Excellent, continue comme ça !" : note >= 12 ? "Bien joué, encore un effort." : note >= 10 ? "C'est juste, revois tes erreurs." : "Courage, revois les corrections et recommence.";
    const fixes = exam ? `<h2>Corrections</h2><div class="list">${qs.map((q) => { const a = answers.find((x) => x.q === q);
      return `<div class="card"><p class="small muted">${esc(subjName(q.s))}</p><p><b>${esc(q.q)}</b></p>
        <p class="${a && a.ok ? "msg-ok" : "msg-ko"}">${a ? (a.ok ? "✓ " : "✗ Ta réponse : " + esc(q.c[a.i]) + " · ") : "Sans réponse · "}Bonne réponse : ${esc(q.c[q.a])}</p>
        <p class="small muted">${esc(q.e)}</p></div>`; }).join("")}</div>` : "";
    $view.innerHTML = `<div class="card" style="text-align:center"><p class="muted">${esc(title)}</p><p class="score">${note} / 20</p>
      <p>${score} bonne${score > 1 ? "s" : ""} réponse${score > 1 ? "s" : ""} sur ${total}</p><p><b>${mot}</b></p></div>
      ${!S.premium ? `<div class="card"><p>Il y a encore beaucoup de questions dans cette matière, avec l'examen blanc chronométré.</p><a class="btn hi-btn" href="#premium">Débloquer tout pour ${fcfa(CFG.price_fcfa)}</a></div>` : ""}
      <div class="btns"><button class="btn" id="again">Recommencer</button><a class="btn alt" href="${back}">Retour</a></div>${fixes}`;
    document.getElementById("again").onclick = () => render();
    window.scrollTo(0, 0);
  }
  step();
}

function viewQuiz(sid) {
  const s = DATA.subjects.find((x) => x.id === sid);
  if (!s) return go("accueil");
  runQuiz(`${S.level} · ${s.name}`, shuffle(qsOf(sid).filter(open)).slice(0, QUIZ_LEN), "#accueil");
}
function viewExam() {
  if (!S.premium) return viewPremium(`Le ${blancName().toLowerCase()} fait partie du pack premium.`);
  const qs = shuffle(DATA.questions.filter(inLevel)).slice(0, EXAM_LEN);
  runQuiz(`${blancName()} ${S.level}`, qs, "#accueil", { exam: true });
}
function viewErrors() {
  const wrong = DATA.questions.filter((q) => open(q) && inLevel(q) && S.stats[q.id] && S.stats[q.id].last === false);
  if (location.hash === "#erreurs/go") return runQuiz(`Mes erreurs ${S.level}`, shuffle(wrong).slice(0, QUIZ_LEN), "#erreurs");
  const by = {}; wrong.forEach((q) => (by[q.s] = (by[q.s] || 0) + 1));
  $view.innerHTML = `<h1>Mes erreurs</h1>
    <p class="muted">Les questions de ${S.level} que tu as ratées la dernière fois. Quand tu les réussis, elles disparaissent de la liste.</p>
    ${wrong.length ? `<div class="card">${Object.entries(by).map(([sid, n]) => `<div class="row"><span>${esc(subjName(sid))}</span><b>${n}</b></div>`).join("")}</div>
      <a class="btn" href="#erreurs/go">Revoir ${Math.min(wrong.length, QUIZ_LEN)} erreur${wrong.length > 1 ? "s" : ""}</a>`
    : `<div class="card"><p>Aucune erreur à revoir. Fais un quiz depuis l'accueil.</p><a class="btn" href="#accueil">Choisir une matière</a></div>`}`;
}

// ---------- Progrès
function viewProgress() {
  const answered = Object.values(S.stats).reduce((n, s) => n + s.ok + s.ko, 0);
  const good = Object.values(S.stats).reduce((n, s) => n + s.ok, 0);
  const rows = subjectsOf(S.level).map((s) => `<div><div class="row small"><span>${esc(s.name)}</span><b>${mastery(s.id)} %</b></div><div class="bar"><i style="width:${mastery(s.id)}%"></i></div></div>`).join("");
  const last = S.sessions.slice(-8).reverse().map((x) => `<div class="row small"><span>${esc(x.t)}<br><span class="muted">${x.d}</span></span><b>${Math.round((200 * x.score) / x.total) / 10} / 20</b></div>`).join("");
  $view.innerHTML = `<h1>Mes progrès</h1>
    <div class="card"><div class="row"><div><p class="small muted">Réponses</p><p class="count">${answered}</p></div>
      <div><p class="small muted">Réussite</p><p class="count">${answered ? Math.round((100 * good) / answered) : 0} %</p></div>
      <div><p class="small muted">Série</p><p class="count">${streak()} 🔥</p></div></div></div>
    <div class="card"><h2>Matières maîtrisées en ${S.level}</h2>${rows}<p class="small muted">Part des questions réussies la dernière fois.</p></div>
    <div class="card"><h2>Derniers quiz</h2>${last || '<p class="muted">Pas encore de quiz.</p>'}</div>`;
}

// ---------- Premium : paiement Wave puis code reçu par WhatsApp
async function sha256(s) {
  const b = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("");
}
function viewPremium(reason = "") {
  const total = DATA.questions.length, wa = CFG.whatsapp, wave = CFG.wave_number;
  const msg = encodeURIComponent(`Bonjour, j'ai payé ${fcfa(CFG.price_fcfa)} par Wave pour le pack premium Révision BAC BFEM. Voici ma capture :`);
  $view.innerHTML = `<h1>Pack premium</h1>
    ${reason ? `<p><b>${esc(reason)}</b></p>` : ""}
    ${S.premium ? `<div class="card"><p class="msg-ok">Ton pack premium est actif. Toutes les questions et les examens blancs sont débloqués.</p><a class="btn" href="#accueil">Réviser</a></div>` : `
    <div class="card">
      <p class="count">${fcfa(CFG.price_fcfa)}</p><p class="muted">Payé une seule fois, valable jusqu'à l'examen.</p>
      <ul class="steps"><li>Les <b>${total}</b> questions de la 6e à la Terminale, toutes corrigées</li><li>Les examens et devoirs blancs chronométrés, notés sur 20</li><li>Les nouvelles questions ajoutées pendant l'année</li></ul>
    </div>
    <div class="card"><h2>Comment payer</h2>
      ${wave ? `<ol class="steps">
        <li>Envoie <b>${fcfa(CFG.price_fcfa)}</b> par Wave au <b>${esc(wave)}</b>.</li>
        <li>Envoie la capture du paiement sur WhatsApp.</li>
        <li>Tu reçois ton code. Entre-le ci-dessous.</li></ol>
        ${wa ? `<a class="btn hi-btn" href="https://wa.me/${esc(wa)}?text=${msg}" target="_blank" rel="noopener">Envoyer la capture sur WhatsApp</a>` : ""}`
      : `<p class="muted">Le paiement par Wave arrive très bientôt. Si tu as déjà un code, entre-le ci-dessous.</p>`}
    </div>
    <div class="card"><h2>J'ai un code</h2>
      <input class="code" id="code" placeholder="XXXX-XXXX" autocomplete="off" maxlength="9">
      <button class="btn" id="unlock">Débloquer</button><p id="codemsg" class="small"></p></div>`}`;
  const btn = document.getElementById("unlock");
  if (btn) btn.onclick = async () => {
    const raw = document.getElementById("code").value.trim().toUpperCase().replace(/\s/g, "");
    const code = raw.length === 8 ? raw.slice(0, 4) + "-" + raw.slice(4) : raw;
    const ok = CFG.codes.includes(await sha256(CFG.salt + code));
    const m = document.getElementById("codemsg");
    if (ok) { S.premium = true; S.code = code; store.save(); m.className = "msg-ok"; m.textContent = "Code accepté !"; setTimeout(render, 700); }
    else { m.className = "msg-ko"; m.textContent = "Code inconnu. Vérifie les lettres et les chiffres."; }
  };
}

function share() {
  const url = location.href.split("#")[0], text = `Je révise mes cours de la 6e à la Terminale avec cette appli gratuite, avec les corrections expliquées : ${url}`;
  if (navigator.share) navigator.share({ title: "Révision BAC BFEM", text, url }).catch(() => {});
  else window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, "_blank");
}

// ---------- Navigation
function go(h) { location.hash = h; }
function render() {
  clearInterval(timer);
  const [tab, arg] = (location.hash.slice(1) || "accueil").split("/");
  document.getElementById("exam-tag").textContent = S.level || "";
  if (!S.level && tab !== "classe") return viewLevel();
  document.querySelectorAll(".tabs a").forEach((a) => { if (a.dataset.tab === tab) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
  ({ classe: viewLevel, quiz: () => viewQuiz(arg), examen: viewExam, erreurs: viewErrors, progres: viewProgress, premium: () => viewPremium() }[tab] || viewHome)();
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", render);

let deferred = null;
window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); deferred = e; document.getElementById("install").hidden = false; });
document.getElementById("install").onclick = () => { if (deferred) { deferred.prompt(); deferred = null; document.getElementById("install").hidden = true; } };
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});

Promise.all([fetch("data/questions.json").then((r) => r.json()), fetch("data/config.json").then((r) => r.json())])
  .then(([d, c]) => { DATA = d; CFG = c; render(); })
  .catch(() => { $view.innerHTML = `<div class="card"><p>Impossible de charger les questions. Vérifie ta connexion puis recharge la page.</p></div>`; });
