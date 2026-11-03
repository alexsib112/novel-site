// SPA-логика: роутинг по hash, рендер каталога/новеллы/читалки.

const view = document.getElementById("view");
const genresBar = document.getElementById("genresBar");
const searchInput = document.getElementById("searchInput");
const themeToggle = document.getElementById("themeToggle");
const langChip = document.getElementById("langChip");

let currentGenre = "Все";
let currentLang = "ru";
let readerSettings = { theme: "light", size: 17.5, serif: true };

// ---------- Утилиты ----------
function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function ratingColor(r) { return r >= 9 ? "★ " + r.toFixed(1) : "☆ " + r.toFixed(1); }

function coverHTML(n, small) {
  return `
    <div class="cover" style="background:${n.gradient}">
      <span class="cover__letter">${esc(n.letter)}</span>
      <span class="cover__badge">${esc(n.status)}</span>
      <span class="cover__rating">★ ${n.rating.toFixed(1)}</span>
    </div>`;
}

function cardHTML(n) {
  return `
    <div class="card" data-id="${n.id}">
      ${coverHTML(n)}
      <div class="card__title">${esc(n.title)}</div>
      <div class="card__meta">${esc(n.author)} · ${n.chapters} гл.</div>
    </div>`;
}

// ---------- Ленивая загрузка глав ----------
const _chunkCache = {};

async function loadIndex(n) {
  if (n.chaptersIndex) return n.chaptersIndex;
  if (!n.indexUrl) return (n.chaptersIndex = []);
  try {
    const j = await (await fetch(n.indexUrl, { cache: "no-cache" })).json();
    n.chaptersIndex = j.chapters || j;
  } catch (e) {
    console.error("не удалось загрузить список глав:", e);
    n.chaptersIndex = [];
  }
  return n.chaptersIndex;
}

function chunkUrl(n, num) {
  const size = n.chunkSize || 100;
  const no = Math.floor((num - 1) / size) + 1;
  return n.indexUrl.replace(/index\.json$/, `chunk-${String(no).padStart(4, "0")}.json`);
}

async function loadChapter(n, num) {
  if (n.chaptersData) return n.chaptersData.find(c => c.n === num) || null;
  if (!n.lazy) return null;
  const cache = (_chunkCache[n.id] = _chunkCache[n.id] || {});
  const url = chunkUrl(n, num);
  if (!cache[url]) {
    try {
      const j = await (await fetch(url, { cache: "no-cache" })).json();
      const m = {};
      (j.chapters || j).forEach(c => { m[c.n] = c; });
      cache[url] = m;
    } catch (e) {
      console.error("не удалось загрузить главу:", e);
      cache[url] = {};
    }
  }
  return cache[url][num] || null;
}

function chapterList(n) {
  if (n.chaptersData) return n.chaptersData;
  return n.chaptersIndex || [];
}

function chapterNeighbors(n, num) {
  const arr = chapterList(n).map(c => c.n).sort((a, b) => a - b);
  if (!arr.length) {
    return { prev: num > 1 ? num - 1 : null, next: num < n.chapters ? num + 1 : null };
  }
  let prev = null, next = null;
  for (const x of arr) {
    if (x < num) prev = x;
    else if (x > num && next === null) next = x;
  }
  return { prev, next };
}

// ---------- Рендер ----------
function renderGenres() {
  genresBar.innerHTML = GENRES.map(g =>
    `<button class="chip ${g === currentGenre ? "active" : ""}" data-genre="${esc(g)}">${esc(g)}</button>`
  ).join("");
  genresBar.querySelectorAll(".chip").forEach(b =>
    b.addEventListener("click", () => {
      currentGenre = b.dataset.genre;
      renderGenres();
      renderCatalog();
    })
  );
}

function renderCatalog() {
  let list = NOVELS;
  const q = searchInput.value.trim().toLowerCase();
  if (currentGenre !== "Все") list = list.filter(n => n.genres.includes(currentGenre));
  if (q) list = list.filter(n =>
    (n.title + " " + n.author + " " + n.orig).toLowerCase().includes(q)
  );

  const top = NOVELS.filter(n => n.translated);
  const featured = top.length ? top[0] : NOVELS[0];

  view.innerHTML = `
    <section class="hero">
      <h1>Веб-новеллы — на твоём языке</h1>
      <p>Собираем популярные новеллы со всего мира и переводим их с помощью ИИ, чтобы ты мог читать на родном языке.</p>
      <button class="primary" data-open="${featured.id}">▶ Начать читать</button>
    </section>

    ${list.length ? `
      <div class="section-head">
        <h2>${currentGenre === "Все" ? "Популярное" : currentGenre}</h2>
        <span class="more">${list.length} новелл</span>
      </div>
      <div class="grid">${list.map(cardHTML).join("")}</div>
    ` : `
      <div class="empty">
        <h3>Ничего не найдено</h3>
        <p>Попробуй другой запрос или жанр.</p>
      </div>
    `}
  `;

  view.querySelectorAll(".card").forEach(c =>
    c.addEventListener("click", () => location.hash = "#/novel/" + c.dataset.id)
  );
  const open = view.querySelector("[data-open]");
  if (open) open.addEventListener("click", () => location.hash = "#/novel/" + open.dataset.open);
}

async function renderNovel(id) {
  const n = NOVELS.find(x => x.id === id);
  if (!n) return location.hash = "#/catalog";

  view.innerHTML = `<div class="empty"><h3>Загрузка…</h3></div>`;

  let list = [];
  if (n.chaptersData) list = n.chaptersData.map(c => ({ n: c.n, title: c.title }));
  else if (n.lazy) list = (await loadIndex(n)).map(c => ({ n: c.n, title: c.title }));

  const ch = list;
  const hasList = !!n.chaptersData || n.lazy;
  view.innerHTML = `
    <button class="btn-secondary" style="margin-bottom:14px" onclick="history.back()">← Назад</button>
    <div class="novel-hero">
      ${coverHTML(n)}
      <div class="novel-info">
        <span class="author">${esc(n.author)}</span>
        <h1>${esc(n.title)}</h1>
        <div class="tags">${n.genres.map(g => `<span class="tag">${esc(g)}</span>`).join("")}</div>
        <div class="novel-stats">
          <span><b>${n.rating.toFixed(1)}</b>рейтинг</span>
          <span><b>${n.likes.toLocaleString("ru-RU")}</b>закладок</span>
          <span><b>${n.chapters}</b>глав</span>
          <span><b>${esc(n.status)}</b>статус</span>
        </div>
        <p class="synopsis">${esc(n.synopsis)}</p>
        <div class="novel-actions">
          <button class="primary" data-read="1">📖 Читать</button>
          <button class="btn-secondary" data-lang>🌐 ${currentLang.toUpperCase()}</button>
        </div>
      </div>
    </div>

    <div class="chapters">
      <div class="chapters__head">
        <h3>Список глав</h3>
        <span class="more">${hasList ? "переведено: " + ch.length + " / " + n.chapters : "перевод в очереди"}</span>
      </div>
      <div class="chapter-list">
        ${ch.map(c => `
          <div class="chapter-row" data-ch="${c.n}">
            <span class="num">${c.n}</span>
            <span class="title">${esc(c.title)}</span>
            <span class="len">~2 000</span>
          </div>`).join("")}
      </div>
    </div>
  `;

  const first = ch.length ? ch[0].n : 1;
  view.querySelector("[data-read]").addEventListener("click", () =>
    location.hash = `#/reader/${id}/${first}`);
  view.querySelector("[data-lang]").addEventListener("click", openLangModal);
  view.querySelectorAll(".chapter-row").forEach(r =>
    r.addEventListener("click", () => location.hash = `#/reader/${id}/${r.dataset.ch}`)
  );
}

async function renderReader(id, chNum) {
  const n = NOVELS.find(x => x.id === id);
  if (!n) return location.hash = "#/catalog";
  if (n.lazy && !n.chaptersIndex) await loadIndex(n);

  const chIdx = Math.max(1, parseInt(chNum) || 1);
  const total = n.chapters;

  view.innerHTML = `<div class="empty"><h3>Загрузка главы…</h3></div>`;

  const sample = await loadChapter(n, chIdx);
  const title = sample ? sample.title : `Глава ${chIdx}`;
  const paragraphs = sample
    ? sample.content
    : ["Перевод этой главы ещё готовится. ИИ-переводчик поставил главу в очередь и скоро вернёт её на твоём языке.", "А пока — загляни в переведённые главы этой или другой новеллы."];

  const prose = paragraphs.map(p =>
    `<p class="${/^«|^—/.test(p) ? "dialogue" : ""}">${esc(p)}</p>`
  ).join("");

  const { prev, next } = chapterNeighbors(n, chIdx);

  view.innerHTML = `
    <div class="reader">
      <div class="reader__toolbar">
        <button class="btn-secondary" onclick="location.hash='#/novel/${id}'">← К новелле</button>
        <div class="reader__tools">
          <button class="tool" data-size="-1">А−</button>
          <button class="tool" data-size="+1">А+</button>
          <button class="tool" data-font>Шрифт</button>
          <button class="tool" data-theme>Тема</button>
          <button class="tool" data-lang>🌐 ${currentLang.toUpperCase()}</button>
        </div>
      </div>
      <div class="reader__paper">
        <div class="novel-name">${esc(n.title)}</div>
        <h2 class="chapter-title">${esc(title)}</h2>
        <div class="prose" id="prose">${prose}</div>
      </div>
      <div class="reader__pager">
        <button class="btn-secondary" data-prev ${prev == null ? "disabled" : ""}>← Пред.</button>
        <button class="primary" data-next ${next == null ? "disabled" : ""}>След. →</button>
      </div>
    </div>
  `;

  view.querySelector("[data-prev]").addEventListener("click", () =>
    prev != null && (location.hash = `#/reader/${id}/${prev}`));
  view.querySelector("[data-next]").addEventListener("click", () =>
    next != null && (location.hash = `#/reader/${id}/${next}`));
  view.querySelector("[data-size='+1']").addEventListener("click", () => adjustSize(1));
  view.querySelector("[data-size='-1']").addEventListener("click", () => adjustSize(-1));
  view.querySelector("[data-font]").addEventListener("click", () => {
    readerSettings.serif = !readerSettings.serif;
    applyReaderSettings();
  });
  view.querySelector("[data-theme]").addEventListener("click", cycleTheme);
  view.querySelector("[data-lang]").addEventListener("click", openLangModal);

  applyReaderSettings();
  window.scrollTo(0, 0);
}

// ---------- Настройки читалки ----------
function applyReaderSettings() {
  const prose = document.getElementById("prose");
  if (!prose) return;
  prose.style.fontSize = readerSettings.size + "px";
  prose.style.fontFamily = readerSettings.serif ? '"PT Serif", serif' : '"Inter", sans-serif';
  document.body.classList.remove("reader-sepia", "reader-dark");
  if (readerSettings.theme === "sepia") document.body.classList.add("reader-sepia");
  if (readerSettings.theme === "dark") document.body.classList.add("reader-dark");
}
function adjustSize(d) {
  readerSettings.size = Math.min(24, Math.max(14, readerSettings.size + d));
  applyReaderSettings();
}
function cycleTheme() {
  const order = ["light", "sepia", "dark"];
  readerSettings.theme = order[(order.indexOf(readerSettings.theme) + 1) % 3];
  applyReaderSettings();
}

// ---------- Модалка языка ----------
function openLangModal() {
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop open";
  backdrop.innerHTML = `
    <div class="modal">
      <h3>Язык чтения</h3>
      ${LANGS.map(l => `
        <button class="lang-option ${l.code === currentLang ? "active" : ""}" data-code="${l.code}">
          <span>${l.flag} ${l.label}</span>
          ${l.code === currentLang ? "✓" : ""}
        </button>`).join("")}
    </div>`;
  document.body.appendChild(backdrop);
  backdrop.querySelectorAll(".lang-option").forEach(b =>
    b.addEventListener("click", () => {
      currentLang = b.dataset.code;
      langChip.textContent = "🌐 " + currentLang.toUpperCase();
      backdrop.remove();
      const h = location.hash;
      if (h.startsWith("#/reader/")) {
        const [, , id, ch] = h.split("/");
        renderReader(id, ch);
      } else if (h.startsWith("#/novel/")) {
        renderNovel(h.split("/")[2]);
      }
    })
  );
  backdrop.addEventListener("click", e => { if (e.target === backdrop) backdrop.remove(); });
}

// ---------- Тема сайта ----------
function toggleSiteTheme() {
  document.documentElement.classList.toggle("dark");
}

// ---------- Роутер ----------
function route() {
  const h = location.hash || "#/catalog";
  const parts = h.replace(/^#\//, "").split("/");
  document.body.classList.remove("reader-sepia", "reader-dark");
  if (parts[0] === "novel") return renderNovel(parts[1]);
  if (parts[0] === "reader") return renderReader(parts[1], parts[2]);
  return renderCatalog();
}

// ---------- Инициализация ----------
searchInput.addEventListener("input", () => {
  if (!location.hash.startsWith("#/reader") && !location.hash.startsWith("#/novel")) renderCatalog();
});
themeToggle.addEventListener("click", toggleSiteTheme);
langChip.addEventListener("click", openLangModal);
window.addEventListener("hashchange", route);

renderGenres();
route();
