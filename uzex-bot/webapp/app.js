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
      assistantStatus: "Yordamga tayyorman", voiceTitle: "Ovozli savol", listening: "Tinglayapman… Gapiring.",
      voiceReady: "Ovoz matnga aylandi — yuborishdan oldin tekshiring.",
      voiceUnsupported: "Bu brauzerda ovozli kiritish ishlamaydi. Savolni yozing yoki botga ovozli xabar yuboring.",
      voicePermission: "Mikrofonga ruxsat bering yoki savolni yozing.", voiceNoSpeech: "Ovoz aniqlanmadi. Yana urinib ko‘ring.",
      voiceUnavailable: "Ovozli xizmat hozir ishlamayapti. Botga ovozli xabar yuboring.",
      listen: "Javobni tinglash", stopListen: "Ovozni to‘xtatish",
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
      assistantStatus: "Готов помочь", voiceTitle: "Голосовой вопрос", listening: "Слушаю… Говорите.",
      voiceReady: "Голос преобразован в текст — проверьте перед отправкой.",
      voiceUnsupported: "Голосовой ввод не поддерживается в этом браузере. Напишите вопрос или отправьте боту голосовое сообщение.",
      voicePermission: "Разрешите доступ к микрофону или введите вопрос.", voiceNoSpeech: "Речь не распознана. Попробуйте ещё раз.",
      voiceUnavailable: "Голосовой сервис сейчас недоступен. Отправьте боту голосовое сообщение.",
      listen: "Прослушать ответ", stopListen: "Остановить озвучивание",
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
  const voiceButton = $("voice"), voiceStatus = $("voiceStatus"), speakButton = $("speak");
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  let recognition = null, listening = false, speaking = false, answerLang = lang;
  let lang = tg?.initDataUnsafe?.user?.language_code?.toLowerCase().startsWith("ru") ? "ru" : "uz";

  if (SpeechRecognition) {
    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;
    voiceButton.hidden = false;
    recognition.onstart = () => {
      listening = true;
      voiceButton.classList.add("is-listening");
      voiceButton.setAttribute("aria-pressed", "true");
      voiceStatus.textContent = copy[lang].listening;
      voiceStatus.hidden = false;
    };
    recognition.onresult = (event) => {
      input.value = Array.from(event.results).map((item) => item[0].transcript).join(" ").trim();
    };
    recognition.onerror = (event) => {
      if (event.error === "no-speech") toast(copy[lang].voiceNoSpeech);
      else if (["not-allowed", "service-not-allowed"].includes(event.error)) toast(copy[lang].voicePermission);
      else if (event.error !== "aborted") toast(copy[lang].voiceUnavailable);
    };
    recognition.onend = () => {
      listening = false;
      voiceButton.classList.remove("is-listening");
      voiceButton.setAttribute("aria-pressed", "false");
      if (input.value.trim()) voiceStatus.textContent = copy[lang].voiceReady;
      else voiceStatus.hidden = true;
    };
  } else {
    voiceButton.hidden = false;
  }

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
    voiceButton.setAttribute("aria-label", copy[lang].voiceTitle);
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
    document.querySelector(".shell").classList.add("is-thinking");
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    speaking = false;
    speakButton.classList.remove("is-speaking");
    speakButton.querySelector("span:last-child").textContent = copy[lang].listen;
    result.hidden = true;
    try {
      const response = await fetch("/api/ask", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({question, initData: tg.initData})
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(copy[lang].err);
      answer.textContent = payload.answer;
      answerLang = detectAnswerLanguage(payload.answer);
      $("elapsed").textContent = payload.elapsed ? `${payload.elapsed.toFixed(1)} s` : "";
      result.hidden = false;
      result.scrollIntoView({behavior: "smooth", block: "start"});
    } catch (error) {
      toast(error.message || copy[lang].err);
    } finally {
      send.disabled = false;
      send.querySelector("span").textContent = copy[lang].send;
      document.querySelector(".shell").classList.remove("is-thinking");
    }
  }

  function detectAnswerLanguage(text) {
    if (/[ўқғҳЎҚҒҲ]/.test(text)) return "uz";
    const cyrillic = (text.match(/[А-ЯЁа-яё]/g) || []).length;
    const latin = (text.match(/[A-Za-z]/g) || []).length;
    return cyrillic > Math.max(latin, 2) ? "ru" : "uz";
  }

  function toggleVoiceInput() {
    if (!recognition) { toast(copy[lang].voiceUnsupported); return; }
    if (listening) { recognition.stop(); return; }
    recognition.lang = lang === "ru" ? "ru-RU" : "uz-UZ";
    voiceStatus.hidden = false;
    voiceStatus.textContent = copy[lang].listening;
    try { recognition.start(); }
    catch (_) { toast(copy[lang].voicePermission); }
  }

  function toggleSpeechOutput() {
    if (!("speechSynthesis" in window)) { toast(copy[lang].voiceUnsupported); return; }
    if (speaking) {
      window.speechSynthesis.cancel();
      speaking = false;
      speakButton.classList.remove("is-speaking");
      speakButton.querySelector("span:last-child").textContent = copy[lang].listen;
      return;
    }
    const utterance = new SpeechSynthesisUtterance(answer.textContent);
    utterance.lang = answerLang === "ru" ? "ru-RU" : "uz-UZ";
    utterance.onstart = () => {
      speaking = true;
      speakButton.classList.add("is-speaking");
      speakButton.querySelector("span:last-child").textContent = copy[lang].stopListen;
    };
    utterance.onend = utterance.onerror = () => {
      speaking = false;
      speakButton.classList.remove("is-speaking");
      speakButton.querySelector("span:last-child").textContent = copy[lang].listen;
    };
    window.speechSynthesis.speak(utterance);
  }

  document.querySelectorAll(".language button").forEach((button) => button.addEventListener("click", () => {
    lang = button.dataset.lang; renderLanguage();
  }));
  voiceButton.addEventListener("click", toggleVoiceInput);
  speakButton.addEventListener("click", toggleSpeechOutput);
  send.addEventListener("click", ask);
  input.addEventListener("keydown", (event) => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) ask(); });
  renderLanguage();
})();
