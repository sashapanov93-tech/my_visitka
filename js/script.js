document.addEventListener('DOMContentLoaded', () => {
  const languageButtons = document.querySelectorAll('[data-lang]');
  const translatable = document.querySelectorAll('[data-ru][data-en]');
  const notice = document.getElementById('notice');

  const setLanguage = (lang) => {
    document.documentElement.lang = lang;
    translatable.forEach((element) => { element.textContent = element.dataset[lang]; });
    languageButtons.forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.lang === lang)));
    localStorage.setItem('site-language', lang);
  };

  languageButtons.forEach((button) => button.addEventListener('click', () => setLanguage(button.dataset.lang)));
  setLanguage(localStorage.getItem('site-language') === 'en' ? 'en' : 'ru');

  document.querySelectorAll('[data-modal]').forEach((button) => {
    button.addEventListener('click', () => document.getElementById(button.dataset.modal).showModal());
  });
  document.querySelectorAll('[data-close]').forEach((button) => {
    button.addEventListener('click', () => button.closest('dialog').close());
  });
  document.querySelectorAll('dialog').forEach((dialog) => {
    dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });
  });
  const TELEGRAM_BOT_TOKEN = '8868231264:AAF_-m9-_Y1HUefzhlXKdNN8ztPKWcTBa60';
  const TELEGRAM_CHAT_ID = '8802399573';

  const sendToTelegram = async (message) => {
    const url = `https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`;
    const body = new URLSearchParams({ chat_id: TELEGRAM_CHAT_ID, text: message });
    const response = await fetch(url, { method: 'POST', body });
    return response.ok;
  };

  document.querySelectorAll('[data-request-form]').forEach((form) => {
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const dialog = form.closest('dialog');
      const fields = Array.from(form.querySelectorAll('input, textarea'))
        .filter((field) => field.name)
        .map((field) => `${field.name}: ${field.value}`)
        .join('\n');
      const title = form.querySelector('h2')?.textContent || 'Заявка';
      const message = `${title}\n\n${fields}`;
      const ok = await sendToTelegram(message);
      dialog.close();
      form.reset();
      notice.textContent = ok
        ? (document.documentElement.lang === 'en' ? 'Thanks! Your request has been received.' : 'Спасибо! Ваша заявка принята.')
        : (document.documentElement.lang === 'en' ? 'Error sending request. Please try again.' : 'Ошибка отправки. Попробуйте ещё раз.');
      notice.hidden = false;
      window.setTimeout(() => { notice.hidden = true; }, 4000);
    });
  });
});
