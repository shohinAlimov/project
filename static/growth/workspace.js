const root = document.querySelector("#root"),
  dialog = document.querySelector("#dialog"),
  modal = document.querySelector("#modal");
let lang = localStorage.getItem("language") || "uz",
  state = null,
  member = null,
  page = "overview",
  isDemo = false,
  config = {},
  memberships = [],
  menuOpen = false;
let signup = false,
  noticeTimer,
  formAction,
  chatTurns = [],
  chatDraft = "",
  chatError = "",
  chatPending = null,
  chatRetry = null,
  simulation = "",
  inviteLink = "",
  guideStep = 0;
const t = (uz, ru) => (lang === "ru" ? ru : uz);
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const money = (v) => new Intl.NumberFormat("ru-RU").format(v || 0) + " UZS";
const today = () =>
  new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Tashkent" }).format(
    new Date(),
  );
const mark =
  '<span class="mark" aria-hidden="true"><i></i><i></i><i></i><i></i></span>';
const wordmark = '<div class="wordmark">' + mark + "AI Growth Assistant</div>";
const btn = (act, label, cls = "button", id = "") =>
  '<button type="button" class="' +
  cls +
  '" data-act="' +
  act +
  '" data-id="' +
  esc(id) +
  '">' +
  esc(label) +
  "</button>";
const langs = () =>
  '<div class="langs">' +
  ["uz", "ru"]
    .map((l) =>
      btn("lang", l === "uz" ? "UZ" : "РУ", l === lang ? "active" : "", l),
    )
    .join("") +
  "</div>";
const empty = () =>
  '<p class="blank">' +
  t("Hozircha yozuvlar yo‘q.", "Записей пока нет.") +
  "</p>";
const panel = (title, html) =>
  '<section class="panel"><h2>' + esc(title) + "</h2>" + html + "</section>";
const item = (a, b = "", small = "") =>
  '<div class="item"><div><strong>' +
  esc(a) +
  "</strong><small>" +
  esc(small) +
  "</small></div>" +
  b +
  "</div>";
const list = (arr, fn) => (arr?.length ? arr.map(fn).join("") : empty());
const field = (name, label, value = "", type = "text", required = false) =>
  "<label>" +
  esc(label) +
  '<input name="' +
  name +
  '" type="' +
  type +
  '" value="' +
  esc(value) +
  '" ' +
  (required ? "required" : "") +
  (type === "number" ? ' min="0" step="1"' : "") +
  "></label>";
const area = (name, label, value = "") =>
  '<label class="wide">' +
  esc(label) +
  '<textarea maxlength="2000" name="' +
  name +
  '">' +
  esc(value) +
  "</textarea></label>";
const select = (name, label, options, value = "") =>
  "<label>" +
  esc(label) +
  '<select name="' +
  name +
  '">' +
  options
    .map(
      ([v, s]) =>
        '<option value="' +
        esc(v) +
        '" ' +
        (String(value) === String(v) ? "selected" : "") +
        ">" +
        esc(s) +
        "</option>",
    )
    .join("") +
  "</select></label>";
const fileUrl = (id) =>
  "/growth/files/" +
  encodeURIComponent(id) +
  "?workspace=" +
  encodeURIComponent(member);
const save = () => t("Saqlash", "Сохранить");
const form = (inputs, label = save()) =>
  '<form class="formgrid">' +
  inputs +
  '<p class="error wide" role="alert"></p><button class="button wide" type="submit">' +
  esc(label) +
  "</button></form>";
const topicName = (k) =>
  ({
    price: t("Narx", "Цена"),
    catalog: t("Katalog", "Каталог"),
    description: t("Tavsif", "Описание"),
    faq: t("Tasdiqlangan javob", "Готовый ответ"),
    delivery: t("Yetkazib berish", "Доставка"),
    payment: t("To‘lov", "Оплата"),
    availability: t("Mavjudligi", "Наличие"),
    variants: t("Dizayn", "Дизайн"),
    lead_time: t("Muddat", "Срок"),
    handoff: t("Egasiga savol", "Вопрос владельцу"),
  })[k] || k;
const pages = () => ({
  overview: ["◫", t("Umumiy ko‘rinish", "Обзор")],
  finances: ["↗", t("Moliya", "Финансы")],
  marketing: ["✦", t("Marketing", "Маркетинг")],
  production: ["▦", t("Ishlab chiqarish", "Производство")],
  assistant: ["✧", t("Shaxsiy yordamchi", "Личный помощник")],
  inbox: ["✉", t("Xabarlar", "Входящие")],
  settings: ["⚙", t("Sozlamalar", "Настройки")],
  billing: ["▤", t("Tarif va to‘lov", "Тариф и оплата")],
});
function allowed() {
  return state.role === "owner"
    ? Object.keys(pages())
    : [
        "overview",
        state.role === "finance" ? "finances" : "marketing",
        "assistant",
      ];
}
function notice(msg) {
  const n = document.querySelector("#notice");
  n.textContent = msg;
  n.hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => (n.hidden = true), 6000);
}
async function api(path, method = "GET", data = null, retry = true) {
  const headers = {};
  if (member) headers["X-Business-Id"] = member;
  const opts = { method, headers, credentials: "same-origin" };
  if (data instanceof FormData) opts.body = data;
  else if (data !== null) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(data);
  }
  const r = await fetch("/growth/" + path, opts);
  if (
    r.status === 401 &&
    retry &&
    !path.startsWith("auth/") &&
    path !== "refresh"
  ) {
    const refresh = await fetch("/growth/refresh", { method: "POST" });
    if (refresh.ok) return api(path, method, data, false);
  }
  if (!r.ok) {
    const e = await r.json().catch(() => ({}));
    throw Object.assign(
      new Error(
        typeof e.detail === "string"
          ? e.detail
          : t("Ma’lumotlarni tekshiring", "Проверьте введённые данные"),
      ),
      { status: r.status },
    );
  }
  return r.json();
}
function modalForm(title, content, action, label) {
  modal.innerHTML = "<h2>" + esc(title) + "</h2>" + form(content, label);
  formAction = action;
  if (!dialog.open) dialog.showModal();
}
function close() {
  dialog.close();
  formAction = null;
}
// Supabase returns an implicit-auth fragment. This app uses server-side password
// sessions. Consume the confirmation status and remove the fragment immediately.
function confirmationStatus() {
  const params = new URLSearchParams(location.hash.slice(1));
  if (
    !params.has("access_token") &&
    !params.has("error") &&
    !params.has("error_code")
  )
    return "";
  history.replaceState(null, "", location.pathname + location.search);
  if (params.has("error") || params.has("error_code")) return "invalid";
  return params.get("type") === "signup" ? "confirmed" : "";
}
let confirmation = confirmationStatus();
let confirmationEmail = "";
function confirmationText() {
  if (confirmation === "invalid")
    return t(
      "Havola eskirgan yoki ishlatilgan. Avval kirib ko‘ring. Kerak bo‘lsa yangi xat so‘rang.",
      "Ссылка недействительна или уже использована. Попробуйте войти. При необходимости запросите новое письмо.",
    );
  if (confirmation === "confirmed")
    return t(
      "Pochta tasdiqlandi. Email va parolingiz bilan kiring.",
      "Почта подтверждена. Войдите со своим адресом и паролем.",
    );
  if (confirmation === "check")
    return t(
      "Oxirgi tasdiqlash xatini oching, so‘ng parolingiz bilan kiring.",
      "Откройте самое новое письмо для подтверждения, затем войдите со своим паролем.",
    );
  return "";
}
function authPage() {
  state = null;
  root.innerHTML =
    '<main class="entry"><section class="cover">' +
    wordmark +
    "<div><h1>" +
    t("Biznesingiz uchun ish joyi", "Рабочее место для вашего бизнеса") +
    "</h1><p>" +
    t(
      "Buyurtmalar, to‘lovlar va mijozlar savollari bir joyda.",
      "Заказы, платежи и вопросы клиентов в одном месте.",
    ) +
    '</p></div></section><section class="entrySide"><div class="toolrow">' +
    langs() +
    "</div><h2>" +
    (signup
      ? t("Hisob ochish", "Регистрация")
      : t("Xush kelibsiz", "Добро пожаловать")) +
    "</h2>" +
    (confirmation
      ? '<p class="tip" role="status">' + esc(confirmationText()) + "</p>"
      : "") +
    form(
      field(
        "email",
        t("Elektron pochta", "Электронная почта"),
        confirmationEmail,
        "email",
        true,
      ) + field("password", t("Parol", "Пароль"), "", "password", true),
      signup ? t("Hisob yaratish", "Создать аккаунт") : t("Kirish", "Войти"),
    ) +
    '<div class="actions">' +
    btn(
      "switchAuth",
      signup
        ? t("Hisobim bor", "У меня есть аккаунт")
        : t("Hisob ochish", "Создать аккаунт"),
      "textbtn",
    ) +
    (!signup && config.auth && confirmation
      ? btn(
          "resendConfirmation",
          t("Tasdiqlash xatini qayta yuborish", "Отправить письмо ещё раз"),
          "textbtn",
        )
      : "") +
    (config.demo
      ? btn("demo", t("Demo do‘konni ochish", "Открыть демомагазин"), "soft")
      : "") +
    '</div><a href="/legacy">' +
    t(
      "Telegram kodi bilan eski kabinetga kirish",
      "Войти в прежний кабинет по коду Telegram",
    ) +
    "</a></section></main>";
  root.querySelector("form").className = "stack";
  document.documentElement.lang = lang;
}
function otherLanguage(fields, obj) {
  return (
    '<details class="wide"><summary>' +
    t("Ikkinchi tildagi javoblar", "Ответы на втором языке") +
    '</summary><div class="stack">' +
    fields
      .map(([key, label]) => field(key + "_other", label, obj[key + "_other"]))
      .join("") +
    "</div></details>"
  );
}
function profileFields(p = {}) {
  return (
    field("name", t("Biznes nomi", "Название бизнеса"), p.name, "text", true) +
    select(
      "language",
      t("Asosiy til", "Основной язык"),
      [
        ["uz", "O‘zbekcha"],
        ["ru", "Русский"],
      ],
      p.language || lang,
    ) +
    select(
      "business_type",
      t("Biznes turi", "Тип бизнеса"),
      [
        ["shop", t("Onlayn do‘kon", "Интернет-магазин")],
        ["bakery", t("Uy qandolatxonasi", "Домашняя пекарня")],
      ],
      p.business_type,
    ) +
    field("stage", t("Biznes bosqichi", "Стадия бизнеса"), p.stage) +
    area("description", t("Biznes haqida", "О бизнесе"), p.description) +
    field("assortment", t("Mahsulotlar", "Ассортимент"), p.assortment) +
    field("customers", t("Mijozlar", "Покупатели"), p.customers) +
    field("goals", t("Maqsadlar", "Цели"), p.goals) +
    field(
      "followup",
      p.business_type === "bakery"
        ? t(
            "Allergenlar va tayyorlash shartlari",
            "Аллергены и условия приготовления",
          )
        : t(
            "Yetkazib beruvchilar va qaytarish shartlari",
            "Поставщики и условия возврата",
          ),
      p.followup,
    ) +
    field(
      "followup_extra",
      p.business_type === "bakery"
        ? t(
            "Bir kunda nechta buyurtma tayyorlaysiz?",
            "Сколько заказов готовите за день?",
          )
        : t(
            "Ombordagi qoldiq qanday tekshiriladi?",
            "Как проверяете остатки на складе?",
          ),
      p.followup_extra,
    ) +
    area(
      "delivery",
      t("Yetkazib berish shartlari", "Условия доставки"),
      p.delivery,
    ) +
    area("payment", t("To‘lov qoidalari", "Правила оплаты"), p.payment) +
    otherLanguage(
      [
        ["delivery", t("Yetkazib berish", "Доставка")],
        ["payment", t("To‘lov shartlari", "Условия оплаты")],
      ],
      p,
    ) +
    '<details class="wide"><summary>' +
    t("To‘lov havolalari", "Платёжные ссылки") +
    '</summary><div class="stack">' +
    field("payme", "Payme", p.payme, "url") +
    field("click", "Click", p.click, "url") +
    "</div></details>" +
    "<label>" +
    t("Brend yo‘nalishi", "Визуальное направление") +
    '<select data-brand><option value="">' +
    t("O‘zingiz tanlang", "Свой вариант") +
    '</option><option value="garden">' +
    t("Botanika", "Ботаника") +
    '</option><option value="clay">' +
    t("Terrakota", "Терракота") +
    "</option></select></label>" +
    field(
      "color",
      t("Brend rangi", "Цвет бренда"),
      p.color || "#286452",
      "color",
    ) +
    field("tone", t("Muloqot uslubi", "Тон общения"), p.tone) +
    field("logo", t("Logotip g‘oyasi", "Идея логотипа"), p.logo)
  );
}
function onboarding() {
  root.innerHTML =
    '<main class="sheet"><div class="toolrow">' +
    wordmark +
    langs() +
    "</div><h1>" +
    t("Biznes profilingiz", "Профиль бизнеса") +
    '</h1><p class="blank">' +
    (isDemo
      ? t(
          "Demo do‘kon · Sinov uchun alohida ma’lumotlar. ",
          "Демомагазин · Отдельные тестовые данные. ",
        )
      : "") +
    t(
      "Nomini kiriting. Qolgan savollarga keyin javob berishingiz mumkin.",
      "Введите название. Остальные ответы можно добавить позже.",
    ) +
    "</p>" +
    form(
      profileFields(
        isDemo
          ? {
              name: t("Demo · Rayhon qandolatxonasi", "Демо · Пекарня Райхон"),
              business_type: "bakery",
            }
          : {},
      ),
      t("Ish joyini yaratish", "Создать рабочее пространство"),
    ) +
    "</main>";
}
async function loadState() {
  const next = await api("state");
  if (state?.id !== next.id || state?.role !== next.role) {
    guideStep = 0;
    chatTurns = [];
    chatDraft = "";
    chatError = "";
    chatPending = null;
    chatRetry = null;
  }
  state = next;
  member = state.id;
  sessionStorage.setItem("business", member);
  lang = localStorage.getItem("language") || state.language;
  if (!allowed().includes(page)) page = "overview";
  try {
    chatTurns = (await api("assistant/history")).turns;
  } catch (err) {
    chatError = err.message;
  }
  render();
}
async function boot() {
  config = await api("config");
  let me;
  try {
    me = await api("me");
  } catch (e) {
    if (e.status === 401) {
      authPage();
      return;
    }
    throw e;
  }
  isDemo = me.demo;
  memberships = me.memberships;
  const invite = location.hash.match(/^#invite=([\w-]+)$/);
  if (invite) {
    const joined = await api("join", "POST", { question: invite[1] });
    member = joined.id;
    history.replaceState(null, "", "/");
    return boot();
  }
  if (!memberships.length) {
    member = null;
    onboarding();
    return;
  }
  member =
    memberships.find(
      (m) => m.business_id === (member || sessionStorage.getItem("business")),
    )?.business_id || memberships[0].business_id;
  await loadState();
}
function metrics() {
  const f = state.figures;
  if (!f) return "";
  return (
    '<div class="cards">' +
    [
      [t("Kelib tushgan daromad", "Полученный доход"), f.income],
      [t("Xarajatlar", "Расходы"), f.expense],
      [t("Qolgan to‘lovlar", "Остаток по заказам"), f.outstanding],
    ]
      .map(
        ([l, v]) =>
          '<div class="card"><small>' +
          l +
          "</small><strong>" +
          new Intl.NumberFormat("ru-RU").format(v) +
          "</strong><small>UZS</small></div>",
      )
      .join("") +
    "</div>"
  );
}
function txList(rows) {
  return list(rows, (r) =>
    item(
      r.category,
      '<strong class="' +
        r.kind +
        '">' +
        (r.kind === "income" ? "+" : "−") +
        esc(money(r.amount)) +
        "</strong>" +
        (r.file_id
          ? ' <a href="' +
            fileUrl(r.file_id) +
            '" target="_blank">' +
            t("Chek", "Чек") +
            "</a>"
          : ""),
      [r.day, r.note, r.payment_type ? paymentName(r.payment_type) : ""]
        .filter(Boolean)
        .join(" · "),
    ),
  );
}
function trend() {
  const rows = state.week_income || [],
    days = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date(today() + "T12:00:00Z");
    d.setUTCDate(d.getUTCDate() - i);
    days.push(d.toISOString().slice(0, 10));
  }
  const vals = days.map((d) => rows.find((r) => r.day === d)?.total || 0);
  return (
    '<div class="chart" aria-label="' +
    t("Oxirgi yetti kun", "Последние семь дней") +
    '">' +
    vals
      .map(
        (v, i) =>
          '<div title="' +
          days[i] +
          " · " +
          money(v) +
          '" style="height:' +
          Math.max(1, (100 * v) / Math.max(1, ...vals)) +
          '%"></div>',
      )
      .join("") +
    '</div><div class="chartfoot"><span>' +
    days[0] +
    "</span><span>" +
    days[6] +
    "</span></div>"
  );
}
function overview() {
  return (
    assistant() +
    metrics() +
    '<div class="cols">' +
    (state.figures
      ? panel(t("Haftalik tushum", "Поступления за неделю"), trend())
      : "") +
    panel(
      t("Ishlar", "Задачи"),
      (state.receipts
        ? item(
            t("Ko‘rib chiqiladigan cheklar", "Чеки на проверку"),
            btn("nav", String(state.receipts.length), "soft", "finances"),
          )
        : "") +
        (state.chats
          ? item(
              t("Egasi javob beradi", "Нужен владелец"),
              btn(
                "nav",
                String(state.chats.filter((c) => c.paused).length),
                "soft",
                "inbox",
              ),
            )
          : "") +
        item(
          t("Katalogdagi mahsulotlar", "Товары в каталоге"),
          String(state.products.length),
        ),
    ) +
    "</div>" +
    (state.journal
      ? panel(
          t("Oxirgi operatsiyalar", "Последние операции"),
          txList(state.journal.slice(0, 4)),
        )
      : "") +
    shared()
  );
}
function shared() {
  return panel(
    t("Jamoa yozuvlari", "Общие заметки"),
    '<div class="actions">' +
      btn("note", t("Yozuv qo‘shish", "Добавить заметку"), "soft") +
      btn(
        "notesSummary",
        t("Jamoa uchun AI xulosa", "AI-сводка для команды"),
        "plain",
      ) +
      "</div>" +
      list(state.notes, (r) =>
        item(
          r.body,
          "",
          r.summary
            ? t("Umumiy AI xulosa", "Общая AI-сводка")
            : r.created_at.slice(0, 10),
        ),
      ),
  );
}
const paymentName = (p) =>
  p === "deposit"
    ? t("Avans", "Аванс")
    : t("Yakuniy to‘lov", "Окончательный платёж");
function finances() {
  return (
    metrics() +
    '<div class="actions">' +
    btn("entry", t("Daromad qo‘shish", "Добавить доход"), "button", "income") +
    btn("entry", t("Xarajat qo‘shish", "Добавить расход"), "plain", "expense") +
    btn("upload", t("Chek yuklash", "Загрузить чек"), "plain") +
    btn("order", t("Buyurtma yaratish", "Создать заказ"), "plain") +
    "</div><br>" +
    panel(
      t("Qabul qilingan cheklar", "Полученные чеки"),
      list(state.receipts, (r) =>
        item(
          r.kind === "income"
            ? t("To‘lov skrinshoti", "Скриншот оплаты")
            : t("Xarajat cheki", "Чек расхода"),
          btn("review", t("Tekshirish", "Проверить"), "soft", r.id),
          r.fields.amount ? money(r.fields.amount) : r.created_at.slice(0, 10),
        ),
      ),
    ) +
    panel(
      t("Buyurtma qoldiqlari", "Остатки по заказам"),
      list(state.orders, (o) =>
        item(
          o.customer + " · " + o.product,
          esc(money(o.balance)),
          [money(o.total), o.due].filter(Boolean).join(" · "),
        ),
      ),
    ) +
    panel(t("Moliya jurnali", "Финансовый журнал"), txList(state.journal))
  );
}
function production() {
  return panel(
    t("Mahsulot katalogi", "Каталог товаров"),
    btn("product", t("Mahsulot qo‘shish", "Добавить товар")) +
      list(state.products, (p) =>
        item(
          p.name,
          btn("product", t("Tahrirlash", "Изменить"), "plain", p.id),
          [money(p.price), p.details.availability, p.details.sourcing]
            .filter(Boolean)
            .join(" · "),
        ),
      ),
  );
}
function postIdea(row) {
  const subject = row.product || t("katalog", "каталог");
  const ideas = {
    variants: t(
      "Mavjud dizaynlarni karuselda ko‘rsating.",
      "Соберите доступные варианты дизайна в карусель.",
    ),
    price: t(
      "Joriy narx va mavjud variantlar bilan mahsulot kartasini chiqaring.",
      "Опубликуйте карточку с текущей ценой и доступными вариантами.",
    ),
    delivery: t(
      "Yetkazish hududi va shartlari haqida post tayyorlang.",
      "Подготовьте пост об условиях и зоне доставки.",
    ),
    payment: t(
      "Buyurtmani qanday to‘lashni tushuntiring.",
      "Объясните, как оплатить заказ.",
    ),
    availability: t(
      "Hozir mavjud mahsulotlar tanlovini chiqaring.",
      "Покажите подборку товаров в наличии.",
    ),
  };
  return (
    subject +
    " · " +
    (ideas[row.topic] ||
      t(
        "Eng ko‘p beriladigan savolga javobni post qiling.",
        "Опубликуйте ответ на частый вопрос.",
      )) +
    " (" +
    row.count +
    ")"
  );
}
function marketing() {
  const first = state.topics[0];
  return (
    '<div class="cols">' +
    panel(
      t("Mijozlar savollari", "Вопросы покупателей"),
      list(state.topics, (r) =>
        item(
          topicName(r.topic) + (r.product ? " · " + r.product : ""),
          "<b>" + r.count + "</b>",
        ),
      ),
    ) +
    panel(
      t("Post g‘oyasi", "Идея публикации"),
      '<p class="blank">' +
        (first
          ? esc(postIdea(first))
          : t(
              "Mijozlar savollari kelganda bu yerda tavsiya paydo bo‘ladi.",
              "Когда появятся вопросы клиентов, здесь будет рекомендация.",
            )) +
        "</p>" +
        btn("visual", t("Mahsulot posti yaratish", "Создать карточку товара")),
    ) +
    "</div>" +
    panel(
      t("Tayyor postlar", "Готовые публикации"),
      (state.demo
        ? '<p class="tip">' +
          t("Demo · Shablon asosidagi PNG.", "Демо · PNG по шаблону.") +
          "</p>"
        : "") +
        list(
          state.visuals,
          (v) =>
            '<div class="item"><img class="poster" alt="' +
            t("Mahsulot posti", "Карточка товара") +
            '" src="' +
            fileUrl(v.file_id) +
            '"><a download="product-post.png" href="' +
            fileUrl(v.file_id) +
            '">' +
            t("PNG yuklab olish", "Скачать PNG") +
            "</a></div>",
        ),
    )
  );
}
function inbox() {
  return (
    panel(
      t("Suhbatlar", "Диалоги"),
      list(state.chats, (r) =>
        item(
          "Telegram · " + r.chat,
          btn(
            "pause",
            r.paused
              ? t("Avtojavobni yoqish", "Возобновить ответы")
              : t("Suhbatni olish", "Взять диалог"),
            "soft",
            r.id,
          ),
          (r.paused
            ? t("Egasi javob beradi", "Нужен владелец")
            : t("Avtojavob yoqilgan", "Автоответ включён")) +
            " · " +
            r.summary,
        ),
      ),
    ) +
    (state.demo
      ? panel(
          t("Telegram simulyatori", "Симулятор Telegram"),
          form(
            field(
              "question",
              t("Mijoz xabari", "Сообщение покупателя"),
              "",
              "text",
              true,
            ),
            t("Sinash", "Проверить"),
          ) +
            '<p class="response">' +
            esc(simulation) +
            "</p>",
        )
      : "")
  );
}
function settings() {
  return (
    panel(
      t("Biznes xotirasi", "Данные бизнеса"),
      item(t("Ish joyi ID", "ID рабочего пространства"), esc(state.id)) +
        item(
          state.name,
          btn("profile", t("Profilni tahrirlash", "Изменить профиль"), "soft"),
          state.profile.description,
        ) +
        item(
          t("Brend fayli", "Файл бренда"),
          btn("brand", t("Yuklash", "Загрузить"), "plain"),
        ) +
        item(
          "Telegram Business",
          state.connections
            ? t("Ulangan", "Подключён")
            : t("Ulanmagan", "Не подключён"),
        ),
    ) +
    panel(
      t("Tasdiqlangan javoblar", "Утверждённые ответы"),
      btn("faq", t("Javob qo‘shish", "Добавить ответ"), "soft") +
        list(state.faqs, (q) =>
          item(
            q.question,
            btn("faq", t("Tahrirlash", "Изменить"), "plain", q.id),
            q.answer,
          ),
        ),
    ) +
    panel(
      t("Jamoa", "Команда"),
      btn(
        "invite",
        t("Xodimni taklif qilish", "Пригласить сотрудника"),
        "soft",
      ) +
        (inviteLink ? '<p class="response">' + esc(inviteLink) + "</p>" : "") +
        list(state.team, (r) =>
          item(
            r.role,
            r.role === "owner"
              ? ""
              : btn(
                  "remove",
                  t("Kirishni yopish", "Закрыть доступ"),
                  "plain",
                  r.subject,
                ),
            r.subject,
          ),
        ),
    )
  );
}
function billing() {
  const b = state.billing;
  return (
    '<div class="cols">' +
    panel(
      b.plan,
      '<p class="blank">' +
        t("Oylik postlar soni", "Публикаций в месяц") +
        " · " +
        b.limit +
        '</p><p class="blank">' +
        t("Amal qilish muddati", "Действует до") +
        " · " +
        esc(b.expires?.slice(0, 10) || "—") +
        "</p>",
    ) +
    panel(
      "Starter",
      "<h3>" +
        money(b.price) +
        " / 30 " +
        t("kun", "дней") +
        '</h3><p class="blank">' +
        t(
          "Bir martalik to‘lov. Muddat qo‘lda uzaytiriladi.",
          "Разовая оплата. Продление вручную.",
        ) +
        "</p>" +
        btn(
          "invoice",
          b.plan === "Starter"
            ? t("Uzaytirish", "Продлить")
            : t("Tarifni oshirish", "Перейти на Starter"),
        ),
    ) +
    "</div>" +
    panel(
      t("Hisoblar", "Счета"),
      (b.test
        ? '<p class="tip">' +
          t(
            "Sinov to‘lovi · Haqiqiy pul olinmaydi.",
            "Тестовая оплата · Без списания денег.",
          ) +
          "</p>"
        : "") +
        list(state.invoices, (i) =>
          item(
            money(i.amount),
            i.paid_at
              ? t("To‘langan", "Оплачен")
              : i.test
                ? btn(
                    "simulate",
                    t(
                      "Sinov to‘lovini tasdiqlash",
                      "Подтвердить тестовую оплату",
                    ),
                    "soft",
                    i.id,
                  )
                : t("Tekshiruv kutilmoqda", "Ожидает проверки"),
            i.id,
          ),
        ),
    ) +
    panel(
      "Team",
      '<p class="blank">' +
        t(
          "Reja: $7/oy, bir xodim kiradi. Har bir qo‘shimcha xodim $2. Pilotda sotuv yopiq.",
          "Предложение: $7 в месяц с одним сотрудником, далее $2 за место. Продажи в пилоте закрыты.",
        ) +
        "</p>",
    )
  );
}
function assistant() {
  const prompts = [t("Bugun nimadan boshlay?", "С чего начать сегодня?")];
  if (state.figures)
    prompts.push(t("Kimning to‘lovi qolgan?", "Кто ещё должен оплатить?"));
  if (state.topics)
    prompts.push(t("Mijozlar nimani so‘rayapti?", "Что спрашивают клиенты?"));
  const messages = chatTurns
    .map(
      (turn) =>
        '<div class="chatMessage chatUser"><small>' +
        t("Siz", "Вы") +
        "</small><p>" +
        esc(turn.question) +
        '</p></div><div class="chatMessage"><small>' +
        (turn.source === "ai"
          ? t("AI yordamchi", "AI-помощник")
          : t("Do‘kon yozuvlari", "По записям магазина")) +
        "</small><p>" +
        esc(turn.answer) +
        "</p></div>",
    )
    .join("");
  return (
    '<section class="panel assistantPanel"><div class="head"><h2>' +
    t("Shaxsiy yordamchi", "Личный помощник") +
    "</h2>" +
    (state.figures
      ? btn("monthly", t("Oylik xulosa", "Сводка за месяц"), "soft")
      : "") +
    '</div><div class="chatLog" role="log" aria-label="' +
    t("Suhbat tarixi", "История разговора") +
    '">' +
    (messages ||
      '<p class="blank">' +
        t(
          "Biznesni birga tahlil qilamiz. Savol bering — mahsulotlar va yozuvlardan boshlaymiz.",
          "Давай разберём твой бизнес. Задай вопрос — начнём с товаров и записей магазина.",
        ) +
        "</p>") +
    (chatPending
      ? '<div class="chatMessage chatUser"><p>' +
        esc(chatPending.question) +
        '</p></div><p role="status">' +
        t("Javob tayyorlanmoqda…", "Разбираюсь в данных…") +
        "</p>"
      : "") +
    '</div><div class="actions">' +
    prompts.map((q) => btn("chatPrompt", q, "textbtn", q)).join("") +
    '</div><form class="stack" data-chat><label>' +
    t("Savol", "Вопрос") +
    '<textarea name="question" required maxlength="2000" rows="2" ' +
    (chatPending ? "readonly" : "") +
    ">" +
    esc(chatDraft) +
    '</textarea></label><p class="error" role="alert">' +
    esc(chatError) +
    '</p><button type="submit" class="button" ' +
    (chatPending ? "disabled" : "") +
    ">" +
    t("Yuborish", "Отправить") +
    "</button></form></section>"
  );
}
async function sendChat(question, monthly = false) {
  if (chatPending || !question.trim()) return;
  chatDraft = question;
  chatError = "";
  const request =
    chatRetry?.question === question && chatRetry.monthly === monthly
      ? chatRetry
      : {
          question,
          request_id: crypto.randomUUID(),
          language: lang,
          monthly,
        };
  chatPending = request;
  chatRetry = request;
  const workspace = member,
    role = state.role;
  render();
  try {
    const { monthly: period, ...body } = request;
    const result = await api(
      "assistant" + (period ? "?monthly=true" : ""),
      "POST",
      body,
    );
    if (member !== workspace || state?.role !== role || chatPending !== request)
      return;
    chatTurns.push({
      question,
      answer: result.text,
      source: result.source,
      request_id: request.request_id,
    });
    chatDraft = "";
    chatRetry = null;
  } catch (err) {
    if (chatPending === request)
      chatError =
        err.status === 503
          ? t(
              "AI xizmati hozir javob bermadi. Qayta urinib ko‘ring.",
              "AI-сервис сейчас не ответил. Нажми «Отправить», чтобы повторить.",
            )
          : err.message;
  } finally {
    if (chatPending === request) {
      chatPending = null;
      if (state && ["overview", "assistant"].includes(page)) render();
    }
  }
}

function guideSteps() {
  const steps = [
    [
      "overview",
      t(
        "Bu yerda biznesingizning umumiy holatini ko‘rasiz. Bo‘limlarni chapdagi menyudan oching.",
        "Здесь видна общая картина бизнеса. Переключайте разделы в меню слева.",
      ),
    ],
    [
      "production",
      t(
        "Birinchi mahsulotni qo‘shing: nomi, narxi va tavsifi. Mijozlarga javoblar shu katalogdan olinadi.",
        "Добавьте первый товар — название, цену и описание. Ответы клиентам используют этот каталог.",
      ),
    ],
    [
      "finances",
      t(
        "Buyurtmalar, daromad va xarajatlarni shu yerda kiriting. Chekni saqlashdan oldin ma’lumotlarini tekshiring.",
        "Здесь добавляют заказы, доходы и расходы. Перед сохранением чека проверьте его данные.",
      ),
    ],
    [
      "marketing",
      t(
        "Mahsulot uchun post yarating va mijozlar qaysi mavzularni so‘rayotganini ko‘ring.",
        "Создавайте публикации для товаров и смотрите, какие темы интересуют клиентов.",
      ),
    ],
    [
      "assistant",
      t(
        "Katalog, to‘lovlar yoki xarajatlar haqida savol bering. Aniq javoblar uchun avval biznes ma’lumotlarini kiriting.",
        "Задавайте вопросы о каталоге, оплатах и расходах. Сначала внесите данные бизнеса, чтобы помощнику было на что опираться.",
      ),
    ],
    [
      "settings",
      t(
        "Profil, yetkazib berish va to‘lov shartlarini to‘ldiring. Bu yerda javoblarni ham sozlaysiz.",
        "Заполните профиль, условия доставки и оплаты. Здесь же настраиваются готовые ответы клиентам.",
      ),
    ],
  ];
  return steps.filter(([key]) => allowed().includes(key));
}
function guideKey() {
  return "growth-guide-v1:" + state.id + ":" + state.role;
}
function guide() {
  if (localStorage.getItem(guideKey()) === "done") return "";
  const steps = guideSteps();
  const [target, text] = steps[guideStep] || steps[0];
  return (
    '<section class="panel guide" aria-label="' +
    t("Boshlash uchun yordam", "Подсказки для начала работы") +
    '"><div class="head"><h2>' +
    esc(t("Qisqa tanishuv", "Короткое знакомство")) +
    " · " +
    (guideStep + 1) +
    "/" +
    steps.length +
    "</h2>" +
    btn("guideDone", t("Yopish", "Закрыть"), "textbtn") +
    "</div><p>" +
    esc(text) +
    '</p><div class="actions">' +
    (page !== target
      ? btn("guideOpen", pages()[target][1], "soft", target)
      : "") +
    btn(
      "guideNext",
      guideStep === steps.length - 1
        ? t("Tayyor", "Готово")
        : t("Keyingi", "Далее"),
    ) +
    "</div></section>"
  );
}
function render() {
  document.documentElement.lang = lang;
  const p = pages();
  const body = {
    overview,
    finances,
    marketing,
    production,
    assistant,
    inbox,
    settings,
    billing,
  }[page]();
  root.innerHTML =
    '<div class="frame"><aside class="sidebar ' +
    (menuOpen ? "open" : "") +
    '"><div class="toolrow">' +
    wordmark +
    btn("menu", "☰", "mobilemenu") +
    '</div><nav class="nav">' +
    allowed()
      .map(
        (k) =>
          '<button data-act="nav" data-id="' +
          k +
          '" class="' +
          (k === page ? "active" : "") +
          '"><span aria-hidden="true">' +
          p[k][0] +
          "</span>" +
          p[k][1] +
          "</button>",
      )
      .join("") +
    '</nav><div class="sidebottom"><b>' +
    esc(state.name) +
    "</b><small>" +
    esc(state.role) +
    '</small></div></aside><main class="main"><div class="toolrow top"><div class="row"><b>' +
    esc(state.name) +
    "</b>" +
    (state.demo
      ? '<span class="tag">' + t("Demo do‘kon", "Демомагазин") + "</span>"
      : "") +
    '</div><div class="row">' +
    (memberships.length > 1
      ? select(
          "workspace",
          t("Ish joyi", "Бизнес"),
          memberships.map((m) => [
            m.business_id,
            m.role + " · " + m.business_id.slice(0, 8),
          ]),
          member,
        )
      : "") +
    langs() +
    btn("guideRestart", t("Yordam", "Подсказки"), "plain") +
    btn("logout", t("Chiqish", "Выйти"), "plain") +
    '</div></div><div class="head"><h1 class="title">' +
    p[page][1] +
    '</h1><span class="muted">' +
    new Date().toLocaleDateString(lang === "ru" ? "ru-RU" : "uz-UZ", {
      day: "numeric",
      month: "long",
      timeZone: "Asia/Tashkent",
    }) +
    "</span></div>" +
    guide() +
    body +
    "</main></div>";
  const log = root.querySelector(".chatLog");
  if (log) log.scrollTop = log.scrollHeight;
  root.querySelector("[data-chat] textarea")?.addEventListener("input", (e) => {
    chatDraft = e.target.value;
  });
  if (chatPending)
    root
      .querySelectorAll('[data-act="monthly"], [data-act="chatPrompt"]')
      .forEach((b) => {
        b.disabled = true;
      });
}
function editProduct(id) {
  const p = state.products.find((p) => p.id === id) || {},
    d = p.details || {};
  modalForm(
    t("Mahsulot", "Товар"),
    field("name", t("Nomi", "Название"), p.name, "text", true) +
      field("price", t("Narx, UZS", "Цена, UZS"), p.price, "number", true) +
      area("description", t("Tavsif", "Описание"), d.description) +
      field(
        "variants",
        t("Variantlar va dizaynlar", "Варианты и дизайн"),
        d.variants,
      ) +
      field("availability", t("Mavjudligi", "Наличие"), d.availability) +
      field(
        "lead_time",
        t("Tayyorlash muddati", "Срок изготовления"),
        d.lead_time,
      ) +
      area(
        "sourcing",
        t("Ishlab chiqarish yoki manba", "Изготовление или закупка"),
        d.sourcing,
      ) +
      otherLanguage(
        [
          ["variants", topicName("variants")],
          ["availability", topicName("availability")],
          ["lead_time", topicName("lead_time")],
        ],
        d,
      ),
    async (o) =>
      api("products" + (id ? "/" + id : ""), id ? "PUT" : "POST", {
        ...o,
        price: Number(o.price),
      }),
  );
}
function entry(kind, r = null) {
  const f = r?.fields || {},
    id = crypto.randomUUID(),
    inc = kind === "income";
  const opts = state.orders
    .filter((o) => o.balance > 0)
    .map((o) => [
      o.id,
      o.customer + " · " + o.product + " · " + money(o.balance),
    ]);
  const cats = inc
    ? [t("Savdo", "Продажа"), t("Xizmat", "Услуга")]
    : [
        t("Masalliqlar", "Ингредиенты"),
        t("Qadoqlash", "Упаковка"),
        t("Yetkazish", "Доставка"),
        t("Reklama", "Реклама"),
      ];
  const receipt = r
    ? '<a class="wide" target="_blank" href="' +
      fileUrl(r.file_id) +
      '"><img alt="' +
      t("Chek rasmi", "Фотография чека") +
      '" class="receiptimg" src="' +
      fileUrl(r.file_id) +
      '"></a>'
    : "";
  modalForm(
    inc ? t("Daromad", "Доход") : t("Xarajat", "Расход"),
    receipt +
      field(
        "amount",
        t("Miqdor, UZS", "Сумма, UZS"),
        f.amount,
        "number",
        true,
      ) +
      field("day", t("Sana", "Дата"), r ? f.day || "" : today(), "date", true) +
      "<label>" +
      t("Toifa", "Категория") +
      '<input required name="category" list="cats" value="' +
      esc(f.category || "") +
      '"><datalist id="cats">' +
      cats.map((x) => "<option>" + esc(x) + "</option>").join("") +
      "</datalist></label>" +
      field(
        "reference",
        t("Tranzaksiya raqami", "Номер транзакции"),
        f.reference,
      ) +
      area(
        "note",
        t("Izoh yoki sotuvchi", "Примечание или продавец"),
        f.vendor,
      ) +
      (inc
        ? select(
            "order_id",
            t("Buyurtma", "Заказ"),
            [["", t("Alohida daromad", "Отдельный доход")], ...opts],
            r?.suggested_order,
          ) +
          select("payment_type", t("To‘lov turi", "Тип платежа"), [
            ["deposit", paymentName("deposit")],
            ["final", paymentName("final")],
          ])
        : "") +
      (r
        ? '<label class="check wide"><input required type="checkbox" name="verified">' +
          (inc
            ? t("Pul tushganini tekshirdim", "Я проверил поступление средств")
            : t("Chek ma’lumotlarini tekshirdim", "Я проверил данные чека")) +
          "</label>"
        : ""),
    (o) =>
      api("journal", "POST", {
        ...o,
        request_id: id,
        kind,
        amount: Number(o.amount),
        order_id: o.order_id || null,
        payment_type: o.order_id ? o.payment_type : null,
        receipt_id: r?.id || null,
        verified: !!o.verified,
      }),
  );
}
const actions = {
  guideDone: () => {
    localStorage.setItem(guideKey(), "done");
    render();
  },
  guideRestart: () => {
    localStorage.removeItem(guideKey());
    guideStep = 0;
    page = "overview";
    render();
  },
  guideOpen: (target) => {
    page = target;
    render();
  },
  guideNext: () => {
    const steps = guideSteps();
    if (guideStep === steps.length - 1)
      localStorage.setItem(guideKey(), "done");
    else {
      guideStep++;
      page = steps[guideStep][0];
    }
    menuOpen = false;
    render();
    window.scrollTo(0, 0);
  },
  lang: async (id) => {
    lang = id;
    localStorage.setItem("language", id);
    if (state) render();
    else if (root.querySelector(".sheet")) onboarding();
    else authPage();
  },
  nav: async (id) => {
    page = id;
    menuOpen = false;
    render();
    window.scrollTo(0, 0);
  },
  menu: async () => {
    menuOpen = !menuOpen;
    render();
  },
  resendConfirmation: async () => {
    const input = root.querySelector('input[name="email"]');
    if (!input.reportValidity()) return;
    await api("auth/resend", "POST", { email: input.value.trim() });
    confirmationEmail = input.value.trim();
    confirmation = "check";
    authPage();
  },
  switchAuth: async () => {
    signup = !signup;
    authPage();
  },
  demo: async () => {
    await api("demo", "POST");
    await boot();
  },
  logout: async () => {
    await api("logout", "POST");
    member = null;
    sessionStorage.removeItem("business");
    authPage();
  },
  product: editProduct,
  profile: () =>
    modalForm(
      t("Biznes profili", "Профиль бизнеса"),
      profileFields(state.profile),
      (o) => api("profile", "PUT", o),
    ),
  entry: (kind) => entry(kind),
  review: (id) => {
    const r = state.receipts.find((x) => x.id === id);
    entry(r.kind, r);
  },
  faq: (id) => {
    const q = state.faqs.find((f) => f.id === id) || {};
    modalForm(
      t("Tasdiqlangan javob", "Утверждённый ответ"),
      field(
        "question",
        t("Mijoz savoli", "Вопрос покупателя"),
        q.question,
        "text",
        true,
      ) +
        select(
          "language",
          t("Javob tili", "Язык ответа"),
          [
            ["uz", "O‘zbekcha"],
            ["ru", "Русский"],
          ],
          q.language || lang,
        ) +
        area(
          "answer",
          t(
            "Javob · joriy narx uchun {price}",
            "Ответ · {price} для актуальной цены",
          ),
          q.answer,
        ),
      (o) => api("faqs" + (id ? "/" + id : ""), id ? "PUT" : "POST", o),
    );
  },
  order: () => {
    if (!state.products.length) {
      notice(
        t(
          "Avval katalogga mahsulot qo‘shing",
          "Сначала добавьте товар в каталог",
        ),
      );
      return;
    }
    modalForm(
      t("Yangi buyurtma", "Новый заказ"),
      select(
        "product_id",
        t("Mahsulot", "Товар"),
        state.products.map((p) => [p.id, p.name]),
      ) +
        field(
          "customer",
          t(
            "Mijoz nomi yoki Telegram chat ID",
            "Имя клиента или ID чата Telegram",
          ),
          "",
          "text",
          true,
        ) +
        field(
          "total",
          t("Jami, UZS", "Сумма, UZS"),
          state.products[0].price,
          "number",
          true,
        ) +
        field("due", t("To‘lov muddati", "Срок оплаты"), "", "date"),
      (o) =>
        api("orders", "POST", {
          ...o,
          total: Number(o.total),
          due: o.due || null,
        }),
    );
  },
  upload: () =>
    modalForm(
      t("Chek yuklash", "Загрузка чека"),
      select("kind", t("Chek turi", "Тип чека"), [
        ["income", t("Mijoz to‘lovi", "Платёж клиента")],
        ["expense", t("Xarajat", "Расход")],
      ]) + fileField(),
      (o, fd) => api("receipts/" + o.kind, "POST", fd),
    ),
  brand: () =>
    modalForm(t("Brend fayli", "Файл бренда"), fileField(), (o, fd) =>
      api("brand", "POST", fd),
    ),
  pause: async (id) => {
    const r = state.chats.find((r) => r.id === id);
    await api("chats/" + id, "PUT", { paused: !r.paused });
    await loadState();
  },
  visual: () => {
    if (!state.products.length) {
      notice(t("Avval mahsulot qo‘shing", "Сначала добавьте товар"));
      return;
    }
    modalForm(
      t("Mahsulot posti", "Карточка товара"),
      select(
        "pid",
        t("Mahsulot", "Товар"),
        state.products.map((p) => [p.id, p.name]),
      ) +
        select("format", t("Post turi", "Формат"), [
          ["template", t("Brend shabloni", "Фирменный шаблон")],
          ...(state.image_ai
            ? [["ai", t("AI fotosurat", "AI-фотография")]]
            : []),
        ]),
      (o) =>
        api(
          "visuals/" + o.pid + "?template=" + (o.format === "template"),
          "POST",
        ),
      t("Yaratish", "Создать"),
    );
  },
  invoice: async () => {
    await api("invoices", "POST");
    await loadState();
  },
  simulate: async (id) => {
    await api("invoices/" + id + "/simulate", "POST");
    await loadState();
  },
  chatPrompt: (question) => sendChat(question),
  monthly: () =>
    sendChat(
      t("Oylik xulosa va tavsiyalar", "Итоги месяца и рекомендации"),
      true,
    ),
  invite: () =>
    modalForm(
      t("Xodimni taklif qilish", "Пригласить сотрудника"),
      field(
        "email",
        t("Xodim pochtasi", "Почта сотрудника"),
        "",
        "email",
        true,
      ) +
        select("role", t("Roli", "Роль"), [
          ["finance", t("Moliya", "Финансы")],
          ["marketing", t("Marketing", "Маркетинг")],
        ]),
      async (o) => {
        const r = await api("invites", "POST", o);
        inviteLink = location.origin + "/#invite=" + r.token;
      },
    ),
  remove: async (id) => {
    await api("members/" + id, "DELETE");
    await loadState();
  },
  note: () =>
    modalForm(
      t("Umumiy yozuv", "Общая заметка"),
      field(
        "question",
        t("Qaror, vazifa yoki savol", "Решение, задача или вопрос"),
        "",
        "text",
        true,
      ),
      (o) => api("notes", "POST", o),
    ),
  notesSummary: async () => {
    await api("notes?summary=true", "POST", { question: "summary" });
    await loadState();
  },
};
function fileField() {
  return (
    '<label class="wide">' +
    t("Rasm · PNG, JPG, WebP, 8 MiB", "Изображение · PNG, JPG, WebP, 8 МиБ") +
    '<input name="file" required type="file" accept="image/jpeg,image/png,image/webp"></label>'
  );
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("button[data-act]");
  if (!b) return;
  b.disabled = true;
  try {
    await actions[b.dataset.act](b.dataset.id);
  } catch (err) {
    notice(err.message);
  } finally {
    b.disabled = false;
  }
});
dialog.querySelector(".close").onclick = close;
document.addEventListener("change", async (e) => {
  const el = e.target;
  if (el.hasAttribute("data-brand") && el.value) {
    const fields = el.form.elements;
    const green = el.value === "garden";
    fields.color.value = green ? "#286452" : "#97472f";
    fields.tone.value = green
      ? t("Sokin va samimiy", "Спокойный и тёплый")
      : t("Jonli va dadil", "Живой и смелый");
    fields.logo.value = green
      ? t("Barg shaklidagi belgi", "Знак в форме листа")
      : t("Sopol muhr", "Глиняная печать");
  }
  if (el.name === "business_type") {
    el.form.elements.followup_extra.closest("label").firstChild.textContent =
      el.value === "bakery"
        ? t(
            "Bir kunda nechta buyurtma tayyorlaysiz?",
            "Сколько заказов готовите за день?",
          )
        : t(
            "Ombordagi qoldiq qanday tekshiriladi?",
            "Как проверяете остатки на складе?",
          );
    const f = el.form.elements.followup;
    f.closest("label").firstChild.textContent =
      el.value === "bakery"
        ? t(
            "Allergenlar va tayyorlash shartlari",
            "Аллергены и условия приготовления",
          )
        : t(
            "Yetkazib beruvchilar va qaytarish shartlari",
            "Поставщики и условия возврата",
          );
  }
  if (el.name === "product_id" && el.form?.elements.total)
    el.form.elements.total.value = state.products.find(
      (p) => p.id === el.value,
    ).price;
  if (el.name === "workspace") {
    member = el.value;
    try {
      await loadState();
    } catch (err) {
      notice(err.message);
    }
  }
});
document.addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target,
    button = f.querySelector("[type=submit]"),
    error = f.querySelector(".error");
  if (button.disabled) return;
  button.disabled = true;
  error.textContent = "";
  const fd = new FormData(f),
    o = Object.fromEntries(fd);
  try {
    if (dialog.contains(f)) {
      await formAction(o, fd);
      close();
      await loadState();
    } else if (f.closest(".entry")) {
      const res = await api("auth/" + (signup ? "signup" : "login"), "POST", o);
      if (res.confirm_email) {
        confirmation = "check";
        confirmationEmail = o.email;
        signup = false;
        authPage();
      } else {
        confirmation = "";
        confirmationEmail = "";
        await boot();
      }
    } else if (f.closest(".sheet")) {
      const r = await api("onboard", "POST", o);
      member = r.id;
      localStorage.setItem("language", o.language);
      await boot();
    } else if (f.hasAttribute("data-chat")) {
      await sendChat(o.question);
    } else if (page === "inbox") {
      const r = await api("demo-message", "POST", o);
      simulation = r.reply || t("Egasiga yuborildi", "Передано владельцу");
      await loadState();
    }
  } catch (err) {
    error.textContent = err.message;
  } finally {
    button.disabled = false;
  }
});
boot().catch((err) => {
  root.textContent = err.message;
});
