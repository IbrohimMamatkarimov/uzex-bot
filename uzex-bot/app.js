(() => {
  const tg = window.Telegram?.WebApp;
  tg?.ready();
  tg?.expand();

  const copy = {
    uz: {
      eyebrow: "BIRJA REYESTRI · 2022–2026", title: "Savol bering.<br>Raqamlar bilan javob oling.",
      description: "UZEX bitimlari bo‘yicha tekshirilgan ma’lumot. O‘zbekcha yoki ruscha yozing.",
      truth: "Faqat reyestr ma’lumotlari", deals: "bitim", askLabel: "Savolingiz",
      placeholder: "Masalan: 2025-yilda eng ko‘p bitim tuzgan 5 ta xaridor kim?",
      hint: "Natijalar manba va hisob-kitob bilan beriladi", send: "Javob olish", try: "BOSHLASH UCHUN",
      examples: "Misol savollar", answer: "JAVOB", verified: "Reyestr ma’lumotlari asosida",
      footer: "Manba: UZEX bitimlar reyestri", wait: "Reyestr tekshirilmoqda…",
      err: "Javob olinmadi. Iltimos, qayta urinib ko‘ring.", init: "Ilovani Telegram ichidan oching.",
      questions: [
        "2025-yilda eng ko‘p savdo qilingan 5 ta tovar qaysi?",
        "2025-yilda eng ko‘p bitim tuzgan 5 ta xaridor kim?",
        "2024 va 2025-yillarda paxta narxi qanday o‘zgargan?",
        "2025-yilda nechta bitim bekor qilingan?",
        "Tsement savdosida qaysi hudud yetakchi?",
        "Dollar kursi 2025-yilda qanday o‘zgargan?"
      ]
    },
    ru: {
      eyebrow: "РЕЕСТР БИРЖИ · 2022–2026", title: "Задайте вопрос.<br>Получите ответ в цифрах.",
      description: "Проверенные данные о сделках UZEX. Пишите на русском или узбекском.",
      truth: "Только данные реестра", deals: "сделок", askLabel: "Ваш вопрос",
      placeholder: "Например: какие 5 покупателей заключили больше всего сделок в 2025 году?",
      hint: "Ответ с источником и расчётом", send: "Получить ответ", try: "ПОПРОБУЙТЕ",
      examples: "Примеры вопросов", answer: "ОТВЕТ", verified: "По данным реестра",
      footer: "Источник: реестр сделок UZEX", wait: "Проверяю реестр…",
      err: "Не удалось получить ответ. Попробуйте ещё раз.", init: "Откройте приложение в Telegram.",
      questions: [
        "Какие 5 товаров лидировали по обороту в 2025 году?",
        "Кто 5 крупнейших покупателей по числу сделок в 2025 году?",
        "Как изменилась цена хлопка в 2024 и 2025 годах?",
        "Сколько сделок было аннулировано в 2025 году?",
        "Какой регион лидирует по торговле цементом?",
        "Как менялся курс доллара в 2025 году?"
      ]
    }
  };

  const $ = (id) => document.getElementById(id);
  const input = $("question"), send = $("send"), answer = $("answer"), result = $("result");
  let lang = tg?.initDataUnsafe?.user?.language_code?.toLowerCase().startsWith("ru") ? "ru" : "uz";

  function renderLanguage() {
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-i18n]").forEach((node) => {
      const key = node.dataset.i18n;
      if (copy[lang][key] !== undefined) node.innerHTML = copy[lang][key];
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((node) => {
      node.placeholder = copy[lang][node.dataset.i18nPlaceholder];
    });
    document.querySelectorAll(".language button").forEach((button) => button.classList.toggle("active", button.dataset.lang === lang));
    const list = $("questions");
    list.replaceChildren(...copy[lang].questions.map((question) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "question";
      const icon = document.createElement("span"); icon.textContent = "↗";
      const label = document.createElement("span"); label.className = "question-text"; label.textContent = question;
      button.append(icon, label);
      button.addEventListener("click", () => { input.value = question; ask(); });
      return button;
    }));
  }

  function toast(message) {
    const node = $("toast"); node.textContent = message; node.hidden = false;
    window.setTimeout(() => { node.hidden = true; }, 2800);
  }

  async function ask() {
    const question = input.value.trim();
    if (!question) { input.focus(); toast(copy[lang].placeholder); return; }
    if (!tg?.initData) { toast(copy[lang].init); return; }
    send.disabled = true;
    send.querySelector("span").textContent = copy[lang].wait;
    result.hidden = true;
    try {
      const response = await fetch("/api/ask", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({question, initData: tg.initData})
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(copy[lang].err);
      answer.textContent = payload.answer;
      $("elapsed").textContent = payload.elapsed ? `${payload.elapsed.toFixed(1)} s` : "";
      result.hidden = false;
      result.scrollIntoView({behavior: "smooth", block: "start"});
    } catch (error) {
      toast(error.message || copy[lang].err);
    } finally {
      send.disabled = false;
      send.querySelector("span").textContent = copy[lang].send;
    }
  }

  document.querySelectorAll(".language button").forEach((button) => button.addEventListener("click", () => {
    lang = button.dataset.lang; renderLanguage();
  }));
  send.addEventListener("click", ask);
  input.addEventListener("keydown", (event) => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) ask(); });
  renderLanguage();
})();
